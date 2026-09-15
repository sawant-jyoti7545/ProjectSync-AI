"""
ProjectSync AI - AI Service Abstraction

Single entrypoint the rest of the codebase calls regardless of which
AI backend is active, per spec section 8:

    MODE 1 ("real"): calls the real Anthropic API using AI_API_KEY
    MODE 2 ("demo"): uses the local rule-based logic in
                      services/risk_analyzer.py - always works offline,
                      no key required

The rule-based result is ALWAYS computed first by the caller and
passed in here as a guaranteed fallback. If AI_MODE="real" but the API
call fails for any reason (missing/invalid key, network issue, rate
limit, malformed response), this silently falls back to the rule-based
result rather than breaking the upload flow - per spec section 9, the
project must stay demoable even if the AI API is unavailable.
"""

import json
import logging
import requests

from config import settings

logger = logging.getLogger("ProjectSync")

ANTHROPIC_VERSION = "2023-06-01"


def _call_anthropic(system_prompt: str, user_prompt: str, max_tokens: int = 1200) -> dict:
    """
    Low-level call to the Anthropic Messages API. Raises on any failure -
    callers must catch and fall back to rule-based logic; this function
    never silently returns partial/fake data.
    """
    if not settings.AI_API_KEY:
        raise RuntimeError("AI_API_KEY is not set in .env")

    headers = {
        "x-api-key": settings.AI_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": settings.AI_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    response = requests.post(settings.AI_API_URL, headers=headers, json=body, timeout=25)
    response.raise_for_status()
    data = response.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()

    # Strip markdown code fences in case the model wrapped its JSON in them,
    # even though the prompt explicitly asks it not to.
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json", "", 1).strip() if raw_text.lower().startswith("json") else raw_text

    return json.loads(raw_text)


def enhance_risk_analysis(rule_based_result: dict, project_name: str, progress_results: list[dict]) -> dict:
    """
    Given the rule-based risk analysis (already computed as a guaranteed
    fallback) plus the underlying progress data, optionally asks a real
    LLM to produce a sharper, more nuanced version in the SAME JSON shape.

    Returns:
        - The AI-enhanced result on success (AI_MODE == "real")
        - The unmodified rule_based_result if AI_MODE == "demo"
        - The unmodified rule_based_result if the API call fails for any reason
    """
    if settings.AI_MODE != "real":
        return rule_based_result

    system_prompt = (
        "You are a construction project risk analyst helping a project manager. "
        "You are given a rule-based risk analysis draft plus the underlying progress "
        "data it was built from. Rewrite it into sharper, more specific, "
        "project-manager-ready language. Stay strictly grounded in the data provided - "
        "do not invent activities, numbers, or risks that aren't supported by the input. "
        "You may reword, merge, prioritize, or add brief practical context to the risks "
        "and actions, but every risk must trace back to something in the input data. "
        "Respond with ONLY valid JSON, no markdown code fences, no preamble or explanation, "
        "matching exactly this shape: "
        '{"overall_risk": "Low|Medium|High", "summary": "string", '
        '"key_risks": [{"risk": "string", "severity": "Low|Medium|High"}], '
        '"recommended_actions": ["string"]}'
    )
    user_prompt = json.dumps({
        "project_name": project_name,
        "progress_results": progress_results,
        "rule_based_draft": rule_based_result,
    })

    try:
        ai_result = _call_anthropic(system_prompt, user_prompt)

        required_keys = ("overall_risk", "summary", "key_risks", "recommended_actions")
        if not all(k in ai_result for k in required_keys):
            raise ValueError(f"AI response missing required fields: {required_keys}")
        if ai_result["overall_risk"] not in ("Low", "Medium", "High"):
            raise ValueError(f"Invalid overall_risk value: {ai_result['overall_risk']}")

        logger.info("[ProjectSync] AI risk analysis (AI_MODE=real) succeeded")
        return ai_result

    except Exception as e:
        logger.warning(
            f"[ProjectSync] AI_MODE=real call failed ({e}) - "
            f"falling back to rule-based risk analysis"
        )
        return rule_based_result


def extract_activities_from_text(raw_text: str, fallback_parser) -> dict:
    """
    Parses free-form text (e.g. a voice-dictated site report transcript,
    which won't reliably contain labeled fields like "Activity ID:") into
    the same structured JSON shape as PDF extraction.

    If AI_MODE == "real", asks the LLM to intelligently extract activities
    from unstructured dictation. Otherwise, or if the AI call fails, falls
    back to `fallback_parser(raw_text)` - the same regex-based parser used
    for PDFs, which works if the dictation happened to follow the
    structured "Field: value" format.
    """
    if settings.AI_MODE == "real":
        system_prompt = (
            "You are extracting structured data from a construction site progress report "
            "that was dictated aloud and transcribed to text, so it will NOT have clean "
            "labeled fields - infer the activity name, location, planned/actual progress "
            "percentages, status, and any issues mentioned from natural language. "
            "Respond with ONLY valid JSON, no markdown fences, no preamble, matching exactly: "
            '{"project": "string or null", "report_date": "YYYY-MM-DD or null", '
            '"activities": [{"activity_id": "string or null", "activity": "string", '
            '"location": "string or null", "planned_progress": number or null, '
            '"actual_progress": number or null, "status": "string or null", '
            '"issues": "string or null", "remarks": "string or null"}]}. '
            "If you cannot find any real activities in the text, return an empty activities array - "
            "never invent data that isn't in the transcript."
        )
        try:
            ai_result = _call_anthropic(system_prompt, raw_text, max_tokens=1500)
            if "activities" in ai_result and isinstance(ai_result["activities"], list) and ai_result["activities"]:
                logger.info(f"[ProjectSync] AI voice extraction succeeded: {len(ai_result['activities'])} activities")
                return ai_result
            logger.warning("[ProjectSync] AI voice extraction returned no activities - falling back to regex parser")
        except Exception as e:
            logger.warning(f"[ProjectSync] AI voice extraction failed ({e}) - falling back to regex parser")

    return fallback_parser(raw_text)

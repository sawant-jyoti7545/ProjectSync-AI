"""
ProjectSync AI - Risk Analyzer

Produces structured project risk output per spec section 3.H, using
rule-based analysis (keyword scanning + dependency-chain checks). This
is the "demo mode" logic - in Phase 6 this gets wrapped by an AI
service abstraction that can optionally call a real LLM instead, but
this rule-based version always works offline and is what keeps the
project demoable per spec section 9.

Signals considered:
    - Delayed / At Risk activities (from progress_analyzer output)
    - Keywords in "issues" text: equipment downtime, material delay,
      manpower shortage
    - Dependency chains: activities that depend on a delayed activity
    - New activities detected (unplanned work, resource diversion)
    - Low-confidence matches pending human verification
"""

import logging
from sqlalchemy.orm import Session

from models import ActivityMatch, Activity, VerificationQueue

logger = logging.getLogger("ProjectSync")

_KEYWORD_RISKS = {
    "equipment": "Equipment downtime has reduced progress on {activity}.",
    "downtime": "Equipment downtime has reduced progress on {activity}.",
    "material": "Material movement delay may affect {activity} and any downstream work.",
    "manpower": "Manpower shortage is limiting progress on {activity}.",
    "shortage": "Manpower shortage is limiting progress on {activity}.",
}

_SEVERITY_BY_DELAY_STATUS = {
    "Delayed": "High",
    "At Risk": "Medium",
}


def _keyword_risks_for(activity_name: str, issues_text: str) -> list[str]:
    """Scans free-text issues for known risk keywords and returns phrased risk strings."""
    if not issues_text:
        return []
    lowered = issues_text.lower()
    found = []
    seen_templates = set()
    for keyword, template in _KEYWORD_RISKS.items():
        if keyword in lowered and template not in seen_templates:
            found.append(template.format(activity=activity_name))
            seen_templates.add(template)
    return found


def _dependency_risk(db: Session, project_id: int, delayed_activity: Activity) -> str | None:
    """
    Checks whether any other scheduled activity depends on this delayed
    one. Dependencies are stored as a comma-separated activity_id string.
    """
    if not delayed_activity or not delayed_activity.activity_id:
        return None

    dependents = (
        db.query(Activity)
        .filter(Activity.project_id == project_id)
        .filter(Activity.dependencies.isnot(None))
        .filter(Activity.dependencies.like(f"%{delayed_activity.activity_id}%"))
        .all()
    )
    if not dependents:
        return None

    names = ", ".join(d.activity_name for d in dependents)
    return f"Downstream activities ({names}) depend on delayed work in {delayed_activity.activity_name}."


def analyze_risk(db: Session, project_id: int, site_report_id: int, progress_results: list[dict]) -> dict:
    """
    Builds the structured risk analysis for a given site report's
    matched-and-analyzed activities.

    Returns:
        {
            "overall_risk": "Low" | "Medium" | "High",
            "summary": "...",
            "key_risks": [{"risk": "...", "severity": "..."}],
            "recommended_actions": ["..."]
        }
    """
    key_risks: list[dict] = []
    actions: list[str] = []

    problem_activities = [r for r in progress_results if r["delay_status"] in ("Delayed", "At Risk")]

    for result in problem_activities:
        severity = _SEVERITY_BY_DELAY_STATUS[result["delay_status"]]
        activity_name = result["activity"]

        # Variance-based risk entry
        key_risks.append({
            "risk": f"{activity_name} is {abs(result['variance']):.0f}% behind planned progress "
                    f"({result['delay_status']}).",
            "severity": severity,
        })

        # Look up the ActivityMatch -> Activity to read issues text + dependencies
        match = db.query(ActivityMatch).filter(ActivityMatch.id == result["match_id"]).first()
        issues_text = None
        if match and match.site_report:
            # issues text lives in the raw extraction, not a DB column on ActivityMatch;
            # pull it back out of the stored extraction for this specific activity.
            import json
            try:
                extraction = json.loads(match.site_report.raw_extracted_json or "{}")
                for a in extraction.get("activities", []):
                    if a.get("activity") == match.site_activity_name:
                        issues_text = a.get("issues")
                        break
            except (json.JSONDecodeError, TypeError):
                pass

        for phrased_risk in _keyword_risks_for(activity_name, issues_text):
            key_risks.append({"risk": phrased_risk, "severity": severity})

        if match and match.activity:
            dep_risk = _dependency_risk(db, project_id, match.activity)
            if dep_risk:
                key_risks.append({"risk": dep_risk, "severity": "Medium"})
                actions.append(f"Review schedule sequencing for activities dependent on {activity_name}.")

        if result["delay_status"] == "Delayed":
            actions.append(f"Expedite resources and escalate {activity_name} to project control immediately.")
        else:
            actions.append(f"Monitor {activity_name} closely - trending behind plan.")

    # New activities detected in this report
    new_activity_matches = (
        db.query(ActivityMatch)
        .filter(ActivityMatch.site_report_id == site_report_id)
        .filter(ActivityMatch.match_status == "New Activity")
        .all()
    )
    if new_activity_matches:
        names = ", ".join(m.site_activity_name for m in new_activity_matches)
        key_risks.append({
            "risk": f"{len(new_activity_matches)} activity(ies) detected on-site with no matching schedule entry "
                    f"({names}) - may indicate scope creep or an outdated schedule.",
            "severity": "Low",
        })
        actions.append("Review newly detected site activities and add to the schedule if legitimate.")

    # Low/medium-confidence matches pending human review
    pending_review_count = (
        db.query(VerificationQueue)
        .join(ActivityMatch, VerificationQueue.match_id == ActivityMatch.id)
        .filter(ActivityMatch.site_report_id == site_report_id)
        .filter(VerificationQueue.reviewer_status == "Pending")
        .count()
    )
    if pending_review_count:
        key_risks.append({
            "risk": f"{pending_review_count} activity match(es) require human verification before being trusted.",
            "severity": "Low",
        })

    # --- Overall risk rollup ---
    severities = [r["severity"] for r in key_risks]
    if "High" in severities:
        overall_risk = "High"
    elif "Medium" in severities:
        overall_risk = "Medium"
    elif severities:
        overall_risk = "Low"
    else:
        overall_risk = "Low"

    delayed_count = sum(1 for r in progress_results if r["delay_status"] == "Delayed")
    at_risk_count = sum(1 for r in progress_results if r["delay_status"] == "At Risk")
    on_track_count = sum(1 for r in progress_results if r["delay_status"] == "On Track")

    if key_risks:
        summary = (
            f"{delayed_count} activity(ies) delayed and {at_risk_count} at risk out of "
            f"{len(progress_results)} matched activities. {on_track_count} on track. "
            f"Overall project risk assessed as {overall_risk}."
        )
    else:
        summary = f"All {len(progress_results)} matched activities are on track. No significant risks detected."

    if not actions:
        actions.append("Continue routine monitoring - no immediate action required.")

    logger.info(f"[ProjectSync] Risk analysis completed: overall_risk={overall_risk}, {len(key_risks)} risks identified")

    return {
        "overall_risk": overall_risk,
        "summary": summary,
        "key_risks": key_risks,
        "recommended_actions": actions,
    }

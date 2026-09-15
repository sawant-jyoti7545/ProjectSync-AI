"""
ProjectSync AI - Schedule Matcher

Compares activities extracted from a site report against the planned
project schedule and produces a confidence-scored match for each,
per spec section 3.E.

Matching signal:
    1. Exact activity_id match  -> very high confidence immediately
    2. Otherwise, a weighted blend of:
        - fuzzy name similarity (difflib.SequenceMatcher - stdlib,
          no extra dependency needed)
        - location match (case-insensitive exact match)

Confidence bands (thresholds are configurable in config.py, not
hardcoded here):
    >= HIGH_CONFIDENCE_THRESHOLD (default 0.85)   -> Matched
    >= MEDIUM_CONFIDENCE_THRESHOLD (default 0.60) -> Needs Review
    < MEDIUM_CONFIDENCE_THRESHOLD or no candidates -> New Activity Detected

The system deliberately does NOT force a match for every site activity -
low-confidence results are routed to the verification queue instead of
being silently accepted, per spec section 3.E ("must NOT blindly claim
every match is correct").
"""

import re
import logging
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from models import Activity, ActivityMatch, VerificationQueue

logger = logging.getLogger("ProjectSync")

# Weight given to name similarity vs location match when there's no
# exact activity_id hit. Tunable, kept in one place.
_NAME_WEIGHT = 0.75
_LOCATION_WEIGHT = 0.25

# Confidence assigned immediately on an exact activity_id match.
_EXACT_ID_CONFIDENCE = 0.98


def _normalize(text: Optional[str]) -> str:
    """Lowercase, strip punctuation/extra whitespace for fair comparison."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[–—\-_/,.]", " ", text)  # treat dashes/punctuation as spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _score_candidate(site_activity: dict, scheduled: Activity) -> float:
    """Returns a 0.0-1.0 confidence score for one (site, scheduled) pair."""
    site_id = (site_activity.get("activity_id") or "").strip().upper()
    sched_id = (scheduled.activity_id or "").strip().upper()

    if site_id and sched_id and site_id == sched_id:
        return _EXACT_ID_CONFIDENCE

    name_sim = _name_similarity(site_activity.get("activity"), scheduled.activity_name)

    site_loc = _normalize(site_activity.get("location"))
    sched_loc = _normalize(scheduled.location)
    loc_match = 1.0 if site_loc and sched_loc and site_loc == sched_loc else 0.0

    return round((_NAME_WEIGHT * name_sim) + (_LOCATION_WEIGHT * loc_match), 4)


def _classify(score: float) -> str:
    if score >= settings.HIGH_CONFIDENCE_THRESHOLD:
        return "Matched"
    if score >= settings.MEDIUM_CONFIDENCE_THRESHOLD:
        return "Needs Review"
    return "New Activity"


def match_activities(db: Session, site_report_id: int, project_id: int, extracted_activities: list[dict]) -> list[dict]:
    """
    Matches every extracted site activity against the project's scheduled
    activities. Persists an ActivityMatch row for each, plus a
    VerificationQueue row for anything below high confidence.

    Returns a summary list (for the API response) - one dict per match.
    """
    scheduled_activities = db.query(Activity).filter(Activity.project_id == project_id).all()

    results = []
    matched_count = 0
    review_count = 0
    new_count = 0

    for site_activity in extracted_activities:
        best_activity = None
        best_score = 0.0

        for scheduled in scheduled_activities:
            score = _score_candidate(site_activity, scheduled)
            if score > best_score:
                best_score = score
                best_activity = scheduled

        status = _classify(best_score) if best_activity else "New Activity"
        if status == "New Activity":
            best_score = 0.0 if not best_activity else best_score
            best_activity_for_record = None
        else:
            best_activity_for_record = best_activity

        planned = best_activity.planned_progress if best_activity_for_record else None
        actual = site_activity.get("actual_progress")
        variance = round(actual - planned, 2) if (planned is not None and actual is not None) else None

        match = ActivityMatch(
            site_report_id=site_report_id,
            activity_id_fk=best_activity_for_record.id if best_activity_for_record else None,
            site_activity_name=site_activity.get("activity") or "Unnamed Activity",
            matched_activity_name=best_activity_for_record.activity_name if best_activity_for_record else None,
            confidence=best_score,
            match_status=status,
            planned_progress=planned,
            actual_progress=actual,
            variance=variance,
        )
        db.add(match)
        db.flush()  # get match.id

        reason = None
        if status == "Needs Review":
            review_count += 1
            reason = (
                f"Moderate similarity to '{best_activity.activity_name}' "
                f"(confidence {best_score:.2f}) - name or location did not fully align."
            )
            db.add(VerificationQueue(match_id=match.id, reason=reason, reviewer_status="Pending"))
        elif status == "Matched":
            matched_count += 1
        else:  # New Activity
            new_count += 1
            reason = "No scheduled activity found with sufficient similarity."
            db.add(VerificationQueue(match_id=match.id, reason=reason, reviewer_status="Pending"))

        results.append({
            "match_id": match.id,
            "site_activity": match.site_activity_name,
            "scheduled_activity": match.matched_activity_name,
            "confidence": match.confidence,
            "match_status": match.match_status,
            "planned_progress": match.planned_progress,
            "actual_progress": match.actual_progress,
            "variance": match.variance,
            "reason": reason,
        })

    db.commit()

    logger.info(
        f"[ProjectSync] Schedule matching complete: {matched_count} matched, "
        f"{review_count} need review, {new_count} new activities detected"
    )

    return results

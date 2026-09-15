"""
ProjectSync AI - Progress Analyzer

Classifies delay status for every matched activity based on variance
(actual_progress - planned_progress), per spec section 3.G.

Thresholds are read from config.py, NOT hardcoded here, so they can be
tuned without touching code:

    variance >= 0                    -> On Track
    AT_RISK_VARIANCE <= variance < 0 -> At Risk   (default: -10 to -1)
    variance < DELAYED_VARIANCE      -> Delayed   (default: < -10)
"""

import logging
from sqlalchemy.orm import Session

from config import settings
from models import ActivityMatch

logger = logging.getLogger("ProjectSync")


def classify_variance(variance: float) -> str:
    """Pure classification function - variance in, status out. Easy to unit test."""
    if variance is None:
        return "Unknown"
    if variance >= 0:
        return "On Track"
    if variance >= settings.AT_RISK_VARIANCE:  # e.g. -10 <= variance < 0
        return "At Risk"
    return "Delayed"  # variance < AT_RISK_VARIANCE (e.g. < -10)


def analyze_progress(db: Session, site_report_id: int) -> list[dict]:
    """
    Runs delay classification over every Matched activity from this site
    report and updates the underlying scheduled Activity's status/actual
    progress so the schedule reflects site reality going forward.

    Returns a summary list for the API response.
    """
    matches = (
        db.query(ActivityMatch)
        .filter(ActivityMatch.site_report_id == site_report_id)
        .filter(ActivityMatch.match_status == "Matched")
        .all()
    )

    results = []
    on_track = at_risk = delayed = 0

    for match in matches:
        status = classify_variance(match.variance)

        if status == "On Track":
            on_track += 1
        elif status == "At Risk":
            at_risk += 1
        elif status == "Delayed":
            delayed += 1

        # Push the site-reality actual_progress and computed status back
        # onto the scheduled activity, so /activities reflects reality.
        if match.activity:
            match.activity.actual_progress = match.actual_progress
            match.activity.status = status

        results.append({
            "match_id": match.id,
            "activity": match.matched_activity_name,
            "planned_progress": match.planned_progress,
            "actual_progress": match.actual_progress,
            "variance": match.variance,
            "delay_status": status,
        })

    db.commit()

    logger.info(
        f"[ProjectSync] Progress analysis complete: "
        f"{on_track} on track, {at_risk} at risk, {delayed} delayed"
    )

    return results

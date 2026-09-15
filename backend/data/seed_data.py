"""
ProjectSync AI - Seed data

Populates the database with a realistic demo project so the app is
immediately demoable after setup, per spec section 9 (Demo Mode).

This is called automatically on startup (see main.py) ONLY if the
projects table is empty - it will never duplicate or overwrite data
on subsequent runs.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import Project, Activity

logger = logging.getLogger("ProjectSync")

# Base date used to generate realistic planned_start/planned_end windows
_TODAY = datetime(2026, 9, 10)


def _days(offset: int) -> datetime:
    return _TODAY + timedelta(days=offset)


# Each tuple: (activity_id, name, location, start_offset, end_offset,
#              planned_progress, actual_progress, dependencies, status)
_SAMPLE_ACTIVITIES = [
    ("L5-EXC-001", "Excavation – Block A", "Block A", -30, -5, 80, 75, None, "On Track"),
    ("L5-FND-002", "Foundation – Block B", "Block B", -25, 5, 50, 40, "L5-EXC-001", "At Risk"),
    ("L6-PIP-023", "Piping – Section C", "Section C", -15, 15, 30, 25, "L5-FND-002", "At Risk"),
    ("L6-ELE-004", "Electrical Installation", "Block A", -10, 20, 20, 15, "L5-EXC-001", "At Risk"),
    ("L7-STR-005", "Structural Work", "Block B", -20, 10, 45, 45, "L5-FND-002", "On Track"),
    ("L7-EQP-006", "Equipment Installation", "Block C", -5, 25, 15, 8, "L7-STR-005", "Delayed"),
    ("L8-TST-007", "Pipeline Testing", "Section C", 5, 30, 0, 0, "L6-PIP-023", "Not Started"),
    ("L4-MAT-008", "Material Delivery", "Site Yard", -35, -20, 100, 90, None, "On Track"),
    ("L7-WLD-009", "Welding", "Section C", -10, 15, 35, 20, "L6-PIP-023", "Delayed"),
    ("L9-CMS-010", "Commissioning", "Block A", 20, 45, 0, 0, "L8-TST-007", "Not Started"),
]


def seed_if_empty(db: Session) -> None:
    """
    Seeds the demo project + schedule ONLY if no projects exist yet.
    Safe to call on every startup.
    """
    existing = db.query(Project).first()
    if existing:
        logger.info("[ProjectSync] Seed skipped - data already present")
        return

    logger.info("[ProjectSync] No data found - seeding demo project")

    project = Project(
        name="Oil India Infrastructure Project",
        description=(
            "Demo infrastructure project used to showcase ProjectSync AI's "
            "schedule-vs-site-reality monitoring capabilities."
        ),
        health="At Risk",
    )
    db.add(project)
    db.flush()  # get project.id without committing yet

    for (
        activity_id, name, location, start_off, end_off,
        planned, actual, deps, status
    ) in _SAMPLE_ACTIVITIES:
        db.add(Activity(
            project_id=project.id,
            activity_id=activity_id,
            activity_name=name,
            location=location,
            planned_start=_days(start_off),
            planned_end=_days(end_off),
            planned_progress=planned,
            actual_progress=actual,
            dependencies=deps,
            status=status,
            is_new_activity=0,
        ))

    db.commit()
    logger.info(f"[ProjectSync] Seeded 1 project and {len(_SAMPLE_ACTIVITIES)} scheduled activities")

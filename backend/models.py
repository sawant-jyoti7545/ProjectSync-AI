"""
ProjectSync AI - Database models
Defines the 7 core tables and their relationships. No data lives here -
this is schema only. Seed data is created separately in Phase 2
(data/seed_data.py) so the schema and the demo dataset stay decoupled.
"""

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Project(Base):
    """A single construction/infrastructure project (e.g. 'Oil India Infrastructure Project')."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    health = Column(String, default="On Track")  # On Track / At Risk / Delayed
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    activities = relationship("Activity", back_populates="project", cascade="all, delete-orphan")
    site_reports = relationship("SiteReport", back_populates="project", cascade="all, delete-orphan")


class Activity(Base):
    """A scheduled activity from the planned project schedule."""
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)

    activity_id = Column(String, unique=True, index=True, nullable=False)  # e.g. L5-EXC-001
    activity_name = Column(String, nullable=False)
    location = Column(String, nullable=True)

    planned_start = Column(DateTime, nullable=True)
    planned_end = Column(DateTime, nullable=True)
    planned_progress = Column(Float, default=0.0)
    actual_progress = Column(Float, default=0.0)

    dependencies = Column(String, nullable=True)  # comma-separated activity_ids
    status = Column(String, default="Not Started")  # On Track / At Risk / Delayed / Completed

    is_new_activity = Column(Integer, default=0)  # 1 if detected from site report, not original schedule

    project = relationship("Project", back_populates="activities")
    matches = relationship("ActivityMatch", back_populates="activity", cascade="all, delete-orphan")


class SiteReport(Base):
    """A single uploaded site report (PDF/Excel/CSV) and its extraction metadata."""
    __tablename__ = "site_reports"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)

    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # pdf / xlsx / csv
    report_date = Column(DateTime, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    raw_extracted_json = Column(Text, nullable=True)  # full structured extraction, stored for audit/debug
    status = Column(String, default="Uploaded")  # Uploaded / Processing / Processed / Failed

    project = relationship("Project", back_populates="site_reports")
    matches = relationship("ActivityMatch", back_populates="site_report", cascade="all, delete-orphan")


class ActivityMatch(Base):
    """Result of matching one site-report activity against one scheduled activity."""
    __tablename__ = "activity_matches"

    id = Column(Integer, primary_key=True, index=True)
    site_report_id = Column(Integer, ForeignKey("site_reports.id"), nullable=False)
    activity_id_fk = Column(Integer, ForeignKey("activities.id"), nullable=True)  # null if unmatched/new

    site_activity_name = Column(String, nullable=False)
    matched_activity_name = Column(String, nullable=True)

    confidence = Column(Float, default=0.0)
    match_status = Column(String, default="Pending")  # Matched / Needs Review / New Activity / Rejected

    planned_progress = Column(Float, nullable=True)
    actual_progress = Column(Float, nullable=True)
    variance = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    site_report = relationship("SiteReport", back_populates="matches")
    activity = relationship("Activity", back_populates="matches")
    verification = relationship("VerificationQueue", back_populates="match", uselist=False, cascade="all, delete-orphan")


class VerificationQueue(Base):
    """Holds matches that need human confirmation (medium/low confidence)."""
    __tablename__ = "verification_queue"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("activity_matches.id"), nullable=False, unique=True)

    reason = Column(String, nullable=True)  # why it needs review, e.g. "Low name similarity"
    reviewer_status = Column(String, default="Pending")  # Pending / Confirmed / Rejected
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_note = Column(Text, nullable=True)

    match = relationship("ActivityMatch", back_populates="verification")


class Risk(Base):
    """AI/rule-identified project risk."""
    __tablename__ = "risks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    activity_id_fk = Column(Integer, ForeignKey("activities.id"), nullable=True)

    risk_description = Column(Text, nullable=False)
    severity = Column(String, default="Low")  # Low / Medium / High
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """System-wide event log for traceability (Audit Trail page)."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    action = Column(String, nullable=False)      # e.g. "Report Uploaded", "Match Confirmed"
    activity_ref = Column(String, nullable=True)  # activity_id or name, for quick reference
    user = Column(String, default="system")       # will map to real users later; "system" for automated actions
    details = Column(Text, nullable=True)

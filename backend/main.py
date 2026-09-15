"""
ProjectSync AI - Backend entrypoint

Full backend for ProjectSync AI: report upload/extraction, schedule
matching, progress/risk analysis (rule-based + optional real AI),
dashboard aggregation, activity detail lookup, verification actions,
and audit logging.

    GET  /                          -> basic API info
    GET  /health                    -> health check for frontend "backend unavailable" detection
    GET  /activities                -> lists scheduled activities
    GET  /activities/{activity_id}  -> single activity detail with AI explanation
    POST /upload                    -> full pipeline: extract -> match -> analyze -> risk
    POST /ai-risk-analysis          -> re-run analysis for an existing report
    GET  /dashboard                 -> aggregated dashboard statistics (never hardcoded)
    GET  /verification              -> pending verification queue
    POST /verification/{match_id}/confirm -> confirm a queued match
    POST /verification/{match_id}/reject  -> reject a queued match
    GET  /insights                  -> AI insight strings built from real data
    GET  /audit-log                 -> system event history
"""

import logging
import os
import shutil
import uuid
import json
from datetime import datetime

from fastapi import FastAPI, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from config import settings
from database import init_db, get_db, SessionLocal
from schemas import APIResponse, HealthResponse
from models import Activity, Project, SiteReport, AuditLog, VerificationQueue, ActivityMatch, Risk
from pydantic import BaseModel
from data.seed_data import seed_if_empty
from services.pdf_extractor import extract_from_pdf, parse_report_text, PDFExtractionError
from services.excel_extractor import extract_from_excel, ExcelExtractionError
from services.schedule_matcher import match_activities
from services.progress_analyzer import analyze_progress, classify_variance
from services.risk_analyzer import analyze_risk
from services import ai_service


# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("ProjectSync")

# --- App instance ---
app = FastAPI(
    title="ProjectSync AI",
    description="AI-powered construction/project monitoring and synchronization platform.",
    version="0.1.0",
)

# --- CORS ---
# Explicit origin list from config (never a bare "*" since we may use
# credentials later for auth). Add your Live Server port to .env if different.
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://projectsync-ai.pages.dev",
        "https://projectsync-ai-1.pages.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    logger.info(f"[ProjectSync] Starting in '{settings.ENV}' mode | AI_MODE={settings.AI_MODE}")
    init_db()

    # Seed demo data if the database is empty, so the app is demoable
    # immediately after setup (spec section 9 - Demo Mode).
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@app.get("/", response_model=APIResponse, tags=["System"])
def root():
    return APIResponse(
        success=True,
        data={
            "app": settings.APP_NAME,
            "message": "ProjectSync AI backend is running. Visit /docs for API documentation.",
        },
    )


@app.get("/health", response_model=APIResponse, tags=["System"])
def health():
    """
    Used by the frontend on every page load to confirm the backend is
    reachable before attempting any real data requests. If this fails,
    the frontend should show 'Backend unavailable' rather than blank/zero data.
    """
    payload = HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        env=settings.ENV,
        ai_mode=settings.AI_MODE,
    )
    return APIResponse(success=True, data=payload.model_dump())


@app.get("/activities", response_model=APIResponse, tags=["Schedule"])
def list_activities(db: Session = Depends(get_db)):
    """
    Returns all scheduled activities for the demo project, straight from
    the database - this is how you verify seeding worked. The full
    matching/verification/dashboard endpoints are built in later phases;
    this is a Phase 2 read-only check.
    """
    try:
        activities = db.query(Activity).all()
        data = [
            {
                "activity_id": a.activity_id,
                "activity_name": a.activity_name,
                "location": a.location,
                "planned_progress": a.planned_progress,
                "actual_progress": a.actual_progress,
                "variance": round(a.actual_progress - a.planned_progress, 2),
                "status": a.status,
                "dependencies": a.dependencies,
            }
            for a in activities
        ]
        return APIResponse(success=True, data=data)
    except Exception as e:
        logger.error(f"[ProjectSync] Failed to fetch activities: {e}")
        return APIResponse(success=False, error="Unable to load project data.")


def _log_audit(db: Session, action: str, activity_ref: str = None, details: str = None):
    """Small helper so every important event gets recorded to the audit trail (spec section 4/J)."""
    db.add(AuditLog(action=action, activity_ref=activity_ref, user="system", details=details))
    db.commit()


def _persist_risks(db: Session, project_id: int, risk_data: dict):
    """Writes each key risk from the analysis into the risks table for historical tracking."""
    for r in risk_data.get("key_risks", []):
        db.add(Risk(project_id=project_id, risk_description=r["risk"], severity=r["severity"]))
    db.commit()


def _run_pipeline_on_result(db: Session, project: Project, site_report: SiteReport, result: dict) -> APIResponse:
    """
    The shared core: given an already-extracted structured result (from
    PDF, sample, or voice), runs matching -> progress -> risk and stores
    everything. Used by every input source so they all produce identical
    downstream behavior.
    """
    site_report.status = "Processed"
    site_report.raw_extracted_json = json.dumps(result)
    if result.get("report_date"):
        try:
            site_report.report_date = datetime.strptime(result["report_date"], "%Y-%m-%d")
        except ValueError:
            pass
    db.commit()

    _log_audit(db, "Report Processed", details=f"{len(result['activities'])} activities extracted")

    logger.info("[ProjectSync] Schedule matching started")
    matches = match_activities(
        db=db,
        site_report_id=site_report.id,
        project_id=project.id,
        extracted_activities=result["activities"],
    )
    matched_n = sum(1 for m in matches if m["match_status"] == "Matched")
    review_n = sum(1 for m in matches if m["match_status"] == "Needs Review")
    new_n = sum(1 for m in matches if m["match_status"] == "New Activity")
    _log_audit(
        db, "Activities Matched",
        details=f"{matched_n} matched, {review_n} need review, {new_n} new activities detected",
    )

    logger.info("[ProjectSync] Calculating progress and delay status")
    progress_results = analyze_progress(db, site_report.id)

    logger.info(f"[ProjectSync] Running AI risk analysis (AI_MODE={settings.AI_MODE})")
    rule_based_risk = analyze_risk(db, project.id, site_report.id, progress_results)
    risk_data = ai_service.enhance_risk_analysis(rule_based_risk, project.name, progress_results)
    _persist_risks(db, project.id, risk_data)
    _log_audit(db, "Risk Analysis Completed", details=f"overall_risk={risk_data['overall_risk']} (mode={settings.AI_MODE})")
    logger.info("[ProjectSync] Risk analysis completed")

    return APIResponse(success=True, data={
        "site_report_id": site_report.id,
        "project": result.get("project"),
        "report_date": result.get("report_date"),
        "extracted_activities": result["activities"],
        "matches": matches,
        "summary": {
            "total": len(matches),
            "matched": matched_n,
            "needs_review": review_n,
            "new_activities": new_n,
        },
        "progress_analysis": progress_results,
        "risk_analysis": risk_data,
    })


def _process_report_file(db: Session, project: Project, save_path: str, filename: str, ext: str) -> APIResponse:
    """
    Runs the full pipeline (extract -> match -> progress -> risk) for an
    already-saved report file - PDF, Excel (.xlsx/.xls), or CSV. Shared
    by /upload (user-provided file) and /upload-sample (the bundled demo
    report).
    """
    site_report = SiteReport(
        project_id=project.id,
        filename=filename,
        file_type=ext.lstrip("."),
        status="Processing",
    )
    db.add(site_report)
    db.commit()
    db.refresh(site_report)
    _log_audit(db, "Report Uploaded", details=filename)

    try:
        if ext == ".pdf":
            logger.info("[ProjectSync] PDF extraction started")
            result = extract_from_pdf(save_path)
        else:
            logger.info(f"[ProjectSync] Spreadsheet extraction started ({ext})")
            result = extract_from_excel(save_path, ext)

        logger.info(f"[ProjectSync] {len(result['activities'])} activities extracted")
        return _run_pipeline_on_result(db, project, site_report, result)

    except (PDFExtractionError, ExcelExtractionError) as e:
        logger.error(f"[ProjectSync] Extraction failed: {e}")
        site_report.status = "Failed"
        db.commit()
        _log_audit(db, "Report Processing Failed", details=str(e))
        return APIResponse(success=False, error=str(e))

    except Exception as e:
        logger.error(f"[ProjectSync] Unexpected extraction error: {e}")
        site_report.status = "Failed"
        db.commit()
        _log_audit(db, "Report Processing Failed", details=str(e))
        return APIResponse(success=False, error="Unable to extract activities from report.")


@app.post("/upload", response_model=APIResponse, tags=["Reports"])
async def upload_report(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accepts a site report file, validates it, saves it, and runs it
    through the full pipeline (PDF only for now - Excel/CSV come in a
    later build).

    Errors are returned as {success: false, error: "..."} with proper
    HTTP semantics per spec section 12 (Error Handling) - the frontend
    should surface `error` directly rather than guessing.
    """
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        return APIResponse(success=False, error=f"Unsupported file type '{ext}'. Allowed: PDF, XLSX, XLS, CSV.")

    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    save_path = os.path.join(settings.UPLOAD_DIR, safe_name)
    try:
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        logger.error(f"[ProjectSync] Failed to save upload: {e}")
        return APIResponse(success=False, error="Unable to save uploaded file.")

    size_mb = os.path.getsize(save_path) / (1024 * 1024)
    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        os.remove(save_path)
        return APIResponse(success=False, error=f"File too large ({size_mb:.1f}MB). Max is {settings.MAX_UPLOAD_SIZE_MB}MB.")

    logger.info(f"[ProjectSync] Report uploaded: {filename} -> {safe_name}")

    project = db.query(Project).first()
    if not project:
        return APIResponse(success=False, error="No project exists yet. Please seed the database first.")

    return _process_report_file(db, project, save_path, filename, ext)


@app.post("/upload-sample", response_model=APIResponse, tags=["Reports"])
def upload_sample_report(db: Session = Depends(get_db)):
    """
    Runs the bundled demo report (backend/data/sample_report.pdf)
    through the exact same pipeline as a real upload - lets the "Use
    Sample Report" button work with one click instead of asking the
    user to manually browse to a file on disk (browsers can't
    pre-select a file for security reasons).
    """
    project = db.query(Project).first()
    if not project:
        return APIResponse(success=False, error="No project exists yet. Please seed the database first.")

    sample_path = os.path.join("data", "sample_report.pdf")
    if not os.path.exists(sample_path):
        return APIResponse(success=False, error="Sample report not found on the server.")

    return _process_report_file(db, project, sample_path, "sample_report.pdf", ".pdf")


class VoiceUploadRequest(BaseModel):
    transcript: str


@app.post("/upload-voice", response_model=APIResponse, tags=["Reports"])
def upload_voice_report(payload: VoiceUploadRequest, db: Session = Depends(get_db)):
    """
    Accepts a voice-dictated site report transcript (captured client-side
    via the browser's speech recognition), extracts structured activity
    data from it, and runs it through the same pipeline as a PDF upload.

    Uses AI-based free-form extraction when AI_MODE=real (since dictated
    speech won't have clean labeled fields), falling back to the same
    regex parser PDFs use if AI is unavailable or the transcript happens
    to follow the structured format.
    """
    transcript = (payload.transcript or "").strip()
    if not transcript:
        return APIResponse(success=False, error="No transcript received. Please dictate your report before analyzing.")
    if len(transcript) < 20:
        return APIResponse(success=False, error="Transcript is too short to contain a meaningful report.")

    project = db.query(Project).first()
    if not project:
        return APIResponse(success=False, error="No project exists yet. Please seed the database first.")

    site_report = SiteReport(
        project_id=project.id,
        filename="Voice Input",
        file_type="voice",
        status="Processing",
    )
    db.add(site_report)
    db.commit()
    db.refresh(site_report)
    _log_audit(db, "Report Uploaded", details="Voice input transcript")

    try:
        logger.info("[ProjectSync] Voice transcript extraction started")
        result = ai_service.extract_activities_from_text(
            transcript,
            fallback_parser=lambda t: parse_report_text(t, source_label="voice transcript"),
        )
        if not result.get("activities"):
            raise PDFExtractionError("Unable to extract activities from voice transcript.")
        logger.info(f"[ProjectSync] {len(result['activities'])} activities extracted from voice input")
        return _run_pipeline_on_result(db, project, site_report, result)

    except PDFExtractionError as e:
        logger.error(f"[ProjectSync] Voice extraction failed: {e}")
        site_report.status = "Failed"
        db.commit()
        _log_audit(db, "Report Processing Failed", details=str(e))
        return APIResponse(success=False, error=str(e))

    except Exception as e:
        logger.error(f"[ProjectSync] Unexpected voice extraction error: {e}")
        site_report.status = "Failed"
        db.commit()
        _log_audit(db, "Report Processing Failed", details=str(e))
        return APIResponse(success=False, error="Unable to extract activities from voice transcript.")


@app.get("/verification", response_model=APIResponse, tags=["Verification"])
def list_verification_queue(db: Session = Depends(get_db)):
    """
    Returns all pending verification items (medium-confidence 'Needs
    Review' matches AND low-confidence 'New Activity' detections), per
    spec section 3.J. Confirm/reject actions are added in Phase 9.
    """
    try:
        pending = (
            db.query(VerificationQueue)
            .join(ActivityMatch, VerificationQueue.match_id == ActivityMatch.id)
            .filter(VerificationQueue.reviewer_status == "Pending")
            .all()
        )
        data = [
            {
                "verification_id": v.id,
                "match_id": v.match.id,
                "site_activity": v.match.site_activity_name,
                "possible_scheduled_activity": v.match.matched_activity_name,
                "confidence": v.match.confidence,
                "match_status": v.match.match_status,
                "planned_progress": v.match.planned_progress,
                "actual_progress": v.match.actual_progress,
                "variance": v.match.variance,
                "reason": v.reason,
            }
            for v in pending
        ]
        return APIResponse(success=True, data=data)
    except Exception as e:
        logger.error(f"[ProjectSync] Failed to fetch verification queue: {e}")
        return APIResponse(success=False, error="Unable to load verification queue.")


class RiskAnalysisRequest(BaseModel):
    site_report_id: int


@app.post("/ai-risk-analysis", response_model=APIResponse, tags=["Analysis"])
def rerun_risk_analysis(payload: RiskAnalysisRequest, db: Session = Depends(get_db)):
    """
    Re-runs progress + risk analysis for an already-uploaded site report,
    without needing to re-upload the file. Useful for re-checking risk
    after verification decisions change which matches are trusted.
    """
    site_report = db.query(SiteReport).filter(SiteReport.id == payload.site_report_id).first()
    if not site_report:
        return APIResponse(success=False, error=f"No site report found with id {payload.site_report_id}.")

    try:
        progress_results = analyze_progress(db, site_report.id)
        rule_based_risk = analyze_risk(db, site_report.project_id, site_report.id, progress_results)
        risk_data = ai_service.enhance_risk_analysis(rule_based_risk, site_report.project.name, progress_results)
        _persist_risks(db, site_report.project_id, risk_data)
        _log_audit(db, "Risk Analysis Completed", details=f"overall_risk={risk_data['overall_risk']} (mode={settings.AI_MODE})")

        return APIResponse(success=True, data={
            "site_report_id": site_report.id,
            "progress_analysis": progress_results,
            "risk_analysis": risk_data,
        })
    except Exception as e:
        logger.error(f"[ProjectSync] Risk analysis failed: {e}")
        return APIResponse(success=False, error="Unable to complete risk analysis.")


@app.get("/dashboard", response_model=APIResponse, tags=["Dashboard"])
def get_dashboard(db: Session = Depends(get_db)):
    """
    Returns everything the dashboard page needs in one call, computed
    live from the database every time - nothing here is hardcoded.
    """
    try:
        project = db.query(Project).first()
        if not project:
            return APIResponse(success=False, error="No project exists yet. Upload a site report to get started.")

        activities = db.query(Activity).filter(Activity.project_id == project.id).all()
        total = len(activities)
        completed = sum(1 for a in activities if (a.actual_progress or 0) >= 100)
        delayed = sum(1 for a in activities if a.status == "Delayed")
        at_risk = sum(1 for a in activities if a.status == "At Risk")

        pending_verification = (
            db.query(VerificationQueue)
            .filter(VerificationQueue.reviewer_status == "Pending")
            .count()
        )

        avg_planned = round(sum(a.planned_progress or 0 for a in activities) / total, 1) if total else 0
        avg_actual = round(sum(a.actual_progress or 0 for a in activities) / total, 1) if total else 0
        variance = round(avg_actual - avg_planned, 1)

        # Project health rolls up from activity delay status - never a fixed label.
        if delayed > 0:
            health = "Delayed"
        elif at_risk > 0:
            health = "At Risk"
        else:
            health = "On Track"

        # Recent site updates: latest matches across all reports for this project
        recent_matches = (
            db.query(ActivityMatch)
            .join(SiteReport, ActivityMatch.site_report_id == SiteReport.id)
            .filter(SiteReport.project_id == project.id)
            .order_by(desc(ActivityMatch.created_at))
            .limit(10)
            .all()
        )
        recent_updates = [
            {
                "activity": m.site_activity_name,
                "activity_id": m.activity.activity_id if m.activity else None,
                "actual_progress": m.actual_progress,
                "updated": m.created_at.isoformat() if m.created_at else None,
                "confidence": m.confidence,
                "status": m.match_status,
            }
            for m in recent_matches
        ]

        insights = _build_insights(db, project.id)

        return APIResponse(success=True, data={
            "project_name": project.name,
            "project_health": health,
            "total_activities": total,
            "completed_activities": completed,
            "delayed_activities": delayed,
            "activities_needing_verification": pending_verification,
            "overall_execution_pct": avg_actual,
            "planned_pct": avg_planned,
            "actual_pct": avg_actual,
            "variance": variance,
            "recent_site_updates": recent_updates,
            "ai_insights": insights,
        })

    except Exception as e:
        logger.error(f"[ProjectSync] Failed to build dashboard: {e}")
        return APIResponse(success=False, error="Unable to load project data.")


@app.get("/activities/{activity_id}", response_model=APIResponse, tags=["Schedule"])
def get_activity_detail(activity_id: str, db: Session = Depends(get_db)):
    """
    Returns full detail for a single scheduled activity, including the
    most recent match/confidence and a plain-language explanation of
    its current status - built from real data, not a canned string.
    """
    try:
        activity = db.query(Activity).filter(Activity.activity_id == activity_id).first()
        if not activity:
            return APIResponse(success=False, error=f"No activity found with id '{activity_id}'.")

        latest_match = (
            db.query(ActivityMatch)
            .filter(ActivityMatch.activity_id_fk == activity.id)
            .order_by(desc(ActivityMatch.created_at))
            .first()
        )

        issues = None
        if latest_match and latest_match.site_report and latest_match.site_report.raw_extracted_json:
            try:
                extraction = json.loads(latest_match.site_report.raw_extracted_json)
                for a in extraction.get("activities", []):
                    if a.get("activity") == latest_match.site_activity_name:
                        issues = a.get("issues")
                        break
            except (json.JSONDecodeError, TypeError):
                pass

        variance = round(activity.actual_progress - activity.planned_progress, 2)
        explanation = (
            f"{activity.activity_name} is at {activity.actual_progress}% actual progress against "
            f"{activity.planned_progress}% planned ({variance:+.0f}% variance), currently classified as "
            f"{activity.status}."
        )
        if issues and issues.lower() != "none reported.":
            explanation += f" Reported issue: {issues}"

        recommended_action = (
            "Expedite resources and escalate to project control." if activity.status == "Delayed"
            else "Monitor closely - trending behind plan." if activity.status == "At Risk"
            else "No action required - on track."
        )

        return APIResponse(success=True, data={
            "activity_id": activity.activity_id,
            "activity_name": activity.activity_name,
            "location": activity.location,
            "planned_progress": activity.planned_progress,
            "actual_progress": activity.actual_progress,
            "variance": variance,
            "planned_start": activity.planned_start.isoformat() if activity.planned_start else None,
            "planned_end": activity.planned_end.isoformat() if activity.planned_end else None,
            "status": activity.status,
            "dependencies": activity.dependencies,
            "ai_confidence": latest_match.confidence if latest_match else None,
            "issues": issues,
            "ai_explanation": explanation,
            "recommended_action": recommended_action,
        })

    except Exception as e:
        logger.error(f"[ProjectSync] Failed to load activity detail: {e}")
        return APIResponse(success=False, error="Unable to load activity details.")


def _build_insights(db: Session, project_id: int) -> list[str]:
    """
    Builds plain-language insight strings from live data, per spec
    section 3.K - every number here is a real query, nothing canned.
    """
    insights = []

    pending = db.query(VerificationQueue).filter(VerificationQueue.reviewer_status == "Pending").count()
    if pending:
        insights.append(f"{pending} activity match(es) require verification.")

    matched = (
        db.query(ActivityMatch)
        .join(SiteReport, ActivityMatch.site_report_id == SiteReport.id)
        .filter(SiteReport.project_id == project_id)
        .filter(ActivityMatch.match_status == "Matched")
        .count()
    )
    if matched:
        insights.append(f"{matched} activities successfully matched to the schedule.")

    new_activities = (
        db.query(ActivityMatch)
        .join(SiteReport, ActivityMatch.site_report_id == SiteReport.id)
        .filter(SiteReport.project_id == project_id)
        .filter(ActivityMatch.match_status == "New Activity")
        .count()
    )
    if new_activities:
        insights.append(f"{new_activities} new activity(ies) detected that aren't in the original schedule.")

    delayed = db.query(Activity).filter(Activity.project_id == project_id, Activity.status == "Delayed").count()
    if delayed:
        insights.append(f"{delayed} activity(ies) are significantly behind schedule.")

    top_risk = (
        db.query(Risk)
        .filter(Risk.project_id == project_id, Risk.severity == "High")
        .order_by(desc(Risk.created_at))
        .first()
    )
    if top_risk:
        insights.append(top_risk.risk_description)

    if not insights:
        insights.append("No significant issues detected. All activities on track.")

    return insights


@app.get("/insights", response_model=APIResponse, tags=["Analysis"])
def get_insights(db: Session = Depends(get_db)):
    """Returns AI insight strings for the AI Insights page, built from live data."""
    try:
        project = db.query(Project).first()
        if not project:
            return APIResponse(success=False, error="No project exists yet.")
        return APIResponse(success=True, data={"insights": _build_insights(db, project.id)})
    except Exception as e:
        logger.error(f"[ProjectSync] Failed to build insights: {e}")
        return APIResponse(success=False, error="Unable to load insights.")


@app.get("/audit-log", response_model=APIResponse, tags=["Audit"])
def get_audit_log(db: Session = Depends(get_db)):
    """Returns the full system audit trail, most recent first."""
    try:
        logs = db.query(AuditLog).order_by(desc(AuditLog.timestamp)).limit(200).all()
        data = [
            {
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "action": log.action,
                "activity": log.activity_ref,
                "user": log.user,
                "details": log.details,
            }
            for log in logs
        ]
        return APIResponse(success=True, data=data)
    except Exception as e:
        logger.error(f"[ProjectSync] Failed to fetch audit log: {e}")
        return APIResponse(success=False, error="Unable to load audit trail.")


@app.post("/verification/{match_id}/confirm", response_model=APIResponse, tags=["Verification"])
def confirm_match(match_id: int, db: Session = Depends(get_db)):
    """
    Confirms a queued match - a human has verified it's correct. A
    'Needs Review' match is promoted to 'Matched'; a 'New Activity' stays
    as-is but is marked reviewed and removed from the pending queue.
    """
    try:
        verification = db.query(VerificationQueue).filter(VerificationQueue.match_id == match_id).first()
        if not verification:
            return APIResponse(success=False, error=f"No verification item found for match {match_id}.")

        match = verification.match
        if match.match_status == "Needs Review":
            match.match_status = "Matched"

        verification.reviewer_status = "Confirmed"
        verification.reviewed_at = datetime.utcnow()
        db.commit()

        _log_audit(db, "Match Verified", activity_ref=match.site_activity_name, details=f"match_id={match_id} confirmed")
        return APIResponse(success=True, data={"match_id": match_id, "match_status": match.match_status})

    except Exception as e:
        logger.error(f"[ProjectSync] Failed to confirm match: {e}")
        return APIResponse(success=False, error="Unable to confirm match.")


@app.post("/verification/{match_id}/reject", response_model=APIResponse, tags=["Verification"])
def reject_match(match_id: int, db: Session = Depends(get_db)):
    """Rejects a queued match - a human has determined the AI's suggestion was wrong."""
    try:
        verification = db.query(VerificationQueue).filter(VerificationQueue.match_id == match_id).first()
        if not verification:
            return APIResponse(success=False, error=f"No verification item found for match {match_id}.")

        match = verification.match
        match.match_status = "Rejected"
        match.activity_id_fk = None

        verification.reviewer_status = "Rejected"
        verification.reviewed_at = datetime.utcnow()
        db.commit()

        _log_audit(db, "Match Rejected", activity_ref=match.site_activity_name, details=f"match_id={match_id} rejected")
        return APIResponse(success=True, data={"match_id": match_id, "match_status": match.match_status})

    except Exception as e:
        logger.error(f"[ProjectSync] Failed to reject match: {e}")
        return APIResponse(success=False, error="Unable to reject match.")

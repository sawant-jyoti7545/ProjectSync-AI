"""
ProjectSync AI - Excel/CSV Report Extractor

Reads .xlsx/.xls/.csv site reports into the same structured JSON shape
as PDF extraction (services/pdf_extractor.py), using flexible,
case-insensitive column-name matching so the exact header wording
doesn't have to match exactly - "Activity", "activity_name", and
"Activity Name" are all recognized as the same field.

Expected columns (any recognized alias works, extra columns are
ignored): Activity ID, Activity (name), Location, Planned Progress,
Actual Progress, Status, Issues, Remarks.
"""

import logging
import pandas as pd

logger = logging.getLogger("ProjectSync")


class ExcelExtractionError(Exception):
    """Raised when a spreadsheet cannot be read or contains no usable activity data."""
    pass


_COLUMN_ALIASES = {
    "activity_id": ["activity_id", "activityid", "activity id", "id"],
    "activity": ["activity", "activity_name", "activity name", "task", "task name"],
    "location": ["location", "site", "block"],
    "planned_progress": ["planned_progress", "planned progress", "planned", "planned_pct", "planned %"],
    "actual_progress": ["actual_progress", "actual progress", "actual", "actual_pct", "actual %"],
    "status": ["status"],
    "issues": ["issues", "issue"],
    "remarks": ["remarks", "remark", "notes", "comment", "comments"],
}


def _normalize_col(col) -> str:
    return str(col).strip().lower()


def _build_column_map(columns) -> dict:
    """Maps our internal field names to whichever actual column header matched an alias."""
    normalized = {_normalize_col(c): c for c in columns}
    mapping = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[field] = normalized[alias]
                break
    return mapping


def _to_float(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(str(val).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _clean_str(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s else None


def extract_from_excel(file_path: str, ext: str) -> dict:
    """
    Main entrypoint. ext should be '.xlsx', '.xls', or '.csv'.
    Returns the same structured JSON shape as extract_from_pdf():

        {"project": None, "report_date": None, "activities": [ {...}, ... ]}

    (Spreadsheets don't carry a report header the way PDFs do, so
    project/report_date are left None - the upload pipeline already
    handles that gracefully.)

    Raises ExcelExtractionError with a user-facing message on genuine
    failure (unreadable file, missing activity column, no usable rows).
    """
    try:
        if ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
    except Exception as e:
        raise ExcelExtractionError(f"Could not read spreadsheet: {e}")

    if df.empty:
        raise ExcelExtractionError("The spreadsheet has no rows.")

    col_map = _build_column_map(df.columns)
    if "activity" not in col_map:
        raise ExcelExtractionError(
            "Could not find an activity name column. Expected a column named "
            "'Activity' or 'Activity Name'."
        )

    activities = []
    for _, row in df.iterrows():
        activity_name = _clean_str(row.get(col_map["activity"]))
        if not activity_name:
            continue  # skip blank rows

        planned = _to_float(row.get(col_map["planned_progress"])) if "planned_progress" in col_map else None
        actual = _to_float(row.get(col_map["actual_progress"])) if "actual_progress" in col_map else None

        # Clamp into a valid range per spec section 14 (Validation), same as PDF extraction.
        if planned is not None:
            planned = max(0.0, min(100.0, planned))
        if actual is not None:
            actual = max(0.0, min(100.0, actual))

        activities.append({
            "activity_id": _clean_str(row.get(col_map["activity_id"])) if "activity_id" in col_map else None,
            "activity": activity_name,
            "location": _clean_str(row.get(col_map["location"])) if "location" in col_map else None,
            "planned_progress": planned,
            "actual_progress": actual,
            "status": _clean_str(row.get(col_map["status"])) if "status" in col_map else None,
            "issues": _clean_str(row.get(col_map["issues"])) if "issues" in col_map else None,
            "remarks": _clean_str(row.get(col_map["remarks"])) if "remarks" in col_map else None,
        })

    if not activities:
        raise ExcelExtractionError("Unable to extract activities from spreadsheet.")

    logger.info(f"[ProjectSync] {len(activities)} activities extracted from spreadsheet")

    return {"project": None, "report_date": None, "activities": activities}

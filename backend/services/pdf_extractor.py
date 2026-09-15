"""
ProjectSync AI - PDF Report Extractor

Reads a site-report PDF and turns it into structured JSON matching
spec section 3.C. Uses rule-based text parsing (pdfplumber + regex) -
no external AI call needed, so extraction always works offline.

Expected report format (see backend/data/sample_report.pdf):

    Project: <name>
    Report Date: YYYY-MM-DD

    ---------------------------------------------
    Activity ID: <id>              (optional)
    Activity: <name>
    Location: <location>
    Planned Progress: <n>%
    Actual Progress: <n>%
    Status: <status>
    Issues: <free text>
    Remarks: <free text>
    ---------------------------------------------
    ... (repeated per activity block)

Real reports won't always match this exactly - fields are extracted
independently and missing ones are simply left as None rather than
failing the whole block, so partial/messy reports still yield partial
results instead of nothing.
"""

import re
import logging
from typing import Optional

import pdfplumber

logger = logging.getLogger("ProjectSync")


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be read or contains no usable activity data."""
    pass


def _extract_raw_text(file_path: str) -> str:
    """Pulls all text out of the PDF, page by page."""
    text_parts = []
    try:
        with pdfplumber.open(file_path) as pdf:
            if len(pdf.pages) == 0:
                raise PDFExtractionError("The PDF has no pages.")
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except PDFExtractionError:
        raise
    except Exception as e:
        raise PDFExtractionError(f"Could not read PDF file: {e}")

    full_text = "\n".join(text_parts).strip()
    if not full_text:
        raise PDFExtractionError("Empty PDF or no extractable text found (it may be a scanned image).")
    return full_text


def _match_one(pattern: str, block: str) -> Optional[str]:
    m = re.search(pattern, block, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _match_number(pattern: str, block: str) -> Optional[float]:
    val = _match_one(pattern, block)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_activity_block(block: str) -> Optional[dict]:
    """
    Parses one activity block. Returns None if the block doesn't look
    like an activity at all (e.g. it's the report header or footer).
    """
    activity_name = _match_one(r"Activity:\s*(.+)", block)
    if not activity_name:
        return None  # not an activity block (header/footer/etc.)

    planned = _match_number(r"Planned Progress:\s*(\d+(?:\.\d+)?)\s*%?", block)
    actual = _match_number(r"Actual Progress:\s*(\d+(?:\.\d+)?)\s*%?", block)

    # Clamp progress values into a valid 0-100 range per spec section 14 (Validation),
    # rather than silently trusting whatever the report contains.
    for val, label in ((planned, "planned"), (actual, "actual")):
        if val is not None and not (0 <= val <= 100):
            logger.warning(f"[ProjectSync] {label} progress out of range ({val}) - clamping")
    if planned is not None:
        planned = max(0.0, min(100.0, planned))
    if actual is not None:
        actual = max(0.0, min(100.0, actual))

    return {
        "activity_id": _match_one(r"Activity ID:\s*(\S+)", block),
        "activity": activity_name,
        "location": _match_one(r"Location:\s*(.+)", block),
        "planned_progress": planned,
        "actual_progress": actual,
        "status": _match_one(r"Status:\s*(.+)", block),
        "issues": _match_one(r"Issues:\s*(.+)", block),
        "remarks": _match_one(r"Remarks:\s*(.+)", block),
    }


def parse_report_text(raw_text: str, source_label: str = "report") -> dict:
    """
    Parses structured report text (regardless of where it came from - a
    PDF's extracted text, or a voice transcript) into the same JSON
    shape. This is the shared core both extract_from_pdf() and the
    voice-input pipeline use, so PDF and voice reports are guaranteed
    to produce identical output structure.
    """
    project_name = _match_one(r"Project:\s*(.+)", raw_text)
    report_date = _match_one(r"Report Date:\s*(\d{4}-\d{2}-\d{2})", raw_text)

    # Split on divider lines of 5+ dashes, which separate activity blocks
    blocks = re.split(r"\n-{5,}\n?", raw_text)

    activities = []
    for block in blocks:
        parsed = _parse_activity_block(block)
        if parsed:
            activities.append(parsed)

    if not activities:
        raise PDFExtractionError(f"Unable to extract activities from {source_label}.")

    logger.info(f"[ProjectSync] {len(activities)} activities extracted from {source_label}")

    return {
        "project": project_name,
        "report_date": report_date,
        "activities": activities,
    }


def extract_from_pdf(file_path: str) -> dict:
    """
    Main entrypoint for PDF reports. Returns structured JSON:

        {
            "project": "...",
            "report_date": "...",
            "activities": [ {...}, {...} ]
        }

    Raises PDFExtractionError with a user-facing message if extraction
    genuinely fails (empty file, no activities found at all).
    """
    raw_text = _extract_raw_text(file_path)
    return parse_report_text(raw_text, source_label="report")

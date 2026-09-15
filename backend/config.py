"""
ProjectSync AI - Configuration
Centralizes all environment-driven settings so nothing is hardcoded
across services. Every other module should import from here instead
of calling os.getenv() directly.
"""

import os
from dotenv import load_dotenv

# Load variables from a .env file if present (never committed to git)
load_dotenv()


class Settings:
    # --- General ---
    APP_NAME: str = "ProjectSync AI"
    ENV: str = os.getenv("ENV", "development")

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./projectsync.db")

    # --- CORS ---
    # Comma-separated list of allowed frontend origins for local dev
    ALLOWED_ORIGINS: list[str] = os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5501,http://localhost:5501"
    ).split(",")

    # --- AI ---
    # "real"  -> calls an external LLM API using AI_API_KEY
    # "demo"  -> uses local rule-based fallback logic (always works, no key needed)
    AI_MODE: str = os.getenv("AI_MODE", "demo")
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")
    AI_API_URL: str = os.getenv("AI_API_URL", "https://api.anthropic.com/v1/messages")
    AI_MODEL: str = os.getenv("AI_MODEL", "claude-sonnet-5")

    # --- Matching confidence thresholds (Phase 4) ---
    HIGH_CONFIDENCE_THRESHOLD: float = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "0.85"))
    MEDIUM_CONFIDENCE_THRESHOLD: float = float(os.getenv("MEDIUM_CONFIDENCE_THRESHOLD", "0.60"))

    # --- Delay / variance thresholds (Phase 5) ---
    AT_RISK_VARIANCE: float = float(os.getenv("AT_RISK_VARIANCE", "-10"))   # -10 to -1 => At Risk
    DELAYED_VARIANCE: float = float(os.getenv("DELAYED_VARIANCE", "-10"))   # < -10 => Delayed

    # --- File upload ---
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
    ALLOWED_UPLOAD_EXTENSIONS: tuple = (".pdf", ".xlsx", ".xls", ".csv")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")


settings = Settings()

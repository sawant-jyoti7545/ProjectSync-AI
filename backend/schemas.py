"""
ProjectSync AI - Pydantic schemas
Defines the consistent API response envelope used by every endpoint,
plus shared request/response models. Endpoint-specific schemas
(upload, verification, insights, etc.) will be added in later phases
as those features are built - kept minimal here on purpose.
"""

from typing import Any, Optional
from pydantic import BaseModel


class APIResponse(BaseModel):
    """
    Every ProjectSync AI endpoint returns this shape, so the frontend
    never has to guess the response structure:

        { "success": true,  "data": {...}, "error": null }
        { "success": false, "data": null,  "error": "message" }
    """
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str
    ai_mode: str

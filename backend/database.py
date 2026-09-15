"""
ProjectSync AI - Database setup
Creates the SQLAlchemy engine, session factory, and declarative Base.
Also exposes get_db() as a FastAPI dependency and init_db() to create
all tables on startup.
"""

import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import settings

logger = logging.getLogger("ProjectSync")

# check_same_thread=False is required for SQLite when used with FastAPI,
# since FastAPI can handle requests on different threads.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and guarantees it closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Creates all tables defined in models.py if they don't already exist.
    Safe to call every startup - it will not drop or duplicate existing tables.
    """
    import models  # noqa: F401  (import ensures models are registered on Base before create_all)
    Base.metadata.create_all(bind=engine)
    logger.info("[ProjectSync] Database initialized (tables ensured)")

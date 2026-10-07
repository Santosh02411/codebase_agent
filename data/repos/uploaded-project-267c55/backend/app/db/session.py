"""
Database connection setup using SQLAlchemy.

Two modes, chosen by whether DATABASE_URL is set:
- Unset (default): SQLite, a single file in the backend/ folder. Zero
  setup — no server to install or run — which is why this stays the
  default for local development.
- Set: whatever real database DATABASE_URL points at — in practice,
  Postgres (see docker-compose.yml, which sets this automatically for
  the containerized setup). The same models, the same lightweight
  migration step (app/db/migrate.py), and the same ORM queries work
  against either — SQLAlchemy's job is exactly this portability, and
  nothing in this codebase writes raw SQLite-specific SQL anywhere
  else, so switching is a config change, not a code change.

A DATABASE_URL starting with `postgres://` (the scheme Heroku-style
providers hand out) is rewritten to `postgresql://`, which is what
SQLAlchemy 1.4+/2.0 actually require — a real, easy-to-hit gotcha
otherwise: the connection silently fails with a scheme it doesn't
recognize.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///./database.db"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

SQLALCHEMY_DATABASE_URL = DATABASE_URL
IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")

# check_same_thread=False is needed only for SQLite (FastAPI may use the
# connection across different threads); Postgres's driver handles
# threading itself and doesn't take this argument at all.
connect_args = {"check_same_thread": False} if IS_SQLITE else {}

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependency used by FastAPI routes to get a database session.
    Ensures the session is always closed after the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

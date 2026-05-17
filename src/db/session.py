"""Database connection setup using SQLAlchemy.

This module initializes the SQLAlchemy engine and session factory for
interacting with the application's database. It reads the database URL
from the application settings and provides a 'SessionLocal' factory
for creating database sessions.

Attributes:
    engine (sqlalchemy.engine.Engine): The SQLAlchemy engine connected
        to the configured database.
    SessionLocal (sqlalchemy.orm.sessionmaker): A sessionmaker factory
        bound to 'engine' for creating database sessions.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

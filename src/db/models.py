"""Database models for users and jobs.

This module defines SQLAlchemy ORM models for the application, including
the 'User' and 'Job' tables. 'User' represents registered users, while
'Job' represents jobs submitted by users, tracking status, payload,
results, errors, and timestamps.

Classes:
    Base: Declarative base class for all ORM models.
    User: Represents a user registered in the system.
    Job: Represents a job submitted by a user.
"""

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, DateTime
from datetime import datetime, timezone


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy ORM models."""
    pass


class User(Base):
    """Represents a registered user.

    Attributes:
        id (int): Primary key of the user.
        username (str): Unique username for login.
        password_hash (str): Hashed password for authentication.
    """
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)


class Job(Base):
    """Represents a user-submitted job/task.

    Tracks the job's status, payload, results, errors, timing, attempts,
    and priority.

    Attributes:
        id (int): Primary key of the job.
        user_id (int): Foreign key referencing the submitting user.
        status (str): Current status of the job (default "pending").
        payload (dict): JSON-serializable dictionary containing job input.
        result (dict): JSON-serializable dictionary containing job output.
        error (str, optional): Error message if the job failed.
        created_at (datetime): UTC timestamp when the job was created.
        started_at (datetime, optional): UTC timestamp when the job started.
        finished_at (datetime, optional): UTC timestamp when the job finished.
        attempts (int): Number of times the job has been attempted.
        max_attempts (int): Maximum number of allowed attempts.
        priority (int): Priority of the job (higher values run first).
        locked_by (str, optional): Identifier of the worker currently locking
            the job.
    """
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")
    payload = Column(JSON)
    result = Column(JSON)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    priority = Column(Integer, default=0)
    locked_by = Column(String, nullable=True)

"""Worker process module.

This module serves as the entry point for a background worker process
that polls a database for jobs, processes them, and handles connection
management and error handling.

Functions:
    get_connection():
        Create and return a new database connection.

    wait_for_database(retries=60, delay=2.0):
        Wait until the database is ready and accepting connections.

    run_worker():
        Run the main worker loop to fetch and process jobs.
"""

import sys
import time

import psycopg2
from sqlalchemy import text

from backend.config import settings
from db.models import Base
from db.session import engine
from worker.runner import fetch_next_job
from worker.processor import process_job


def get_connection():
    """Create and return a new database connection using psycopg2.

    Converts the SQLAlchemy-style DATABASE_URL to a format compatible with
    psycopg2 if necessary.

    Returns:
        psycopg2.extensions.connection: A new database connection.
    """
    connection_string = settings.DATABASE_URL
    # Remove 'postgresql://' prefix if present and replace with psycopg2 format
    if connection_string.startswith("postgresql://"):
        connection_string = connection_string.replace("postgresql://", "")

    return psycopg2.connect(f"postgresql://{connection_string}")


def wait_for_database(retries: int = 60, delay: float = 2.0):
    """Wait until the database is ready and the engine can connect.

    Attempts to connect to the database and execute a simple query.
    Retries the specified number of times with a delay between attempts.

    Args:
        retries (int, optional): Number of connection attempts. Defaults to 60.
        delay (float, optional): Delay between retries in seconds. Defaults to 2.0.

    Raises:
        RuntimeError: If the database does not become ready within the specified retries.
    """
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            print(f"Database not ready (attempt {attempt}/{retries}): {exc}", flush=True)
            time.sleep(delay)
    raise RuntimeError("Database did not become ready in time")


def run_worker():
    """Run the main worker loop to fetch and process jobs.

    The worker waits for the database to be ready, ensures database tables exist,
    then continuously polls for jobs. Each job is processed in a separate database
    connection with proper transaction handling.

    Exceptions during job fetching or processing are logged, and the worker
    continues running after a short delay.

    This function blocks indefinitely until manually stopped.
    """
    print("Worker starting...", flush=True)
    sys.stdout.flush()

    wait_for_database()

    # Ensure the jobs table exists before polling.
    Base.metadata.create_all(bind=engine)

    while True:
        conn = None
        try:
            conn = get_connection()
            conn.autocommit = False

            job = fetch_next_job(conn)

            if job:
                job_id, payload = job
                conn.commit()
                conn.close()
                conn = None

                print(f"Processing job {job_id}", flush=True)
                conn = get_connection()
                conn.autocommit = False
                process_job(conn, job_id, payload)
                conn.commit()
            else:
                conn.commit()
                time.sleep(1)
        except Exception as e:
            if conn is not None:
                conn.rollback()
            print(f"Worker error: {e}", flush=True)
            time.sleep(1)
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    run_worker()

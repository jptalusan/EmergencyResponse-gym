"""
Module for fetching the next pending job from the database.

This module provides functionality to retrieve the next pending job
for processing while avoiding conflicts between multiple workers
using 'FOR UPDATE SKIP LOCKED'.

Functions:
    fetch_next_job(conn):
        Fetches the next pending job and marks it as running.
"""

from psycopg2.extensions import connection

def fetch_next_job(conn: connection):
    """Fetch the next pending job from the database and mark it as running.

    This function selects the oldest job with status 'pending', locks it
    to prevent other workers from fetching it, and updates its status to
    'running' with the current timestamp.

    The SQL 'FOR UPDATE SKIP LOCKED' ensures that multiple workers
    querying the jobs table simultaneously do not pick the same job.

    Args:
        conn (connection): A database connection object with cursor support.

    Returns:
        tuple[int, Any] or None: A tuple containing the job ID and payload
        if a pending job exists, or None if no pending jobs are available.

    Raises:
        Exception: Any exception raised during database operations is
        propagated to the caller.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, payload
            FROM jobs
            WHERE status = 'pending'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1;
        """)
        row = cur.fetchone()
        if not row:
            return None

        job_id, payload = row

        cur.execute("""
            UPDATE jobs
            SET status = 'running', started_at = NOW()
            WHERE id = %s;
        """, (job_id,))

        return job_id, payload

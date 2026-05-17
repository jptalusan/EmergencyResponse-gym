"""Module for processing simulation jobs.

This module provides functions to parse job payloads, run simulations, 
store outputs, and update job statuses in the database.

Functions:
    process_job(conn, job_id, payload): Processes a simulation job and
        updates its status in the database.
"""

import json
from pathlib import Path
from typing import Any

from psycopg2.extensions import connection

from backend.schemas.sim import SimInput
from backend.services.sim import run_sim
from db.storage import LocalStorage


def _parse_payload(payload: Any) -> SimInput:
    """
    Parse a job payload into a SimInput object.

    Args:
        payload (Any): The job payload, either a JSON string or a dictionary.

    Returns:
        SimInput: A validated SimInput object representing the simulation input.

    Raises:
        json.JSONDecodeError: If the payload is a string but cannot be parsed as JSON.
        ValidationError: If the payload cannot be validated as a SimInput model.
    """
    if isinstance(payload, str):
        payload = json.loads(payload)
    return SimInput.model_validate(payload)


def _serialize_result(result: Any) -> dict:
    """
    Serialize a simulation result to a dictionary.

    Args:
        result (Any): The result object from the simulation.

    Returns:
        dict: A dictionary representation of the result. If the object has a
            'model_dump' method, it uses it; otherwise, returns the object as-is.
    """
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


def process_job(conn: connection, job_id: int | str, payload: Any):
    """
    Process a simulation job and update its status in the database.

    This function parses the job payload, runs the simulation, stores the
    simulation outputs locally, updates the file paths in the result, and
    marks the job as 'done' in the database. If any exception occurs, the
    job status is updated to 'failed' and the error is recorded.

    Args:
        conn (connection): A database connection object with cursor support.
        job_id (int | str): The unique identifier of the job.
        payload (Any): The job payload, either a JSON string or a dictionary.

    Raises:
        Exception: Any exception raised during processing is caught internally
            and stored in the database as job failure.
    """
    try:
        sim_input = _parse_payload(payload)
        result = run_sim(sim_input)
        job_output_dir = LocalStorage.store_output(job_id, result)
        for attribute in list(vars(result).keys()):
            filepath = getattr(result, attribute, None)
            filename = filepath.rsplit("/", 1)[-1] if filepath else ""
            setattr(result, attribute, str(Path(job_output_dir) / filename))

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'done',
                    result = %s,
                    finished_at = NOW()
                WHERE id = %s;
            """,
                (json.dumps(_serialize_result(result)), job_id),
            )

    except Exception as e:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = %s,
                    finished_at = NOW()
                WHERE id = %s;
            """,
                (str(e), job_id),
            )

"""User jobs routes in backend.

This submodule defines the routes for jobs of an authenticated user.
It includes endpoints for submitting jobs, retrieving user-specific
jobs, and accessing individual job details.

Functions:
    submit((data, user_id):
        Submit a job for a user.
    
    list_all(user_id):
        List all the jobs belonging to a user.
        
    get_one(job_id, user_id):
        Get (retrieve) the details of a specific job of a user.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from backend.schemas.sim import SimInput, SimJob
from backend.services.auth import get_current_user
from db.session import SessionLocal
from db import crud

# Add router with prefix "/jobs" for job-related routes
router = APIRouter(prefix="/jobs")


def _serialize_job(job: SimJob) -> dict:
    """Serialize a job (SimJob object) into a dictionary.

    Converts the given 'Job' object into a dictionary containing key
    attributes that can be easily used for JSON responses, logging, or
    other serialization purposes. This helper function standardizes the
    structure of serialized job responses across the module.

    Args:
        job (SimJob): The job object to serialize.

    Returns:
        (dict): A dictionary representation of the job, including the keys:
            - "id": Job ID.
            - "user_id": ID of the user who submitted the job. 
            - "status": Current status of the job.
            - "payload": Input payload of the job.
            - "result": Output result of the job.
    """
    return {
        "id": job.id,
        "user_id": job.user_id,
        "status": job.status,
        "payload": job.payload,
        "result": job.result,
    }


def _submit_job(data: SimInput, user_id: int):
    """Submit a new job to the database and job queue.

    Creates a new job entry associated with the specified user and
    stores the provided simulation input payload.

    Args:
        data (SimInput): Simulation input (configuration file path).
        user_id (int): User ID of the user submitting a new job.

    Returns;
        (dict): Job details (ID, user ID, status, payload, result).
    """
    db = SessionLocal()
    result = None
    try:
        job = crud.create_job(db, user_id=user_id, payload=data.model_dump())
        if job is not None:
            result = _serialize_job(job)
    finally:
        db.close()
        return result


def _list_user_jobs(user_id: int) -> list[dict]:
    """List all the jobs belonging to a user.

    Retrieves all jobs associated with the specified user ID and
    serializes them into dictionary format.

    Args:
        user_id (int): User ID of the intended user.

    Returns:
        list[dict]: List of the jobs belonging to the input user.
    """
    db = SessionLocal()
    result = None
    try:
        result = [_serialize_job(job) for job in crud.list_jobs(db, user_id=user_id)]
    finally:
        db.close()
        return result


@router.post("")
def submit(data: SimInput, user_id: int = Depends(get_current_user)):
    """Submit a job for a user.

    Endpoint for authenticated users to submit a new simulation job.

    Args:
        data (SimInput): Simulation input (configuration file path).
        user_id (int): User ID of the user submitting a new job.

    Returns:
        (dict): Job details (ID, user ID, status, payload, result).
    """
    return _submit_job(data, user_id)


@router.get("")
def list_all(user_id: int = Depends(get_current_user)):
    """List all the jobs belonging to a user.

    Retrieves all jobs currently associated with the authenticated user.

    Args:
        user_id (int): User ID of the intended user.

    Returns:
        list[dict]: List of the jobs belonging to the input user.
    """
    return _list_user_jobs(user_id)


@router.get("/{job_id}")
def get_one(job_id: int, user_id: int = Depends(get_current_user)):
    """Get (retrieve) the details of a specific job of a user.

    Retrieves a single job by its ID after validating that the job
    belongs to the authenticated user.

    Args:
        job_id (int): Job ID of the requested job.
        user_id (int): User ID of the intended user.

    Returns:
        (dict): Job details (ID, user ID, status, payload, result).

    Raises:
        HTTPException: If 'job_id' not found or 'user_id' not matching.
    """
    db = SessionLocal()
    result = None
    try:
        job = crud.get_job(db, job_id)
        if not job or job.user_id != user_id:
            raise HTTPException(
                status_code = status.HTTP_404_NOT_FOUND,
                detail = "Job not found",
            )
        result = _serialize_job(job)
    finally:
        db.close()
        return result

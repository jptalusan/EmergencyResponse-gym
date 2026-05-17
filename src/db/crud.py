"""DataBase CRUD (Create, Read, Update, Delete) operations.

This module provides the fundamental CRUD (Create, Read, Update, Delete)
operations for the following database entry types:
    - User: Featuring Create and Read operations.
    - Job: Featuring Create, Read and Update operations.
These entries are correlated via the user ID associated with a job.

At this point there is no Delete operation implemented.

Functions:
    create_user(db, username, password_hash):
        Create a new user and save it to the database.

    get_user(db, username):
        Retrieve a user from the database by username.

    def create_job(db, user_id, payload):
        Create a job for a user using the specified configuration.
    
    list_jobs(db, user_id):
        Retrieve all jobs for a specific user from the database.

    get_job(db, job_id):
        Retrieve a job from the database by its ID.
"""

from db.models import User, Job
from db.storage import LocalStorage
from utils.config_validator import load_cfg


def create_user(db, username, password_hash):
    """Create a new user and save it to the database.

    This function creates a 'User' object with the specified username and
    password hash, adds it to the database session, commits the session,
    and returns the created user.

    Args:
        db: The database session or connection used to add and commit the user.
        username (str): The username for the new user.
        password_hash (str): The hashed password for the new user.

    Returns:
        User: The newly created 'User' object.
    """
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    return user


def get_user(db, username):
    """Retrieve a user from the database by username.

    This function queries the database for a 'User' object with the
    specified username. If a matching user exists, it returns the 'User'
    object; otherwise, it returns 'None'.

    Args:
        db: The database session or connection used to perform the query.
        username (str): The username of the user to retrieve.

    Returns:
        Optional[User]: The 'User' object if found, otherwise 'None'.
    """
    return db.query(User).filter_by(username=username).first()


def create_job(db, user_id, payload):
    """Create a job for a user using the specified configuration.

    This function loads a configuration from the given payload and, if valid,
    creates a new 'Job' object associated with the specified user. It stores
    the configuration and related data in local storage, updates the job
    payload with storage paths, and commits the job to the database. If the
    configuration cannot be loaded, it returns 'None'.

    Args:
        db: The database session or connection used to add and commit the job.
        user_id (int): The ID of the user creating the job.
        payload (dict): A dictionary containing the job configuration, with
            keys 'config_dir' and 'config_name'.

    Returns:
        Optional[Job]: The created 'Job' object if the configuration is valid,
        otherwise 'None'.
    """
    cfg = load_cfg(payload["config_dir"], payload["config_name"])
    if cfg is not None:
        job = Job(user_id=user_id, payload=payload)
        db.add(job)
        db.flush()
        LocalStorage.mkdirs(job.id)
        store_config_dir, store_config_name = LocalStorage.store_config(job.id, payload)
        job.payload = {"config_dir": store_config_dir, "config_name": store_config_name}
        LocalStorage.store_data(job.id, cfg)
        db.commit()
        db.refresh(job)
        return job
    else:
        return None


def list_jobs(db, user_id):
    """Retrieve all jobs for a specific user from the database.

    This function queries the database for all 'Job' objects associated
    with the given user ID and returns them as a list.

    Args:
        db: The database session or connection used to perform the query.
        user_id (int): The ID of the user whose jobs are to be retrieved.

    Returns:
        list[Job]: A list of 'Job' objects associated with the specified user.
    """
    return db.query(Job).filter_by(user_id=user_id).all()


def get_job(db, job_id):
    """Retrieve a job from the database by its ID.

    This function queries the database for a 'Job' object with the specified
    job ID. If a matching job exists, it returns the 'Job' object; otherwise,
    it returns 'None'.

    Args:
        db: The database session or connection used to perform the query.
        job_id (int): The ID of the job to retrieve.

    Returns:
        Optional[Job]: The 'Job' object if found, otherwise 'None'.
    """
    return db.query(Job).filter_by(id=job_id).first()


def update_job(db, job_id, **kwargs):
    """Update attributes of an existing job and commit changes to the database.

    This function retrieves a 'Job' object by its ID, updates the specified
    attributes using keyword arguments, and commits the changes to the
    database.

    Args:
        db: The database session or connection used to query and commit the job.
        job_id (int): The ID of the job to update.
        **kwargs: Arbitrary keyword arguments representing the attributes
            to update and their new values.

    Returns:
        None
    """
    job = get_job(db, job_id)
    for k, v in kwargs.items():
        setattr(job, k, v)
    db.commit()

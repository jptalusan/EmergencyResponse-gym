"""Schemas for simulation-related objects.

This submodule defines the schema for simulation-related objects.
These schemas are used for validation, serialization, and data
exchange between API endpoints, services, and the database.

Classes:
    SimInput:
        Represents a simulation input.
    
    SimOutput:
        Represents a simulation output.
    
    SimJob:
        Represents a simulation job.
"""

from pydantic import BaseModel

class SimInput(BaseModel):
    """Represents a simulation input.

    Attributes:
        config_dir (str): Configuration file directory.
        config_name (str): Configuration file name.
    """
    config_dir: str
    config_name: str

class SimOutput(BaseModel):
    """Represents a simulation output.

    Attributes:
        path_incident_report (str): Path to the incidident report CSV file.
        path_apparatus_events (str): Path to the apparatus events CSV file.
        path_step_trace (str): Path to the step trace CSV file.
    """
    path_incident_report: str
    path_apparatus_events: str
    path_step_trace: str

class SimJob(BaseModel):
    """Represents a simulation job.

    Stores the complete information about a job submitted by a user,
    including input, current status, and resulting output.

    Attributes:
        id (int): Job ID.
        user_id (int): User ID.
        status (status): Job status (may get updated if not final).
            Possible values:
                - "pending": Job pending
                - "running": Job running
                - "failed": Job failed
                - "done": Job done
        payload: SimInput
        result: SimOutput
    """
    id: int
    user_id: int
    status: str
    payload: SimInput
    result: SimOutput

from emergency_response import app as core_run
from backend.schemas.simulation import SimInput, SimOutput


def run_simulation(payload: SimInput) -> SimOutput:
    result = core_run(payload.dict())

    return SimOutput(**result)

from backend.schemas.simulation import SimInput, SimOutput


def run_simulation(payload: SimInput) -> SimOutput:
    """
    Current synchronous execution.
    Later this can delegate to a queue instead.
    """
    result = core_run(payload.dict())
    return SimOutput(**result)


def enqueue_simulation(payload: SimInput) -> str:
    """
    भविष्य: enqueue simulation job and return job_id
    """
    raise NotImplementedError("Queue not implemented yet")
"""Simulation routes in backend.

This submodule defines the simulation routes in backend.
It provides an endpoint to run a simulation.
The endpoint executes simulations directly from the provided
configuration input and returns the generated results.

Functions:
    sim(payload):
        Run a simulation.
        Notes:
            - There is no user authentication required.
            - This request is not treated as a regular job.
            - The result will not be stored in a dedicated location.

This submodule is intended for development purposes. Avoid using it as
part of the application. It will be removed eventually.
"""

from fastapi import APIRouter, Body, HTTPException

from backend.schemas.sim import SimInput, SimOutput
from backend.services.sim import run_sim

# Add router with prefix "/sim" for simulation-related routes
router = APIRouter(prefix="/sim")


@router.post("", response_model=SimOutput)
async def sim(payload: SimInput = Body(...)) -> SimOutput:
    """Run a simulation.

    Executes a simulation using the provided input payload and
    returns the resulting simulation output.

    Args:
        payload (SimInput): Simulation input (configuration path).

    Returns:
        (SimOutput): Simulation output (result path).
    
    Raises:
        HTTPException: if 'run_sim(payload)' fails for any reason.
    """
    try:
        return run_sim(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

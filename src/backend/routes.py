from fastapi import APIRouter, HTTPException
from backend.schemas.simulation import SimInput, SimOutput
from backend.services.simulator_service import run_simulation

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/simulate", response_model=SimOutput)
async def simulate(payload: SimInput):
    try:
        result = run_simulation(payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

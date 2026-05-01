from pydantic import BaseModel


class SimInput(BaseModel):
    x: int
    y: float


class SimOutput(BaseModel):
    result: float
    message: str

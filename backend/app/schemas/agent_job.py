from pydantic import BaseModel, Field, field_validator
from app.schemas.common import ORMModel
from app.core.constants import JOB_STATUSES


class AgentJobCreate(BaseModel):
    vehicle_id: int
    agent_version: str | None = None


class AgentJobRead(ORMModel):
    id: int
    vehicle_id: int
    status: str
    current_step: str | None
    attempts: int
    error_message: str | None
    agent_version: str | None


class AgentJobUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in JOB_STATUSES:
            raise ValueError("invalid job status")
        return v

from pydantic import BaseModel

from app.domain.enums import JobStatus
from app.schemas.common import ORMModel


class AgentJobCreate(BaseModel):
    vehicle_id: int
    research_run_id: int | None
    agent_version: str | None = None


class AgentJobRead(ORMModel):
    id: int
    vehicle_id: int
    status: JobStatus
    current_step: str | None
    attempts: int
    error_message: str | None
    agent_version: str | None


class AgentJobUpdate(BaseModel):
    status: JobStatus

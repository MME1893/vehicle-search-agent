from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobStatus
from app.schemas.common import ORMModel


class AgentJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: int
    agent_version: str | None = Field(None, max_length=80)


class AgentJobRead(ORMModel):
    id: int
    vehicle_id: int
    research_run_id: int | None
    status: JobStatus
    current_step: str | None
    attempts: int
    status_reason: str | None
    agent_version: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentJobUpdate(BaseModel):
    status: JobStatus

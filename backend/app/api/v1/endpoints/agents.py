from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.agent_job_repository import AgentJobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.agent_job import AgentJobRead
from app.workers.agent_worker import run_agent_job

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/vehicles/{vehicle_id}/run", response_model=AgentJobRead, status_code=201)
def run_vehicle_research(
    vehicle_id: int,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    if not VehicleRepository(db).get_by_id(vehicle_id):
        raise HTTPException(404, "vehicle not found")
    job = AgentJobRepository(db).create(
        {"vehicle_id": vehicle_id, "status": "PENDING", "agent_version": "research-v1"}
    )
    db.commit()
    background_tasks.add_task(run_agent_job, job.id)
    return job

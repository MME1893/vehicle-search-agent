from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.agent_job_repository import AgentJobRepository
from app.schemas.agent_job import AgentJobCreate, AgentJobRead, AgentJobUpdate

router = APIRouter(prefix="/agent-jobs", tags=["agent jobs"])
DB_DEPENDENCY = Depends(get_db)


@router.post("", response_model=AgentJobRead, status_code=201)
def create(data: AgentJobCreate, db: Session = DB_DEPENDENCY):
    return AgentJobRepository(db).create(data.model_dump())


@router.get("/{job_id}", response_model=AgentJobRead)
def get(job_id: int, db: Session = DB_DEPENDENCY):
    item = AgentJobRepository(db).get_by_id(job_id)
    if not item:
        raise HTTPException(404, "job not found")
    return item


@router.patch("/{job_id}", response_model=AgentJobRead)
def update(job_id: int, data: AgentJobUpdate, db: Session = DB_DEPENDENCY):
    repo = AgentJobRepository(db)
    item = repo.get_by_id(job_id)
    if not item:
        raise HTTPException(404, "job not found")
    return repo.update(item, data.model_dump())

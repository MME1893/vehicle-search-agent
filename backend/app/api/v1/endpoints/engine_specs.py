from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.repositories.engine_spec_repository import EngineSpecRepository
from app.schemas.engine_spec import EngineSpecCreate, EngineSpecRead

router = APIRouter(prefix="/engine-specs", tags=["engine specifications"])


@router.post("", response_model=EngineSpecRead, status_code=201)
def create(data: EngineSpecCreate, db: Session = Depends(get_db)):
    return EngineSpecRepository(db).create(data.model_dump())


@router.get("/by-engine-code/{engine_code}", response_model=list[EngineSpecRead])
def get_by_engine_code(engine_code: str, db: Session = Depends(get_db)):
    return EngineSpecRepository(db).find_by_engine_code(engine_code)

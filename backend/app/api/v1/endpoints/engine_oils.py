from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.engine_oil_repository import EngineOilRepository
from app.schemas.engine_oil import EngineOilCreate, EngineOilRead, EngineOilUpdate

router = APIRouter(prefix="/engine-oils", tags=["engine oils"])
DB_DEPENDENCY = Depends(get_db)


@router.post("", response_model=EngineOilRead, status_code=201)
def create(data: EngineOilCreate, db: Session = DB_DEPENDENCY):
    return EngineOilRepository(db).create(data.model_dump())


@router.get("")
def list_(
    sae_viscosity: str | None = None,
    api_spec: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = DB_DEPENDENCY,
):
    items, total = EngineOilRepository(db).list(sae_viscosity, api_spec, offset, limit)
    return {
        "items": [EngineOilRead.model_validate(x).model_dump() for x in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{oil_id}", response_model=EngineOilRead)
def get(oil_id: int, db: Session = DB_DEPENDENCY):
    item = EngineOilRepository(db).get_by_id(oil_id)
    if not item:
        raise HTTPException(404, "engine oil not found")
    return item


@router.patch("/{oil_id}", response_model=EngineOilRead)
def update(oil_id: int, data: EngineOilUpdate, db: Session = DB_DEPENDENCY):
    repo = EngineOilRepository(db)
    item = repo.get_by_id(oil_id)
    if not item:
        raise HTTPException(404, "engine oil not found")
    return repo.update(item, data.model_dump(exclude_unset=True))


@router.delete("/{oil_id}", status_code=204)
def delete(oil_id: int, db: Session = DB_DEPENDENCY):
    repo = EngineOilRepository(db)
    item = repo.get_by_id(oil_id)
    if not item:
        raise HTTPException(404, "engine oil not found")
    try:
        repo.delete(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "engine oil is referenced by audit history") from exc
    return Response(status_code=204)

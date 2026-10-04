from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])
DB_DEPENDENCY = Depends(get_db)


@router.post("", response_model=VehicleRead, status_code=201)
def create(data: VehicleCreate, db: Session = DB_DEPENDENCY):
    return VehicleRepository(db).create(data.model_dump())


@router.get("")
def list_(
    manufacturer: str | None = None,
    engine_code: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = DB_DEPENDENCY,
):
    items, total = VehicleRepository(db).list(manufacturer, engine_code, offset, limit)
    return {
        "items": [VehicleRead.model_validate(x).model_dump() for x in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{vehicle_id}", response_model=VehicleRead)
def get(vehicle_id: int, db: Session = DB_DEPENDENCY):
    item = VehicleRepository(db).get_by_id(vehicle_id)
    if not item:
        raise HTTPException(404, "vehicle not found")
    return item


@router.patch("/{vehicle_id}", response_model=VehicleRead)
def update(vehicle_id: int, data: VehicleUpdate, db: Session = DB_DEPENDENCY):
    repo = VehicleRepository(db)
    item = repo.get_by_id(vehicle_id)
    if not item:
        raise HTTPException(404, "vehicle not found")
    return repo.update(item, data.model_dump(exclude_unset=True))


@router.delete("/{vehicle_id}", status_code=204)
def delete(vehicle_id: int, db: Session = DB_DEPENDENCY):
    repo = VehicleRepository(db)
    item = repo.get_by_id(vehicle_id)
    if not item:
        raise HTTPException(404, "vehicle not found")
    try:
        repo.delete(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "vehicle is referenced by audit history") from exc
    return Response(status_code=204)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.compatibility import CompatibilityCreate, CompatibilityRead
from app.services.compatibility.compatibility_service import CompatibilityService

router = APIRouter(tags=["compatibility"])


@router.post("/compatibilities", response_model=CompatibilityRead, status_code=201)
def create(data: CompatibilityCreate, db: Session = Depends(get_db)):
    try:
        return CompatibilityService(
            CompatibilityRepository(db), VehicleRepository(db), EngineOilRepository(db)
        ).save(data.model_dump())
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.get(
    "/vehicles/{vehicle_id}/compatible-oils", response_model=list[CompatibilityRead]
)
def oils(vehicle_id: int, db: Session = Depends(get_db)):
    return CompatibilityRepository(db).get_for_vehicle(vehicle_id)


@router.get(
    "/engine-oils/{oil_id}/compatible-vehicles", response_model=list[CompatibilityRead]
)
def vehicles(oil_id: int, db: Session = Depends(get_db)):
    return CompatibilityRepository(db).get_for_oil(oil_id)

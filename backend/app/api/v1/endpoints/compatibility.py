from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import raise_conflict
from app.db.session import get_db
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.compatibility import CompatibilityCreate, CompatibilityRead
from app.services.compatibility.compatibility_service import CompatibilityService

router = APIRouter(tags=["compatibility"])
DB_DEPENDENCY = Depends(get_db)


@router.post("/compatibilities", response_model=CompatibilityRead, status_code=201)
def create(data: CompatibilityCreate, db: Session = DB_DEPENDENCY):
    try:
        return CompatibilityService(
            CompatibilityRepository(db), VehicleRepository(db), EngineOilRepository(db)
        ).create_event(
            {
                **data.model_dump(mode="json"),
                "match_method": "MANUAL",
                "research_run_id": None,
                "created_by": "ADMIN",
            }
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except IntegrityError as exc:
        raise_conflict(db, "compatibility event already exists for this research run", exc)


@router.get(
    "/vehicles/{vehicle_id}/compatible-oils", response_model=list[CompatibilityRead]
)
def oils(vehicle_id: int, db: Session = DB_DEPENDENCY):
    return CompatibilityRepository(db).get_current_for_vehicle(vehicle_id)


@router.get(
    "/engine-oils/{oil_id}/compatible-vehicles", response_model=list[CompatibilityRead]
)
def vehicles(oil_id: int, db: Session = DB_DEPENDENCY):
    return CompatibilityRepository(db).get_current_for_oil(oil_id)

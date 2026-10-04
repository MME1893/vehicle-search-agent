from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.research_history import VehicleResearchHistory
from app.services.research.history_service import ResearchHistoryService

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get(
    "/vehicles/{vehicle_id}/history",
    response_model=VehicleResearchHistory,
)
def get_vehicle_research_history(
    vehicle_id: int, db: Annotated[Session, Depends(get_db)]
) -> VehicleResearchHistory:
    try:
        return ResearchHistoryService(db).get_vehicle_history(vehicle_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

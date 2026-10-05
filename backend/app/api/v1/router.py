from fastapi import APIRouter

from app.api.v1.endpoints import (
    agent_jobs,
    agents,
    compatibility,
    engine_oils,
    research_history,
    vehicles,
)

router = APIRouter(prefix="/api/v1")
router.include_router(vehicles.router)
router.include_router(engine_oils.router)
router.include_router(compatibility.router)
router.include_router(agent_jobs.router)
router.include_router(agents.router)
router.include_router(research_history.router)

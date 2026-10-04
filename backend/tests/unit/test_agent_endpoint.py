from fastapi import BackgroundTasks

from app.api.v1.endpoints.agents import run_vehicle_research
from app.models import AgentJob
from app.repositories.vehicle_repository import VehicleRepository
from app.workers.agent_worker import run_agent_job


def test_creating_agent_run_creates_pending_job_and_schedules_worker(db):
    vehicle = VehicleRepository(db).create({"manufacturer": "M", "model": "V"})
    background_tasks = BackgroundTasks()

    job = run_vehicle_research(vehicle.id, background_tasks, db)

    saved = db.get(AgentJob, job.id)
    assert saved is not None
    assert saved.status == "PENDING"
    assert saved.attempts == 0
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is run_agent_job
    assert task.args == (job.id,)

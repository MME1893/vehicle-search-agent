from datetime import UTC, datetime

from sqlalchemy import select

from app.models import AgentJob
from app.repositories.base import Repository


class AgentJobRepository(Repository[AgentJob]):
    model = AgentJob

    def get_next_pending(self):
        # PostgreSQL uses SKIP LOCKED to permit safe concurrent workers.
        return self.db.scalar(
            select(AgentJob)
            .where(AgentJob.status == "PENDING")
            .order_by(AgentJob.created_at)
            .with_for_update(skip_locked=True)
        )

    def get_pending_for_update(self, job_id: int):
        return self.db.scalar(
            select(AgentJob)
            .where(AgentJob.id == job_id, AgentJob.status == "PENDING")
            .with_for_update(skip_locked=True)
        )

    def mark_running(self, job):
        return self.update(
            job,
            {
                "status": "RUNNING",
                "current_step": "loading_vehicle",
                "attempts": job.attempts + 1,
                "started_at": job.started_at or datetime.now(UTC),
                "completed_at": None,
                "error_message": None,
            },
        )

    def update_step(self, job, step: str):
        return self.update(job, {"current_step": step})

    def mark_failed(self, job, message):
        return self.update(
            job,
            {
                "status": "FAILED",
                "current_step": job.current_step,
                "error_message": (message or "agent job failed")[:2000],
                "completed_at": datetime.now(UTC),
            },
        )

    def mark_needs_review(self, job, message):
        return self.update(
            job,
            {
                "status": "NEEDS_REVIEW",
                "current_step": "evidence_review",
                "error_message": message,
                "completed_at": datetime.now(UTC),
            },
        )

    def mark_completed(self, job):
        return self.update(
            job,
            {
                "status": "COMPLETED",
                "current_step": "completed",
                "completed_at": datetime.now(UTC),
            },
        )

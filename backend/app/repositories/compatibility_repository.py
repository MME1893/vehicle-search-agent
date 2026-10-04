from sqlalchemy import func, select

from app.models import Compatibility
from app.repositories.base import Repository


class CompatibilityRepository(Repository[Compatibility]):
    model = Compatibility

    @staticmethod
    def _latest_ids():
        return (
            select(
                Compatibility.id.label("id"),
                func.row_number()
                .over(
                    partition_by=(
                        Compatibility.vehicle_id,
                        Compatibility.engine_oil_id,
                    ),
                    order_by=(Compatibility.created_at.desc(), Compatibility.id.desc()),
                )
                .label("position"),
            )
            .subquery()
        )

    def get_current_for_vehicle(self, vehicle_id: int):
        latest = self._latest_ids()
        return list(
            self.db.scalars(
                select(Compatibility)
                .join(latest, latest.c.id == Compatibility.id)
                .where(
                    Compatibility.vehicle_id == vehicle_id,
                    latest.c.position == 1,
                )
                .order_by(Compatibility.created_at.desc(), Compatibility.id.desc())
            )
        )

    def get_current_for_oil(self, oil_id: int):
        latest = self._latest_ids()
        return list(
            self.db.scalars(
                select(Compatibility)
                .join(latest, latest.c.id == Compatibility.id)
                .where(
                    Compatibility.engine_oil_id == oil_id,
                    latest.c.position == 1,
                )
                .order_by(Compatibility.created_at.desc(), Compatibility.id.desc())
            )
        )

    def get_for_research_runs(self, run_ids: list[int]):
        return list(
            self.db.scalars(
                select(Compatibility)
                .where(Compatibility.research_run_id.in_(run_ids))
                .order_by(Compatibility.created_at, Compatibility.id)
            )
        )

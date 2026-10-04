from sqlalchemy import select
from app.models import Compatibility
from app.repositories.base import Repository


class CompatibilityRepository(Repository[Compatibility]):
    model = Compatibility

    def get_for_vehicle(self, vehicle_id: int):
        return list(
            self.db.scalars(
                select(Compatibility).where(Compatibility.vehicle_id == vehicle_id)
            )
        )

    def get_for_oil(self, oil_id: int):
        return list(
            self.db.scalars(
                select(Compatibility).where(Compatibility.engine_oil_id == oil_id)
            )
        )

    def find_pair(self, vehicle_id: int, oil_id: int):
        return self.db.scalar(
            select(Compatibility).where(
                Compatibility.vehicle_id == vehicle_id,
                Compatibility.engine_oil_id == oil_id,
            )
        )

    def upsert(self, data: dict):
        item = self.find_pair(data["vehicle_id"], data["engine_oil_id"])
        return self.update(item, data) if item else self.create(data)

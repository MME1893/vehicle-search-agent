from sqlalchemy import select

from app.domain.identity import vehicle_identity_key
from app.models import Vehicle
from app.repositories.base import Repository


class VehicleRepository(Repository[Vehicle]):
    model = Vehicle

    def find_by_identity(self, data: dict) -> Vehicle | None:
        key = vehicle_identity_key(
            data["manufacturer"], data["model"], data.get("trim"),
            data.get("production_year_from"), data.get("production_year_to"),
            data.get("engine_code"), data.get("engine_displacement"),
            data.get("engine_type"), data.get("fuel_type"), data.get("transmission"),
            data.get("drivetrain"), data.get("body_type"), data.get("body_style"),
        )
        return self.db.scalar(select(Vehicle).where(Vehicle.identity_key == key))

    def list(self, manufacturer=None, engine_code=None, offset=0, limit=50):
        stmt = select(Vehicle)
        if manufacturer:
            stmt = stmt.where(Vehicle.manufacturer.ilike(f"%{manufacturer}%"))
        if engine_code:
            stmt = stmt.where(Vehicle.engine_code == engine_code)
        return self.paged(stmt.order_by(Vehicle.id), offset, limit)

from sqlalchemy import select

from app.models import Vehicle
from app.repositories.base import Repository


class VehicleRepository(Repository[Vehicle]):
    model = Vehicle

    def list(self, manufacturer=None, engine_code=None, offset=0, limit=50):
        stmt = select(Vehicle)
        if manufacturer:
            stmt = stmt.where(Vehicle.manufacturer.ilike(f"%{manufacturer}%"))
        if engine_code:
            stmt = stmt.where(Vehicle.engine_code == engine_code)
        return self.paged(stmt.order_by(Vehicle.id), offset, limit)

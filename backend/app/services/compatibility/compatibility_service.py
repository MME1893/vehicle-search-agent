from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository


class CompatibilityService:
    def __init__(self, compat, vehicles, oils):
        self.compat, self.vehicles, self.oils = compat, vehicles, oils

    def save(self, data: dict):
        if not self.vehicles.get_by_id(data["vehicle_id"]) or not self.oils.get_by_id(
            data["engine_oil_id"]
        ):
            raise LookupError("vehicle or engine oil not found")
        if data["match_score"] < 1:
            raise ValueError("match score must be positive")
        return self.compat.upsert(data)

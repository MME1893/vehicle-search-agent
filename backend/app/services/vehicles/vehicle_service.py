from app.repositories.vehicle_repository import VehicleRepository


class VehicleService:
    def __init__(self, repo: VehicleRepository):
        self.repo = repo

    def create(self, data):
        return self.repo.create(data)

    def update(self, ident, data):
        item = self.repo.get_by_id(ident)
        return self.repo.update(item, data) if item else None

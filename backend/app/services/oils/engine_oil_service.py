from app.repositories.engine_oil_repository import EngineOilRepository


class EngineOilService:
    def __init__(self, repo: EngineOilRepository):
        self.repo = repo

    def create(self, data):
        return self.repo.create(data)

    def update(self, ident, data):
        item = self.repo.get_by_id(ident)
        return self.repo.update(item, data) if item else None

from sqlalchemy import select
from app.models import EngineSpec
from app.repositories.base import Repository


class EngineSpecRepository(Repository[EngineSpec]):
    model = EngineSpec

    def find_by_engine_code(self, code: str, verified_only: bool = False):
        stmt = select(EngineSpec).where(EngineSpec.engine_code == code)
        if verified_only:
            stmt = stmt.where(EngineSpec.status == "VERIFIED")
        return list(self.db.scalars(stmt.order_by(EngineSpec.confidence.desc())))

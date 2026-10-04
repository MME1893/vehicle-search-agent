from sqlalchemy import select

from app.models import CompatibilityHistory
from app.repositories.base import Repository


class CompatibilityHistoryRepository(Repository[CompatibilityHistory]):
    model = CompatibilityHistory

    def get_for_compatibility(self, compatibility_id: int):
        return list(
            self.db.scalars(
                select(CompatibilityHistory)
                .where(CompatibilityHistory.compatibility_id == compatibility_id)
                .order_by(CompatibilityHistory.id)
            )
        )

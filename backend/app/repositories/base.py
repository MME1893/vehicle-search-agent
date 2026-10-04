from typing import Generic, TypeVar
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class Repository(Generic[T]):
    model: type[T]

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, ident: int) -> T | None:
        return self.db.get(self.model, ident)

    def create(self, data: dict) -> T:
        obj = self.model(**data)
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, obj: T, data: dict) -> T:
        for key, value in data.items():
            setattr(obj, key, value)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: T) -> None:
        self.db.delete(obj)
        self.db.commit()

    def paged(self, stmt: Select, offset: int, limit: int) -> tuple[list[T], int]:
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        return list(self.db.scalars(stmt.offset(offset).limit(limit))), total

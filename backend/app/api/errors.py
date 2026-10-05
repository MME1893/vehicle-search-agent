from typing import NoReturn

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def raise_conflict(db: Session, message: str, exc: IntegrityError) -> NoReturn:
    db.rollback()
    raise HTTPException(status_code=409, detail=message) from exc

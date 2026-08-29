"""users 테이블 CRUD."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


def create_user(db: Session, *, email: str, password_hash: str, name: str) -> User:
    user = User(email=email.strip().lower(), password_hash=password_hash, name=name)
    db.add(user)
    db.flush()
    return user

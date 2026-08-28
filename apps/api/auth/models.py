"""인증 DB 모델 (users 테이블).

family_graph/orchestrator와 같은 `db.base.Base`를 공유해서, Alembic이
자동 생성할 때 함께 잡히도록 합니다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _uuid4_hex() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """서비스 사용자 한 명. 이메일 + 비밀번호 해시로 로그인합니다."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid4_hex)
    #: 로그인 아이디. 소문자로 정규화해서 저장합니다(repository.create_user).
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    #: security.hash_password 형식 — "pbkdf2_sha256$<iter>$<salt>$<hash>".
    #: 평문 비밀번호는 어디에도 저장하지 않습니다.
    password_hash: Mapped[str] = mapped_column(String(255))
    #: 화면 인사말용. 민감정보는 아니지만 표시 최소화 원칙상 성명만 받습니다.
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

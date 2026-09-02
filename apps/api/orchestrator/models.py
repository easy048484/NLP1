"""오케스트레이터 세션 상태의 DB 모델 (담당: 지원).

session_store.py의 인메모리 SessionState를 그대로 테이블 하나로 옮긴
것입니다. PostgresSessionStore(session_store.py)가 이 모델을 읽고 씁니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatSession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    #: 이 세션을 소유한 사용자(auth.models.User). NULL이면 비로그인 세션입니다.
    #:
    #: 이 컬럼 하나로 보관 정책이 갈립니다 — NULL이면 짧은 TTL(2시간)을 걸고
    #: 정리 배치가 실제로 지우고, 값이 있으면 30일 보관해서 다음 방문에
    #: 가족정보·재산정보·대화 이력을 그대로 이어씁니다. family_graphs.user_id와
    #: 같은 규칙입니다 (family_graph/repository.user_can_access).
    user_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    family_graph_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("family_graphs.id", ondelete="SET NULL"), nullable=True
    )
    last_agent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    pending_handoff: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    #: 에이전트별 상태. {"heir_navigator": {...}, "tax_calculator": {...}, ...}
    per_agent_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    #: save() 시점에 (updated_at + TTL)로 채웁니다. load()가 매번 "지금 -
    #: updated_at"을 계산하는 대신 이 컬럼과 비교만 하면 되게 하기 위함이고,
    #: 나중에 만료 세션 삭제 배치를 붙일 때도 이 컬럼으로 바로 걸러낼 수
    #: 있습니다.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

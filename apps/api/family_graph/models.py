"""
family_graph DB 모델 (담당: 지원).

스키마는 통합_개발_방향_계획.md에서 팀과 정한 초안을 그대로 옮긴 것입니다.
relation 6종(spouse/child/parent/grandchild/sibling/grandparent)은
agents/heir_navigator/consent.py의 _RELATION_LABELS와 정확히 일치시켰습니다 —
그쪽이 이미 "형태 A"(heirs: [...])로 기대하고 있던 값 그대로입니다.

family_graphs를 세션(orchestrator의 ChatSession, 2시간 TTL)과 분리한 이유:
상속 절차는 몇 주~몇 달 이어질 수 있어서, 대화 세션이 만료돼도 가족관계
정보 자체는 남아있어야 합니다. 프론트가 family_graph_id를 세션과 별도로
(예: localStorage) 들고 있다가 매 요청에 함께 보내는 걸 전제로 합니다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _uuid4_hex() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelationType(str, Enum):
    SPOUSE = "spouse"
    CHILD = "child"
    PARENT = "parent"
    GRANDCHILD = "grandchild"
    SIBLING = "sibling"
    GRANDPARENT = "grandparent"


class FamilyGraph(Base):
    """가족관계 정보 한 벌. 세션보다 오래 사는 단위입니다."""

    __tablename__ = "family_graphs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid4_hex)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    #: 마지막으로 조회/수정된 시각. 장기 미사용 자동 파기 배치(개발_배포_
    #: 파이프라인_계획.md 10절)를 나중에 붙일 때 이 컬럼을 기준으로 삼습니다.
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    members: Mapped[list["FamilyMember"]] = relationship(
        back_populates="family_graph",
        cascade="all, delete-orphan",
        order_by="FamilyMember.created_at",
    )


class FamilyMember(Base):
    """가족 구성원 한 명."""

    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    family_graph_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("family_graphs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    relation: Mapped[RelationType] = mapped_column(
        SAEnum(
            RelationType,
            name="relation_type",
            # 기본값은 Enum 멤버 이름("SPOUSE")을 DB에 저장하는데, 그러면
            # API가 쓰는 값("spouse", consent.py의 relation 문자열과 동일)과
            # 어긋나 DB를 직접 볼 때 헷갈립니다. values_callable로 .value를
            # 저장하도록 맞춥니다.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    is_alive: Mapped[bool] = mapped_column(default=True)
    is_minor: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    family_graph: Mapped["FamilyGraph"] = relationship(back_populates="members")

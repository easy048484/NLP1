"""
family_graph DB 모델 (담당: 지원 · 노드-엣지 개편: 정민).

가족그래프 개편(docs/가족그래프_개편_설계안.md)에 따라 평평한 family_members
리스트를 persons(노드) + relations(엣지) 구조로 교체했습니다. GEDCOM 모델을
참고한 설계로, **피상속인도 명시적 노드**가 됩니다(is_decedent=True, 그래프당
정확히 1명).

"배우자/자녀/손자녀" 같은 관계 명칭은 더 이상 저장하지 않습니다 — 피상속인
노드로부터의 엣지 탐색으로 파생합니다(repository.derive_heirs 참고). 파생된
라벨 문자열은 기존 RelationType 6종 그대로라, 에이전트가 소비하는 "형태 A"
({"heirs": [...]}, agents/heir_navigator/consent.py)는 이 개편에서 바뀌지
않습니다.

family_graphs를 세션(orchestrator의 ChatSession, 2시간 TTL)과 분리한 이유:
상속 절차는 몇 주~몇 달 이어질 수 있어서, 대화 세션이 만료돼도 가족관계
정보 자체는 남아있어야 합니다. 프론트가 family_graph_id를 세션과 별도로
(예: localStorage) 들고 있다가 매 요청에 함께 보내는 걸 전제로 합니다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _uuid4_hex() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelationType(str, Enum):
    """피상속인 기준 파생 관계 라벨 6종.

    DB에 저장되지 않습니다(엣지 탐색으로 파생). 값 문자열은
    agents/heir_navigator/consent.py의 _RELATION_LABELS 키와 정확히 일치합니다.
    """

    SPOUSE = "spouse"
    CHILD = "child"
    PARENT = "parent"
    GRANDCHILD = "grandchild"
    SIBLING = "sibling"
    GRANDPARENT = "grandparent"


class RelationEdgeType(str, Enum):
    """구성원 사이의 실제 엣지 2종. 나머지 관계는 전부 이 둘의 조합으로 파생됩니다."""

    #: from이 to의 부모다
    PARENT_OF = "parent_of"
    #: from과 to가 배우자다 (방향 무의미 — 조회 시 양방향으로 봅니다)
    SPOUSE_OF = "spouse_of"


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

    persons: Mapped[list["Person"]] = relationship(
        back_populates="family_graph",
        cascade="all, delete-orphan",
        order_by="Person.id",
    )
    relations: Mapped[list["RelationEdge"]] = relationship(
        back_populates="family_graph",
        cascade="all, delete-orphan",
        order_by="RelationEdge.id",
    )


class Person(Base):
    """가족 구성원 노드 한 명. 피상속인 본인도 노드입니다."""

    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    family_graph_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("family_graphs.id", ondelete="CASCADE"), index=True
    )
    #: 표시용 호칭. 실명을 강제하지 않습니다("첫째", "배우자" 허용 — 민감정보 최소화).
    name: Mapped[str] = mapped_column(String(100))
    #: 피상속인(돌아가신 분 또는 대비하려는 분) 노드 표시. 그래프당 정확히 1명 —
    #: schemas.FamilyTreeIn이 저장 전에 검증합니다.
    is_decedent: Mapped[bool] = mapped_column(default=False)
    is_alive: Mapped[bool] = mapped_column(default=True)
    is_minor: Mapped[bool] = mapped_column(default=False)
    #: is_alive=False일 때의 사망일(선택). 지금은 저장만 하고 쓰지 않습니다 —
    #: 판정 엔진(engine.py)이 대습상속(민법 제1001조)의 선사망 여부를 따질 때
    #: 쓰게 될 자리입니다.
    death_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: 생년월일(선택). 채워지면 is_minor를 파생 계산할 수 있게 될 자리입니다.
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    family_graph: Mapped["FamilyGraph"] = relationship(back_populates="persons")


class RelationEdge(Base):
    """구성원 사이의 엣지 한 개."""

    __tablename__ = "relations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    family_graph_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("family_graphs.id", ondelete="CASCADE"), index=True
    )
    from_person_id: Mapped[int] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE")
    )
    to_person_id: Mapped[int] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE")
    )
    type: Mapped[RelationEdgeType] = mapped_column(
        SAEnum(
            RelationEdgeType,
            name="relation_edge_type",
            # Enum 멤버 이름("PARENT_OF")이 아니라 값("parent_of")을 저장합니다 —
            # API가 쓰는 값과 DB를 직접 볼 때의 값을 일치시키기 위해서입니다.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    family_graph: Mapped["FamilyGraph"] = relationship(back_populates="relations")

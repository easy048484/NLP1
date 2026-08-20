"""
family_graph CRUD + 오케스트레이터가 쓰는 조회 함수 (담당: 지원).

`get_heirs_dict()`가 이 모듈의 핵심 진입점입니다 — 오케스트레이터가
family_graph_id 하나만 갖고 AgentInput.family_graph를 채울 때 이 함수만
부르면 됩니다. DB가 설정 안 돼 있거나 조회에 실패하거나 구성원이 없으면
조용히 None을 돌려줍니다 — handoff.py의 "형식이 안 맞으면 조용히 폴백"과
같은 원칙입니다. family_graph_id 하나 잘못 보냈다고 오케스트레이터가
죽으면 안 됩니다.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.base import DatabaseNotConfigured, session_scope

from .models import FamilyGraph, FamilyMember, RelationType

logger = logging.getLogger(__name__)


def create_family_graph(db: Session) -> FamilyGraph:
    graph = FamilyGraph()
    db.add(graph)
    db.flush()
    return graph


def add_member(
    db: Session,
    family_graph_id: str,
    *,
    name: str,
    relation: RelationType | str,
    is_alive: bool = True,
    is_minor: bool = False,
) -> FamilyMember:
    member = FamilyMember(
        family_graph_id=family_graph_id,
        name=name,
        relation=RelationType(relation),
        is_alive=is_alive,
        is_minor=is_minor,
    )
    db.add(member)
    db.flush()
    return member


def list_members(db: Session, family_graph_id: str) -> list[FamilyMember]:
    stmt = (
        select(FamilyMember)
        .where(FamilyMember.family_graph_id == family_graph_id)
        .order_by(FamilyMember.created_at)
    )
    return list(db.scalars(stmt))


def member_to_heir_dict(member: FamilyMember) -> dict[str, Any]:
    """agents/heir_navigator/consent.py의 "형태 A" 항목 하나와 동일한 모양."""
    return {
        "name": member.name,
        "relation": member.relation.value,
        "alive": member.is_alive,
        "minor": member.is_minor,
    }


def get_heirs_dict(family_graph_id: Optional[str]) -> Optional[dict[str, Any]]:
    """family_graph_id로 DB를 조회해 AgentInput.family_graph에 넣을 dict를 만듭니다.

    성공하면 {"heirs": [...]} (consent.py가 기대하는 "형태 A" 그대로).
    다음 경우엔 조용히 None을 돌려줍니다 — 호출부(오케스트레이터)가 다른
    값으로 폴백할 수 있게: family_graph_id가 없을 때, DB가 설정 안 됐을 때,
    DB 조회 자체가 실패했을 때, 구성원이 하나도 없을 때.
    """
    if not family_graph_id:
        return None
    try:
        with session_scope() as db:
            members = list_members(db, family_graph_id)
    except DatabaseNotConfigured:
        return None
    except Exception:  # noqa: BLE001 — DB 조회 실패로 요청 전체를 죽이지 않음
        logger.warning(
            "family_graph_id=%s 조회 실패, family_graph 없이 진행합니다.",
            family_graph_id,
            exc_info=True,
        )
        return None

    if not members:
        return None
    return {"heirs": [member_to_heir_dict(m) for m in members]}

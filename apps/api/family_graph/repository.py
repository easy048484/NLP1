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

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db.base import DatabaseNotConfigured, mask_sensitive_id, session_scope

from .models import FamilyGraph, FamilyMember, RelationType

logger = logging.getLogger(__name__)


def create_family_graph(db: Session, *, user_id: Optional[str] = None) -> FamilyGraph:
    graph = FamilyGraph(user_id=user_id)
    db.add(graph)
    db.flush()
    return graph


def get_latest_for_user(db: Session, user_id: str) -> Optional[FamilyGraph]:
    """이 사용자가 소유한 가족관계 그래프 중 가장 최근 것.

    MVP에서는 한 사용자가 그래프 하나만 쓰는 것을 전제로 하지만, 과거에
    익명으로 만든 그래프를 로그인 후 연결하는 흐름 등에서 여러 개가 생길 수
    있어 "가장 최근 생성분"을 돌려줍니다.
    """
    stmt = (
        select(FamilyGraph)
        .where(FamilyGraph.user_id == user_id)
        .order_by(FamilyGraph.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def user_can_access(graph: FamilyGraph, user_id: Optional[str]) -> bool:
    """요청자가 이 그래프를 조회·수정할 수 있는지.

    - user_id가 NULL인 그래프: 누구나(id를 아는 사람) 접근 — 기존
      capability-token 모델 유지(테스트·레거시).
    - user_id가 채워진 그래프: 그 사용자 본인만.
    """
    if graph.user_id is None:
        return True
    return graph.user_id == user_id


def claim_family_graph(
    db: Session, family_graph_id: str, user_id: str
) -> Optional[FamilyGraph]:
    """소유자가 없는(user_id IS NULL) 그래프를 이 사용자 것으로 연결합니다.

    로그인 전 익명으로 시작해 가족관계를 입력한 사용자가 나중에 가입/로그인
    했을 때, 그 그래프를 계정에 붙이는 용도입니다. 이미 다른 사람 소유면
    None(연결 불가), 대상이 없어도 None.
    """
    graph = db.get(FamilyGraph, family_graph_id)
    if graph is None:
        return None
    if graph.user_id is not None and graph.user_id != user_id:
        return None
    graph.user_id = user_id
    touch_family_graph(db, family_graph_id)
    db.flush()
    return graph


def purge_anonymous_graphs(db: Session, *, older_than: datetime) -> int:
    """소유자 없는(비로그인) 가족관계 그래프 중 오래 안 쓰인 것을 지웁니다.

    비로그인 사용자가 입력한 가족정보는 "대화창을 떠나면 남지 않는다"가
    원칙입니다. 그런데 프론트가 family_graph_id를 localStorage에 들고 있고
    이 행에는 만료 개념이 없어서, 지금까지는 익명으로 입력한 가족관계가
    서버에 영구히 남아 있었습니다. id만 알면 누구나 조회할 수 있는 데이터라
    (user_can_access — user_id가 NULL이면 접근 허용) 더 오래 둘 이유가 없습니다.

    소유자가 있는 그래프는 건드리지 않습니다. 그쪽 장기 미사용 파기(예: 1년)는
    docs/개발_배포_파이프라인_계획.md 10절의 별도 항목입니다.

    family_members는 FK의 ON DELETE CASCADE로 함께 지워지고, 이 그래프를
    가리키던 sessions.family_graph_id는 SET NULL로 비워집니다.
    """
    result = db.execute(
        delete(FamilyGraph).where(
            FamilyGraph.user_id.is_(None),
            FamilyGraph.last_accessed_at < older_than,
        )
    )
    return int(result.rowcount or 0)


def touch_family_graph(db: Session, family_graph_id: str) -> None:
    """family_graphs.last_accessed_at을 지금 시각으로 갱신합니다.

    조회/구성원 추가처럼 "이 family_graph가 실제로 쓰이고 있다"는 신호가
    있을 때마다 호출합니다. 나중에 붙일 장기 미사용 자동 파기 배치
    (개발_배포_파이프라인_계획.md 10절)가 이 컬럼을 기준으로 삼기로 했으므로,
    갱신을 빼먹으면 계속 쓰이는 family_graph가 생성일 기준으로 잘못
    파기될 수 있습니다. 대상이 없으면 조용히 아무 것도 하지 않습니다 —
    호출부가 존재 여부를 매번 따로 확인할 필요 없게 하기 위해서입니다.
    """
    graph = db.get(FamilyGraph, family_graph_id)
    if graph is not None:
        graph.last_accessed_at = datetime.now(timezone.utc)


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
    touch_family_graph(db, family_graph_id)
    db.flush()
    return member


def list_members(db: Session, family_graph_id: str) -> list[FamilyMember]:
    stmt = (
        select(FamilyMember)
        .where(FamilyMember.family_graph_id == family_graph_id)
        .order_by(FamilyMember.created_at)
    )
    return list(db.scalars(stmt))


def get_member(
    db: Session, family_graph_id: str, member_id: int
) -> Optional[FamilyMember]:
    """구성원을 조회하되, 그 family_graph_id 소속이 아니면 못 찾은 것으로 취급합니다.

    member_id(자동증가 정수)만으로 조회하면 다른 family_graph의 구성원을
    실수로/악의적으로 수정·삭제할 수 있으므로, 두 값이 같이 맞아야만
    돌려줍니다.
    """
    member = db.get(FamilyMember, member_id)
    if member is None or member.family_graph_id != family_graph_id:
        return None
    return member


def update_member(
    db: Session,
    family_graph_id: str,
    member_id: int,
    *,
    name: Optional[str] = None,
    relation: Optional[RelationType | str] = None,
    is_alive: Optional[bool] = None,
    is_minor: Optional[bool] = None,
) -> Optional[FamilyMember]:
    """구성원의 일부 필드만 갱신합니다. None인 필드는 건드리지 않습니다.

    대상이 없으면(다른 family_graph 소속 포함) None을 돌려줘서, 라우터가
    404로 응답할 수 있게 합니다.
    """
    member = get_member(db, family_graph_id, member_id)
    if member is None:
        return None

    if name is not None:
        member.name = name
    if relation is not None:
        member.relation = RelationType(relation)
    if is_alive is not None:
        member.is_alive = is_alive
    if is_minor is not None:
        member.is_minor = is_minor

    touch_family_graph(db, family_graph_id)
    db.flush()
    return member


def delete_member(db: Session, family_graph_id: str, member_id: int) -> bool:
    """구성원을 삭제합니다. 실제로 지웠으면 True, 대상이 없었으면 False."""
    member = get_member(db, family_graph_id, member_id)
    if member is None:
        return False

    db.delete(member)
    touch_family_graph(db, family_graph_id)
    db.flush()
    return True


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
            if members:
                touch_family_graph(db, family_graph_id)
    except DatabaseNotConfigured:
        return None
    except Exception:  # noqa: BLE001 — DB 조회 실패로 요청 전체를 죽이지 않음
        logger.warning(
            "family_graph_id=%s 조회 실패, family_graph 없이 진행합니다.",
            mask_sensitive_id(family_graph_id),
            exc_info=True,
        )
        return None

    if not members:
        return None
    return {"heirs": [member_to_heir_dict(m) for m in members]}

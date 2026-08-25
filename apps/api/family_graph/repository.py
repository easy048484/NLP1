"""
family_graph 저장/조회 + 오케스트레이터가 쓰는 파생 함수 (담당: 지원 · 개편: 정민).

`get_heirs_dict()`가 이 모듈의 핵심 진입점입니다 — 오케스트레이터가
family_graph_id 하나만 갖고 AgentInput.family_graph를 채울 때 이 함수만
부르면 됩니다. DB가 설정 안 돼 있거나 조회에 실패하거나 구성원이 없으면
조용히 None을 돌려줍니다 — handoff.py의 "형식이 안 맞으면 조용히 폴백"과
같은 원칙입니다. family_graph_id 하나 잘못 보냈다고 오케스트레이터가
죽으면 안 됩니다.

노드-엣지 개편 이후 관계 명칭(spouse/child/…)은 저장돼 있지 않고, 피상속인
노드로부터의 엣지 탐색으로 파생합니다(derive_heirs). 이건 "라벨링"이지
상속인 판정이 아닙니다 — 누가 법적으로 상속인인지(순위·대습·결격)는
engine.py에 들어올 판정 엔진의 몫이고, 지금은 heir_navigator/consent.py가
하던 대로 입력된 가족을 그대로 신뢰합니다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from db.base import DatabaseNotConfigured, mask_sensitive_id, session_scope

from .models import FamilyGraph, Person, RelationEdge, RelationEdgeType, RelationType
from .schemas import FamilyTreeIn

logger = logging.getLogger(__name__)


def create_family_graph(db: Session) -> FamilyGraph:
    graph = FamilyGraph()
    db.add(graph)
    db.flush()
    return graph


def touch_family_graph(db: Session, family_graph_id: str) -> None:
    """family_graphs.last_accessed_at을 지금 시각으로 갱신합니다.

    조회/저장처럼 "이 family_graph가 실제로 쓰이고 있다"는 신호가 있을 때마다
    호출합니다. 장기 미사용 자동 파기 배치(개발_배포_파이프라인_계획.md 10절)가
    이 컬럼을 기준으로 삼기로 했으므로, 갱신을 빼먹으면 계속 쓰이는
    family_graph가 생성일 기준으로 잘못 파기될 수 있습니다. 대상이 없으면
    조용히 아무 것도 하지 않습니다.
    """
    graph = db.get(FamilyGraph, family_graph_id)
    if graph is not None:
        graph.last_accessed_at = datetime.now(timezone.utc)


def replace_tree(db: Session, family_graph_id: str, tree: FamilyTreeIn) -> None:
    """그래프의 persons/relations를 트리 입력으로 통째로 교체합니다.

    부분 수정 API를 두지 않는 이유: 프론트가 항상 완성된 트리를 들고 있어서
    "이 트리로 교체"면 충분하고, 피상속인 1명 같은 트리 단위 검증
    (schemas.FamilyTreeIn)을 우회할 경로가 생기지 않습니다.
    """
    db.execute(
        delete(RelationEdge).where(RelationEdge.family_graph_id == family_graph_id)
    )
    db.execute(delete(Person).where(Person.family_graph_id == family_graph_id))

    key_to_person: dict[str, Person] = {}
    for spec in tree.persons:
        person = Person(
            family_graph_id=family_graph_id,
            name=spec.name,
            is_decedent=spec.is_decedent,
            is_alive=spec.is_alive,
            is_minor=spec.is_minor,
            death_date=spec.death_date,
            birth_date=spec.birth_date,
        )
        db.add(person)
        key_to_person[spec.key] = person
    db.flush()  # persons의 id 확정 (relations가 참조해야 하므로)

    for rel in tree.relations:
        db.add(
            RelationEdge(
                family_graph_id=family_graph_id,
                from_person_id=key_to_person[rel.from_key].id,
                to_person_id=key_to_person[rel.to_key].id,
                type=rel.type,
            )
        )
    touch_family_graph(db, family_graph_id)
    db.flush()


def load_tree(
    db: Session, family_graph_id: str
) -> tuple[list[Person], list[RelationEdge]]:
    persons = list(
        db.scalars(
            select(Person)
            .where(Person.family_graph_id == family_graph_id)
            .order_by(Person.id)
        )
    )
    relations = list(
        db.scalars(
            select(RelationEdge)
            .where(RelationEdge.family_graph_id == family_graph_id)
            .order_by(RelationEdge.id)
        )
    )
    return persons, relations


#: 형태 A 목록의 표시 순서. 협의 서명자 안내에서 배우자·자녀가 먼저 보여야
#: 자연스럽습니다.
_LABEL_ORDER = {
    RelationType.SPOUSE: 0,
    RelationType.CHILD: 1,
    RelationType.PARENT: 2,
    RelationType.SIBLING: 3,
    RelationType.GRANDCHILD: 4,
    RelationType.GRANDPARENT: 5,
}


def derive_heirs(
    persons: list[Person], relations: list[RelationEdge]
) -> list[dict[str, Any]]:
    """피상속인 노드에서 엣지를 따라가 각 구성원의 관계 라벨을 파생합니다.

    반환 형태는 consent.py의 "형태 A" 항목과 동일합니다:
        {"name": ..., "relation": "spouse"|"child"|..., "alive": ..., "minor": ...}

    피상속인 본인은 목록에서 제외합니다. 엣지로 라벨을 파생할 수 없는 노드
    (피상속인과 2단계 안에 연결되지 않음)는 경고만 남기고 건너뜁니다 —
    잘못된 라벨을 지어내느니 빼는 쪽이 안전합니다.
    """
    decedent = next((p for p in persons if p.is_decedent), None)
    if decedent is None:
        return []

    children_of: dict[int, list[int]] = {}  # 부모 id -> 자식 id들
    parents_of: dict[int, list[int]] = {}  # 자식 id -> 부모 id들
    spouses_of: dict[int, list[int]] = {}
    for edge in relations:
        if edge.type is RelationEdgeType.PARENT_OF:
            children_of.setdefault(edge.from_person_id, []).append(edge.to_person_id)
            parents_of.setdefault(edge.to_person_id, []).append(edge.from_person_id)
        elif edge.type is RelationEdgeType.SPOUSE_OF:
            spouses_of.setdefault(edge.from_person_id, []).append(edge.to_person_id)
            spouses_of.setdefault(edge.to_person_id, []).append(edge.from_person_id)

    labels: dict[int, RelationType] = {}

    def label(person_id: int, relation: RelationType) -> None:
        # 먼저 매긴(더 가까운) 라벨을 유지합니다 — 탐색이 가까운 관계부터
        # 진행되므로, 이미 라벨이 있으면 더 먼 경로로 온 것입니다.
        if person_id != decedent.id and person_id not in labels:
            labels[person_id] = relation

    for spouse_id in spouses_of.get(decedent.id, []):
        label(spouse_id, RelationType.SPOUSE)

    child_ids = children_of.get(decedent.id, [])
    for child_id in child_ids:
        label(child_id, RelationType.CHILD)
    for child_id in child_ids:
        for grandchild_id in children_of.get(child_id, []):
            label(grandchild_id, RelationType.GRANDCHILD)

    parent_ids = parents_of.get(decedent.id, [])
    for parent_id in parent_ids:
        label(parent_id, RelationType.PARENT)
    for parent_id in parent_ids:
        # 부모의 다른 자식 = 형제자매, 부모의 부모 = 조부모
        for sibling_id in children_of.get(parent_id, []):
            label(sibling_id, RelationType.SIBLING)
        for grandparent_id in parents_of.get(parent_id, []):
            label(grandparent_id, RelationType.GRANDPARENT)

    unreachable = [p.name for p in persons if not p.is_decedent and p.id not in labels]
    if unreachable:
        logger.warning(
            "피상속인과 연결되지 않아 관계를 파생할 수 없는 구성원을 " "제외합니다: %s",
            ", ".join(unreachable),
        )

    entries = [
        {
            "name": p.name,
            "relation": labels[p.id].value,
            "alive": p.is_alive,
            "minor": p.is_minor,
        }
        for p in persons
        if p.id in labels
    ]
    entries.sort(
        key=lambda e: _LABEL_ORDER[RelationType(e["relation"])]
    )  # 같은 라벨끼리는 persons의 입력 순서(id 순) 유지 — sort는 안정 정렬
    return entries


def get_heirs_dict(family_graph_id: Optional[str]) -> Optional[dict[str, Any]]:
    """family_graph_id로 DB를 조회해 AgentInput.family_graph에 넣을 dict를 만듭니다.

    성공하면 {"heirs": [...]} (consent.py가 기대하는 "형태 A" 그대로).
    다음 경우엔 조용히 None을 돌려줍니다 — 호출부(오케스트레이터)가 다른
    값으로 폴백할 수 있게: family_graph_id가 없을 때, DB가 설정 안 됐을 때,
    DB 조회 자체가 실패했을 때, 구성원(피상속인 제외)이 하나도 없을 때.
    """
    if not family_graph_id:
        return None
    try:
        with session_scope() as db:
            persons, relations = load_tree(db, family_graph_id)
            if persons:
                touch_family_graph(db, family_graph_id)
            heirs = derive_heirs(persons, relations)
    except DatabaseNotConfigured:
        return None
    except Exception:  # noqa: BLE001 — DB 조회 실패로 요청 전체를 죽이지 않음
        logger.warning(
            "family_graph_id=%s 조회 실패, family_graph 없이 진행합니다.",
            mask_sensitive_id(family_graph_id),
            exc_info=True,
        )
        return None

    if not heirs:
        return None
    return {"heirs": heirs}

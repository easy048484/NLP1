from __future__ import annotations

from sqlalchemy.orm import Session

from .models import RelationType
from .repository import list_members


def compute_legal_shares(spouse_alive: bool, num_children: int) -> dict[str, float]:
    """민법상 법정상속분 계산 (배우자 1.5 : 자녀 각 1 비율)의 최소 구현.

    실제로는 직계존속만 있는 경우, 형제자매 상속 등 더 많은 케이스를 다뤄야 하며,
    아직 여기까지는 구현하지 않았습니다 (자녀가 없는 케이스는 이번 Phase 2
    범위 밖 — DB 연결과는 별개의 법률 로직 확장 작업입니다).
    """
    if num_children == 0:
        raise NotImplementedError("자녀가 없는 케이스는 3단계에서 구현 예정")

    spouse_share = 1.5 if spouse_alive else 0.0
    total_units = spouse_share + num_children
    child_unit = 1 / total_units

    result = {"child_each": round(child_unit, 4)}
    if spouse_alive:
        result["spouse"] = round((spouse_share / total_units), 4)
    return result


def compute_legal_shares_for_family(
    db: Session, family_graph_id: str
) -> dict[str, float]:
    """DB에 저장된 가족 구성원을 조회해서 compute_legal_shares()를 대신 호출합니다.

    compute_legal_shares() 자체는 순수 함수로 그대로 두고, 이 함수는 그
    입력(spouse_alive, num_children)을 DB에서 채워주는 얇은 래퍼입니다.
    num_children이 0인 케이스의 NotImplementedError는 여기서도 그대로
    전파됩니다 — 위 함수 docstring 참고.
    """
    members = list_members(db, family_graph_id)
    spouse_alive = any(
        m.relation == RelationType.SPOUSE and m.is_alive for m in members
    )
    num_children = sum(
        1 for m in members if m.relation == RelationType.CHILD and m.is_alive
    )
    return compute_legal_shares(spouse_alive=spouse_alive, num_children=num_children)

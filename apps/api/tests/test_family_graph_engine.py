"""family_graph.engine 테스트: 순수 함수(기존)와 DB 연동 래퍼(신규)."""

from __future__ import annotations

import pytest

from db.base import session_scope
from family_graph.engine import compute_legal_shares, compute_legal_shares_for_family
from family_graph.models import RelationType
from family_graph.repository import add_member, create_family_graph


def test_compute_legal_shares_pure_function_unchanged():
    """기존 순수 함수는 이번 작업에서 건드리지 않았습니다 — 회귀 확인용."""
    assert compute_legal_shares(spouse_alive=True, num_children=2) == {
        "child_each": 0.2857,
        "spouse": 0.4286,
    }

    with pytest.raises(NotImplementedError):
        compute_legal_shares(spouse_alive=True, num_children=0)


def test_compute_legal_shares_for_family_reads_from_db(with_db):
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(db, graph_id, name="배우자", relation=RelationType.SPOUSE)
        add_member(db, graph_id, name="자녀 1", relation=RelationType.CHILD)
        add_member(db, graph_id, name="자녀 2", relation=RelationType.CHILD)
        # 사망한 형제자매는 spouse_alive/num_children 계산에 영향을 주면 안 됩니다.
        add_member(
            db, graph_id, name="사망한 배우자 아님", relation=RelationType.SIBLING
        )

        result = compute_legal_shares_for_family(db, graph_id)

    assert result == compute_legal_shares(spouse_alive=True, num_children=2)


def test_compute_legal_shares_for_family_ignores_deceased_members(with_db):
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(
            db, graph_id, name="배우자", relation=RelationType.SPOUSE, is_alive=False
        )
        add_member(db, graph_id, name="자녀 1", relation=RelationType.CHILD)

        result = compute_legal_shares_for_family(db, graph_id)

    assert result == compute_legal_shares(spouse_alive=False, num_children=1)

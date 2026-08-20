"""family_graph 모델·repository CRUD 테스트 (실제 Postgres 필요, with_db 참고)."""

from __future__ import annotations

from db.base import session_scope
from family_graph.models import RelationType
from family_graph.repository import (
    add_member,
    create_family_graph,
    get_heirs_dict,
    list_members,
)


def test_create_family_graph_and_add_members(with_db):
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(db, graph_id, name="배우자", relation=RelationType.SPOUSE)
        add_member(db, graph_id, name="자녀 1", relation="child", is_minor=True)

    with session_scope() as db:
        members = list_members(db, graph_id)

    assert [m.name for m in members] == ["배우자", "자녀 1"]
    assert members[0].relation == RelationType.SPOUSE
    assert members[1].is_minor is True


def test_get_heirs_dict_matches_consent_shape_a(with_db):
    """consent.py의 _read_heirs가 기대하는 '형태 A' 그대로 나오는지 확인."""
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(db, graph_id, name="배우자", relation=RelationType.SPOUSE)
        add_member(
            db, graph_id, name="자녀 1", relation=RelationType.CHILD, is_minor=True
        )
        add_member(
            db, graph_id, name="자녀 2", relation=RelationType.CHILD, is_alive=False
        )

    result = get_heirs_dict(graph_id)

    assert result == {
        "heirs": [
            {"name": "배우자", "relation": "spouse", "alive": True, "minor": False},
            {"name": "자녀 1", "relation": "child", "alive": True, "minor": True},
            {"name": "자녀 2", "relation": "child", "alive": False, "minor": False},
        ]
    }


def test_get_heirs_dict_returns_none_for_unknown_id(with_db):
    assert get_heirs_dict("no-such-id") is None


def test_get_heirs_dict_returns_none_for_empty_id():
    assert get_heirs_dict(None) is None
    assert get_heirs_dict("") is None

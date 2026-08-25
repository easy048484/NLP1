"""family_graph 모델·repository 테스트.

derive_heirs는 순수 함수라 DB 없이 검증하고, 저장/조회 왕복은 실제
Postgres가 있을 때만 돌아갑니다(with_db 참고).
"""

from __future__ import annotations

from db.base import session_scope
from family_graph.models import Person, RelationEdge, RelationEdgeType
from family_graph.repository import (
    create_family_graph,
    derive_heirs,
    get_heirs_dict,
    load_tree,
    replace_tree,
)
from family_graph.schemas import FamilyTreeIn


def _tree_payload() -> FamilyTreeIn:
    """피상속인 + 배우자 + 자녀 2(막내 미성년, 첫째 사망)의 표준 트리."""
    return FamilyTreeIn.model_validate(
        {
            "persons": [
                {"key": "d", "name": "고인", "is_decedent": True, "is_alive": False},
                {"key": "s", "name": "배우자"},
                {"key": "c1", "name": "자녀 1", "is_alive": False},
                {"key": "c2", "name": "자녀 2", "is_minor": True},
            ],
            "relations": [
                {"type": "spouse_of", "from_key": "d", "to_key": "s"},
                {"type": "parent_of", "from_key": "d", "to_key": "c1"},
                {"type": "parent_of", "from_key": "d", "to_key": "c2"},
            ],
        }
    )


# ---------------------------------------------------------- derive_heirs (순수)


def _person(pid: int, name: str, *, decedent=False, alive=True, minor=False) -> Person:
    person = Person(name=name, is_decedent=decedent, is_alive=alive, is_minor=minor)
    person.id = pid
    return person


def _edge(type_: RelationEdgeType, from_id: int, to_id: int) -> RelationEdge:
    return RelationEdge(type=type_, from_person_id=from_id, to_person_id=to_id)


def test_derive_heirs_labels_spouse_and_children_shape_a():
    persons = [
        _person(1, "고인", decedent=True, alive=False),
        _person(2, "배우자"),
        _person(3, "자녀 1", alive=False),
        _person(4, "자녀 2", minor=True),
    ]
    edges = [
        _edge(RelationEdgeType.SPOUSE_OF, 1, 2),
        _edge(RelationEdgeType.PARENT_OF, 1, 3),
        _edge(RelationEdgeType.PARENT_OF, 1, 4),
    ]

    assert derive_heirs(persons, edges) == [
        {"name": "배우자", "relation": "spouse", "alive": True, "minor": False},
        {"name": "자녀 1", "relation": "child", "alive": False, "minor": False},
        {"name": "자녀 2", "relation": "child", "alive": True, "minor": True},
    ]


def test_derive_heirs_labels_two_hop_relations():
    """부모·형제자매·손자녀·조부모까지 2단계 탐색 라벨이 맞는지."""
    persons = [
        _person(1, "고인", decedent=True, alive=False),
        _person(2, "아버지"),
        _person(3, "동생"),
        _person(4, "자녀"),
        _person(5, "손자"),
        _person(6, "할아버지"),
    ]
    edges = [
        _edge(RelationEdgeType.PARENT_OF, 2, 1),  # 아버지 → 고인
        _edge(RelationEdgeType.PARENT_OF, 2, 3),  # 아버지 → 동생 (형제자매)
        _edge(RelationEdgeType.PARENT_OF, 1, 4),  # 고인 → 자녀
        _edge(RelationEdgeType.PARENT_OF, 4, 5),  # 자녀 → 손자
        _edge(RelationEdgeType.PARENT_OF, 6, 2),  # 할아버지 → 아버지
    ]

    result = {entry["name"]: entry["relation"] for entry in derive_heirs(persons, edges)}
    assert result == {
        "아버지": "parent",
        "동생": "sibling",
        "자녀": "child",
        "손자": "grandchild",
        "할아버지": "grandparent",
    }


def test_derive_heirs_skips_unreachable_person():
    persons = [
        _person(1, "고인", decedent=True),
        _person(2, "연결 안 된 사람"),
    ]
    assert derive_heirs(persons, []) == []


def test_derive_heirs_without_decedent_returns_empty():
    assert derive_heirs([_person(1, "누군가")], []) == []


# ------------------------------------------------------------- DB 왕복 (with_db)


def test_replace_tree_and_load(with_db):
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        replace_tree(db, graph_id, _tree_payload())

    with session_scope() as db:
        persons, relations = load_tree(db, graph_id)

    assert [p.name for p in persons] == ["고인", "배우자", "자녀 1", "자녀 2"]
    assert [p.is_decedent for p in persons] == [True, False, False, False]
    assert len(relations) == 3


def test_replace_tree_replaces_everything(with_db):
    """같은 id로 다시 저장하면 이전 구성원이 남지 않아야 합니다."""
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        replace_tree(db, graph_id, _tree_payload())
        replace_tree(
            db,
            graph_id,
            FamilyTreeIn.model_validate(
                {
                    "persons": [
                        {"key": "d", "name": "고인", "is_decedent": True},
                        {"key": "m", "name": "어머니"},
                    ],
                    "relations": [
                        {"type": "parent_of", "from_key": "m", "to_key": "d"}
                    ],
                }
            ),
        )

    with session_scope() as db:
        persons, relations = load_tree(db, graph_id)

    assert [p.name for p in persons] == ["고인", "어머니"]
    assert len(relations) == 1


def test_get_heirs_dict_matches_consent_shape_a(with_db):
    """consent.py의 _read_heirs가 기대하는 '형태 A' 그대로 나오는지 확인."""
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        replace_tree(db, graph_id, _tree_payload())

    assert get_heirs_dict(graph_id) == {
        "heirs": [
            {"name": "배우자", "relation": "spouse", "alive": True, "minor": False},
            {"name": "자녀 1", "relation": "child", "alive": False, "minor": False},
            {"name": "자녀 2", "relation": "child", "alive": True, "minor": True},
        ]
    }


def test_get_heirs_dict_returns_none_for_unknown_id(with_db):
    assert get_heirs_dict("no-such-id") is None


def test_get_heirs_dict_returns_none_for_empty_id():
    assert get_heirs_dict(None) is None
    assert get_heirs_dict("") is None

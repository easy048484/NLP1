"""family_graph REST API 테스트 (실제 Postgres 필요, with_db 참고).

트리 검증(피상속인 1명 등)은 pydantic 스키마에서 일어나므로 DB 없이도
422가 확인되지만, get_db 의존성이 DATABASE_URL을 먼저 요구하므로
검증 테스트도 with_db로 묶습니다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from family_graph.router import router as family_graph_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(family_graph_router)
    return TestClient(app)


def _tree_body() -> dict:
    return {
        "persons": [
            {"key": "d", "name": "고인", "is_decedent": True, "is_alive": False},
            {"key": "s", "name": "배우자"},
            {"key": "c1", "name": "첫째", "is_minor": True},
        ],
        "relations": [
            {"type": "spouse_of", "from_key": "d", "to_key": "s"},
            {"type": "parent_of", "from_key": "d", "to_key": "c1"},
        ],
    }


def test_create_and_read_family_tree(with_db):
    client = _client()

    create_resp = client.post("/family-graph", json=_tree_body())
    assert create_resp.status_code == 201
    body = create_resp.json()
    graph_id = body["id"]
    assert [p["name"] for p in body["persons"]] == ["고인", "배우자", "첫째"]
    assert len(body["relations"]) == 2

    read_resp = client.get(f"/family-graph/{graph_id}")
    assert read_resp.status_code == 200
    read_body = read_resp.json()
    assert read_body["id"] == graph_id
    assert [p["name"] for p in read_body["persons"]] == ["고인", "배우자", "첫째"]
    # 프리필에 필요한 필드가 다 내려오는지
    decedent = read_body["persons"][0]
    assert decedent["is_decedent"] is True
    assert read_body["relations"][0]["type"] == "spouse_of"


def test_put_replaces_tree_keeping_id(with_db):
    client = _client()
    graph_id = client.post("/family-graph", json=_tree_body()).json()["id"]

    new_tree = {
        "persons": [
            {"key": "d", "name": "고인", "is_decedent": True},
            {"key": "m", "name": "어머니"},
        ],
        "relations": [{"type": "parent_of", "from_key": "m", "to_key": "d"}],
    }
    put_resp = client.put(f"/family-graph/{graph_id}", json=new_tree)
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["id"] == graph_id
    assert [p["name"] for p in body["persons"]] == ["고인", "어머니"]


def test_read_unknown_family_graph_returns_404(with_db):
    client = _client()
    assert client.get("/family-graph/no-such-id").status_code == 404


def test_put_unknown_family_graph_returns_404(with_db):
    client = _client()
    resp = client.put("/family-graph/no-such-id", json=_tree_body())
    assert resp.status_code == 404


def test_tree_without_decedent_is_rejected(with_db):
    client = _client()
    resp = client.post(
        "/family-graph",
        json={"persons": [{"key": "s", "name": "배우자"}], "relations": []},
    )
    assert resp.status_code == 422


def test_tree_with_two_decedent_spouses_is_rejected(with_db):
    client = _client()
    resp = client.post(
        "/family-graph",
        json={
            "persons": [
                {"key": "d", "name": "고인", "is_decedent": True},
                {"key": "s1", "name": "배우자 1"},
                {"key": "s2", "name": "배우자 2"},
            ],
            "relations": [
                {"type": "spouse_of", "from_key": "d", "to_key": "s1"},
                {"type": "spouse_of", "from_key": "s2", "to_key": "d"},
            ],
        },
    )
    assert resp.status_code == 422


def test_tree_with_dangling_relation_key_is_rejected(with_db):
    client = _client()
    resp = client.post(
        "/family-graph",
        json={
            "persons": [{"key": "d", "name": "고인", "is_decedent": True}],
            "relations": [{"type": "parent_of", "from_key": "d", "to_key": "ghost"}],
        },
    )
    assert resp.status_code == 422

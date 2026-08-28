"""family_graph REST API 테스트 (실제 Postgres 필요, with_db 참고)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from family_graph.router import router as family_graph_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(family_graph_router)
    return TestClient(app)


def test_create_family_graph_and_add_member(with_db):
    client = _client()

    create_resp = client.post("/family-graph")
    assert create_resp.status_code == 201
    graph_id = create_resp.json()["id"]

    member_resp = client.post(
        f"/family-graph/{graph_id}/members",
        json={"name": "배우자", "relation": "spouse"},
    )
    assert member_resp.status_code == 201
    assert member_resp.json()["relation"] == "spouse"

    read_resp = client.get(f"/family-graph/{graph_id}")
    assert read_resp.status_code == 200
    body = read_resp.json()
    assert body["id"] == graph_id
    assert len(body["members"]) == 1
    assert body["members"][0]["name"] == "배우자"


def test_read_unknown_family_graph_returns_404(with_db):
    client = _client()
    resp = client.get("/family-graph/no-such-id")
    assert resp.status_code == 404


def test_add_member_to_unknown_family_graph_returns_404(with_db):
    client = _client()
    resp = client.post(
        "/family-graph/no-such-id/members",
        json={"name": "배우자", "relation": "spouse"},
    )
    assert resp.status_code == 404


def _create_graph_with_member(client: TestClient) -> tuple[str, int]:
    graph_id = client.post("/family-graph").json()["id"]
    member = client.post(
        f"/family-graph/{graph_id}/members",
        json={"name": "자녀 1", "relation": "child", "is_minor": True},
    ).json()
    return graph_id, member["id"]


def test_patch_member_updates_only_sent_fields(with_db):
    client = _client()
    graph_id, member_id = _create_graph_with_member(client)

    resp = client.patch(
        f"/family-graph/{graph_id}/members/{member_id}",
        json={"is_minor": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_minor"] is False
    # 안 보낸 필드(name, relation)는 그대로 유지돼야 함
    assert body["name"] == "자녀 1"
    assert body["relation"] == "child"

    read_resp = client.get(f"/family-graph/{graph_id}")
    assert read_resp.json()["members"][0]["is_minor"] is False


def test_patch_member_with_empty_body_returns_400(with_db):
    client = _client()
    graph_id, member_id = _create_graph_with_member(client)

    resp = client.patch(f"/family-graph/{graph_id}/members/{member_id}", json={})
    assert resp.status_code == 400


def test_patch_unknown_member_returns_404(with_db):
    client = _client()
    graph_id = client.post("/family-graph").json()["id"]

    resp = client.patch(
        f"/family-graph/{graph_id}/members/999999",
        json={"name": "새 이름"},
    )
    assert resp.status_code == 404


def test_patch_member_of_another_family_graph_returns_404(with_db):
    """다른 family_graph 소속 member_id로 고치려 하면 404 — 그래프 간 교차 접근 방지."""
    client = _client()
    _, member_id = _create_graph_with_member(client)
    other_graph_id = client.post("/family-graph").json()["id"]

    resp = client.patch(
        f"/family-graph/{other_graph_id}/members/{member_id}",
        json={"name": "새 이름"},
    )
    assert resp.status_code == 404


def test_delete_member_removes_it(with_db):
    client = _client()
    graph_id, member_id = _create_graph_with_member(client)

    resp = client.delete(f"/family-graph/{graph_id}/members/{member_id}")
    assert resp.status_code == 204

    read_resp = client.get(f"/family-graph/{graph_id}")
    assert read_resp.json()["members"] == []


def test_delete_unknown_member_returns_404(with_db):
    client = _client()
    graph_id = client.post("/family-graph").json()["id"]

    resp = client.delete(f"/family-graph/{graph_id}/members/999999")
    assert resp.status_code == 404

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

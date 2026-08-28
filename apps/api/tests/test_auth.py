"""회원가입·로그인 + family_graph 소유권 테스트 (실제 Postgres 필요, with_db)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.router import router as auth_router
from family_graph.router import router as family_graph_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(family_graph_router)
    return TestClient(app)


def _register(client: TestClient, email: str = "kim@example.com") -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "hunter2pass", "name": "김민준"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- register


def test_register_returns_token_and_user(with_db):
    client = _client()
    resp = client.post(
        "/auth/register",
        json={"email": "A@Example.com", "password": "hunter2pass", "name": "김민준"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "a@example.com"  # 소문자 정규화
    assert body["user"]["name"] == "김민준"
    assert "password" not in body["user"]


def test_register_duplicate_email_returns_409(with_db):
    client = _client()
    _register(client, "dup@example.com")
    resp = client.post(
        "/auth/register",
        json={"email": "dup@example.com", "password": "another1pass", "name": "다른"},
    )
    assert resp.status_code == 409


def test_register_rejects_bad_email_and_short_password(with_db):
    client = _client()
    assert (
        client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": "hunter2pass", "name": "김"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/auth/register",
            json={"email": "ok@example.com", "password": "short", "name": "김"},
        ).status_code
        == 422
    )


# ------------------------------------------------------------------------ login


def test_login_with_correct_password(with_db):
    client = _client()
    _register(client, "login@example.com")
    resp = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "hunter2pass"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password_and_unknown_email_both_401(with_db):
    client = _client()
    _register(client, "real@example.com")
    assert (
        client.post(
            "/auth/login",
            json={"email": "real@example.com", "password": "wrongpass1"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "hunter2pass"},
        ).status_code
        == 401
    )


# -------------------------------------------------------------------------- me


def test_me_requires_valid_token(with_db):
    client = _client()
    token = _register(client, "me@example.com")

    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=_auth("garbage")).status_code == 401

    resp = client.get("/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"


# --------------------------------------------------------- family_graph 소유권


def test_authed_graph_is_private_to_owner(with_db):
    client = _client()
    owner = _register(client, "owner@example.com")
    other = _register(client, "other@example.com")

    graph_id = client.post("/family-graph", headers=_auth(owner)).json()["id"]

    # 본인은 조회 가능
    assert (
        client.get(f"/family-graph/{graph_id}", headers=_auth(owner)).status_code == 200
    )
    # 다른 사용자는 존재 자체를 숨기기 위해 404
    assert (
        client.get(f"/family-graph/{graph_id}", headers=_auth(other)).status_code == 404
    )
    # 비로그인도 404
    assert client.get(f"/family-graph/{graph_id}").status_code == 404


def test_anonymous_graph_stays_accessible_by_id(with_db):
    client = _client()
    graph_id = client.post("/family-graph").json()["id"]
    # 토큰 없이 만든 그래프는 id만 알면 접근 가능(capability token)
    assert client.get(f"/family-graph/{graph_id}").status_code == 200
    resp = client.post(
        f"/family-graph/{graph_id}/members",
        json={"name": "배우자", "relation": "spouse"},
    )
    assert resp.status_code == 201


def test_claim_attaches_anonymous_graph_to_user(with_db):
    client = _client()
    graph_id = client.post("/family-graph").json()["id"]
    token = _register(client, "claimer@example.com")

    claim = client.post(f"/family-graph/{graph_id}/claim", headers=_auth(token))
    assert claim.status_code == 200

    # 연결 후에는 다른 사람이 접근 못 함
    other = _register(client, "stranger@example.com")
    assert (
        client.get(f"/family-graph/{graph_id}", headers=_auth(other)).status_code == 404
    )
    # /mine 으로 되찾을 수 있음
    mine = client.get("/family-graph/mine", headers=_auth(token))
    assert mine.status_code == 200
    assert mine.json()["id"] == graph_id


def test_cannot_claim_someone_elses_graph(with_db):
    client = _client()
    owner = _register(client, "haveit@example.com")
    graph_id = client.post("/family-graph", headers=_auth(owner)).json()["id"]

    thief = _register(client, "thief@example.com")
    assert (
        client.post(f"/family-graph/{graph_id}/claim", headers=_auth(thief)).status_code
        == 404
    )


def test_mine_returns_404_when_user_has_no_graph(with_db):
    client = _client()
    token = _register(client, "empty@example.com")
    assert client.get("/family-graph/mine", headers=_auth(token)).status_code == 404

"""재로그인 후 대화 이어보기 테스트 (GET /sessions/mine).

로그아웃하면 클라이언트가 session_id 를 버립니다. 서버에는 그 세션이 30일
동안 그대로 남아 있는데 아무도 그걸 가리키지 않으니, 다시 로그인해도 대화가
처음부터 시작됐습니다 — 가족관계는 /family-graph/mine 으로 되찾아지는데 대화
맥락(사망일, 확정된 슬롯, 이력)만 유실되는 비대칭이 있었습니다.

여기서 잡는 회귀는 그 비대칭입니다. 이어보기가 "있으면 좋은 것"이 아니라
로그인 사용자에게 약속한 동작(30일 보관)의 일부라서, 조회 경로가 끊기면
보관 자체가 무의미해집니다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.router import router as auth_router
from orchestrator import router as orchestrator_router
from orchestrator.session_api import router as sessions_router
from orchestrator.session_store import InMemorySessionStore, SessionState
from schemas import AgentName

ALICE = "alice-user-id"
BOB = "bob-user-id"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(sessions_router)
    return TestClient(app)


def _register(client: TestClient, email: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "hunter2pass", "name": "김민준"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


# ------------------------------------------------------- latest_for_user


def test_latest_returns_the_most_recently_used_session():
    store = InMemorySessionStore()

    older = SessionState(user_id=ALICE)
    older.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 1}, pending_handoff=None)
    older.updated_at -= 600
    store.save("old", older)

    newer = SessionState(user_id=ALICE)
    newer.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 9}, pending_handoff=None)
    store.save("new", newer)

    found = store.latest_for_user(ALICE)

    assert found is not None
    assert found[0] == "new"


def test_latest_ignores_other_peoples_sessions():
    store = InMemorySessionStore()
    store.save("bobs", SessionState(user_id=BOB))

    assert store.latest_for_user(ALICE) is None


def test_latest_ignores_anonymous_sessions():
    """비로그인 세션은 '떠나면 남지 않는' 것이 원칙이라 되찾을 대상이 아니다."""
    store = InMemorySessionStore()
    store.save("anon", SessionState())

    assert store.latest_for_user(ALICE) is None


def test_latest_ignores_expired_sessions():
    store = InMemorySessionStore()
    expired = SessionState(user_id=ALICE)
    expired.updated_at -= 60 * 60 * 24 * 31  # 30일 보관을 넘김
    store.save("stale", expired)

    assert store.latest_for_user(ALICE) is None


# ------------------------------------------------------- GET /sessions/mine


def test_endpoint_requires_login(with_db):
    assert _client().get("/sessions/mine").status_code == 401


def test_endpoint_404_when_there_is_nothing_to_resume(with_db, monkeypatch):
    monkeypatch.setattr(orchestrator_router, "default_store", InMemorySessionStore())
    client = _client()
    token = _register(client, "nothing@example.com")

    resp = client.get("/sessions/mine", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 404


def test_endpoint_returns_session_id_and_past_conversation(with_db, monkeypatch):
    store = InMemorySessionStore()
    monkeypatch.setattr(orchestrator_router, "default_store", store)
    client = _client()
    token = _register(client, "resume@example.com")
    user_id = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    ).json()["id"]

    state = SessionState(user_id=user_id)
    state.append_history("user", "어제 부모님이 돌아가셨어요")
    state.append_history("assistant", "사망신고부터 하셔야 합니다.")
    state.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 1}, pending_handoff=None)
    store.save("LOGIN-1", state)

    resp = client.get("/sessions/mine", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "LOGIN-1"
    assert body["history"] == [
        {"role": "user", "content": "어제 부모님이 돌아가셨어요"},
        {"role": "assistant", "content": "사망신고부터 하셔야 합니다."},
    ]


def test_endpoint_does_not_leak_another_users_session(with_db, monkeypatch):
    store = InMemorySessionStore()
    monkeypatch.setattr(orchestrator_router, "default_store", store)
    client = _client()

    owner_token = _register(client, "owner@example.com")
    owner_id = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {owner_token}"}
    ).json()["id"]
    owned = SessionState(user_id=owner_id)
    owned.append_history("user", "남에게 보이면 안 되는 내용")
    store.save("LOGIN-1", owned)

    other_token = _register(client, "other@example.com")
    resp = client.get(
        "/sessions/mine", headers={"Authorization": f"Bearer {other_token}"}
    )

    assert resp.status_code == 404

"""PostgresSessionStore 테스트 (실제 Postgres 필요, with_db 참고).

InMemorySessionStore와 인터페이스가 동일하다는 걸 확인하기 위해, 기존
test_orchestrator.py의 시나리오 일부를 그대로 이 구현체로도 반복합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from schemas import AgentName

from family_graph.repository import create_family_graph
from orchestrator.models import ChatSession
from orchestrator.session_store import PostgresSessionStore, SessionState
from db.base import session_scope


def test_save_then_load_round_trips_state(with_db):
    with session_scope() as db:
        graph_id = create_family_graph(db).id

    store = PostgresSessionStore()
    state = SessionState()
    state.remember(
        AgentName.HEIR_NAVIGATOR,
        context={"turns": 1},
        pending_handoff=AgentName.DECEDENT_ESTATE,
    )
    state.family_graph_id = graph_id

    store.save("session-a", state)
    loaded = store.load("session-a")

    assert loaded.last_agent == AgentName.HEIR_NAVIGATOR
    assert loaded.pending_handoff == AgentName.DECEDENT_ESTATE
    assert loaded.family_graph_id == graph_id
    assert loaded.context_for(AgentName.HEIR_NAVIGATOR) == {"turns": 1}


def test_save_silently_drops_unknown_family_graph_id(with_db):
    """존재하지 않는 family_graph_id를 세션에 저장하려 하면, 요청을 죽이는
    대신 조용히 비우고 저장합니다 (sessions.family_graph_id FK 보호)."""
    store = PostgresSessionStore()
    state = SessionState()
    state.remember(AgentName.HEIR_NAVIGATOR, context={}, pending_handoff=None)
    state.family_graph_id = "no-such-family-graph"

    store.save("session-unknown-fg", state)
    loaded = store.load("session-unknown-fg")

    assert loaded.family_graph_id is None


def test_load_unknown_session_returns_fresh_state(with_db):
    store = PostgresSessionStore()
    state = store.load("never-seen-before")
    assert state.last_agent is None
    assert state.pending_handoff is None
    assert state.family_graph_id is None


def test_load_expired_session_returns_fresh_state(with_db):
    store = PostgresSessionStore()
    state = SessionState()
    state.remember(AgentName.TAX_CALCULATOR, context={}, pending_handoff=None)
    store.save("session-b", state)

    # 강제로 만료시킵니다 (save()가 방금 미래로 채운 expires_at을 과거로 되돌림).
    with session_scope() as db:
        row = db.get(ChatSession, "session-b")
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    loaded = store.load("session-b")
    assert loaded.last_agent is None

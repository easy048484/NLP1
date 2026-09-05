"""PostgresSessionStore 테스트 (실제 Postgres 필요, with_db 참고).

InMemorySessionStore와 인터페이스가 동일하다는 걸 확인하기 위해, 기존
test_orchestrator.py의 시나리오 일부를 그대로 이 구현체로도 반복합니다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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


def test_save_then_load_round_trips_pending_reply_agent(with_db):
    """pending_reply_agent는 DB 컬럼이 아니라 per_agent_context의 "_shared" JSON
    아래에 직렬화되지만, PostgresSessionStore를 거친 실제 왕복에서도 유지돼야
    한다."""
    store = PostgresSessionStore()
    state = SessionState()
    state.remember(AgentName.DECEDENT_ESTATE, context={}, pending_handoff=None)
    state.pending_reply_agent = AgentName.DECEDENT_ESTATE

    store.save("session-pending-reply", state)
    loaded = store.load("session-pending-reply")

    assert loaded.pending_reply_agent == AgentName.DECEDENT_ESTATE


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


def test_concurrent_first_save_same_session_id_does_not_raise(with_db):
    """같은 session_id로 동시에 첫 save가 와도 PK 충돌로 실패하지 않는다."""
    store = PostgresSessionStore()
    session_id = "session-concurrent-first-save"

    def _save(agent: AgentName, turn: int) -> None:
        state = SessionState()
        state.remember(agent, context={"turn": turn}, pending_handoff=None)
        store.save(session_id, state)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_save, AgentName.HEIR_NAVIGATOR, 1),
            pool.submit(_save, AgentName.TAX_CALCULATOR, 2),
        ]
        for future in as_completed(futures):
            future.result()

    loaded = store.load(session_id)
    assert loaded.last_agent in (
        AgentName.HEIR_NAVIGATOR,
        AgentName.TAX_CALCULATOR,
    )
    assert loaded.context_for(loaded.last_agent)["turn"] in (1, 2)

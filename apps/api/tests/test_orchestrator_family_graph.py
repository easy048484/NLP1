"""오케스트레이터 ↔ family_graph 연동 테스트 (실제 Postgres 필요, with_db 참고).

router.node_build_context가 family_graph_id를 DB에서 실제로 풀어서
AgentInput.family_graph를 채우는지, 그리고 DB에 없을 때 요청에 담겨온
family_graph로 제대로 폴백하는지를 확인합니다.
"""

from __future__ import annotations

import pytest

from db.base import session_scope
from family_graph.models import RelationType
from family_graph.repository import add_member, create_family_graph
from orchestrator import router
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName, AgentOutput


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())


def _fake_agent(agent_name: AgentName):
    captured = []

    def _run(payload: AgentInput) -> AgentOutput:
        captured.append(payload)
        return AgentOutput(agent=agent_name, reply="ok", next_action=None, data={})

    _run.captured = captured
    return _run


def test_family_graph_id_resolves_to_db_backed_heirs(monkeypatch, with_db):
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(db, graph_id, name="배우자", relation=RelationType.SPOUSE)
        add_member(db, graph_id, name="자녀 1", relation=RelationType.CHILD)

    fake = _fake_agent(AgentName.HEIR_NAVIGATOR)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, fake)

    router.route(
        AgentInput(
            session_id="fg-session-1",
            user_message="도와주세요",
            family_graph_id=graph_id,
        )
    )

    assert fake.captured[0].family_graph == {
        "heirs": [
            {"name": "배우자", "relation": "spouse", "alive": True, "minor": False},
            {"name": "자녀 1", "relation": "child", "alive": True, "minor": False},
        ]
    }


def test_family_graph_id_persists_across_turns_without_resending(monkeypatch, with_db):
    """첫 턴에만 family_graph_id를 보내도, 다음 턴에는 세션이 기억해서 계속 채워줍니다."""
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(db, graph_id, name="배우자", relation=RelationType.SPOUSE)

    fake = _fake_agent(AgentName.HEIR_NAVIGATOR)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, fake)

    router.route(
        AgentInput(
            session_id="fg-session-2", user_message="첫 턴", family_graph_id=graph_id
        )
    )
    router.route(AgentInput(session_id="fg-session-2", user_message="두번째 턴"))

    assert fake.captured[1].family_graph == {
        "heirs": [
            {"name": "배우자", "relation": "spouse", "alive": True, "minor": False}
        ]
    }


def test_unknown_family_graph_id_falls_back_to_payload_family_graph(
    monkeypatch, with_db
):
    fake = _fake_agent(AgentName.HEIR_NAVIGATOR)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, fake)

    router.route(
        AgentInput(
            session_id="fg-session-3",
            user_message="도와주세요",
            family_graph_id="no-such-id",
            family_graph={"spouse_alive": True, "num_children": 1},
        )
    )

    assert fake.captured[0].family_graph == {"spouse_alive": True, "num_children": 1}


def test_explicit_family_graph_overrides_valid_family_graph_id(monkeypatch, with_db):
    """family_graph_id가 DB에서 정상적으로 풀려도, 이번 요청이 family_graph를
    직접 채워 보냈으면 그 값이 우선해야 합니다 (schemas/agent_io.py의
    AgentInput.family_graph_id docstring이 명시하는 우선순위)."""
    with session_scope() as db:
        graph = create_family_graph(db)
        graph_id = graph.id
        add_member(db, graph_id, name="배우자", relation=RelationType.SPOUSE)

    fake = _fake_agent(AgentName.HEIR_NAVIGATOR)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, fake)

    router.route(
        AgentInput(
            session_id="fg-session-4",
            user_message="도와주세요",
            family_graph_id=graph_id,
            family_graph={"spouse_alive": True, "num_children": 1},
        )
    )

    assert fake.captured[0].family_graph == {"spouse_alive": True, "num_children": 1}

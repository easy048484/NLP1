"""
오케스트레이터 라우팅 규약 테스트 (담당: 지원)

실제 에이전트 로직을 호출하지 않고, 각 에이전트의 run()을 가짜로 바꿔치기해서
오케스트레이터의 라우팅/세션/핸드오프 규약만 검증합니다. 에이전트 로직 자체의
정확성은 각 에이전트 폴더의 테스트(test_decedent_*.py, test_heir_navigator.py,
test_tax_calculator.py)가 담당합니다.
"""

from __future__ import annotations

import pytest

from orchestrator import router
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName, AgentOutput


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    """세션 저장소를 테스트마다 초기화해서 테스트 간 상태가 새지 않게 합니다."""
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())


def _fake_agent(agent_name: AgentName, *, next_action=None, data=None):
    def _run(payload: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent=agent_name,
            reply=f"[fake:{agent_name.value}] {payload.user_message}",
            next_action=next_action,
            data=data or {},
        )

    return _run


def test_first_turn_with_no_keyword_routes_to_default_agent(monkeypatch):
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.HEIR_NAVIGATOR,
        _fake_agent(AgentName.HEIR_NAVIGATOR),
    )
    output = router.route(AgentInput(session_id="s1", user_message="도와주세요"))
    assert output.agent == AgentName.HEIR_NAVIGATOR


def test_keyword_routes_to_matching_agent(monkeypatch):
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.TAX_CALCULATOR,
        _fake_agent(AgentName.TAX_CALCULATOR),
    )
    output = router.route(
        AgentInput(session_id="s2", user_message="상속세 얼마나 나와요?")
    )
    assert output.agent == AgentName.TAX_CALCULATOR


def test_handoff_next_action_routes_next_turn_to_target_agent(monkeypatch):
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.HEIR_NAVIGATOR,
        _fake_agent(AgentName.HEIR_NAVIGATOR, next_action="handoff:decedent_estate"),
    )
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.DECEDENT_ESTATE,
        _fake_agent(AgentName.DECEDENT_ESTATE),
    )

    first = router.route(AgentInput(session_id="s3", user_message="도와주세요"))
    assert first.agent == AgentName.HEIR_NAVIGATOR

    second = router.route(AgentInput(session_id="s3", user_message="네"))
    assert second.agent == AgentName.DECEDENT_ESTATE


def test_no_handoff_continues_with_last_agent_even_without_keyword(monkeypatch):
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.DECEDENT_ESTATE,
        _fake_agent(AgentName.DECEDENT_ESTATE, next_action="await_user_confirmation"),
    )
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.HEIR_NAVIGATOR,
        _fake_agent(AgentName.HEIR_NAVIGATOR),
    )

    first = router.route(
        AgentInput(session_id="s4", user_message="유언장 확인하고 싶어요")
    )
    assert first.agent == AgentName.DECEDENT_ESTATE

    # 키워드가 없는 짧은 답("네")도 직전 에이전트(decedent_estate)로 이어져야
    # 한다 — 키워드 라우팅으로 폴백되어 기본 에이전트(heir_navigator)로
    # 새지 않아야 함.
    second = router.route(AgentInput(session_id="s4", user_message="네"))
    assert second.agent == AgentName.DECEDENT_ESTATE


def test_namespaced_state_round_trips_through_session(monkeypatch):
    captured_inputs = []

    def _run(payload: AgentInput) -> AgentOutput:
        captured_inputs.append(payload.context)
        return AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR,
            reply="ok",
            next_action=None,
            data={"heir_navigator": {"turns": len(captured_inputs)}},
        )

    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, _run)

    router.route(AgentInput(session_id="s5", user_message="첫 메시지"))
    router.route(AgentInput(session_id="s5", user_message="두번째 메시지"))

    # 두번째 호출 시 첫 턴에서 저장된 heir_navigator 네임스페이스 상태가
    # 그대로 다음 AgentInput.context["heir_navigator"]로 들어와야 한다.
    assert captured_inputs[1]["heir_navigator"] == {"turns": 1}


def test_legacy_flat_context_agent_is_not_namespaced(monkeypatch):
    captured_inputs = []

    def _run(payload: AgentInput) -> AgentOutput:
        captured_inputs.append(payload.context)
        return AgentOutput(
            agent=AgentName.DECEDENT_ESTATE, reply="ok", next_action=None, data={}
        )

    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.DECEDENT_ESTATE, _run)

    router.route(
        AgentInput(
            session_id="s6",
            user_message="유언장 확인",
            context={"will_type": "handwritten"},
        )
    )

    assert captured_inputs[0]["will_type"] == "handwritten"
    assert "decedent_estate" not in captured_inputs[0]

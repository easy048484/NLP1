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


def test_forced_share_keyword_routes_to_share_analyzer(monkeypatch):
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.HEIR_SHARE_ANALYZER,
        _fake_agent(AgentName.HEIR_SHARE_ANALYZER),
    )
    output = router.route(
        AgentInput(session_id="share-routing", user_message="유류분이 부족한가요?")
    )
    assert output.agent == AgentName.HEIR_SHARE_ANALYZER


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


def test_decedent_estate_is_namespaced_like_other_agents(monkeypatch):
    """decedent_estate도 네임스페이스 규약을 따르므로 다른 에이전트와 동일하게
    context["decedent_estate"]가 채워지고, 세션에도 상태가 저장돼야 한다.

    (예전에는 LEGACY_FLAT_CONTEXT_AGENTS에 들어 있어서 평면 context가 그대로
    통과하고 세션 저장은 아예 없었다 — 그 동작을 검증하던 테스트를 갱신한 것.)
    """
    captured_inputs = []

    def _run(payload: AgentInput) -> AgentOutput:
        captured_inputs.append(payload.context)
        return AgentOutput(
            agent=AgentName.DECEDENT_ESTATE,
            reply="ok",
            next_action=None,
            data={"decedent_estate": {"will_type": "handwritten"}},
        )

    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.DECEDENT_ESTATE, _run)

    router.route(
        AgentInput(
            session_id="s6",
            user_message="유언장 확인",
            context={"will_type": "handwritten"},
        )
    )

    # 네임스페이스 키가 생기고(첫 턴이라 비어 있음), 평면 키는 클라이언트가 보낸
    # 그대로 함께 전달된다 — 옛 클라이언트 호환은 이제 에이전트 쪽 안전망이 맡는다.
    assert captured_inputs[0]["decedent_estate"] == {}
    assert captured_inputs[0]["will_type"] == "handwritten"

    # 두 번째 턴: 지난 턴 data["decedent_estate"]가 세션을 거쳐 되돌아와야 한다.
    router.route(AgentInput(session_id="s6", user_message="네", context={}))
    assert captured_inputs[1]["decedent_estate"] == {"will_type": "handwritten"}


# (삭제됨) test_legacy_flat_context_set_is_empty
#
# LEGACY_FLAT_CONTEXT_AGENTS 가 빈 집합인지를 그대로 단언하던 테스트를 지웠다.
# 동작이 아니라 상수 값을 확인하는 테스트라 정보량이 적고, 같은 회귀는 바로 위
# test_decedent_estate_is_namespaced_like_other_agents 가 이미 잡는다 —
# decedent_estate 를 다시 집합에 넣으면 네임스페이스 키가 만들어지지 않아
# KeyError 로 실패한다.
#
# 더 중요하게는, 네 번째 에이전트를 규약 적용 전까지 임시로 이 집합에 등록하는
# 정당한 사용(handoff.py 가 상수를 확장점으로 남겨둔 이유)에서 이 테스트가
# 실패해 설계 결정과 모순됐다.

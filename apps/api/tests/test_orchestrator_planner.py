"""
라우터 → 플래너 재설계 테스트 (담당: 정민, docs/라우팅방식변경.md)

실제 에이전트 로직은 호출하지 않고 run()을 가짜로 바꿔 오케스트레이터의
분류 등급 / DAG 층 구성 / 병렬·순차 주입 / compose+verify / 공유 financial_profile
왕복만 검증합니다. ANTHROPIC_API_KEY 는 conftest 가 지우므로 LLM 경로는 항상
폴백(키워드 후보 전부, 이어붙이기)을 탑니다.
"""

from __future__ import annotations

import threading
import time

import pytest

from orchestrator import compose as compose_mod
from orchestrator import planner, registry, router
from orchestrator.session_store import InMemorySessionStore, SessionState
from schemas import (
    AgentInput,
    AgentName,
    AgentOutput,
    FinancialProfile,
    HandoffRequest,
)


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "auto")


def _fake(agent_name: AgentName, *, reply=None, data=None, delay=0.0, **kwargs):
    captured = []

    def _run(payload: AgentInput) -> AgentOutput:
        captured.append(payload)
        if delay:
            time.sleep(delay)
        return AgentOutput(
            agent=agent_name,
            reply=reply or f"[fake:{agent_name.value}] {payload.user_message}",
            data=data or {agent_name.value: {"seen": True}},
            **kwargs,
        )

    _run.captured = captured
    return _run


def _patch(monkeypatch, *fakes):
    for fake in fakes:
        name = fake(AgentInput(session_id="probe", user_message="")).agent
        fake.captured.clear()
        monkeypatch.setitem(router._AGENT_RUNNERS, name, fake)


# ------------------------------------------------------------- registry


def test_registry_discovers_every_agent_name():
    specs = registry.all_specs()
    assert set(specs) == set(AgentName)
    assert specs[AgentName.RETIREMENT_PLANNER].is_stub is True
    assert specs[AgentName.HEIR_NAVIGATOR].is_stub is False


def test_stub_agent_is_routable_by_keyword_without_touching_orchestrator():
    output = router.route(
        AgentInput(session_id="st1", user_message="은퇴 자금 얼마나 필요해요?")
    )
    assert output.agent == AgentName.RETIREMENT_PLANNER
    assert output.path == "standard"
    assert output.data.get("stub") is True
    # 껍데기도 네임스페이스 규약대로 상태를 남겨야 다음 턴에 이어진다.
    second = router.route(AgentInput(session_id="st1", user_message="네"))
    assert second.agent == AgentName.RETIREMENT_PLANNER
    assert second.data[AgentName.RETIREMENT_PLANNER.value]["turns"] == 2


# ------------------------------------------------------------- classify


def test_fast_path_when_pending_handoff(monkeypatch):
    plan = planner.classify(
        "상속세 얼마예요",  # 키워드가 있어도 핸드오프가 우선
        pending_handoff=AgentName.DECEDENT_ESTATE,
        last_agent=AgentName.HEIR_NAVIGATOR,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "fast"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


def test_standard_path_single_keyword():
    plan = planner.classify(
        "상속세 얼마예요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


def test_full_pipeline_without_llm_takes_all_keyword_candidates():
    plan = planner.classify(
        "은퇴 준비하면서 상속세도 궁금해요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "full"
    assert plan.llm_used is False
    # 서로 requires/produces 가 안 겹치므로 한 층에서 병렬
    assert len(plan.layers) == 1
    assert set(plan.layers[0]) == {
        AgentName.TAX_CALCULATOR,
        AgentName.RETIREMENT_PLANNER,
    }


def test_llm_selection_narrows_candidates(monkeypatch):
    monkeypatch.setattr(
        planner, "_llm_select", lambda msg, cands: [AgentName.TAX_CALCULATOR]
    )
    plan = planner.classify(
        "은퇴 준비하면서 상속세도 궁금해요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


# ------------------------------------------------------------ build_plan


def test_build_plan_orders_by_requires_produces():
    plan = planner.build_plan(
        [AgentName.TAX_CALCULATOR, AgentName.HEIR_NAVIGATOR, AgentName.DECEDENT_ESTATE]
    )
    # heir_navigator ∥ decedent_estate → tax_calculator (will_status 의존)
    assert len(plan.layers) == 2
    assert set(plan.layers[0]) == {AgentName.HEIR_NAVIGATOR, AgentName.DECEDENT_ESTATE}
    assert plan.layers[1] == [AgentName.TAX_CALCULATOR]


def test_build_plan_soft_dependency_when_producer_not_selected():
    plan = planner.build_plan([AgentName.TAX_CALCULATOR])
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


# ---------------------------------------------------------- execute_plan


def test_parallel_layer_runs_concurrently(monkeypatch):
    started = []
    lock = threading.Lock()

    def _slow(agent_name):
        def _run(payload):
            with lock:
                started.append((agent_name, time.perf_counter()))
            time.sleep(0.3)
            return AgentOutput(agent=agent_name, reply=f"{agent_name.value} ok")

        return _run

    monkeypatch.setitem(
        router._AGENT_RUNNERS, AgentName.TAX_CALCULATOR, _slow(AgentName.TAX_CALCULATOR)
    )
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.RETIREMENT_PLANNER,
        _slow(AgentName.RETIREMENT_PLANNER),
    )

    t0 = time.perf_counter()
    output = router.route(
        AgentInput(session_id="p1", user_message="은퇴 준비하면서 상속세도 궁금해요")
    )
    elapsed = time.perf_counter() - t0

    assert output.path == "full"
    assert set(output.agents) == {
        AgentName.TAX_CALCULATOR,
        AgentName.RETIREMENT_PLANNER,
    }
    assert elapsed < 0.55, f"병렬이면 0.3초대여야 하는데 {elapsed:.2f}s"
    assert (
        "tax_calculator ok" in output.reply and "retirement_planner ok" in output.reply
    )


def test_sequential_layer_receives_upstream_context(monkeypatch):
    decedent = _fake(
        AgentName.DECEDENT_ESTATE,
        reply="유언장은 없습니다.",
        data={AgentName.DECEDENT_ESTATE.value: {"will_type": "none"}},
    )
    tax = _fake(AgentName.TAX_CALCULATOR)
    _patch(monkeypatch, decedent, tax)

    output = router.route(
        AgentInput(
            session_id="q1", user_message="유언장이 없는데 상속세는 얼마나 나와요?"
        )
    )
    assert output.agents == [AgentName.DECEDENT_ESTATE, AgentName.TAX_CALCULATOR]
    tax_input = tax.captured[0]
    assert tax_input.context[AgentName.DECEDENT_ESTATE.value] == {"will_type": "none"}
    assert (
        tax_input.context[planner.UPSTREAM_KEY]["decedent_estate"]["reply"]
        == "유언장은 없습니다."
    )
    # 응답의 대표 에이전트는 DAG 의 마지막
    assert output.agent == AgentName.TAX_CALCULATOR


def test_one_agent_failure_does_not_kill_the_turn(monkeypatch):
    def _boom(payload):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.TAX_CALCULATOR, _boom)
    _patch(
        monkeypatch, _fake(AgentName.RETIREMENT_PLANNER, reply="은퇴 갭은 1억원입니다.")
    )

    output = router.route(
        AgentInput(session_id="f1", user_message="은퇴 준비하면서 상속세도 궁금해요")
    )
    assert "1억원" in output.reply
    assert output.data.get("error") == "agent_failed"


# ------------------------------------------------------- financial_profile


def test_financial_profile_round_trips_and_merges(monkeypatch):
    retirement = _fake(
        AgentName.RETIREMENT_PLANNER,
        financial_profile=FinancialProfile(
            financial_assets=300_000_000, monthly_expense=3_000_000
        ),
    )
    tax = _fake(AgentName.TAX_CALCULATOR)
    _patch(monkeypatch, retirement, tax)

    router.route(AgentInput(session_id="fp1", user_message="은퇴 자금 상담"))
    output = router.route(
        AgentInput(
            session_id="fp1",
            user_message="상속세도 계산해줘",
            financial_profile=FinancialProfile(real_estate_value=500_000_000),
        )
    )
    # 이전 턴에서 retirement_planner 가 알려준 값 + 이번 요청의 값이 병합돼 전달된다
    received = tax.captured[0].financial_profile
    assert received.financial_assets == 300_000_000
    assert received.monthly_expense == 3_000_000
    assert received.real_estate_value == 500_000_000
    assert output.financial_profile.financial_assets == 300_000_000


def test_session_state_json_round_trip_keeps_shared_profile():
    state = SessionState(
        per_agent_context={"tax_calculator": {"x": 1}},
        financial_profile=FinancialProfile(financial_assets=10, extra={"k": "v"}),
    )
    raw = state.to_json_context()
    assert raw["_shared"]["financial_profile"] == {
        "financial_assets": 10,
        "extra": {"k": "v"},
    }
    back = SessionState.from_json_context(raw)
    assert back.per_agent_context == {"tax_calculator": {"x": 1}}
    assert back.financial_profile.financial_assets == 10
    assert back.financial_profile.extra == {"k": "v"}


# --------------------------------------------------------------- handoffs


def test_structured_handoff_takes_priority_over_legacy_string(monkeypatch):
    heir = _fake(
        AgentName.HEIR_NAVIGATOR,
        next_action="handoff:decedent_estate",
        handoffs=[
            HandoffRequest(target=AgentName.TAX_CALCULATOR, priority=1),
            HandoffRequest(target=AgentName.DECEDENT_ESTATE, priority=5),
        ],
    )
    _patch(
        monkeypatch,
        heir,
        _fake(AgentName.DECEDENT_ESTATE),
        _fake(AgentName.TAX_CALCULATOR),
    )

    router.route(AgentInput(session_id="h1", user_message="도와주세요"))
    second = router.route(AgentInput(session_id="h1", user_message="네"))
    assert second.agent == AgentName.DECEDENT_ESTATE
    assert second.path == "fast"


# ------------------------------------------------------- compose / verify


def _outputs():
    return [
        AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply="예상 상속세는 1,234,000원이고 세율은 20%입니다.",
        ),
        AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR,
            reply="신고 기한은 2026년 2월 28일까지입니다.",
            data={"deadline": "2026-02-28"},
        ),
    ]


def test_verify_numbers_passes_when_all_facts_in_source():
    draft = (
        "상속세는 1,234,000원(세율 20%)이며, 신고는 2026년 2월 28일까지 하셔야 합니다."
    )
    result = compose_mod.verify_numbers(draft, _outputs())
    assert result.ok, result.mismatches


def test_verify_numbers_accepts_data_field_values():
    draft = "신고 기한: 2026-02-28"
    assert compose_mod.verify_numbers(draft, _outputs()).ok


def test_verify_numbers_fails_on_altered_amount():
    draft = (
        "상속세는 약 1,240,000원이고 세율은 20%입니다. 기한은 2026년 2월 28일입니다."
    )
    result = compose_mod.verify_numbers(draft, _outputs())
    assert not result.ok
    assert result.mismatches == ["1240000원"]


def test_verify_numbers_ignores_small_counts():
    # '3개월', '2명' 같은 짧은 정수는 검증 대상이 아니다
    assert compose_mod.verify_numbers("3개월 안에 2명이 신고합니다.", _outputs()).ok


def test_compose_falls_back_to_concat_when_llm_alters_numbers(monkeypatch):
    monkeypatch.setattr(
        compose_mod,
        "llm_synthesize",
        lambda outputs, msg: "상속세는 9,999,000원입니다.",
    )
    reply, verification = compose_mod.compose(_outputs(), "질문")
    assert verification.ok is False
    assert verification.mode == "concat_after_failure"
    assert "9,999,000" not in reply
    assert "1,234,000원" in reply and "2026년 2월 28일" in reply


def test_compose_uses_draft_when_verified(monkeypatch):
    draft = "상속세 1,234,000원 · 세율 20% · 기한 2026년 2월 28일"
    monkeypatch.setattr(compose_mod, "llm_synthesize", lambda outputs, msg: draft)
    reply, verification = compose_mod.compose(_outputs(), "질문")
    assert reply == draft
    assert verification.ok and verification.mode == "synthesized"


def test_compose_single_output_is_verbatim():
    reply, verification = compose_mod.compose(_outputs()[:1], "질문")
    assert reply == _outputs()[0].reply
    assert verification.mode == "single"


def test_full_pipeline_response_carries_verification(monkeypatch):
    _patch(
        monkeypatch,
        _fake(AgentName.TAX_CALCULATOR),
        _fake(AgentName.RETIREMENT_PLANNER),
    )
    output = router.route(
        AgentInput(session_id="v1", user_message="은퇴 준비하면서 상속세도 궁금해요")
    )
    assert output.verification is not None
    assert output.verification.mode == "concat"  # LLM 없음 → 이어붙이기
    assert output.verification.ok

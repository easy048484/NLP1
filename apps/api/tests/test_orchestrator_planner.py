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
    """등록된 5개 에이전트 전부가 registry 에 자동 편입된다 (spec.py 만
    두면 router.py 수정 없이 잡힌다).

    is_stub 플래그: asset_organizer/heir_navigator 는 실제 구현이 채워져
    False. retirement_planner 는 엔진 구현이 있는데도 True 인데 — 2026-08-30
    팀 계획서 결정으로 데모 범위에서 제외하면서 스펙을 스텁 상태로
    되돌렸다(agents/retirement_planner/spec.py 참고). 엔진 자체는 삭제하지
    않고 보존돼 있으므로 데모 범위에 다시 들어오면 spec.py 만 되살리면 된다."""
    specs = registry.all_specs()
    assert set(specs) == set(AgentName)
    assert specs[AgentName.RETIREMENT_PLANNER].is_stub is True
    assert specs[AgentName.ASSET_ORGANIZER].is_stub is False
    assert specs[AgentName.HEIR_NAVIGATOR].is_stub is False


def test_retirement_planner_is_registered_but_unreachable_by_keyword():
    """retirement_planner 데모 제외 정책의 회귀 가드.

    원래 이 테스트는 retirement_planner 가 "은퇴/노후" 키워드로 라우팅되는
    걸 확인했는데, 2026-08-30 데모 제외 결정으로 spec.py 의 keywords 를
    비웠다. 이제는 반대로 — 스펙은 여전히 registry 에 있지만(엔진 보존),
    사용자가 은퇴 얘기로 먼저 말을 걸어도 이 에이전트에 도달하지 못하고
    default_agent 로 폴백해야 한다.

    ⚠️ 차단 장치는 keywords=[] 하나뿐이다. is_stub=True 는 planner.classify()
    의 Standard 경로(단독 키워드)를 전혀 안 거치므로 그것만으로는 라우팅이
    안 막힌다(실측 확인). keywords 를 되살리면 is_stub 여부와 무관하게 다시
    라우팅되므로, 이 테스트가 깨지면 "데모 제외"가 풀린 것이다."""
    specs = registry.all_specs()
    assert AgentName.RETIREMENT_PLANNER in specs  # 스펙은 계속 등록돼 있다
    assert specs[AgentName.RETIREMENT_PLANNER].keywords == []

    for utterance in ("은퇴 자금 얼마나 필요해요?", "노후 준비가 걱정돼요"):
        assert AgentName.RETIREMENT_PLANNER not in registry.match_keywords(utterance)
        output = router.route(
            AgentInput(session_id=f"rp-{utterance[:2]}", user_message=utterance)
        )
        assert output.agent != AgentName.RETIREMENT_PLANNER


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
    # asset_organizer("정리"/"재산") + tax_calculator("상속세") 2개 후보.
    # (retirement_planner 는 데모 제외로 keywords=[] — 더 이상 후보로 안 잡힌다.)
    plan = planner.classify(
        "재산 정리하고 상속세도 궁금해요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "full"
    assert plan.llm_used is False
    # asset_inventory ↔ will_status — 서로 requires/produces 가 안 겹치므로 한 층에서 병렬
    assert len(plan.layers) == 1
    assert set(plan.layers[0]) == {
        AgentName.TAX_CALCULATOR,
        AgentName.ASSET_ORGANIZER,
    }


def test_llm_selection_narrows_candidates(monkeypatch):
    monkeypatch.setattr(
        planner,
        "_llm_select",
        lambda msg, cands, **kwargs: [AgentName.TAX_CALCULATOR],
    )
    plan = planner.classify(
        "재산 정리하고 상속세도 궁금해요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


# --------------------------------------------------- LLM-first routing (신규)
#
# 2026-09-05: planner.classify()가 키워드 후보 개수와 무관하게 매번 LLM을
# 부르도록 바뀌었다(_llm_select 호출부가 candidates 대신 eligible 전체를
# 넘김). 여기서는 실제 Anthropic API를 타지 않도록 llm.claude.extract 또는
# planner._llm_select 자체를 mock한다(conftest의 _no_real_llm_calls가
# ANTHROPIC_API_KEY를 지우므로, llm_enabled() 게이트를 통과시키려면
# monkeypatch.setenv로 키를 다시 채워야 한다).


def test_llm_called_even_with_zero_keyword_candidates(monkeypatch):
    calls = []

    def _fake_llm_select(user_message, candidates, **kwargs):
        calls.append((user_message, candidates))
        return [AgentName.DECEDENT_ESTATE]

    monkeypatch.setattr(planner, "_llm_select", _fake_llm_select)
    message = "아버지가 손으로 남긴 문서가 있는데 이게 효력이 있는지 모르겠어요"
    assert registry.match_keywords(message) == []  # 키워드 후보 0개 확인

    plan = planner.classify(
        message,
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert len(calls) == 1
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


def test_llm_called_even_with_one_keyword_candidate(monkeypatch):
    calls = []

    def _fake_llm_select(user_message, candidates, **kwargs):
        calls.append((user_message, candidates))
        return [AgentName.TAX_CALCULATOR]

    monkeypatch.setattr(planner, "_llm_select", _fake_llm_select)
    message = "상속세 얼마예요"
    assert len(registry.match_keywords(message)) == 1  # 키워드 후보 1개 확인

    plan = planner.classify(
        message,
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert len(calls) == 1
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


def test_llm_candidates_are_full_eligible_set_excluding_stubs(monkeypatch):
    """키워드로 후보를 좁히지 않는다 — LLM에는 등록된 전체 에이전트(is_stub
    제외)가 넘어간다. retirement_planner(is_stub=True, 2026-08-30 데모 제외
    결정)는 절대 후보에 들어가면 안 된다."""
    captured = {}

    def _fake_llm_select(user_message, candidates, **kwargs):
        captured["candidates"] = candidates
        return [AgentName.HEIR_NAVIGATOR]

    monkeypatch.setattr(planner, "_llm_select", _fake_llm_select)
    planner.classify(
        "아무 키워드도 없는 문장입니다",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    eligible = set(captured["candidates"])
    all_specs = registry.all_specs()
    assert eligible == {n for n, s in all_specs.items() if not s.is_stub}
    assert AgentName.RETIREMENT_PLANNER not in eligible


def test_classify_prompt_includes_all_eligible_agent_specs():
    """_classify_prompt 에 전체 eligible 에이전트의 name/description/
    example_utterances(앞 3개)가 빠짐없이 들어간다."""
    eligible = [name for name, spec in registry.all_specs().items() if not spec.is_stub]
    prompt = planner._classify_prompt(eligible)
    specs = registry.all_specs()
    for name in eligible:
        spec = specs[name]
        assert name.value in prompt
        assert spec.description in prompt
        for utterance in spec.example_utterances[:3]:
            assert utterance in prompt


def test_classify_prompt_includes_last_agent_continuation_hint():
    """#126/#127 F/G 회귀 — last_agent가 있으면 LLM 프롬프트에 "이어가는 것이
    자연스럽다" 힌트가 들어간다(그렇다고 last_agent가 하드 필터는 아니다 —
    실제로 다른 주제를 물으면 다른 에이전트를 고르라는 문구도 함께 준다)."""
    eligible = [AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR]
    prompt = planner._classify_prompt(eligible, last_agent=AgentName.DECEDENT_ESTATE)
    assert "decedent_estate" in prompt
    assert "다른 주제" in prompt

    # last_agent가 후보 목록에 없으면(예: 없거나 stub) 힌트를 넣지 않는다.
    prompt_without_hint = planner._classify_prompt(eligible, last_agent=None)
    assert "직전 턴에 답변한 에이전트" not in prompt_without_hint


def test_llm_select_receives_last_agent_hint(monkeypatch):
    """classify()가 last_agent를 _llm_select까지 그대로 전달한다."""
    captured = {}

    def _fake_llm_select(user_message, candidates, *, last_agent=None):
        captured["last_agent"] = last_agent
        return [AgentName.DECEDENT_ESTATE]

    monkeypatch.setattr(planner, "_llm_select", _fake_llm_select)
    planner.classify(
        "그럼 요건은 일단 다 맞는 건가?",
        pending_handoff=None,
        last_agent=AgentName.DECEDENT_ESTATE,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert captured["last_agent"] == AgentName.DECEDENT_ESTATE


def test_llm_select_returns_single_agent(monkeypatch):
    from llm import claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        claude, "extract", lambda **kwargs: {"agents": ["heir_navigator"]}
    )
    result = planner._llm_select(
        "아버지가 돌아가셨는데 뭘 해야 하나요",
        [AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR],
    )
    assert result == [AgentName.HEIR_NAVIGATOR]


def test_llm_select_returns_multiple_agents(monkeypatch):
    from llm import claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        claude,
        "extract",
        lambda **kwargs: {"agents": ["decedent_estate", "heir_navigator"]},
    )
    result = planner._llm_select(
        "유언장 효력도 확인하고 상속 절차도 알고 싶어",
        [
            AgentName.DECEDENT_ESTATE,
            AgentName.HEIR_NAVIGATOR,
            AgentName.TAX_CALCULATOR,
        ],
    )
    assert result == [AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR]


def test_llm_select_invalid_result_falls_back_to_none(monkeypatch):
    """후보 밖 이름만 돌려주면(registry에 없거나 이번 후보가 아님) 빈 선택으로
    간주해 None(호출부 폴백 신호)을 돌려준다."""
    from llm import claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        claude, "extract", lambda **kwargs: {"agents": ["not_a_real_agent"]}
    )
    result = planner._llm_select(
        "아무 말이나", [AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR]
    )
    assert result is None


def test_llm_select_exception_falls_back_to_none(monkeypatch):
    from llm import claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(claude, "extract", _boom)
    result = planner._llm_select(
        "아무 말이나", [AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR]
    )
    assert result is None


def test_pending_handoff_never_calls_llm(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("pending_handoff 상태에서는 LLM을 호출하면 안 된다")

    monkeypatch.setattr(planner, "_llm_select", _boom)
    plan = planner.classify(
        "아무 말이나",
        pending_handoff=AgentName.DECEDENT_ESTATE,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "fast"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


def test_pending_reply_agent_never_calls_llm(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("pending_reply_agent 상태에서는 LLM을 호출하면 안 된다")

    monkeypatch.setattr(planner, "_llm_select", _boom)
    plan = planner.classify(
        "아무 말이나",
        pending_handoff=None,
        pending_reply_agent=AgentName.DECEDENT_ESTATE,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


def test_regression_scenarios_route_via_llm_when_available(monkeypatch):
    """핵심 routing regression 9-C/D/E — LLM-first 배관이 LLM 판단 결과를 그대로
    Plan에 반영하는지 확인한다. 실제 LLM의 판단 품질(정말 올바른 에이전트를
    고르는지)은 production smoke로 확인하고, 여기서는 mock으로 파이프라인
    자체(단일/복수 선택 → Standard/Full 전환, build_plan)만 검증한다."""

    def _select(expected_agents):
        def _fake(user_message, candidates, **kwargs):
            return expected_agents

        return _fake

    # C. 자산 정리 — 단일 선택.
    monkeypatch.setattr(planner, "_llm_select", _select([AgentName.ASSET_ORGANIZER]))
    plan = planner.classify(
        "내 재산이 아파트랑 예금이 있는데 한 번 정리하고 싶어",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.ASSET_ORGANIZER]]

    # D. 상속 절차 — 단일 선택.
    monkeypatch.setattr(planner, "_llm_select", _select([AgentName.HEIR_NAVIGATOR]))
    plan = planner.classify(
        "아버지가 돌아가셨는데 이제 뭘 해야 해?",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.HEIR_NAVIGATOR]]

    # E. 복합 질문 — 복수 선택 시 Full Pipeline(build_plan)으로 정상 전환.
    monkeypatch.setattr(
        planner,
        "_llm_select",
        _select([AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR]),
    )
    plan = planner.classify(
        "유언장 효력도 확인하고 상속 절차도 알고 싶어",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "full"
    assert set(plan.agents) == {AgentName.DECEDENT_ESTATE, AgentName.HEIR_NAVIGATOR}


def test_decedent_estate_routing_scenarios():
    """decedent_estate example_utterances 보강(자필/직접 작성/녹음 유언) 관련
    회귀 — 5개 라우팅 시나리오. 응답 문구가 아니라 agents/path/층 순서 등
    라우팅 계약만 검증한다. ANTHROPIC_API_KEY 는 conftest 가 지우므로 후보
    2개 이상(#4)은 LLM 실패 폴백(키워드 후보 전부)을 탄다."""

    # 1) 자필 표현이 문장에 명확 — 키워드 "유언장" 단독 후보로 Standard.
    #    PR #92(will_type 되물음 방지)는 agent.py 쪽 동작이라 이 테스트의
    #    범위(라우팅) 밖이지만, decedent_estate 로 정확히 도달하는지는 확인한다.
    plan = planner.classify(
        "자필로 쓴 유언장이 있는데 효력이 있나요?",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]

    # 2) "유언장을 직접 쓰려고" — 마찬가지로 "유언장" 키워드 단독 후보.
    plan = planner.classify(
        "유언장을 직접 쓰려고 하는데 형식 요건이 궁금해요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]

    # 3) 녹음 유언 — "유언" 키워드로 여전히 decedent_estate 단독 후보.
    plan = planner.classify(
        "녹음으로 남긴 유언도 효력이 있나요?",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]

    # 4) 유언 효력 + 상속세 — 후보 2개(Full). decedent_estate 가 will_status 를
    #    생산하고 tax_calculator 가 그걸 참고하므로, DAG 상 decedent_estate 층이
    #    tax_calculator 층보다 먼저 와야 한다.
    plan = planner.classify(
        "유언장 효력도 확인하고 상속세도 계산해줘",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "full"
    assert set(plan.agents) == {AgentName.DECEDENT_ESTATE, AgentName.TAX_CALCULATOR}
    decedent_layer_idx = next(
        i for i, layer in enumerate(plan.layers) if AgentName.DECEDENT_ESTATE in layer
    )
    tax_layer_idx = next(
        i for i, layer in enumerate(plan.layers) if AgentName.TAX_CALCULATOR in layer
    )
    assert decedent_layer_idx < tax_layer_idx

    # 5) 상속포기 — heir_navigator 단독. decedent_estate 가 섞이면 안 된다.
    plan = planner.classify(
        "상속포기는 언제까지 해야 하나요?",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.HEIR_NAVIGATOR]]
    assert AgentName.DECEDENT_ESTATE not in plan.agents


# ------------------------------------------------- pending_reply_agent (classify)


def test_pending_reply_agent_wins_over_keyword_candidate():
    """직전 턴에 답변을 기다리던 에이전트가 있으면, 이번 턴 메시지가 다른
    에이전트의 키워드(예금 → asset_organizer)를 포함해도 그 에이전트가
    우선한다 — 실제 재현: decedent_estate가 유언장 자료를 요청해놓은 상태에서
    사용자가 유언장 본문(아파트/예금 언급 포함)을 보내는 경우."""
    plan = planner.classify(
        "내 소유 아파트는 장남 김민수에게 주고, 은행 예금은 두 아들이 반씩 나누어 가진다.",
        pending_handoff=None,
        pending_reply_agent=AgentName.DECEDENT_ESTATE,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


def test_pending_handoff_wins_over_pending_reply_agent():
    """pending_handoff와 pending_reply_agent가 동시에 있으면 handoff가 최우선
    (기존 규칙 그대로) — Fast Path."""
    plan = planner.classify(
        "아무 말이나",
        pending_handoff=AgentName.HEIR_NAVIGATOR,
        pending_reply_agent=AgentName.DECEDENT_ESTATE,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "fast"
    assert plan.layers == [[AgentName.HEIR_NAVIGATOR]]


def test_pending_reply_agent_none_falls_back_to_keyword_routing():
    """pending_reply_agent가 없으면(하위 호환 — 기본값 None) 기존 키워드
    라우팅이 그대로 동작한다."""
    plan = planner.classify(
        "예금이 얼마나 있는지 정리하고 싶어요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.ASSET_ORGANIZER]]


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
        AgentName.ASSET_ORGANIZER,
        _slow(AgentName.ASSET_ORGANIZER),
    )

    t0 = time.perf_counter()
    output = router.route(
        AgentInput(session_id="p1", user_message="재산 정리하고 상속세도 궁금해요")
    )
    elapsed = time.perf_counter() - t0

    assert output.path == "full"
    assert set(output.agents) == {
        AgentName.TAX_CALCULATOR,
        AgentName.ASSET_ORGANIZER,
    }
    assert elapsed < 0.55, f"병렬이면 0.3초대여야 하는데 {elapsed:.2f}s"
    assert "tax_calculator ok" in output.reply and "asset_organizer ok" in output.reply


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
    _patch(monkeypatch, _fake(AgentName.ASSET_ORGANIZER, reply="순자산은 1억원입니다."))

    output = router.route(
        AgentInput(session_id="f1", user_message="재산 정리하고 상속세도 궁금해요")
    )
    assert "1억원" in output.reply
    assert output.data.get("error") == "agent_failed"


# ------------------------------------------------------- financial_profile


def test_financial_profile_round_trips_and_merges(monkeypatch):
    # 공유 financial_profile 왕복 검증 — 생산자 에이전트는 아무나 되지만,
    # 실제로 공유 프로필을 내보내는 asset_organizer 로 잡아 대화가 실제
    # 라우팅되게 한다 (retirement_planner 는 데모 제외로 도달 불가).
    organizer = _fake(
        AgentName.ASSET_ORGANIZER,
        financial_profile=FinancialProfile(
            financial_assets=300_000_000, monthly_expense=3_000_000
        ),
    )
    tax = _fake(AgentName.TAX_CALCULATOR)
    _patch(monkeypatch, organizer, tax)

    router.route(AgentInput(session_id="fp1", user_message="자산 정리 상담"))
    output = router.route(
        AgentInput(
            session_id="fp1",
            user_message="상속세도 계산해줘",
            financial_profile=FinancialProfile(real_estate_value=500_000_000),
        )
    )
    # 이전 턴에서 asset_organizer 가 알려준 값 + 이번 요청의 값이 병합돼 전달된다
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


def test_session_state_json_round_trip_keeps_pending_reply_agent():
    """pending_reply_agent는 DB 컬럼이 아니라 다른 공유 상태와 같이 "_shared"
    아래에 직렬화된다 — 새 컬럼/마이그레이션 없이."""
    state = SessionState(pending_reply_agent=AgentName.DECEDENT_ESTATE)
    raw = state.to_json_context()
    assert raw["_shared"]["pending_reply_agent"] == "decedent_estate"

    back = SessionState.from_json_context(raw)
    assert back.pending_reply_agent == AgentName.DECEDENT_ESTATE


def test_session_state_json_round_trip_omits_pending_reply_agent_when_unset():
    state = SessionState()
    raw = state.to_json_context()
    assert "pending_reply_agent" not in raw.get("_shared", {})

    back = SessionState.from_json_context(raw)
    assert back.pending_reply_agent is None


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


# ------------------------------------------------ waiting-agent continuation
#
# 재현: decedent_estate가 review intake gate(#103)에서 "유언장 사진을
# 올려주시거나, 적힌 내용을 그대로 입력해 주세요"를 next_action=
# await_user_confirmation으로 반환해 답변을 기다리는 중인데, 다음 턴에 사용자가
# 보낸 실제 유언장 본문에 asset_organizer 키워드("예금")가 섞여 있어 대화가
# 엉뚱한 에이전트로 이탈하던 버그.


_AWAIT_REPLY = "await_user_confirmation"
_DECEDENT_INTAKE_REPLY = (
    "자필 유언장의 형식 요건을 확인하려면 유언장 내용을 확인해야 합니다. "
    "유언장 사진을 올려주시거나, 적힌 내용을 그대로 입력해 주세요."
)
_WILL_BODY_WITH_ASSET_KEYWORDS = (
    "내 소유 아파트는 장남 김민수에게 주고, 은행 예금은 두 아들이 반씩 나누어 가진다."
)


def test_waiting_agent_keeps_next_turn_over_other_agent_keyword(monkeypatch):
    decedent = _fake(
        AgentName.DECEDENT_ESTATE,
        reply=_DECEDENT_INTAKE_REPLY,
        next_action=_AWAIT_REPLY,
        data={"decedent_estate": {"will_type": "handwritten", "requirements": {}}},
    )
    asset_organizer = _fake(AgentName.ASSET_ORGANIZER)
    _patch(monkeypatch, decedent, asset_organizer)

    turn1 = router.route(
        AgentInput(
            session_id="wait-1",
            user_message=(
                "아버지가 돌아가시고 집 정리하다가 손으로 직접 쓴 유언장을 발견했어요. "
                "이게 법적으로 효력이 있는 건지 확인하고 싶어요."
            ),
        )
    )
    assert turn1.agent == AgentName.DECEDENT_ESTATE
    assert turn1.next_action == _AWAIT_REPLY

    turn2 = router.route(
        AgentInput(session_id="wait-1", user_message=_WILL_BODY_WITH_ASSET_KEYWORDS)
    )
    assert turn2.agents == [AgentName.DECEDENT_ESTATE]
    assert not asset_organizer.captured  # asset_organizer가 아예 실행되지 않았다


def test_waiting_agent_pending_clears_after_non_waiting_response(monkeypatch):
    """대기 중이던 에이전트가 다음 응답에서 next_action=None을 내면 pending이
    풀리고, 그 다음 턴은 새 키워드에 따라 정상적으로 다른 에이전트로 전환된다."""
    decedent_waiting = _fake(
        AgentName.DECEDENT_ESTATE,
        reply=_DECEDENT_INTAKE_REPLY,
        next_action=_AWAIT_REPLY,
    )
    asset_organizer = _fake(AgentName.ASSET_ORGANIZER)
    _patch(monkeypatch, decedent_waiting, asset_organizer)

    router.route(AgentInput(session_id="wait-2", user_message="유언장 확인하고 싶어요"))

    # decedent_estate가 이번엔 확인을 마치고 next_action=None으로 응답 — pending 해제.
    decedent_done = _fake(
        AgentName.DECEDENT_ESTATE, reply="확인 완료", next_action=None
    )
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.DECEDENT_ESTATE, decedent_done)
    turn2 = router.route(
        AgentInput(session_id="wait-2", user_message=_WILL_BODY_WITH_ASSET_KEYWORDS)
    )
    assert turn2.agents == [AgentName.DECEDENT_ESTATE]
    assert turn2.next_action is None

    # pending이 해제됐으므로 다음 턴은 키워드에 따라 asset_organizer로 정상 전환.
    turn3 = router.route(
        AgentInput(
            session_id="wait-2", user_message="예금이 얼마나 있는지 정리하고 싶어요"
        )
    )
    assert turn3.agents == [AgentName.ASSET_ORGANIZER]
    assert len(asset_organizer.captured) == 1


def test_red_requirement_keeps_pending_reply_agent_for_correction_turn():
    """decedent_estate review에 RED 요건이 남아 heir_navigator로 handoff하지
    못하면(#118), 다음 턴 라우팅 소유권(pending_reply_agent)이 decedent_estate에
    남아야 한다 — #110/#111 continuation 메커니즘을 그대로 재사용한다(실제
    decedent_estate 에이전트로 실행, fake 아님).
    """
    turn1 = router.route(
        AgentInput(
            session_id="red-gate-1",
            user_message=(
                "유언장\n유언자: 홍길동\n2026년 5월 3일\n\n"
                "나의 전 재산을 배우자에게 상속한다."
            ),
            context={
                "decedent_estate": {
                    "will_type": "handwritten",
                    "handwriting_answer": "yes",
                    "seal_answer": "seal_or_fingerprint",
                    "address_envelope_answer": "no_envelope",  # 봉투에도 없음 → RED
                }
            },
        )
    )
    assert turn1.agent == AgentName.DECEDENT_ESTATE
    assert turn1.data["requirements"]["address"]["grade"] == "RED"
    assert turn1.next_action != "handoff:heir_navigator"

    stored = router.default_store.load("red-gate-1")
    assert stored.pending_reply_agent == AgentName.DECEDENT_ESTATE

    # 정정 메시지에 다른 에이전트 키워드가 없어도(또는 있어도) decedent_estate가
    # 계속 받아야 한다 — pending_reply_agent가 keyword routing보다 우선.
    turn2 = router.route(
        AgentInput(
            session_id="red-gate-1",
            user_message=(
                "주소는 서울특별시 강남구 테헤란로 123, 101동 1203호라고 적혀 있습니다."
            ),
        )
    )
    assert turn2.agents == [AgentName.DECEDENT_ESTATE]
    assert turn2.data["requirements"]["address"]["grade"] == "GREEN"


def test_yellow_address_detail_question_keeps_pending_reply_agent():
    """주소가 도로명 건물번호까지만 있고 동·호수가 불명확해 YELLOW +
    후속 질문으로 열려 있으면(2026-09-05), grade가 RED가 아니라 YELLOW여도
    pending_reply_agent가 decedent_estate에 남아야 한다 — 다음 턴 상세주소
    입력이 다른 에이전트로 새지 않는다(실제 decedent_estate 에이전트로 실행,
    fake 아님)."""
    turn1 = router.route(
        AgentInput(
            session_id="yellow-detail-1",
            user_message=(
                "유언장\n유언자: 홍길동\n주소: 서울특별시 강남구 테헤란로 123\n"
                "2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
            ),
            context={
                "decedent_estate": {
                    "will_type": "handwritten",
                    "handwriting_answer": "yes",
                    "seal_answer": "seal_or_fingerprint",
                }
            },
        )
    )
    assert turn1.agent == AgentName.DECEDENT_ESTATE
    assert turn1.data["requirements"]["address"]["grade"] == "YELLOW"
    assert (
        turn1.data["requirements"]["address"]["condition_id"] == "building_number_only"
    )
    assert turn1.next_action != "handoff:heir_navigator"

    stored = router.default_store.load("yellow-detail-1")
    assert stored.pending_reply_agent == AgentName.DECEDENT_ESTATE

    turn2 = router.route(
        AgentInput(
            session_id="yellow-detail-1",
            user_message=(
                "주소는 서울특별시 강남구 테헤란로 123, 101동 1203호라고 적혀 있습니다."
            ),
        )
    )
    assert turn2.agents == [AgentName.DECEDENT_ESTATE]
    assert turn2.data["requirements"]["address"]["grade"] == "GREEN"


def test_completed_review_does_not_auto_handoff_and_keeps_followup_with_decedent():
    """실측 재현 버그 — 형식요건 점검이 전부 종결(GREEN)되면 decedent_estate가
    next_action=handoff:heir_navigator를 반환해 session.pending_handoff가
    세워졌다. "그럼 요건은 일단 다 맞는 건가?"처럼 순수 결과 후속 질문에도
    다음 턴 라우팅이 pending_handoff(최우선)를 따라 heir_navigator로 가버려,
    "돌아가신 날짜가 언제인가요?" 같은 엉뚱한 절차 안내가 나왔다.

    수정 후: 종결돼도 pending_handoff가 서지 않고(next_action=None),
    keyword가 없는 후속 질문은 router의 기존 last_agent continuation으로
    decedent_estate가 계속 받는다. 사용자가 실제로 다른 주제("절차")를
    물으면 기존 keyword routing으로 heir_navigator가 정상 선택된다(실제
    decedent_estate/heir_navigator 에이전트로 실행, fake 아님)."""
    turn1 = router.route(
        AgentInput(
            session_id="no-auto-handoff-1",
            user_message=(
                "유언장\n유언자: 홍길동\n주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
                "2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
            ),
            context={
                "decedent_estate": {
                    "will_type": "handwritten",
                    "handwriting_answer": "yes",
                    "seal_answer": "seal_or_fingerprint",
                }
            },
        )
    )
    assert turn1.agent == AgentName.DECEDENT_ESTATE
    for rid in ("date", "address", "name", "handwriting", "seal"):
        assert turn1.data["requirements"][rid]["grade"] == "GREEN"
    assert turn1.next_action is None

    stored = router.default_store.load("no-auto-handoff-1")
    assert stored.pending_handoff is None
    assert stored.pending_reply_agent is None
    assert stored.last_agent == AgentName.DECEDENT_ESTATE

    # A) 결과 후속 질문 — 키워드가 없으므로 last_agent continuation을 타야 한다.
    turn2 = router.route(
        AgentInput(
            session_id="no-auto-handoff-1",
            user_message="그럼 요건은 일단 다 맞는 건가?",
        )
    )
    assert turn2.agents == [AgentName.DECEDENT_ESTATE]
    assert "requirements" in turn2.data
    # 상속 절차 안내(heir_navigator)로 새지 않았다 — 사망일 질문이 나오면 안 된다.
    assert "돌아가신 날짜" not in turn2.reply

    # B) 실제로 다른 주제를 물으면 기존 keyword routing으로 heir_navigator가 선택된다.
    turn3 = router.route(
        AgentInput(
            session_id="no-auto-handoff-1",
            user_message="그럼 상속 절차는 어떻게 해야 해?",
        )
    )
    assert turn3.agents == [AgentName.HEIR_NAVIGATOR]


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


# ---------------------------------------- verify: 값 수준(semantic) 대조


def _notation_outputs():
    return [
        AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply="상속재산은 3억 5천만원으로 평가되며 세율은 20%입니다.",
        ),
        AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR,
            reply="협의분할 서류를 준비하세요.",
            data={"deadline": "2026-02-28"},
        ),
    ]


def test_verify_accepts_amount_notation_change():
    # 값은 같고 표기만 바뀐 금액은 오탐이 아니다
    draft = "상속재산 평가액은 350,000,000원입니다."
    result = compose_mod.verify_numbers(draft, _notation_outputs())
    assert result.ok, result.mismatches


def test_verify_accepts_decimal_unit_notation():
    draft = "상속재산 평가액은 3.5억 원입니다."
    result = compose_mod.verify_numbers(draft, _notation_outputs())
    assert result.ok, result.mismatches


def test_verify_accepts_date_format_change():
    # data 필드의 ISO 날짜 ↔ 한국어 날짜 표기
    draft = "신고 기한은 2026년 2월 28일입니다."
    result = compose_mod.verify_numbers(draft, _notation_outputs())
    assert result.ok, result.mismatches


def test_verify_accepts_year_omitted_date():
    draft = "신고 기한은 2월 28일입니다."
    assert compose_mod.verify_numbers(draft, _notation_outputs()).ok


def test_verify_rejects_invented_year():
    # 원본에 연도가 없는데 draft 가 연도를 붙이면 mismatch
    outputs = [
        AgentOutput(agent=AgentName.HEIR_NAVIGATOR, reply="기일은 2월 28일입니다."),
        AgentOutput(agent=AgentName.TAX_CALCULATOR, reply="세율은 20%입니다."),
    ]
    result = compose_mod.verify_numbers("기일은 2027년 2월 28일입니다.", outputs)
    assert not result.ok
    assert "2027년2월28일" in result.mismatches


def test_verify_rejects_altered_amount_across_notation():
    # 표기 변환처럼 보여도 값이 다르면 잡는다
    draft = "상속재산 평가액은 360,000,000원입니다."
    result = compose_mod.verify_numbers(draft, _notation_outputs())
    assert not result.ok
    assert result.mismatches == ["360,000,000원".replace(",", "")]


def test_verify_accepts_percent_decimal_notation():
    draft = "세율은 20.0%입니다."
    assert compose_mod.verify_numbers(draft, _notation_outputs()).ok


def test_extract_compound_amount_as_single_token():
    assert compose_mod.extract_facts("평가액 3억 5천만원") == ["3억5천만원"]
    # 단위 없는 뒷숫자는 "원"이 붙을 때만 금액에 포함된다
    assert compose_mod.extract_facts("1억 2026년") == ["1억", "2026"]


def test_parse_amount_values():
    assert compose_mod._parse_amount("3억5천만원") == 350_000_000
    assert compose_mod._parse_amount("12.5억") == 1_250_000_000
    assert compose_mod._parse_amount("1234000원") == 1_234_000
    assert compose_mod._parse_amount("1억2345원") == 100_002_345
    # 단위 없는 묶음이 중간에 오면 해석 불가 → None (fail-closed)
    assert compose_mod._parse_amount("3원5억") is None


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
        _fake(AgentName.ASSET_ORGANIZER),
    )
    output = router.route(
        AgentInput(session_id="v1", user_message="재산 정리하고 상속세도 궁금해요")
    )
    assert output.verification is not None
    assert output.verification.mode == "concat"  # LLM 없음 → 이어붙이기
    assert output.verification.ok


# ---------------------------------------- ChatResponse.contributions 계약


def test_contributions_preserve_overlapping_keys(monkeypatch):
    """겹치는 평면 키(pending_questions)가 에이전트별로 보존되는지.

    최상위 data 는 평면 병합(update)이라 나중 에이전트 값이 덮어쓰지만,
    contributions[] 에는 각 에이전트의 원본 data 가 그대로 남아야 한다 —
    프론트 카드 렌더가 이것만 보고 LEGACY_FLAT_KEYS 방어를 제거할 수 있는
    근거다.
    """
    de_q = [{"question": "유언장 날짜를 확인해주세요", "field": "date"}]
    hn_q = [{"question": "사망일이 언제인가요", "field": "death_date"}]
    _patch(
        monkeypatch,
        _fake(AgentName.DECEDENT_ESTATE, data={"pending_questions": de_q}),
        _fake(AgentName.HEIR_NAVIGATOR, data={"pending_questions": hn_q}),
    )
    response = router.route(
        AgentInput(
            session_id="contrib-1",
            user_message="아버지가 돌아가셨는데 유언장이 있어요",
        )
    )
    assert [c.agent for c in response.contributions] == [o for o in response.agents]
    by_agent = {c.agent: c for c in response.contributions}
    assert by_agent[AgentName.DECEDENT_ESTATE].data["pending_questions"] == de_q
    assert by_agent[AgentName.HEIR_NAVIGATOR].data["pending_questions"] == hn_q
    # 최상위 평면 병합은 여전히 마지막 값 — 전환기 레거시임을 문서화
    assert response.data["pending_questions"] in (de_q, hn_q)


def test_contributions_single_agent(monkeypatch):
    _patch(
        monkeypatch,
        _fake(AgentName.TAX_CALCULATOR, data={"last_result": {"final_amount": 1}}),
    )
    response = router.route(
        AgentInput(session_id="contrib-2", user_message="상속세 계산해줘")
    )
    assert len(response.contributions) == 1
    assert response.contributions[0].agent == AgentName.TAX_CALCULATOR
    assert response.contributions[0].reply.startswith("[fake:tax_calculator]")

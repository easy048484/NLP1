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
    # LLM 이 하나로 좁히면 합성할 것이 없으니 Standard 로 내려간다.
    # (LLM 경로 자체의 검증은 test_orchestrator_llm_routing.py)
    monkeypatch.setattr(
        planner, "_llm_route", lambda msg, **kw: [AgentName.TAX_CALCULATOR]
    )
    plan = planner.classify(
        "재산 정리하고 상속세도 궁금해요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


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

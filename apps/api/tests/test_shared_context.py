"""공유 컨텍스트 정비 회귀 테스트.

- family_graph.heirs.classify_heirs: 상속인 분류 1벌 통합
- tax_calculator / heir_share_analyzer: 세션 공유 상속재산(financial_profile)을
  읽어 재질문하지 않는다
- decedent_estate: compact WillStatus 를 산출한다
- planner.classify: axis(생전/사후)로 키워드 없는 발화를 라우팅한다
- orchestrator: will_status 가 decedent_estate → tax_calculator 로 흐른다
  (같은 턴 Full Pipeline + 다음 턴 세션 왕복)
"""

from __future__ import annotations

import pytest

from family_graph.heirs import classify_heirs
from orchestrator import planner, registry, router
from orchestrator.session_store import InMemorySessionStore, SessionState
from schemas import AgentInput, AgentName, AgentOutput, FinancialProfile, WillStatus

SPOUSE_TWO_CHILDREN = {
    "heirs": [
        {"name": "배우자", "relation": "spouse", "alive": True},
        {"name": "자녀1", "relation": "child", "alive": True},
        {"name": "자녀2", "relation": "child", "alive": True},
    ]
}


# --------------------------------------------------------- classify_heirs


def test_classify_heirs_spouse_and_children():
    c = classify_heirs(SPOUSE_TWO_CHILDREN)
    assert c.ok
    assert c.spouse_exists and c.children_count == 2
    assert not c.spouse_is_sole_heir
    assert {n: str(v) for n, v in c.statutory_shares.items()} == {
        "배우자": "3/7",
        "자녀1": "2/7",
        "자녀2": "2/7",
    }


def test_classify_heirs_sibling_does_not_block_sole_spouse():
    c = classify_heirs(
        {
            "heirs": [
                {"name": "배우자", "relation": "spouse", "alive": True},
                {"name": "형", "relation": "sibling", "alive": True},
            ]
        }
    )
    assert c.spouse_is_sole_heir is True
    assert [h.name for h in c.legal_heirs] == ["배우자"]


def test_classify_heirs_grandchild_is_unsupported():
    c = classify_heirs({"heirs": [{"name": "손자", "relation": "grandchild"}]})
    assert not c.ok
    assert "대습상속" in c.unsupported_reason


def test_classify_heirs_no_data():
    assert classify_heirs(None).has_family_data is False
    assert classify_heirs({}).has_family_data is False


# -------------------------------------------- tax_calculator reads estate


def test_tax_calculator_prefills_from_shared_estate():
    from agents.tax_calculator.agent import STATE_KEY, run

    payload = AgentInput(
        session_id="t-estate",
        user_message="상속세 계산해주세요",
        family_graph=SPOUSE_TWO_CHILDREN,
        financial_profile=FinancialProfile(
            real_estate_value=800_000_000,
            financial_assets=200_000_000,
            total_debts=100_000_000,
        ),
        context={
            STATE_KEY: {
                "status": "collecting",
                "values": {"decedent_is_resident": True},
                "confirmed_fields": ["decedent_is_resident"],
                "asked_slot": None,
                "missing_fields": [],
                "last_result": None,
            }
        },
    )
    output = run(payload)
    values = output.data[STATE_KEY]["values"]
    # asset_organizer 가 넘긴 값이 그대로 슬롯에 들어가 재질문되지 않는다
    assert values["original_inherited_property"] == 1_000_000_000
    assert values["financial_assets"] == 200_000_000
    assert values["debts"] == 100_000_000
    # 재산 관련 질문이 아니라 다음 단계(배우자 실제 상속액 등)로 넘어갔다
    assert output.data[STATE_KEY]["asked_slot"] != "original_inherited_property"


def test_tax_calculator_user_confirmed_value_wins_over_estate():
    from agents.tax_calculator.agent import STATE_KEY, run

    payload = AgentInput(
        session_id="t-estate2",
        user_message="계산",
        family_graph=SPOUSE_TWO_CHILDREN,
        financial_profile=FinancialProfile(real_estate_value=800_000_000),
        context={
            STATE_KEY: {
                "status": "collecting",
                "values": {
                    "decedent_is_resident": True,
                    "original_inherited_property": 500_000_000,
                },
                "confirmed_fields": [
                    "decedent_is_resident",
                    "original_inherited_property",
                ],
                "asked_slot": None,
                "missing_fields": [],
                "last_result": None,
            }
        },
    )
    output = run(payload)
    assert (
        output.data[STATE_KEY]["values"]["original_inherited_property"] == 500_000_000
    )


# ---------------------------------------- heir_share_analyzer reads estate


def test_heir_share_analyzer_prefills_estate_and_debts():
    from agents.heir_share_analyzer.agent import STATE_KEY, run

    payload = AgentInput(
        session_id="hs-estate",
        user_message="유류분 점검",
        family_graph=SPOUSE_TWO_CHILDREN,
        financial_profile=FinancialProfile(
            real_estate_value=600_000_000,
            financial_assets=100_000_000,
            total_debts=50_000_000,
        ),
    )
    output = run(payload)
    values = output.data[STATE_KEY]["values"]
    assert values["estate_value"] == 700_000_000
    assert values["debts"] == 50_000_000
    assert output.data[STATE_KEY]["asked_slot"] not in {"estate_value", "debts"}


# -------------------------------------- decedent_estate emits will_status


def test_decedent_estate_emits_will_status_no_will():
    from agents.decedent_estate.agent import run

    output = run(
        AgentInput(
            session_id="d-nowill",
            user_message="유언장 없이 돌아가셨어요",
            context={"decedent_estate": {"will_type": "none"}},
        )
    )
    assert isinstance(output.will_status, WillStatus)
    assert output.will_status.checked is True
    assert output.will_status.no_will is True


def test_decedent_estate_will_status_pending_when_asking_type():
    from agents.decedent_estate.agent import run

    output = run(AgentInput(session_id="d-ask", user_message="유언장 있어요"))
    assert output.will_status.checked is False


# --------------------------------------------------- planner axis routing


def test_classify_axis_post_death_routes_to_heir_navigator():
    plan = planner.classify(
        "그냥 막막해서 상담하고 싶어요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
        axis="post_death",
    )
    assert plan.agents == [AgentName.HEIR_NAVIGATOR]


def test_classify_axis_pre_need_routes_to_asset_organizer_when_registered():
    spec = registry.get_optional(AgentName.ASSET_ORGANIZER)
    plan = planner.classify(
        "뭐부터 준비해야 할지 모르겠어요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
        axis="pre_need",
    )
    # asset_organizer 가 아직 껍데기(is_stub)면 기본 에이전트로 되돌린다.
    if spec is not None and not spec.is_stub:
        assert plan.agents == [AgentName.ASSET_ORGANIZER]
    else:
        assert plan.agents == [AgentName.HEIR_NAVIGATOR]


def test_classify_axis_ignored_when_keyword_matches():
    plan = planner.classify(
        "상속세 얼마나 나오나요",
        pending_handoff=None,
        last_agent=None,
        default_agent=AgentName.HEIR_NAVIGATOR,
        axis="post_death",
    )
    assert plan.agents == [AgentName.TAX_CALCULATOR]


# ------------------------------------- orchestrator will_status flow (E2E)


@pytest.fixture()
def _store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "0")


def _fake(agent_name: AgentName, **kwargs):
    captured: list[AgentInput] = []

    def _run(payload: AgentInput) -> AgentOutput:
        captured.append(payload)
        return AgentOutput(
            agent=agent_name,
            reply=f"[fake:{agent_name.value}]",
            data={agent_name.value: {"seen": True}},
            **kwargs,
        )

    _run.captured = captured
    return _run


def test_will_status_flows_same_turn(monkeypatch, _store):
    decedent = _fake(
        AgentName.DECEDENT_ESTATE,
        will_status=WillStatus(
            checked=True,
            will_type="handwritten",
            overall_grade="green",
            has_effect=True,
        ),
    )
    tax = _fake(AgentName.TAX_CALCULATOR)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.DECEDENT_ESTATE, decedent)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.TAX_CALCULATOR, tax)

    out = router.route(
        AgentInput(
            session_id="ws-1",
            user_message="유언장 효력도 보고 상속세도 계산해줘",
        )
    )
    assert {a for a in out.agents} == {
        AgentName.DECEDENT_ESTATE,
        AgentName.TAX_CALCULATOR,
    }
    assert tax.captured[0].will_status is not None
    assert tax.captured[0].will_status.has_effect is True
    assert out.will_status.will_type == "handwritten"


def test_will_status_flows_next_turn(monkeypatch, _store):
    decedent = _fake(
        AgentName.DECEDENT_ESTATE,
        will_status=WillStatus(checked=True, no_will=True),
    )
    tax = _fake(AgentName.TAX_CALCULATOR)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.DECEDENT_ESTATE, decedent)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.TAX_CALCULATOR, tax)

    router.route(AgentInput(session_id="ws-2", user_message="유언장 효력 봐주세요"))
    router.route(AgentInput(session_id="ws-2", user_message="상속세 알려줘"))

    assert tax.captured[0].will_status is not None
    assert tax.captured[0].will_status.no_will is True


def test_session_state_json_round_trip_keeps_will_status():
    state = SessionState(
        per_agent_context={"tax_calculator": {"x": 1}},
        will_status=WillStatus(checked=True, will_type="handwritten", has_effect=True),
    )
    raw = state.to_json_context()
    assert raw["_shared"]["will_status"]["will_type"] == "handwritten"
    back = SessionState.from_json_context(raw)
    assert back.will_status is not None
    assert back.will_status.has_effect is True


def test_session_state_unchecked_will_status_not_persisted():
    state = SessionState(will_status=WillStatus(checked=False))
    assert "_shared" not in state.to_json_context()


# ------------------------------- heir_navigator reads estate (빚 vs 재산)


def test_heir_navigator_flags_insolvency_from_estate():
    from datetime import date

    from agents.heir_navigator.planner import build_plan
    from agents.heir_navigator.state import HeirState

    plan = build_plan(
        HeirState(death_date=date(2026, 1, 10)),
        today=date(2026, 2, 1),
        estate=FinancialProfile(real_estate_value=30_000_000, total_debts=80_000_000),
    )
    assert plan.solvency is not None
    assert plan.solvency.debt_exceeds_assets is True
    # 사용자가 "빚 있어요"라고 말하지 않았어도 선택지가 자동으로 붙는다
    assert [b.title for b in plan.branches] == ["단순승인", "한정승인", "상속포기"]


def test_heir_navigator_solvent_estate_shows_note_but_no_branches():
    from datetime import date

    from agents.heir_navigator.planner import build_plan
    from agents.heir_navigator.state import HeirState

    plan = build_plan(
        HeirState(death_date=date(2026, 1, 10)),
        today=date(2026, 2, 1),
        estate=FinancialProfile(real_estate_value=300_000_000, total_debts=50_000_000),
    )
    assert plan.solvency is not None
    assert plan.solvency.debt_exceeds_assets is False
    assert plan.branches == []


def test_heir_navigator_no_estate_no_solvency():
    from datetime import date

    from agents.heir_navigator.planner import build_plan
    from agents.heir_navigator.state import HeirState

    plan = build_plan(HeirState(death_date=date(2026, 1, 10)), today=date(2026, 2, 1))
    assert plan.solvency is None
    assert plan.branches == []


def test_heir_navigator_run_surfaces_insolvency(monkeypatch):
    from agents.heir_navigator.agent import run

    monkeypatch.setenv("HEIR_NAVIGATOR_DISABLE_LLM", "1")
    output = run(
        AgentInput(
            session_id="hn-insolvent",
            user_message="아버지가 2026년 1월 10일에 돌아가셨어요",
            financial_profile=FinancialProfile(
                real_estate_value=20_000_000, total_debts=90_000_000
            ),
            context={"today": "2026-02-01"},
        )
    )
    assert "한정승인" in output.reply and "상속포기" in output.reply

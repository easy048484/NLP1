"""
agent.run()의 체크리스트 흐름 테스트 (develop 기준 재작업).

⚠️ v3/v4 세션들과 달리 이 에이전트는 더 이상 시뮬레이션을 하지 않는다
(그건 agents/retirement_planner/가 담당) — 자산·부채 카테고리를 모으고
develop의 공유 schemas.FinancialProfile로 눌러서 내보내는 것까지만 본다.
"""

from __future__ import annotations

import pytest

from agents.asset_organizer import agent
from schemas import AgentInput, AgentName, FinancialProfile

STATE_KEY = agent.STATE_KEY


def _continue(
    session_id: str,
    message: str,
    state: dict,
    *,
    financial_profile: FinancialProfile | None = None,
) -> AgentInput:
    return AgentInput(
        session_id=session_id,
        user_message=message,
        context={STATE_KEY: state},
        financial_profile=financial_profile,
    )


def test_local_format_krw_matches_retirement_planner_copy():
    """extractor.py의 TODO와 같은 이유로 의도적으로 복제된 함수 — 두 복제본이
    갈라지지 않았는지 직접 대조한다."""
    from agents.retirement_planner.format_utils import format_krw as shared_format_krw

    for amount in (0, 5_000, 30_000_000, 250_000_000, -30_000_000):
        assert agent._format_krw(amount) == shared_format_krw(amount)


def test_first_turn_empty_message_shows_opening_prompt():
    output = agent.run(AgentInput(session_id="i1", user_message=""))

    assert output.agent == AgentName.ASSET_ORGANIZER
    assert "자산" in output.reply and "부채" in output.reply
    assert output.financial_profile is None
    state = output.data[STATE_KEY]
    assert state["assets"] == []
    assert state["checked_categories"] == []


def test_first_turn_with_content_extracts_and_asks_about_missing_categories():
    output = agent.run(AgentInput(session_id="i2", user_message="예금 3천 있어요"))

    state = output.data[STATE_KEY]
    assert any(
        a["type"] == "예금" and a["value"] == 30_000_000 for a in state["assets"]
    )
    assert "예금" in state["checked_categories"]
    assert "주식" in output.reply
    assert "부채" in output.reply
    assert output.financial_profile is None  # 아직 체크리스트가 안 끝남


def test_asset_type_known_without_amount_then_bare_number_resolves_it():
    output1 = agent.run(AgentInput(session_id="i3", user_message="집 한 채 있어요"))

    assert "부동산" in output1.reply and "얼마" in output1.reply
    state1 = output1.data[STATE_KEY]
    assert not any(a["type"] == "부동산" for a in state1["assets"])
    assert state1["pending_amounts"][0]["asset_type"] == "부동산"

    output2 = agent.run(_continue("i3", "5억이요", state1))
    state2 = output2.data[STATE_KEY]

    assert any(
        a["type"] == "부동산" and a["value"] == 500_000_000 for a in state2["assets"]
    )
    assert state2["pending_amounts"] == []


def test_negative_answer_mixed_with_new_item_only_resolves_mentioned_item(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    state1 = agent.run(
        AgentInput(session_id="i5", user_message="예금 3천 있어요")
    ).data[STATE_KEY]

    output2 = agent.run(_continue("i5", "아니요, 주식도 5천만원 있어요", state1))
    state2 = output2.data[STATE_KEY]

    assert any(
        a["type"] == "주식" and a["value"] == 50_000_000 for a in state2["assets"]
    )
    assert state2["status"] == "collecting"
    assert "펀드" in output2.reply


def test_liability_without_amount_asks_then_resolves_via_bare_number():
    output1 = agent.run(AgentInput(session_id="i6", user_message="대출이 좀 있어요"))

    assert "얼마" in output1.reply
    state1 = output1.data[STATE_KEY]
    assert state1["pending_amounts"][0]["liability_type"] == "대출"

    output2 = agent.run(_continue("i6", "3천만원이요", state1))
    state2 = output2.data[STATE_KEY]

    assert any(
        liability["type"] == "대출" and liability["remaining_balance"] == 30_000_000
        for liability in state2["liabilities"]
    )


def test_full_checklist_exports_flat_financial_profile_with_extra_detail():
    """체크리스트가 끝나면 flat 집계(schemas.FinancialProfile) + itemized
    상세(extra["asset_organizer"])를 함께 반환해야 한다."""
    session_id = "i7"
    state = agent.run(
        AgentInput(
            session_id=session_id, user_message="예금 1억 있고 대출 3천만원 있어요"
        )
    ).data[STATE_KEY]

    output = agent.run(_continue(session_id, "없어요", state))
    state = output.data[STATE_KEY]
    assert state["liability_followup_asked"] is True  # 대출에 상환 정보가 없어 후속질문

    output = agent.run(_continue(session_id, "몰라요", state))
    state = output.data[STATE_KEY]

    assert state["status"] == "done"
    assert output.financial_profile is not None
    # financial_assets는 추측 분류하지 않고 항상 0 — 부동산 제외 전부를
    # other_assets 하나로 합산한다 (tax_calculator 조사 때와 동일 사유).
    assert output.financial_profile.financial_assets == 0
    assert output.financial_profile.other_assets == 100_000_000
    assert output.financial_profile.total_debts == 30_000_000
    assert output.financial_profile.real_estate_value == 0

    extra = output.financial_profile.extra["asset_organizer"]
    assert any(
        a["type"] == "예금" and a["value"] == 100_000_000 for a in extra["assets"]
    )
    assert any(
        liability["type"] == "대출" and liability["remaining_balance"] == 30_000_000
        for liability in extra["liabilities"]
    )
    assert "순자산: 7,000만원" in output.reply


def test_liability_followup_uses_shared_current_age_for_relative_years():
    """current_age는 이제 이 에이전트가 직접 안 모으고 develop의 공유
    financial_profile(retirement_planner가 먼저 물어봤다고 가정)에서 온다."""
    session_id = "p1"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="대출 5천만원 있어요")
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))
    state = output.data[STATE_KEY]
    assert state["liability_followup_asked"] is True

    shared = FinancialProfile(current_age=58)
    output2 = agent.run(
        _continue(
            session_id, "월 50만원, 3년 남았어요", state, financial_profile=shared
        )
    )
    state2 = output2.data[STATE_KEY]

    liability = state2["liabilities"][0]
    assert liability["monthly_payment"] == 500_000
    assert liability["end_age"] == 61  # 58 + 3


def test_liability_followup_without_shared_current_age_skips_relative_interpretation():
    """공유 financial_profile에 current_age가 아직 없으면(retirement_planner를
    아직 거치지 않음) 상대 표현은 추측하지 않고 단순 모드로 남긴다."""
    session_id = "p2"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="대출 5천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(_continue(session_id, "3년 남았어요", state))  # current_age 없음
    state2 = output.data[STATE_KEY]

    liability = state2["liabilities"][0]
    assert liability["end_age"] is None


def test_ambiguous_followup_answer_falls_back_to_simple_mode_without_loop():
    session_id = "p5"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="대출 5천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(
        _continue(
            session_id,
            "나중에요",
            state,
            financial_profile=FinancialProfile(current_age=58),
        )
    )
    state2 = output.data[STATE_KEY]

    liability = state2["liabilities"][0]
    assert liability["monthly_payment"] is None
    assert liability["end_age"] is None
    assert state2["status"] == "done"  # 재질문 없이 바로 마무리로 진행


def test_parse_end_age_rejects_calendar_year_expression():
    assert agent._parse_end_age("2030년까지 갚아요", current_age=58) is None

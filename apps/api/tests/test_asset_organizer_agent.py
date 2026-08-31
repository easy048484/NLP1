"""
agent.run()의 체크리스트 흐름 테스트 (develop 기준 재작업).

⚠️ v3/v4 세션들과 달리 이 에이전트는 더 이상 시뮬레이션을 하지 않는다
(그건 agents/retirement_planner/가 담당) — 자산·부채 카테고리를 모으고
develop의 공유 schemas.FinancialProfile로 눌러서 내보내는 것까지만 본다.
"""

from __future__ import annotations

import json

import pytest

from agents.asset_organizer import agent
from schemas import AgentInput, AgentName, FinancialProfile

STATE_KEY = agent.STATE_KEY


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContent(text)]


class _FakeMessages:
    def __init__(
        self, *, text: str | None = None, exc: Exception | None = None
    ) -> None:
        self._text = text
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._text)


class _FakeAnthropicClient:
    def __init__(
        self, *, text: str | None = None, exc: Exception | None = None, **_kwargs
    ) -> None:
        self.messages = _FakeMessages(text=text, exc=exc)


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str | None = None,
    exc: Exception | None = None,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        agent.extractor.anthropic,
        "Anthropic",
        lambda **kwargs: _FakeAnthropicClient(text=text, exc=exc),
    )


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
    # tax_calculator 담당자 확정 기준 — 예금은 financial_assets로 분류.
    assert output.financial_profile.financial_assets == 100_000_000
    assert output.financial_profile.other_assets == 0
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


def test_finalize_no_longer_hands_off_to_retirement_planner():
    """⚠️ 2026-08-30 데모 제외 결정으로 retirement_planner 핸드오프를
    비활성화했다(agent.py의 _finalize() 참고 — 주석 처리해서 나중에
    복원 가능하게 남겨둠). 체크리스트가 끝나면 이제 handoffs가 비어
    있어야 하고, 자산·부채 목록 + 순자산 요약만 보여주고 거기서
    끝나야 한다 — 별도 트리거나 안내 문구 없이."""
    output = agent.run(AgentInput(session_id="ho1", user_message="예금 1억 있어요"))
    output = agent.run(_continue("ho1", "없어요", output.data[STATE_KEY]))

    assert output.data[STATE_KEY]["status"] == "done"
    assert output.handoffs == []
    assert "순자산" in output.reply
    # 노후자금 시뮬레이션으로 이어가자는 안내 문구가 없어야 한다.
    assert "은퇴" not in output.reply
    assert "노후" not in output.reply
    assert "시뮬레이션" not in output.reply


# ======================================= financial_assets/other_assets 분류


def test_deposit_stock_fund_classified_as_financial_assets():
    """tax_calculator 담당자 확정 기준: 예금·주식·펀드 → financial_assets,
    other_assets에는 들어가지 않는다."""
    session_id = "fa1"
    state = agent.run(
        AgentInput(
            session_id=session_id,
            user_message="예금 3천만원, 주식 2천만원, 펀드 1천만원 있어요",
        )
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))

    assert output.financial_profile.financial_assets == 60_000_000
    assert output.financial_profile.other_assets == 0


def test_real_estate_only_in_real_estate_value_field():
    """부동산은 financial_assets/other_assets 어느 쪽에도 중복되지 않고
    real_estate_value 하나에만 담긴다."""
    session_id = "fa2"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="부동산 5억 있어요")
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))

    assert output.financial_profile.real_estate_value == 500_000_000
    assert output.financial_profile.financial_assets == 0
    assert output.financial_profile.other_assets == 0


def test_other_and_vehicle_and_pension_classified_as_other_assets():
    """기타·자동차·퇴직연금은 금융자산으로 추측 분류하지 않고 other_assets에
    남는다 — tax_calculator가 "기타" 항목명을 보고 추가로 확인하기로 함."""
    session_id = "fa3"
    state = agent.run(
        AgentInput(
            session_id=session_id,
            user_message="자동차 3천만원, 퇴직연금 8천만원 있어요",
        )
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]
    assert state["pension_followup_asked"] is True  # 퇴직연금이 있어 후속질문

    output = agent.run(_continue(session_id, "일시금으로 받을게요", state))

    assert output.financial_profile.other_assets == 110_000_000
    assert output.financial_profile.financial_assets == 0


def test_mixed_asset_types_are_classified_exclusively_without_overlap():
    """예금+주식+부동산+기타가 섞여도 세 필드에 배타적으로 분배되고,
    합계가 원래 자산 총액과 정확히 일치해야 한다(겹치거나 누락되지 않음)."""
    session_id = "fa4"
    state = agent.run(
        AgentInput(
            session_id=session_id,
            user_message=("예금 1억, 주식 5천만원, 부동산 5억, 자동차 2천만원 있어요"),
        )
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))
    profile = output.financial_profile

    assert profile.financial_assets == 150_000_000  # 예금 1억 + 주식 5천만
    assert profile.real_estate_value == 500_000_000
    assert profile.other_assets == 20_000_000  # 자동차만
    total = profile.financial_assets + profile.real_estate_value + profile.other_assets
    assert total == 100_000_000 + 50_000_000 + 500_000_000 + 20_000_000


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


# ================================ 부채 후속질문 게이트가 다른 후속질문을 안 가로채는지


def test_liability_simple_mode_resolved_flag_prevents_reasking():
    """부채가 단순 모드로 확정되면(예: "몰라요") liability_followup_resolved가
    True로 마킹돼, 다음 턴에 같은 후속질문이 다시 뜨지 않아야 한다 — 실측
    재현됐던 버그: monthly_payment/end_age 필드가 영구히 비어 있어서
    _liabilities_needing_followup()만으로 판단하면 계속 "아직 답변
    대기 중"으로 오판했다."""
    session_id = "gate1"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="대출 5천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]
    assert state["liability_followup_asked"] is True
    assert state["liability_followup_resolved"] is False  # 아직 답변 전

    output = agent.run(_continue(session_id, "몰라요", state))
    state2 = output.data[STATE_KEY]
    assert state2["liability_followup_resolved"] is True
    assert state2["status"] == "done"

    # 다음 턴에 아무 말이나 보내도 부채 후속질문이 다시 뜨면 안 된다.
    output2 = agent.run(_continue(session_id, "네 알겠습니다", state2))
    assert "월 얼마씩 갚고" not in output2.reply


def test_pension_followup_gets_asked_after_liability_simple_mode_resolves():
    """이전엔 버그로 인해 부채가 단순 모드로 남으면(필드가 계속 비어 있어)
    liability 게이트가 매 턴 재발동해서 퇴직연금 후속질문 차례가 영영 안
    왔다 — 이제는 부채 답변 직후 곧바로 퇴직연금 후속질문이 나와야 한다
    (버그가 재현되던 시나리오를 그대로 재검증)."""
    session_id = "gate2"
    state = agent.run(
        AgentInput(
            session_id=session_id,
            user_message="대출 5천만원, 퇴직연금 8천만원 있어요",
        )
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]
    assert state["liability_followup_asked"] is True

    output = agent.run(_continue(session_id, "몰라요", state))  # 부채 후속질문 답변
    state2 = output.data[STATE_KEY]

    assert "퇴직연금은 일시금으로 받으실 예정인가요" in output.reply
    assert state2["pension_followup_asked"] is True
    assert state2["status"] == "collecting"  # 아직 안 끝남 — 퇴직연금 답변 대기 중


def test_liability_and_pension_followups_each_asked_exactly_once():
    """부채·퇴직연금이 같은 대화에 함께 있어도 각자 후속질문을 정확히 한
    번씩만 받고, 둘 다 해결된 뒤에는 어느 쪽도 다시 뜨지 않아야 한다."""
    session_id = "gate3"
    state = agent.run(
        AgentInput(
            session_id=session_id,
            user_message="대출 5천만원, 퇴직연금 8천만원 있어요",
        )
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(_continue(session_id, "몰라요", state))
    assert "퇴직연금은 일시금으로 받으실 예정인가요" in output.reply
    state = output.data[STATE_KEY]

    output = agent.run(
        _continue(session_id, "연금으로 65살부터 월 100만원씩 받을 거예요", state)
    )
    state = output.data[STATE_KEY]

    assert state["status"] == "done"
    assert state["liability_followup_asked"] is True
    assert state["liability_followup_resolved"] is True
    assert state["pension_followup_asked"] is True
    assert state["pension_followup_resolved"] is True
    assert state["incomes"] == [
        {"type": "퇴직연금", "monthly": 1_000_000, "start_age": 65, "end_age": None}
    ]

    # 마무리 이후 아무 말이나 보내도 두 후속질문 다 다시 뜨면 안 된다.
    output2 = agent.run(_continue(session_id, "감사합니다", state))
    assert "월 얼마씩 갚고" not in output2.reply
    assert "퇴직연금은 일시금으로" not in output2.reply


# =============================================== 퇴직연금 수령 방식 후속질문


def test_pension_followup_asked_once_when_pension_asset_present():
    session_id = "pen1"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))

    assert output.data[STATE_KEY]["pension_followup_asked"] is True
    assert "일시금" in output.reply and "연금" in output.reply


def test_pension_annuity_with_absolute_start_age_creates_income_stream():
    """정밀 모드: 연금형 의사 + 절대 나이 표현 + 월액이 모두 확인되면
    IncomeStream을 만들고, 자산 목록의 퇴직연금 원금은 그대로 유지된다
    (정보 손실 없음)."""
    session_id = "pen2"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]
    assert state["pension_followup_asked"] is True

    output = agent.run(
        _continue(session_id, "연금으로 65살부터 월 100만원씩 받을 거예요", state)
    )
    state2 = output.data[STATE_KEY]

    assert state2["incomes"] == [
        {"type": "퇴직연금", "monthly": 1_000_000, "start_age": 65, "end_age": None}
    ]
    assert any(
        a["type"] == "퇴직연금" and a["value"] == 80_000_000 for a in state2["assets"]
    )
    assert state2["status"] == "done"

    extra = output.financial_profile.extra["asset_organizer"]
    assert extra["incomes"] == state2["incomes"]


def test_pension_annuity_with_relative_start_age_uses_shared_current_age():
    """상대 나이 표현("3년 뒤")은 부채 정밀 모드와 동일하게 공유
    financial_profile.current_age를 기준으로 절대 나이로 변환된다."""
    session_id = "pen3"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(
        _continue(
            session_id,
            "연금으로 3년 뒤부터 월 80만원씩 받을 것 같아요",
            state,
            financial_profile=FinancialProfile(current_age=62),
        )
    )
    state2 = output.data[STATE_KEY]

    assert state2["incomes"] == [
        {"type": "퇴직연금", "monthly": 800_000, "start_age": 65, "end_age": None}
    ]


def test_pension_relative_start_age_without_shared_current_age_skips_conversion():
    """부채 정밀 모드와 동일하게, current_age를 아직 모르면 상대 나이
    표현은 추측하지 않고 포기한다 — 이 경우 소득 전환도 안 된다."""
    session_id = "pen4"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(
        _continue(session_id, "연금으로 3년 뒤부터 월 80만원씩 받을 거예요", state)
    )
    state2 = output.data[STATE_KEY]

    assert state2["incomes"] == []
    assert state2["status"] == "done"  # 재질문 없이 단순 모드로 진행


def test_pension_lump_sum_answer_skips_income_conversion():
    """단순 모드: 일시금이면 소득 전환 없이 기존처럼 비유동 자산으로만
    남고, 재질문 없이 바로 다음 단계로 진행된다."""
    session_id = "pen5"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(_continue(session_id, "일시금으로 받을 거예요", state))
    state2 = output.data[STATE_KEY]

    assert state2["incomes"] == []
    assert state2["status"] == "done"
    assert any(
        a["type"] == "퇴직연금" and a["value"] == 80_000_000 for a in state2["assets"]
    )


def test_pension_dont_know_answer_skips_income_conversion_without_reasking():
    """단순 모드: "몰라요"처럼 연금/일시금 의사 자체가 안 드러나면 소득
    전환 없이 바로 진행된다 — 재질문하지 않는다."""
    session_id = "pen6"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(_continue(session_id, "몰라요", state))
    state2 = output.data[STATE_KEY]

    assert state2["incomes"] == []
    assert state2["status"] == "done"


def test_pension_annuity_intent_without_amount_or_age_still_skips_conversion():
    """연금형 의사는 밝혔지만 시작 나이·월액을 둘 다 안 알려주면(부분
    정보만으로는 정밀 모드로 못 감) 소득 전환 없이 단순 모드로 남는다 —
    재질문하지 않는다(부채 정밀 모드의 "몰라요"/"나중에요" 처리와 동일)."""
    session_id = "pen7"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="퇴직연금 8천만원 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]

    output = agent.run(
        _continue(
            session_id,
            "연금으로 받고 싶긴 한데 아직 잘 모르겠어요",
            state,
            financial_profile=FinancialProfile(current_age=60),
        )
    )
    state2 = output.data[STATE_KEY]

    assert state2["incomes"] == []
    assert state2["status"] == "done"


def test_no_pension_asset_skips_followup_entirely():
    """퇴직연금 자산이 아예 없으면 후속질문 자체가 뜨지 않고 바로
    마무리된다."""
    session_id = "pen8"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="예금 1억 있어요")
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))
    state2 = output.data[STATE_KEY]

    assert state2["pension_followup_asked"] is False
    assert state2["status"] == "done"


# ================================================ 자동차/퇴직연금/임대보증금반환채무


def test_vehicle_and_pension_mentions_are_not_reasked_as_missing():
    output = agent.run(
        AgentInput(
            session_id="v1", user_message="자동차 3천만원, 퇴직연금 8천만원 있어요"
        )
    )
    state = output.data[STATE_KEY]

    assert any(
        a["type"] == "자동차" and a["value"] == 30_000_000 for a in state["assets"]
    )
    assert any(
        a["type"] == "퇴직연금" and a["value"] == 80_000_000 for a in state["assets"]
    )
    assert "자동차" in state["checked_categories"]
    assert "퇴직연금" in state["checked_categories"]
    assert "자동차" not in output.reply and "퇴직연금" not in output.reply


def test_lease_deposit_liability_recognized_under_debt_category_simple_mode():
    """임대보증금반환채무는 새 카테고리가 아니라 기존 "부채" 카테고리 안에서
    인식되어야 하고, monthly_payment가 없는 성격이라 자연히 단순 모드로
    남아야 한다(정밀 모드 후속질문을 강제로 만들지 않음)."""
    session_id = "v2"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="임대보증금 반환채무 2억 있어요")
    ).data[STATE_KEY]

    assert any(
        liability["type"] == "임대보증금반환채무"
        and liability["remaining_balance"] == 200_000_000
        for liability in state["liabilities"]
    )
    assert "부채" in state["checked_categories"]
    # 새 체크리스트 카테고리가 아니라 기존 "부채" 하나로 묶인다.
    assert "임대보증금반환채무" not in agent._ALL_CATEGORIES

    state = agent.run(_continue(session_id, "없어요", state)).data[STATE_KEY]
    assert (
        state["liability_followup_asked"] is True
    )  # 기존 부채 이중 모드 로직 그대로 동작

    # 이 유형은 보통 "월 상환액"이라는 개념이 없어 후속질문에 답을 못 하고
    # 자연히 단순 모드(정밀 모드 강제 없음)로 남는다.
    output = agent.run(_continue(session_id, "몰라요", state))
    state2 = output.data[STATE_KEY]

    assert state2["status"] == "done"
    liability = state2["liabilities"][0]
    assert liability["monthly_payment"] is None
    assert liability["end_age"] is None


# ============================================================ 보험 카테고리


def test_insurance_mention_marks_category_checked_and_not_reasked():
    output = agent.run(AgentInput(session_id="ins1", user_message="보험 하나 있어요"))

    state = output.data[STATE_KEY]
    assert "보험" in state["checked_categories"]
    assert len(state["insurance"]) == 1
    # 아직 안 물어본 나머지 카테고리만 되묻고, 보험은 다시 대상에 없어야 한다.
    assert "보험" not in state["pending_categories"]


def test_insurance_is_the_only_remaining_category_gets_asked_specifically():
    """자산·부채 카테고리를 다 언급했는데 보험만 빠지면, 보험만 콕 집어
    되물어야 한다(나머지를 다시 나열하지 않음)."""
    session_id = "ins2"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="예금 3천 있어요")
    ).data[STATE_KEY]

    output = agent.run(
        _continue(
            session_id,
            "주식 5천만원, 펀드 1천만원, 부동산 5억, 자동차 3천만원, "
            "퇴직연금 8천만원, 대출 3천만원 있어요",
            state,
        )
    )
    state = output.data[STATE_KEY]

    assert set(state["checked_categories"]) == {
        "예금",
        "주식",
        "펀드",
        "부동산",
        "자동차",
        "퇴직연금",
        "부채",
    }
    assert output.reply == (
        "아직 말씀 안 하신 항목이 있어요: 보험. "
        "있으면 알려주시고, 없으면 '없음'이라고 답해주세요."
    )


def test_insurance_extra_preserved_through_to_finalize():
    session_id = "ins3"
    state = agent.run(
        AgentInput(
            session_id=session_id, user_message="예금 3천 있어요, 보험 5천만원 있어요"
        )
    ).data[STATE_KEY]
    assert "보험" in state["checked_categories"]

    output = agent.run(_continue(session_id, "없어요", state))  # 나머지 없음
    state = output.data[STATE_KEY]

    assert state["status"] == "done"
    extra = output.financial_profile.extra["asset_organizer"]
    assert extra["insurance"][0]["value"] == 50_000_000


# ============================================================== 이미지 판독


def test_image_recognized_merges_into_checklist(monkeypatch: pytest.MonkeyPatch):
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [{"type": "예금", "value": 80_000_000}],
                "liabilities": [{"type": "대출", "remaining_balance": 10_000_000}],
                "insurance": [],
                "unclear": [],
            }
        ),
    )

    output = agent.run(
        AgentInput(
            session_id="img1",
            user_message="",
            image_base64="fake-base64-data",
            image_media_type="image/png",
        )
    )

    state = output.data[STATE_KEY]
    assert any(
        a["type"] == "예금" and a["value"] == 80_000_000 for a in state["assets"]
    )
    assert any(
        liability["type"] == "대출" and liability["remaining_balance"] == 10_000_000
        for liability in state["liabilities"]
    )
    assert "예금" in state["checked_categories"]
    assert "부채" in state["checked_categories"]


def test_image_unreadable_asks_to_reupload_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_llm(
        monkeypatch,
        text=json.dumps({"unreadable": True, "assets": [], "unclear": ["화면이 흐림"]}),
    )

    output = agent.run(
        AgentInput(
            session_id="img2",
            user_message="",
            image_base64="fake-base64-data",
            image_media_type="image/png",
        )
    )

    state = output.data[STATE_KEY]
    assert output.reply == agent._IMAGE_UNREADABLE_REPLY
    # 추측해서 채우지 않는다 — 카테고리 상태가 전혀 바뀌지 않아야 한다.
    assert state["assets"] == []
    assert state["checked_categories"] == []


def test_image_api_failure_asks_to_reupload_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_llm(monkeypatch, exc=TimeoutError("network timeout"))

    output = agent.run(
        AgentInput(
            session_id="img3",
            user_message="",
            image_base64="fake-base64-data",
            image_media_type="image/png",
        )
    )

    assert output.reply == agent._IMAGE_UNREADABLE_REPLY
    assert output.data[STATE_KEY]["assets"] == []


def test_image_unclear_field_pii_never_reaches_reply_or_state(
    monkeypatch: pytest.MonkeyPatch,
):
    """ "unclear"는 화이트리스트가 없는 완전 자유텍스트라 모델이 계좌번호·
    이름·주민등록번호 같은 걸 그대로 적어 보낼 수 있다 — 프롬프트가
    금지해도 실측으로 확인해야 하는 지점(PR 열린 이슈 참고). 이 값이
    reply나 세션 저장 데이터(output.data) 어디에도 그대로 노출되지
    않아야 한다."""
    pii_text = (
        "계좌번호 110-123-456789, 예금주 홍길동, 주민등록번호 900101-1234567 확인됨"
    )
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [{"type": "예금", "value": 50_000_000}],
                "liabilities": [],
                "insurance": [],
                "unclear": [pii_text],
            }
        ),
    )

    output = agent.run(
        AgentInput(
            session_id="img_pii1",
            user_message="",
            image_base64="fake-base64-data",
            image_media_type="image/png",
        )
    )

    haystack = repr(output.reply) + repr(output.data)
    assert pii_text not in haystack
    assert "계좌번호" not in haystack
    assert "홍길동" not in haystack
    assert "주민등록번호" not in haystack


# ============================================ 생전/사후 모드 게이트 (decedent_estate와 동일 패턴)


def test_mode_unset_defaults_silently_to_pre_need():
    """decedent_estate._resolve_intent()와 동일하게, mode를 아예 안 보내면
    되묻지 않고 조용히 기존 동작(생전)으로 진행한다 — 하위 호환."""
    output = agent.run(AgentInput(session_id="mode1", user_message="예금 3천 있어요"))

    state = output.data[STATE_KEY]
    assert state["mode"] == "pre_need"
    assert "돌아가신" not in output.reply


def test_mode_explicit_pre_need_shows_original_opening_prompt():
    output = agent.run(
        AgentInput(
            session_id="mode2",
            user_message="",
            context={"mode": "pre_need"},
        )
    )

    assert "자산" in output.reply and "부채" in output.reply
    assert "돌아가신" not in output.reply
    assert output.data[STATE_KEY]["mode"] == "pre_need"


def test_mode_explicit_post_death_shows_post_death_opening_prompt():
    output = agent.run(
        AgentInput(
            session_id="mode3",
            user_message="",
            context={"mode": "post_death"},
        )
    )

    assert "돌아가신" in output.reply
    assert output.data[STATE_KEY]["mode"] == "post_death"


def test_mode_invalid_value_reasks_without_persisting():
    """유효하지 않은 명시적 mode 값이 오면(오케스트레이터 버그 등)
    decedent_estate와 동일하게 재확인 질문을 하고, 잘못된 값을 그대로
    저장해두지 않는다(다음 턴에 같은 잘못된 값이 반복 사용되는 것 방지)."""
    output = agent.run(
        AgentInput(
            session_id="mode4",
            user_message="자산 정리해줘",
            context={"mode": "bogus"},
        )
    )

    assert output.data[STATE_KEY]["mode"] is None
    assert "본인 재산" in output.reply and "가족분" in output.reply


def test_mode_persists_across_turns_without_resending_flat_key():
    """이번 턴에 mode를 안 보내도, namespaced 세션 상태(STATE_KEY)에 저장된
    이전 턴의 mode가 그대로 유지돼야 한다 — flat key는 "이번 턴 명시적
    답변이 우선"일 때만 override하는 것이지 매턴 필수가 아니다."""
    state1 = agent.run(
        AgentInput(
            session_id="mode5",
            user_message="",
            context={"mode": "post_death"},
        )
    ).data[STATE_KEY]
    assert state1["mode"] == "post_death"

    output2 = agent.run(_continue("mode5", "예금은 확인됐어요", state1))

    assert output2.data[STATE_KEY]["mode"] == "post_death"


def test_mode_flat_key_this_turn_overrides_persisted_state():
    """decedent_estate 규약과 동일: 이번 턴에 명시적으로 다른 mode를 보내면
    저장된 값보다 이번 턴 값이 우선한다."""
    state1 = agent.run(
        AgentInput(
            session_id="mode6",
            user_message="",
            context={"mode": "pre_need"},
        )
    ).data[STATE_KEY]

    output2 = agent.run(
        AgentInput(
            session_id="mode6",
            user_message="",
            context={STATE_KEY: state1, "mode": "post_death"},
        )
    )

    assert output2.data[STATE_KEY]["mode"] == "post_death"


# ===================================================== 3단계 금액 신뢰도: "몰라요"


def test_dont_know_amount_creates_permanent_unknown_amount_asset():
    """유형은 알지만 금액을 모르면("몰라요") confirmed가 아니라
    unknown_amount로 영구 확정하고, pending_amounts에서 제거한다."""
    output1 = agent.run(AgentInput(session_id="unk1", user_message="집 한 채 있어요"))
    state1 = output1.data[STATE_KEY]
    assert state1["pending_amounts"][0]["asset_type"] == "부동산"

    output2 = agent.run(_continue("unk1", "몰라요", state1))
    state2 = output2.data[STATE_KEY]

    asset = next(a for a in state2["assets"] if a["type"] == "부동산")
    assert asset["confidence"] == "unknown_amount"
    assert asset["value"] == 0
    assert state2["pending_amounts"] == []


def test_unknown_amount_asset_is_never_reasked_in_next_turn():
    """한 번 unknown_amount로 확정되면, 이후 아무 턴에서도 그 항목의 금액을
    다시 묻지 않아야 한다(부채/퇴직연금 후속질문의 "한 번 답하면 끝"
    원칙과 동일하게, 재질문 자체가 무의미하다는 게 더 확실한 케이스)."""
    state1 = agent.run(
        AgentInput(session_id="unk2", user_message="집 한 채 있어요")
    ).data[STATE_KEY]
    state2 = agent.run(_continue("unk2", "몰라요", state1)).data[STATE_KEY]

    output3 = agent.run(_continue("unk2", "없어요", state2))

    assert "부동산" not in output3.reply or "얼마" not in output3.reply
    state3 = output3.data[STATE_KEY]
    assert state3["pending_amounts"] == []
    assert len([a for a in state3["assets"] if a["type"] == "부동산"]) == 1


# ============================================ 3단계 신뢰도 + 순자산 계산 제외/안내


def test_net_worth_excludes_unknown_amount_and_shows_disclaimer():
    session_id = "nw1"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="예금 1억 있고 집 한 채 있어요")
    ).data[STATE_KEY]

    state = agent.run(_continue(session_id, "몰라요", state)).data[
        STATE_KEY
    ]  # 부동산 금액
    output = agent.run(_continue(session_id, "없어요", state))

    assert output.financial_profile.real_estate_value == 0
    assert output.financial_profile.financial_assets == 100_000_000
    assert "1개 항목은 금액이 확인되지 않아 총액에서 제외됨" in output.reply
    assert "금액 확인 안 됨" in output.reply


def test_extra_asset_organizer_items_carry_confidence_field():
    session_id = "nw2"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="집 한 채 있어요")
    ).data[STATE_KEY]
    state = agent.run(_continue(session_id, "몰라요", state)).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))

    extra = output.financial_profile.extra["asset_organizer"]
    asset = next(a for a in extra["assets"] if a["type"] == "부동산")
    assert asset["confidence"] == "unknown_amount"


def test_all_confirmed_assets_show_no_disclaimer():
    """모든 항목이 confirmed면 기존 동작과 완전히 동일해야 한다 —
    제외 안내 문구가 붙지 않는다(회귀 방지)."""
    session_id = "nw3"
    state = agent.run(
        AgentInput(session_id=session_id, user_message="예금 1억 있어요")
    ).data[STATE_KEY]
    output = agent.run(_continue(session_id, "없어요", state))

    assert "제외됨" not in output.reply
    assert output.financial_profile.financial_assets == 100_000_000


# ===================================================== 사후 모드: 다기관 조회 결과 해석


def test_post_death_mode_mixed_institution_sentence_splits_confirmed_and_unknown(
    monkeypatch: pytest.MonkeyPatch,
):
    """기획서 3-1/5-3절 예시 그대로: 한 문장에 여러 기관의 조회 결과가
    섞여 와도, 기관별 공개 수준에 맞춰 confirmed/unknown_amount로 정확히
    나뉘어야 한다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "disclosures": [
                    {"type": "예금", "confidence": "confirmed", "value": 30_000_000},
                    {"type": "주식", "confidence": "unknown_amount", "value": None},
                ]
            }
        ),
    )

    output = agent.run(
        AgentInput(
            session_id="pd1",
            user_message="OO은행은 잔액까지 나왔고 OO증권은 계좌만 확인됐어요",
            context={"mode": "post_death"},
        )
    )

    state = output.data[STATE_KEY]
    deposit = next(a for a in state["assets"] if a["type"] == "예금")
    stock = next(a for a in state["assets"] if a["type"] == "주식")
    assert deposit["confidence"] == "confirmed" and deposit["value"] == 30_000_000
    assert stock["confidence"] == "unknown_amount" and stock["value"] == 0
    assert "예금" in state["checked_categories"]
    assert "주식" in state["checked_categories"]


def test_post_death_mode_falls_back_to_regular_extraction_when_no_disclosures(
    monkeypatch: pytest.MonkeyPatch,
):
    """사후 모드여도 extract_disclosures()가 빈 결과/None을 돌려주면
    (다기관 패턴이 아닌 평범한 문장) 기존 일반 추출 경로로 폴백해야
    한다 — 사후 모드가 일반 자산 언급을 못 알아듣게 만들면 안 된다."""
    _install_fake_llm(monkeypatch, text=json.dumps({"disclosures": []}))

    output = agent.run(
        AgentInput(
            session_id="pd2",
            user_message="예금 3천만원 있어요",
            context={"mode": "post_death"},
        )
    )

    state = output.data[STATE_KEY]
    assert any(
        a["type"] == "예금"
        and a["value"] == 30_000_000
        and a["confidence"] == "confirmed"
        for a in state["assets"]
    )


def test_pre_need_mode_never_calls_disclosure_extraction(
    monkeypatch: pytest.MonkeyPatch,
):
    """생전 모드에서는 다기관 조회 해석 경로 자체를 안 타야 한다 — 켜져
    있으면 몰라도 될 LLM 호출이 추가되고, 잘못 파싱될 위험도 생긴다."""
    calls: list[str] = []

    def _fake_extract_disclosures(text: str):
        calls.append(text)
        return None

    monkeypatch.setattr(
        agent.extractor, "extract_disclosures", _fake_extract_disclosures
    )

    agent.run(
        AgentInput(
            session_id="pd3",
            user_message="예금 3천만원 있어요",
            context={"mode": "pre_need"},
        )
    )

    assert calls == []


def test_post_death_disclosure_merge_marks_categories_checked_without_reasking(
    monkeypatch: pytest.MonkeyPatch,
):
    """사후 모드에서 존재만 확인된(unknown_amount) 항목도 checked_categories
    에 반영돼야 한다 — 안 그러면 "금액 몰라요"라고 이미 답한 카테고리를
    다시 "아직 말씀 안 하신 항목"으로 되물어보는 모순이 생긴다."""

    def _fake_extract_disclosures(text: str):
        from agents.asset_organizer.extractor import DisclosureItem

        return [
            DisclosureItem(asset_type="보험", confidence="unknown_amount", value=None)
        ]

    monkeypatch.setattr(
        agent.extractor, "extract_disclosures", _fake_extract_disclosures
    )

    output = agent.run(
        AgentInput(
            session_id="pd5",
            user_message="OO보험은 가입 여부만 확인됐어요",
            context={"mode": "post_death"},
        )
    )

    state = output.data[STATE_KEY]
    assert "보험" in state["checked_categories"]
    assert "보험" not in output.reply or "얼마" not in output.reply

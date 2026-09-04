"""
agents.retirement_planner.agent.run() 테스트.

체크리스트(자산·부채)는 이제 asset_organizer가 전담하므로, 여기서는
1. 시뮬레이션 필수값(현재 나이, 월 생활비)만 확인하는 최소 흐름
2. develop 공유 financial_profile을 재질문 없이 받아들이는지
3. asset_organizer가 남긴 extra["asset_organizer"] itemized 데이터를
   엔진 입력으로 정확히 재구성하는지 (유동성·부채 정밀/단순 모드 보존)
4. itemized 데이터가 없을 때 flat 집계만으로 안전하게 합성하는지
를 확인한다.
"""

from __future__ import annotations

import pytest

from agents.retirement_planner import agent
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


def test_first_turn_empty_message_shows_opening_prompt():
    output = agent.run(AgentInput(session_id="r1", user_message=""))

    assert output.agent == AgentName.RETIREMENT_PLANNER
    assert "나이" in output.reply and "생활비" in output.reply


def test_asks_current_age_then_monthly_expense_then_simulates():
    session_id = "r2"
    output = agent.run(
        AgentInput(session_id=session_id, user_message="은퇴 준비하고 싶어요")
    )
    assert "나이" in output.reply
    state = output.data[STATE_KEY]

    output = agent.run(_continue(session_id, "60살이에요", state))
    assert "생활비" in output.reply
    state = output.data[STATE_KEY]
    assert state["current_age"] == 60

    output = agent.run(_continue(session_id, "생활비는 200만원 정도예요", state))
    state = output.data[STATE_KEY]

    assert state["status"] == "done"
    assert "85세" in output.reply  # 기본 target_ages=[85, 90, 95]
    assert output.financial_profile.current_age == 60
    assert output.financial_profile.monthly_expense == 2_000_000


def test_thousands_comma_parsed_as_single_number():
    """asset_organizer/extractor.py의 같은 버그(P0-3)의 로컬 복제본 —
    "3,200만원"을 콤마 뒤 "200만원"으로만 읽고 앞자리를 날리던 걸 하나의
    숫자로 합쳐 읽도록 고쳤다. 콤마 없는 기존 표현도 회귀 없이 정상
    동작해야 한다."""
    assert agent._parse_amount("3,200만원") == 32_000_000
    assert agent._parse_amount("1,020,000원") == 1_020_000
    assert agent._parse_amount("5,000만원") == 50_000_000
    assert agent._parse_amount("3200만원") == 32_000_000
    assert agent._parse_amount("5000만원") == 50_000_000


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3천200만원", 32_000_000),
        ("3천200만", 32_000_000),
        ("3천 200만원", 32_000_000),
        ("3천 200만 원", 32_000_000),
        ("3천2백만원", 32_000_000),
        ("3천2백만 원", 32_000_000),
        ("3,200,000원", 3_200_000),
        ("32,000,000원", 32_000_000),
    ],
)
def test_demo_amount_expressions_parsed_consistently(text, expected):
    """asset_organizer/extractor.py의 같은 회귀 테스트(Round 15)의 로컬
    복제본 — 두 에이전트의 금액 파서 복제본이 같은 데모 표현을 같은 값으로
    처리하는지 확인."""
    assert agent._parse_amount(text) == expected


def test_thousands_comma_monthly_expense_flows_through_conversation():
    session_id = "r2-comma"
    output = agent.run(
        AgentInput(session_id=session_id, user_message="은퇴 준비하고 싶어요")
    )
    state = agent.run(_continue(session_id, "60살이에요", output.data[STATE_KEY])).data[
        STATE_KEY
    ]

    output = agent.run(_continue(session_id, "생활비는 3,200만원 정도예요", state))

    assert output.financial_profile.monthly_expense == 32_000_000


def test_adopts_shared_financial_profile_without_reasking():
    """current_age/monthly_expense가 이미 공유 프로필에 있으면(예:
    asset_organizer나 이전 턴이 채워둠) 재질문하지 않고 바로 계산한다."""
    shared = FinancialProfile(current_age=65, monthly_expense=1_500_000)
    output = agent.run(
        AgentInput(
            session_id="r3", user_message="상담해주세요", financial_profile=shared
        )
    )
    state = output.data[STATE_KEY]

    assert state["status"] == "done"
    assert "85세" in output.reply


def test_uses_itemized_asset_organizer_extra_when_present():
    """asset_organizer가 남긴 extra의 itemized 리스트가 있으면 유동성·부채
    정밀/단순 모드가 그대로 보존돼 계산에 반영돼야 한다."""
    shared = FinancialProfile(
        current_age=60,
        monthly_expense=1_000_000,
        real_estate_value=500_000_000,  # flat 집계 — itemized가 있으면 무시돼야 함
        extra={
            "asset_organizer": {
                "assets": [
                    {
                        "type": "부동산",
                        "value": 500_000_000,
                        "liquid": False,
                        "return_rate": None,
                    },
                    {
                        "type": "예금",
                        "value": 1_000_000_000,
                        "liquid": True,
                        "return_rate": 0.0,
                    },
                ],
                "liabilities": [],
            }
        },
    )
    output = agent.run(
        AgentInput(
            session_id="r4", user_message="계산해주세요", financial_profile=shared
        )
    )

    # 부동산(비유동) 5억은 잔액 계산에서 빠지고, 예금(유동) 10억만 인출 대상이다
    # — 유동자산만으로 25~35년치 생활비(연 1200만원)를 감당하고도 남으므로
    # 고갈되지 않아야 한다. flat 집계(real_estate_value)만 봤다면 이 구분
    # 자체가 불가능하다(정보 손실 보고 1번 참고).
    assert "고갈 없이 유지될 것으로 예상됩니다" in output.reply
    assert "고갈될 것으로 예상됩니다" not in output.reply


def test_synthesizes_from_flat_aggregate_when_no_itemized_extra():
    """asset_organizer를 거치지 않고 바로 이 에이전트에게 말을 걸면
    itemized 데이터가 없다 — flat 집계만으로도 부동산은 여전히 기본
    비유동으로 합성돼야 한다(정보 손실 보고 3번 참고)."""
    shared = FinancialProfile(
        current_age=60,
        monthly_expense=1_000_000,
        real_estate_value=500_000_000,
        financial_assets=0,
        total_debts=30_000_000,
    )
    profile = agent._build_engine_input(
        {"current_age": 60, "monthly_expense": 1_000_000}, shared
    )

    real_estate = next(a for a in profile.assets if a.type == "부동산")
    assert real_estate.value == 500_000_000
    assert real_estate.liquid is None  # adapter가 유형 기준으로 비유동 처리

    liability = profile.liabilities[0]
    assert liability.remaining_balance == 30_000_000
    assert liability.monthly_payment is None  # 단순 모드로만 합성 가능
    assert liability.end_age is None


def test_pension_income_from_extra_is_wired_into_engine_profile():
    """asset_organizer가 퇴직연금을 연금형으로 전환해 extra["asset_organizer"]
    ["incomes"]에 남긴 IncomeStream이 그대로 엔진 입력으로 재구성돼야
    한다 — retirement_pension kind로 매핑되고, 자산 목록의 퇴직연금
    원금(itemized)도 그대로 유지된다."""
    shared = FinancialProfile(
        current_age=60,
        monthly_expense=1_000_000,
        extra={
            "asset_organizer": {
                "assets": [
                    {
                        "type": "퇴직연금",
                        "value": 500_000_000,
                        "liquid": None,
                        "return_rate": None,
                    },
                ],
                "liabilities": [],
                "incomes": [
                    {
                        "type": "퇴직연금",
                        "monthly": 2_000_000,
                        "start_age": 65,
                        "end_age": None,
                    }
                ],
            }
        },
    )
    profile = agent._build_engine_input(
        {"current_age": 60, "monthly_expense": 1_000_000}, shared
    )

    assert len(profile.incomes) == 1
    income = profile.incomes[0]
    assert income.type == "퇴직연금"
    assert income.monthly == 2_000_000
    assert income.start_age == 65
    assert income.end_age is None

    pension_asset = next(a for a in profile.assets if a.type == "퇴직연금")
    assert pension_asset.value == 500_000_000  # 원금은 그대로 유지(정보 손실 없음)


def test_itemized_liability_with_unknown_amount_is_excluded_not_crashed():
    """asset_organizer는 금액을 모르는 부채(confidence=="unknown_amount")를
    remaining_balance=None으로 넘길 수 있다 — 이 에이전트의 로컬 Liability
    모델은 remaining_balance가 여전히 필수 int라(engine.py가 실제 숫자로
    산술) None을 그대로 재구성하면 검증 오류가 난다. 0으로 추측해 넣지도
    않고(부채가 없는 것처럼 계산됨) 조용히 시뮬레이션 입력에서 제외해야
    한다 — 확정된 다른 부채는 그대로 반영된다."""
    shared = FinancialProfile(
        current_age=60,
        monthly_expense=1_000_000,
        extra={
            "asset_organizer": {
                "assets": [],
                "liabilities": [
                    {
                        "type": "대출",
                        "remaining_balance": None,
                        "monthly_payment": None,
                        "end_age": None,
                        "note": None,
                        "confidence": "unknown_amount",
                    },
                    {
                        "type": "카드론",
                        "remaining_balance": 3_000_000,
                        "monthly_payment": None,
                        "end_age": None,
                        "note": None,
                        "confidence": "confirmed",
                    },
                ],
            }
        },
    )
    profile = agent._build_engine_input(
        {"current_age": 60, "monthly_expense": 1_000_000}, shared
    )

    assert len(profile.liabilities) == 1
    assert profile.liabilities[0].type == "카드론"
    assert profile.liabilities[0].remaining_balance == 3_000_000


def test_no_incomes_key_in_extra_synthesizes_empty_income_list():
    """asset_organizer가 애초에 퇴직연금을 연금형으로 전환한 적이 없으면
    extra에 "incomes" 자체가 없다 — flat 집계엔 소득을 담을 자리가 없어
    합성할 방법도 없으므로 빈 목록이어야 한다(조용히 추측해 채우지 않음)."""
    shared = FinancialProfile(
        current_age=60,
        monthly_expense=1_000_000,
        extra={
            "asset_organizer": {
                "assets": [],
                "liabilities": [],
            }
        },
    )
    profile = agent._build_engine_input(
        {"current_age": 60, "monthly_expense": 1_000_000}, shared
    )

    assert profile.incomes == []


def test_flat_fallback_does_not_reclassify_financial_vs_other_assets():
    """asset_organizer를 거치지 않고 flat 집계만 온 경우(financial_assets가
    이미 0으로 주어진 임의의 입력) — 이 폴백 함수는 financial_assets/
    other_assets를 유형별로 다시 쪼개거나 재분류하지 않고, 두 필드를 각각
    있는 그대로("기타" 자산 항목)만 합성해야 한다. (실제 분류 기준은
    asset_organizer._to_shared_profile()이 담당 — 이 테스트와는 무관.)"""
    shared = FinancialProfile(
        current_age=60,
        monthly_expense=1_000_000,
        financial_assets=0,
        other_assets=100_000_000,
    )
    profile = agent._build_engine_input(
        {"current_age": 60, "monthly_expense": 1_000_000}, shared
    )

    assert len(profile.assets) == 1  # financial_assets=0이라 추가 항목 없음
    assert profile.assets[0].type == "기타"
    assert profile.assets[0].value == 100_000_000

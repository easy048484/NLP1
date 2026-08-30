from __future__ import annotations

from agents.retirement_planner.adapter import to_engine_profile
from agents.retirement_planner.models import (
    Asset,
    FinancialProfile,
    IncomeStream,
    Liability,
)


def test_real_estate_defaults_to_non_liquid():
    """확정 사항: liquid 미지정 부동산은 어댑터가 자동으로 False 처리."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="부동산", value=500_000_000)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].liquid is False


def test_real_estate_explicit_liquid_override_respected():
    """명시적으로 liquid=True를 준 경우 (예: 주택연금·매각 시나리오)는 존중."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="부동산", value=500_000_000, liquid=True)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].liquid is True


def test_vehicle_defaults_to_non_liquid():
    """감가상각되고 즉시 현금화하기 어려운 자산이라 부동산과 같은 이유로
    기본 비유동 처리한다."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="자동차", value=30_000_000)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].liquid is False


def test_pension_defaults_to_non_liquid():
    """중도 인출 시 불이익이 커 실질적으로 못 쓰는 돈인 경우가 많아 기본
    비유동 처리한다."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="퇴직연금", value=80_000_000)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].liquid is False


def test_vehicle_explicit_liquid_override_respected():
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="자동차", value=30_000_000, liquid=True)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].liquid is True


def test_non_real_estate_defaults_to_liquid():
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="예금", value=30_000_000)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].liquid is True


def test_missing_return_rate_maps_to_zero():
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="주식", value=30_000_000, return_rate=None)],
    )
    engine_profile = to_engine_profile(profile)
    assert engine_profile.assets[0].nominal_return == 0.0


def test_pension_income_maps_to_retirement_pension_kind():
    """국민연금/개인연금과 구분되는 별도 kind("retirement_pension")로
    매핑돼야 engine.py가 (kind는 안 쓰지만) 향후 구분이 필요해질 때
    국민연금/개인연금과 섞이지 않는다."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        incomes=[
            IncomeStream(type="퇴직연금", monthly=2_000_000, start_age=65),
        ],
    )
    engine_profile = to_engine_profile(profile)

    assert engine_profile.incomes[0].kind == "retirement_pension"
    assert engine_profile.incomes[0].monthly_amount == 2_000_000
    assert engine_profile.incomes[0].start_age == 65
    assert engine_profile.incomes[0].end_age is None


def test_pension_principal_excluded_from_liquid_balance_even_with_income():
    """퇴직연금이 연금형으로 전환돼 incomes에도 들어가지만, 자산 목록의
    퇴직연금 원금은 liquid=False라 유동자산 합계(엔진이 인출 대상으로
    보는 잔액)에는 애초에 포함되지 않는다 — 원금과 소득 흐름이 이중으로
    반영되지 않는다는 것을 직접 확인한다."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        assets=[Asset(type="퇴직연금", value=500_000_000)],
        incomes=[
            IncomeStream(type="퇴직연금", monthly=2_000_000, start_age=65),
        ],
    )
    engine_profile = to_engine_profile(profile)

    liquid_balance = sum(a.value for a in engine_profile.assets if a.liquid)
    assert liquid_balance == 0  # 퇴직연금 원금 5억이 잔액 계산에 안 들어감
    assert engine_profile.assets[0].value == 500_000_000  # 자산 자체는 그대로 보존


def test_liability_fields_pass_through_unchanged():
    """정밀/단순 모드 판단은 engine.py가 monthly_payment/end_age 존재 여부로
    그때그때 하므로, adapter는 값을 그대로 옮기기만 하면 된다."""
    profile = FinancialProfile(
        current_age=60,
        monthly_expense=2_000_000,
        liabilities=[
            Liability(
                type="대출",
                remaining_balance=50_000_000,
                monthly_payment=500_000,
                end_age=65,
            ),
            Liability(type="카드론", remaining_balance=3_000_000),
        ],
    )
    engine_profile = to_engine_profile(profile)

    precise = engine_profile.liabilities[0]
    assert precise.remaining_balance == 50_000_000
    assert precise.monthly_payment == 500_000
    assert precise.end_age == 65

    simple = engine_profile.liabilities[1]
    assert simple.remaining_balance == 3_000_000
    assert simple.monthly_payment is None
    assert simple.end_age is None

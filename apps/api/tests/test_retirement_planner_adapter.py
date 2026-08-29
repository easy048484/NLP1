from __future__ import annotations

from agents.retirement_planner.adapter import to_engine_profile
from agents.retirement_planner.models import Asset, FinancialProfile, Liability


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

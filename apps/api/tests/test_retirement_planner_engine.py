"""
계획서 6장 "품질 검증"에 명시된 회귀 테스트:
- 부동산만 있고 유동자산 0 -> 즉시 고갈
- 연금이 생활비를 상회 -> 고갈 없음, 잔액 증가
- 수익률 미입력 -> 0으로 처리, 예외 없음
- 실질수익률 음수 -> 잔액 단조 감소
"""

from __future__ import annotations

import pytest

from agents.retirement_planner.engine import real_return_rate, simulate
from agents.retirement_planner.engine_models import (
    EngineAsset,
    EngineAssumptions,
    EngineIncome,
    EngineLiability,
    EngineProfile,
)


def _profile(**overrides) -> EngineProfile:
    defaults = {
        "current_age": 60,
        "monthly_expense": 2_000_000,
        "assets": [],
        "incomes": [],
        "assumptions": EngineAssumptions(),
    }
    defaults.update(overrides)
    return EngineProfile(**defaults)


def test_real_estate_only_depletes_immediately():
    """부동산만 있고 유동자산 0 -> 첫 해에 즉시 고갈."""
    profile = _profile(
        assets=[
            EngineAsset(
                kind="real_estate", value=500_000_000, liquid=False, nominal_return=0.0
            )
        ],
    )
    result = simulate(profile, target_age=65)
    assert result.depletion_age == profile.current_age
    assert result.yearly_balances[0][1] == 0


def test_income_exceeding_expense_never_depletes():
    """연금 수령액이 생활비를 초과하면 고갈 없음, 잔액은 매년 증가."""
    profile = _profile(
        monthly_expense=1_000_000,
        assets=[
            EngineAsset(
                kind="deposit", value=10_000_000, liquid=True, nominal_return=0.0
            )
        ],
        incomes=[
            EngineIncome(
                kind="national_pension",
                monthly_amount=2_000_000,
                start_age=60,
                end_age=None,
            )
        ],
    )
    result = simulate(profile, target_age=80)
    assert result.depletion_age is None
    balances = [b for _, b in result.yearly_balances]
    assert balances == sorted(balances)  # 단조 증가
    assert balances[-1] > balances[0]


def test_missing_return_rate_defaults_to_zero_no_exception():
    """수익률(nominal_return) 미입력 -> 0으로 처리, 예외 없이 계산됨."""
    profile = _profile(
        assets=[
            EngineAsset(kind="stock", value=50_000_000, liquid=True, nominal_return=0.0)
        ],
    )
    result = simulate(profile, target_age=70)  # 예외 없이 끝까지 실행되면 통과
    assert isinstance(result.remaining_at_target, int)


def test_negative_real_return_causes_monotonic_decrease():
    """명목수익률이 물가상승률보다 낮으면 실질수익률이 음수 -> 잔액 단조 감소.
    소득=지출로 맞춰 원금 유출입은 0으로 만들고, 순수 수익률 효과만 검증."""
    profile = _profile(
        monthly_expense=1_000_000,
        assets=[
            EngineAsset(
                kind="deposit", value=100_000_000, liquid=True, nominal_return=0.0
            )
        ],
        incomes=[
            EngineIncome(
                kind="other", monthly_amount=1_000_000, start_age=60, end_age=None
            )
        ],
        assumptions=EngineAssumptions(inflation=0.05),  # nominal 0% < inflation 5%
    )
    assert real_return_rate(0.0, 0.05) < 0
    result = simulate(profile, target_age=75)
    balances = [b for _, b in result.yearly_balances]
    assert balances == sorted(balances, reverse=True)  # 단조 감소
    assert balances[-1] < balances[0]


def test_target_age_before_current_age_raises():
    profile = _profile(current_age=60)
    with pytest.raises(ValueError):
        simulate(profile, target_age=59)


def test_no_liquid_assets_and_no_income_depletes_first_year():
    """자산 없이 계산 요청 -> 크래시 없이 즉시 고갈로 처리 (온보딩 유도는 상위 레이어 책임)."""
    profile = _profile(assets=[], incomes=[])
    result = simulate(profile, target_age=65)
    assert result.depletion_age == profile.current_age


# ============================================== 부채 이중 모드 (asset_organizer v3)


def test_precise_mode_liability_adds_expense_only_within_payment_period():
    """monthly_payment+end_age 둘 다 있으면 정밀 모드 — current_age부터
    end_age까지만 매년 monthly_payment*12가 지출에 더해지고, end_age
    이후엔 원래 생활비 지출로 복귀한다."""
    profile = _profile(
        current_age=60,
        monthly_expense=1_000_000,
        assets=[
            EngineAsset(
                kind="deposit", value=1_000_000_000, liquid=True, nominal_return=0.0
            )
        ],
        liabilities=[
            EngineLiability(
                remaining_balance=50_000_000, monthly_payment=500_000, end_age=62
            )
        ],
        assumptions=EngineAssumptions(inflation=0.0),
    )
    result = simulate(profile, target_age=65)
    balances = dict(result.yearly_balances)

    assert balances[60] == 982_000_000  # 1,000M - (12M 생활비 + 6M 상환액)
    assert balances[62] == 946_000_000
    # end_age(62)까지는 생활비+상환액, 그 이후는 생활비만 차감된다.
    assert balances[61] - balances[62] == 18_000_000
    assert balances[62] - balances[63] == 12_000_000


def test_simple_mode_liability_deducted_once_at_start():
    """monthly_payment나 end_age 중 하나라도 없으면 단순 모드 —
    remaining_balance를 시뮬레이션 시작 시점에 유동자산에서 딱 한 번만
    차감하고, 그 이후로는 다시 빠지지 않는다."""
    profile = _profile(
        current_age=60,
        monthly_expense=1_000_000,
        assets=[
            EngineAsset(
                kind="deposit", value=200_000_000, liquid=True, nominal_return=0.0
            )
        ],
        liabilities=[
            EngineLiability(
                remaining_balance=30_000_000, monthly_payment=None, end_age=None
            )
        ],
        assumptions=EngineAssumptions(inflation=0.0),
    )
    result = simulate(profile, target_age=62)
    balances = dict(result.yearly_balances)

    assert balances[60] == 158_000_000  # 200M - 30M(1회 차감) - 12M(생활비)
    assert balances[60] - balances[61] == 12_000_000  # 이후엔 생활비만 차감


def test_multiple_liabilities_apply_modes_independently():
    """부채가 여러 개면 정밀/단순 모드가 섞여도 각각 독립적으로 적용된다."""
    profile = _profile(
        current_age=60,
        monthly_expense=1_000_000,
        assets=[
            EngineAsset(
                kind="deposit", value=500_000_000, liquid=True, nominal_return=0.0
            )
        ],
        liabilities=[
            EngineLiability(
                remaining_balance=20_000_000, monthly_payment=None, end_age=None
            ),  # 단순 모드
            EngineLiability(
                remaining_balance=40_000_000, monthly_payment=300_000, end_age=61
            ),  # 정밀 모드
        ],
        assumptions=EngineAssumptions(inflation=0.0),
    )
    result = simulate(profile, target_age=63)
    balances = dict(result.yearly_balances)

    # 시작 잔액: 500M - 20M(단순 모드 1회 차감) = 480M
    # age60 지출: 12M(생활비) + 3.6M(정밀 모드 상환액) = 15.6M
    assert balances[60] == 464_400_000
    # end_age(61) 이후로는 정밀 모드 상환액이 빠지고 생활비만 남는다.
    assert balances[61] - balances[62] == 12_000_000


def test_precise_mode_end_age_beyond_target_age_keeps_payment_throughout():
    """end_age가 target_age보다 늦으면 시뮬레이션 구간 전체에서 상환액이
    계속 반영되고, target_age를 넘는 나이는 애초에 계산되지 않는다."""
    profile = _profile(
        current_age=60,
        monthly_expense=1_000_000,
        assets=[
            EngineAsset(
                kind="deposit", value=1_000_000_000, liquid=True, nominal_return=0.0
            )
        ],
        liabilities=[
            EngineLiability(
                remaining_balance=50_000_000, monthly_payment=500_000, end_age=90
            )
        ],
        assumptions=EngineAssumptions(inflation=0.0),
    )
    result = simulate(profile, target_age=63)
    ages = [age for age, _ in result.yearly_balances]

    assert ages == [60, 61, 62, 63]  # target_age를 넘는 나이는 계산 대상이 아님
    balances = dict(result.yearly_balances)
    assert balances[60] - balances[61] == balances[61] - balances[62] == 18_000_000

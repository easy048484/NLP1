"""
은퇴 후 자금 시뮬레이션 엔진.

LLM을 전혀 호출하지 않는 순수 결정론 로직입니다. 계산·판정은
여기서 전담하고, 자연어 해석은 상위(extractor/formatter)에서
담당한다는 원칙(기획서 5-2절)을 그대로 따릅니다.

핵심 가정:
- 실질수익률 하나로 계산 (명목수익률·물가상승률을 합성) → 모든
  결과는 "오늘 돈 가치" 기준
- 유동자산(liquid=True)만 인출 대상. 부동산 등 비유동 자산은
  잔액 계산에서 제외됨 (adapter가 이미 유동성 여부를 확정해서 넘김)
- 연도 순서: 그 해 소득 반영 → 생활비(+정밀 모드 부채 상환액) 차감 →
  남은 잔액에 실질수익률 적용

부채 이중 모드 (asset_organizer v3):
- 정밀 모드 (monthly_payment·end_age 둘 다 있음): current_age부터
  end_age까지 매년 monthly_payment*12를 생활비와 동일하게 연간 지출에
  더한다. end_age 이후로는 더 반영하지 않는다 (_annual_liability_payment).
- 단순 모드 (둘 중 하나라도 없음): remaining_balance를 시뮬레이션
  시작 시점에 유동자산 총액에서 딱 한 번 차감한다
  (_simple_mode_liability_total). 비유동 자산에서는 빼지 않는다 — 어차피
  이 엔진이 다루는 건 유동자산뿐이라서.
- 부채가 여러 개면 각각 독립적으로 모드를 판단한다 (섞여도 됨).
"""

from __future__ import annotations

from dataclasses import dataclass

from .engine_models import EngineLiability, EngineProfile


@dataclass
class SimulationResult:
    target_age: int
    yearly_balances: list[tuple[int, int]]  # (나이, 잔액)
    depletion_age: int | None
    remaining_at_target: int


def real_return_rate(nominal: float, inflation: float) -> float:
    """명목수익률과 물가상승률을 합성한 실질수익률."""
    return (1 + nominal) / (1 + inflation) - 1


def _annual_income(profile: EngineProfile, age: int) -> int:
    total = 0
    for inc in profile.incomes:
        if age >= inc.start_age and (inc.end_age is None or age <= inc.end_age):
            total += inc.monthly_amount * 12
    return total


def _is_precise_mode(liability: EngineLiability) -> bool:
    return liability.monthly_payment is not None and liability.end_age is not None


def _annual_liability_payment(profile: EngineProfile, age: int) -> int:
    """정밀 모드 부채의 해당 연도 상환액 합계. end_age 이후로는 0."""
    total = 0.0
    for liability in profile.liabilities:
        if _is_precise_mode(liability) and age <= liability.end_age:
            total += liability.monthly_payment * 12
    return round(total)


def _simple_mode_liability_total(profile: EngineProfile) -> int:
    """단순 모드 부채의 remaining_balance 합계 — 시작 시점에 한 번만 차감."""
    return sum(
        liability.remaining_balance
        for liability in profile.liabilities
        if not _is_precise_mode(liability)
    )


def _weighted_real_return(profile: EngineProfile) -> float:
    liquid_assets = [a for a in profile.assets if a.liquid]
    liquid_total = sum(a.value for a in liquid_assets)
    if liquid_total == 0:
        return 0.0
    weighted_nominal = (
        sum(a.value * a.nominal_return for a in liquid_assets) / liquid_total
    )
    return real_return_rate(weighted_nominal, profile.assumptions.inflation)


def simulate(profile: EngineProfile, target_age: int) -> SimulationResult:
    if target_age < profile.current_age:
        raise ValueError("target_age는 current_age 이상이어야 합니다")

    liquid_balance = float(sum(a.value for a in profile.assets if a.liquid))
    # 단순 모드 부채: 시작 시점에 유동자산에서 딱 한 번 차감 (비유동 자산은
    # 애초에 balance에 안 들어 있으므로 자동으로 제외됨).
    liquid_balance -= _simple_mode_liability_total(profile)
    real_return = _weighted_real_return(profile)

    balance = liquid_balance
    depletion_age: int | None = None
    yearly_balances: list[tuple[int, int]] = []

    for age in range(profile.current_age, target_age + 1):
        income = _annual_income(profile, age)
        # 정밀 모드 부채: 해당 연도만 생활비와 동일하게 지출에 더해진다.
        annual_expense = profile.monthly_expense * 12 + _annual_liability_payment(
            profile, age
        )
        balance = balance - (annual_expense - income)

        if balance < 0 and depletion_age is None:
            depletion_age = age
            balance = 0.0  # 고갈 이후 음수로 표시하지 않음

        balance *= 1 + real_return
        yearly_balances.append((age, round(balance)))

    return SimulationResult(
        target_age=target_age,
        yearly_balances=yearly_balances,
        depletion_age=depletion_age,
        remaining_at_target=round(balance),
    )


def simulate_scenarios(profile: EngineProfile) -> list[SimulationResult]:
    """assumptions.target_ages(기본 85/90/95) 각각에 대해 시뮬레이션."""
    return [simulate(profile, t) for t in profile.assumptions.target_ages]

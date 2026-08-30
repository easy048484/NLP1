"""
models.py(엔진 입력 모델) → EngineProfile(엔진 내부 모델) 변환.

입력 모델이 바뀌면 이 파일만 고칩니다. engine.py는 이 파일의 입력 모델을
몰라야 합니다 (역방향 의존 금지).
"""

from __future__ import annotations

from .engine_models import (
    EngineAsset,
    EngineAssumptions,
    EngineIncome,
    EngineLiability,
    EngineProfile,
)
from .models import Asset as ExtAsset
from .models import FinancialProfile
from .models import Liability as ExtLiability

_ASSET_TYPE_MAP: dict[str, str] = {
    "예금": "deposit",
    "주식": "stock",
    "펀드": "fund",
    "부동산": "real_estate",
    "자동차": "vehicle",
    # 나중에 필요해지면: 수령 시작 나이가 되면 자산에서 소득 흐름(incomes)으로
    # 전환하는 로직을 추가할 수 있다 — 이번 범위는 아니며, 지금은 그냥
    # 비유동 자산 하나로만 잡아서 목록·순자산 계산에 반영한다.
    "퇴직연금": "pension",
    "기타": "other",
}

#: 명시적 liquid override가 없을 때 기본 비유동으로 처리하는 kind들.
#: 부동산(즉시 현금화 어려움)에 자동차(감가상각·즉시 현금화 어려움)와
#: 퇴직연금(중도 인출 시 불이익이 커 실질적으로 못 쓰는 돈인 경우가 많음)을
#: 같은 이유로 추가했다 — 노후자금 계산에서 "실제보다 좋아 보이는" 쪽으로
#: 왜곡되지 않게 안전한 방향(제외)을 기본값으로 둔다.
_ILLIQUID_BY_DEFAULT_KINDS = frozenset({"real_estate", "vehicle", "pension"})

_INCOME_TYPE_MAP: dict[str, str] = {
    "국민연금": "national_pension",
    "개인연금": "private_pension",
    "기타": "other",
}


def _to_engine_asset(asset: ExtAsset) -> EngineAsset:
    kind = _ASSET_TYPE_MAP[asset.type]

    # 확정 사항: 부동산·자동차·퇴직연금은 기본 유동화 불가. 명시적 override만 예외.
    if asset.liquid is not None:
        liquid = asset.liquid
    else:
        liquid = kind not in _ILLIQUID_BY_DEFAULT_KINDS

    return EngineAsset(
        kind=kind,  # type: ignore[arg-type]
        value=asset.value,
        liquid=liquid,
        # 수익률 미입력 → 0 (서비스가 기본 수익률을 제시하지 않는다는 결정)
        nominal_return=asset.return_rate or 0.0,
    )


def _to_engine_liability(liability: ExtLiability) -> EngineLiability:
    # 정밀/단순 모드는 저장된 플래그가 아니라 monthly_payment/end_age의
    # 존재 여부로 engine.py가 그때그때 판단한다 (engine_models.EngineLiability
    # 참고) — 여기서는 값만 그대로 옮긴다.
    return EngineLiability(
        remaining_balance=liability.remaining_balance,
        monthly_payment=liability.monthly_payment,
        end_age=liability.end_age,
    )


def to_engine_profile(profile: FinancialProfile) -> EngineProfile:
    assets = [_to_engine_asset(a) for a in profile.assets]
    liabilities = [_to_engine_liability(liability) for liability in profile.liabilities]

    incomes = [
        EngineIncome(
            kind=_INCOME_TYPE_MAP[i.type],  # type: ignore[arg-type]
            monthly_amount=i.monthly,
            start_age=i.start_age,
            end_age=i.end_age,
        )
        for i in profile.incomes
    ]

    assumptions = EngineAssumptions(
        inflation=profile.assumptions.inflation,
        retire_age=profile.assumptions.retire_age,
        target_ages=list(profile.assumptions.target_ages),
    )

    return EngineProfile(
        current_age=profile.current_age,
        monthly_expense=profile.monthly_expense,
        assets=assets,
        liabilities=liabilities,
        incomes=incomes,
        assumptions=assumptions,
    )

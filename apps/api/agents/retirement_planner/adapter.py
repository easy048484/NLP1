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
    "기타": "other",
}

_INCOME_TYPE_MAP: dict[str, str] = {
    "국민연금": "national_pension",
    "개인연금": "private_pension",
    "기타": "other",
}


def _to_engine_asset(asset: ExtAsset) -> EngineAsset:
    kind = _ASSET_TYPE_MAP[asset.type]

    # 확정 사항: 부동산은 기본 유동화 불가. 명시적 override만 예외.
    if asset.liquid is not None:
        liquid = asset.liquid
    else:
        liquid = kind != "real_estate"

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

"""
시뮬레이션 엔진 전용 내부 모델.

models.py(엔진 입력 모델)와 의도적으로 분리되어 있습니다.
입력 모델이 바뀌어도 이 파일과 engine.py는 영향받지 않아야 하며,
변환 책임은 전부 adapter.py가 집니다.

EngineAsset.liquid는 기본값을 두지 않습니다 — "부동산은 기본
유동화 불가"라는 결정을 adapter가 항상 명시적으로 내리도록
강제하기 위함입니다 (조용히 잘못된 기본값이 스며드는 걸 방지).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EngineAssetKind = Literal["deposit", "stock", "fund", "real_estate", "other"]
EngineIncomeKind = Literal["national_pension", "private_pension", "other"]


class EngineAsset(BaseModel):
    kind: EngineAssetKind
    value: int = Field(ge=0)
    liquid: bool  # 기본값 없음 — adapter가 항상 명시적으로 결정
    nominal_return: float = 0.0


class EngineIncome(BaseModel):
    kind: EngineIncomeKind
    monthly_amount: int = Field(ge=0)
    start_age: int
    end_age: int | None = None


class EngineLiability(BaseModel):
    """부채. monthly_payment와 end_age가 둘 다 있으면 "정밀 모드"(engine.py의
    _annual_liability_payment가 current_age~end_age 동안 매년 지출에 더함),
    하나라도 없으면 "단순 모드"(remaining_balance를 시작 시점에 유동자산에서
    한 번만 차감)로 계산한다. 어느 모드인지는 저장된 값이 아니라 이 두
    필드의 존재 여부로 그때그때 판단한다 — 모드를 별도 필드로 들고 다니면
    값과 모드가 어긋나는 상태가 생길 수 있어서다."""

    remaining_balance: int = Field(ge=0)
    monthly_payment: float | None = None
    end_age: int | None = None


class EngineAssumptions(BaseModel):
    inflation: float = 0.02
    retire_age: int = 65
    target_ages: list[int] = Field(default_factory=lambda: [85, 90, 95])


class EngineProfile(BaseModel):
    current_age: int
    monthly_expense: int = Field(ge=0)
    assets: list[EngineAsset] = Field(default_factory=list)
    liabilities: list[EngineLiability] = Field(default_factory=list)
    incomes: list[EngineIncome] = Field(default_factory=list)
    assumptions: EngineAssumptions = Field(default_factory=EngineAssumptions)

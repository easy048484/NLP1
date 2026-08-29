"""
retirement_planner 시뮬레이션 입력 모델.

⚠️ develop 기준 재작업 메모: 이 파일은 원래 asset_organizer의
"contracts.py"(외부 계약 초안)였다. develop에는 이제 진짜 공유 계약인
schemas.FinancialProfile(flat 집계)이 따로 있어서, 이 파일은 더 이상
"외부 계약"이 아니라 retirement_planner 엔진(engine.py/engine_models.py/
adapter.py)이 기대하는 입력 모양을 그대로 유지하기 위한 내부 모델이다.
클래스 정의(필드)는 검증된 계산 로직과 맞물려 있어 한 글자도 안 바꿨고,
agent.py의 _build_profile()이 schemas.FinancialProfile(+ extra 안의
asset_organizer itemized 데이터)로부터 이 모델을 조립한다.

`Liability`(부채)의 monthly_payment/end_age 이중 모드 계산은 engine.py
참고 — 이 필드들이 둘 다 있으면 "정밀 모드", 하나라도 없으면 "단순 모드".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AssetType = Literal["예금", "주식", "펀드", "부동산", "기타"]
IncomeType = Literal["국민연금", "개인연금", "기타"]


class Asset(BaseModel):
    """스톡 자산. 부동산은 liquid를 명시하지 않으면 어댑터가 False로 처리."""

    type: AssetType
    value: int = Field(ge=0, description="평가액 (원)")
    liquid: bool | None = Field(
        default=None,
        description="None이면 유형별 기본값 적용 (부동산=False, 그 외=True)",
    )
    return_rate: float | None = Field(
        default=None,
        description="사용자가 직접 입력한 연 명목수익률. 서비스가 기본값을 제시하지 않음",
    )


class IncomeStream(BaseModel):
    """플로우 소득. 연금 등 매년 유입되는 현금흐름."""

    type: IncomeType
    monthly: int = Field(ge=0)
    start_age: int
    end_age: int | None = Field(default=None, description="None이면 종신")


class InsuranceTag(BaseModel):
    """사망보험금 등 — 노후 재원 계산에서 제외, decedent_estate/tax_calculator 전달용."""

    type: str
    value: int = Field(ge=0)
    note: str | None = None


class Liability(BaseModel):
    """부채. remaining_balance는 항상 필요 — 없으면 재질문 대상(조용한 실패
    금지 원칙, asset_organizer/extractor.py 참고). monthly_payment/end_age는
    사용자가 자연스럽게 말했을 때만 채워지는 선택 정보이며, 둘 다 있으면
    엔진이 "정밀 모드"(상환 기간 동안 연간 지출에 반영)로, 하나라도 없으면
    "단순 모드"(remaining_balance를 시뮬레이션 시작 시점에 유동자산에서
    한 번 차감)로 계산한다 — engine.py 참고."""

    type: str = Field(
        description='"대출", "카드론", "전세자금대출" 등 — asset_organizer가 추출한 값'
    )
    remaining_balance: int = Field(ge=0, description="남은 원금 (원)")
    monthly_payment: int | None = Field(
        default=None, description="매월 상환액 (원). 있으면 정밀 모드 후보"
    )
    end_age: int | None = Field(
        default=None, description="상환 종료 예상 나이. 있으면 정밀 모드 후보"
    )
    note: str | None = None


class Assumptions(BaseModel):
    inflation: float = Field(
        default=0.02, description="물가상승률, 기본값=한은 중기 목표 2%"
    )
    retire_age: int = Field(default=65)
    target_ages: list[int] = Field(default_factory=lambda: [85, 90, 95])


class FinancialProfile(BaseModel):
    """retirement_planner 엔진의 입력 모델 (itemized). schemas.FinancialProfile
    (develop 공유 flat 계약)과 이름은 같지만 다른 클래스다 — 이 모듈
    안에서만 쓰고, agent.py 경계를 넘어갈 때는 절대 이 이름 그대로
    내보내지 않는다(schemas.FinancialProfile로 변환해서 내보낸다)."""

    current_age: int = Field(ge=0, le=130)
    monthly_expense: int = Field(ge=0)
    assets: list[Asset] = Field(default_factory=list)
    liabilities: list[Liability] = Field(default_factory=list)
    incomes: list[IncomeStream] = Field(default_factory=list)
    insurance_tags: list[InsuranceTag] = Field(default_factory=list)
    assumptions: Assumptions = Field(default_factory=Assumptions)

"""상속세 계산 엔진 전용 입출력 계약."""

from pydantic import BaseModel, Field
from datetime import date


class InheritanceTaxInput(BaseModel):
    """피상속인이 거주자인 경우의 상속세 계산 입력값."""

    filing_within_deadline: bool = Field(
        default=False,
        description="법정 신고기한 내 신고 여부",
    )
    decedent_is_resident: bool = Field(
        default=True,
        description="피상속인의 거주자 여부",
    )
    inheritance_commencement_date: date | None = Field(
        default=None,
        description="상속개시일(일반적으로 피상속인의 사망일)",
    )
    spouse_exists: bool = Field(
        default=False,
        description="피상속인의 배우자 생존 여부",
    )
    children_count: int = Field(
        default=0,
        ge=0,
        description="피상속인의 자녀 수",
    )
    spouse_is_sole_heir: bool = Field(
        default=False,
        description="배우자가 단독상속인인지 여부",
    )
    spouse_actual_inheritance: int = Field(
        default=0,
        ge=0,
        description="배우자가 실제 상속받은 순재산가액(원)",
    )
    spouse_prior_gift_tax_base: int = Field(
        default=0,
        ge=0,
        description=("배우자가 사전증여받은 재산의 증여세 과세표준(원)"),
    )
    # 1. 총상속재산가액
    original_inherited_property: int = Field(
        default=0,
        ge=0,
        description="본래의 상속재산가액(원)",
    )
    deemed_inherited_property: int = Field(
        default=0,
        ge=0,
        description="보험금·신탁재산·퇴직금 등 간주상속재산가액(원)",
    )
    estimated_inherited_property: int = Field(
        default=0,
        ge=0,
        description="상속재산에 가산하는 추정상속재산가액(원)",
    )
    bequests_to_non_heirs: int = Field(
        default=0,
        ge=0,
        description=("상속인이 아닌 수유자가 유증·사인증여받은 재산가액(원)"),
    )
    next_rank_inheritance_due_to_renunciation: int = Field(
        default=0,
        ge=0,
        description=("상속인의 상속포기로 다음 순위 상속인이 받은 재산가액(원)"),
    )
    # 금융재산 상속공제 계산 정보
    financial_assets: int = Field(
        default=0,
        ge=0,
        description=("총상속재산에 포함된 공제대상 금융재산가액(원)"),
    )
    financial_debts: int = Field(
        default=0,
        ge=0,
        description=("전체 채무에 포함된 금융기관 금융채무가액(원)"),
    )
    # 2. 비과세 및 과세가액 불산입액
    non_taxable_property: int = Field(
        default=0,
        ge=0,
        description="비과세 재산가액(원)",
    )
    excluded_property: int = Field(
        default=0,
        ge=0,
        description="과세가액 불산입 재산가액(원)",
    )

    # 3. 공과금·장례비용·채무
    public_charges: int = Field(
        default=0,
        ge=0,
        description="상속재산에서 차감할 공과금(원)",
    )
    funeral_expenses: int = Field(
        default=0,
        ge=0,
        description="실제로 지출한 일반 장례비용(원)",
    )
    burial_facility_expenses: int = Field(
        default=0,
        ge=0,
        description="봉안시설·자연장지에 실제 지출한 비용(원)",
    )
    debts: int = Field(
        default=0,
        ge=0,
        description="상속재산에서 차감할 채무(원)",
    )

    # 4. 사전증여재산
    prior_gifts_to_heirs: int = Field(
        default=0,
        ge=0,
        description="10년 이내 상속인에게 증여한 재산가액(원)",
    )
    prior_gifts_to_non_heirs: int = Field(
        default=0,
        ge=0,
        description="5년 이내 상속인이 아닌 자에게 증여한 재산가액(원)",
    )
    prior_gift_tax_base_included_in_taxable_value: int = Field(
        default=0,
        ge=0,
        description=(
            "상속세 과세가액에 가산된 사전증여재산의 " "증여세 과세표준 합계(원)"
        ),
    )
    # 5. 상속공제
    basic_or_lump_sum_deduction: int | None = Field(
        default=None,
        ge=0,
        description=(
            "기초·인적공제 또는 일괄공제 직접 적용액. " "입력하지 않으면 자동 계산(원)"
        ),
    )
    business_or_farming_deduction: int = Field(
        default=0,
        ge=0,
        description="가업·영농상속공제 적용액(원)",
    )
    spouse_inheritance_deduction: int | None = Field(
        default=None,
        ge=0,
        description=("배우자 상속공제 직접 적용액. " "입력하지 않으면 자동 계산(원)"),
    )
    financial_asset_deduction: int | None = Field(
        default=None,
        ge=0,
        description=("금융재산 상속공제 직접 적용액. " "입력하지 않으면 자동 계산(원)"),
    )
    disaster_loss_deduction: int = Field(
        default=0,
        ge=0,
        description="재해손실공제 적용액(원)",
    )
    cohabiting_home_deduction: int = Field(
        default=0,
        ge=0,
        description="동거주택 상속공제 적용액(원)",
    )

    # 6. 과세표준 계산
    appraisal_fees: int = Field(
        default=0,
        ge=0,
        description="공제 가능한 감정평가수수료(원)",
    )

    # 7. 산출세액 이후 조정
    generation_skipping_surcharge: int = Field(
        default=0,
        ge=0,
        description="세대생략 할증세액(원)",
    )
    tax_credits: int = Field(
        default=0,
        ge=0,
        description="신고세액공제를 제외한 그 밖의 세액공제 합계",
    )
    penalties: int = Field(
        default=0,
        ge=0,
        description="신고불성실·납부지연 가산세 합계(원)",
    )


class InheritanceTaxResult(BaseModel):
    """상속세 계산 과정과 예상 납부세액."""

    warnings: list[str] = Field(
        default_factory=list,
        description="계산 결과와 함께 표시할 주의사항",
    )
    filing_tax_credit: int = Field(
        default=0,
        ge=0,
        description="법정 신고기한 내 신고에 따른 신고세액공제",
    )
    total_inherited_property: int
    deductible_expenses: int
    prior_gifts: int
    taxable_inheritance_value: int

    total_inheritance_deduction: int
    appraisal_fees: int
    inheritance_tax_base: int

    tax_rate_percent: int
    progressive_deduction: int
    calculated_inheritance_tax: int

    generation_skipping_surcharge: int
    tax_credits: int
    penalties: int
    estimated_tax_due: int

    rule_version: str
    warnings: list[str] = Field(default_factory=list)
    estimated_filing_deadline: date | None = Field(
        default=None,
        description=(
            "주말을 반영한 예상 상속세 신고기한. " "공휴일은 별도 확인이 필요함"
        ),
    )


class BaseTaxResult(BaseModel):
    """과세표준에 세율을 적용한 산출세액 결과."""

    inheritance_tax_base: int
    tax_rate_percent: int
    progressive_deduction: int
    calculated_inheritance_tax: int
    rule_version: str

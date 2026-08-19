"""상속세 계산 엔진."""

from calendar import monthrange
from datetime import date, timedelta
from .models import (
    BaseTaxResult,
    InheritanceTaxInput,
    InheritanceTaxResult,
)
from .rules import (
    BASIC_DEDUCTION,
    FINANCIAL_DEDUCTION_CAP,
    FINANCIAL_DEDUCTION_FIXED_AMOUNT,
    FINANCIAL_DEDUCTION_FIXED_LIMIT,
    FINANCIAL_DEDUCTION_FULL_LIMIT,
    FINANCIAL_DEDUCTION_PERCENT_LIMIT,
    FINANCIAL_DEDUCTION_RATE_PERCENT,
    LUMP_SUM_DEDUCTION,
    RULE_VERSION,
    SPOUSE_DEDUCTION_CAP,
    SPOUSE_MINIMUM_DEDUCTION,
    TAX_BRACKETS,
    TaxBracket,
    BURIAL_FACILITY_EXPENSE_CAP,
    FUNERAL_EXPENSE_MAXIMUM,
    FUNERAL_EXPENSE_MINIMUM,
    FILING_TAX_CREDIT_RATE_PERCENT,
)


def calculate_filing_deadline(
    inheritance_commencement_date: date,
    non_business_days: set[date] | None = None,
) -> date:
    """거주자 상속세 신고기한을 계산한다."""

    target_month_index = inheritance_commencement_date.month - 1 + 6
    target_year = inheritance_commencement_date.year + target_month_index // 12
    target_month = target_month_index % 12 + 1

    last_day = monthrange(target_year, target_month)[1]
    deadline = date(target_year, target_month, last_day)

    closed_days = non_business_days or set()

    while deadline.weekday() >= 5 or deadline in closed_days:
        deadline += timedelta(days=1)

    return deadline


def calculate_total_inherited_property(
    data: InheritanceTaxInput,
) -> int:
    """본래·간주·추정상속재산을 합산한다."""

    return (
        data.original_inherited_property
        + data.deemed_inherited_property
        + data.estimated_inherited_property
    )


def calculate_funeral_expense_deduction(
    data: InheritanceTaxInput,
) -> int:
    """거주자의 장례비용 공제액을 계산한다."""

    if not data.decedent_is_resident:
        return 0

    direct_funeral_expenses = min(
        max(data.funeral_expenses, FUNERAL_EXPENSE_MINIMUM),
        FUNERAL_EXPENSE_MAXIMUM,
    )

    burial_facility_expenses = min(
        data.burial_facility_expenses,
        BURIAL_FACILITY_EXPENSE_CAP,
    )

    return direct_funeral_expenses + burial_facility_expenses


def calculate_deductible_expenses(
    data: InheritanceTaxInput,
    total_inherited_property: int,
) -> int:
    """공과금·장례비용·채무의 공제 합계를 계산한다."""

    funeral_expense_deduction = calculate_funeral_expense_deduction(data)

    requested_expenses = data.public_charges + funeral_expense_deduction + data.debts

    return min(requested_expenses, total_inherited_property)


def calculate_prior_gifts(data: InheritanceTaxInput) -> int:
    """상속세 과세가액에 합산할 사전증여재산을 계산한다."""

    return data.prior_gifts_to_heirs + data.prior_gifts_to_non_heirs


def calculate_taxable_inheritance_value(
    data: InheritanceTaxInput,
) -> int:
    """거주자의 상속세 과세가액을 계산한다."""

    if not data.decedent_is_resident:
        raise ValueError("현재 계산기는 피상속인이 거주자인 경우만 지원합니다.")

    total_inherited_property = calculate_total_inherited_property(data)

    deductible_expenses = calculate_deductible_expenses(
        data,
        total_inherited_property,
    )
    prior_gifts = calculate_prior_gifts(data)

    net_inherited_property = (
        total_inherited_property
        - data.non_taxable_property
        - data.excluded_property
        - deductible_expenses
    )
    net_inherited_property = max(0, net_inherited_property)

    return net_inherited_property + prior_gifts


def calculate_basic_or_lump_sum_deduction(
    data: InheritanceTaxInput,
) -> int:
    """기초공제 또는 일괄공제 적용액을 계산한다."""

    if data.basic_or_lump_sum_deduction is not None:
        return data.basic_or_lump_sum_deduction

    if data.spouse_is_sole_heir:
        if not data.spouse_exists:
            raise ValueError("배우자 단독상속을 적용하려면 배우자가 존재해야 합니다.")

        return BASIC_DEDUCTION

    return LUMP_SUM_DEDUCTION


def calculate_spouse_legal_share(
    data: InheritanceTaxInput,
) -> tuple[int, int]:
    """배우자 법정상속분을 분자와 분모로 반환한다."""

    if not data.spouse_exists:
        return (0, 1)

    if data.spouse_is_sole_heir:
        return (1, 1)

    if data.children_count > 0:
        numerator = 3
        denominator = 3 + 2 * data.children_count
        return (numerator, denominator)

    raise ValueError(
        "현재 배우자공제는 배우자·자녀 공동상속 또는 " "배우자 단독상속만 지원합니다."
    )


def calculate_spouse_deduction_limit(
    data: InheritanceTaxInput,
) -> int:
    """배우자의 법정상속분에 따른 공제한도를 계산한다."""

    numerator, denominator = calculate_spouse_legal_share(data)

    total_inherited_property = calculate_total_inherited_property(data)

    spouse_limit_base = (
        total_inherited_property
        - data.bequests_to_non_heirs
        + data.prior_gifts_to_heirs
        - data.non_taxable_property
        - data.excluded_property
        - data.public_charges
        - data.debts
    )
    spouse_limit_base = max(0, spouse_limit_base)

    legal_share_amount = spouse_limit_base * numerator // denominator

    deduction_limit = legal_share_amount - data.spouse_prior_gift_tax_base
    deduction_limit = max(0, deduction_limit)

    return min(deduction_limit, SPOUSE_DEDUCTION_CAP)


def calculate_financial_asset_deduction(
    data: InheritanceTaxInput,
) -> int:
    """순금융재산에 따른 금융재산 상속공제를 계산한다."""

    if data.financial_asset_deduction is not None:
        return data.financial_asset_deduction

    net_financial_assets = max(
        0,
        data.financial_assets - data.financial_debts,
    )

    if net_financial_assets <= FINANCIAL_DEDUCTION_FULL_LIMIT:
        return net_financial_assets

    if net_financial_assets <= FINANCIAL_DEDUCTION_FIXED_LIMIT:
        return FINANCIAL_DEDUCTION_FIXED_AMOUNT

    if net_financial_assets <= FINANCIAL_DEDUCTION_PERCENT_LIMIT:
        return net_financial_assets * FINANCIAL_DEDUCTION_RATE_PERCENT // 100

    return FINANCIAL_DEDUCTION_CAP


def calculate_spouse_inheritance_deduction(
    data: InheritanceTaxInput,
) -> int:
    """배우자 실제 상속액과 법정 한도로 공제액을 계산한다."""

    if data.spouse_inheritance_deduction is not None:
        return data.spouse_inheritance_deduction

    if not data.spouse_exists:
        return 0

    if data.spouse_actual_inheritance < SPOUSE_MINIMUM_DEDUCTION:
        return SPOUSE_MINIMUM_DEDUCTION

    deduction_limit = calculate_spouse_deduction_limit(data)

    return min(
        data.spouse_actual_inheritance,
        deduction_limit,
    )


def calculate_total_inheritance_deduction(
    data: InheritanceTaxInput,
    taxable_inheritance_value: int,
) -> int:
    """각종 상속공제액을 합산한다."""

    basic_or_lump_sum_deduction = calculate_basic_or_lump_sum_deduction(data)
    spouse_inheritance_deduction = calculate_spouse_inheritance_deduction(data)
    financial_asset_deduction = calculate_financial_asset_deduction(data)

    requested_deduction = (
        basic_or_lump_sum_deduction
        + data.business_or_farming_deduction
        + spouse_inheritance_deduction
        + financial_asset_deduction
        + data.disaster_loss_deduction
        + data.cohabiting_home_deduction
    )

    return min(requested_deduction, taxable_inheritance_value)


def build_calculation_warnings(
    data: InheritanceTaxInput,
) -> list[str]:
    """입력값과 현재 지원 범위에 따른 주의사항을 만든다."""

    warnings = [
        ("이 결과는 입력한 금액을 기준으로 계산한 " "참고용 시뮬레이션입니다."),
        ("실제 신고 전에는 홈택스 계산 결과 또는 " "세무 전문가의 확인이 필요합니다."),
    ]

    if data.inheritance_commencement_date is None:
        warnings.append("상속개시일이 없어 신고기한을 계산하지 않았습니다.")

    if data.filing_within_deadline and data.inheritance_commencement_date is None:
        warnings.append(
            ("기한 내 신고 여부는 사용자가 입력한 값을 " "그대로 사용했습니다.")
        )

    special_deductions = (
        data.business_or_farming_deduction
        + data.disaster_loss_deduction
        + data.cohabiting_home_deduction
    )

    if special_deductions > 0:
        warnings.append(
            (
                "가업·영농·재해·동거주택 공제는 입력 금액을 "
                "반영했으며 법적 요건은 판단하지 않았습니다."
            )
        )

    if data.tax_credits > 0:
        warnings.append(
            (
                "그 밖의 세액공제는 입력 금액을 반영했으며 "
                "공제 자격과 증빙은 확인하지 않았습니다."
            )
        )

    return warnings


def calculate_inheritance_tax_base(
    data: InheritanceTaxInput,
) -> int:
    """상속세 과세가액에서 공제액을 차감해 과세표준을 계산한다."""

    taxable_inheritance_value = calculate_taxable_inheritance_value(data)

    total_inheritance_deduction = calculate_total_inheritance_deduction(
        data,
        taxable_inheritance_value,
    )

    inheritance_tax_base = (
        taxable_inheritance_value - total_inheritance_deduction - data.appraisal_fees
    )

    return max(0, inheritance_tax_base)


def select_tax_bracket(tax_base: int) -> TaxBracket:
    """과세표준에 적용할 세율 구간을 찾는다."""

    if tax_base < 0:
        raise ValueError("상속세 과세표준은 0원 이상이어야 합니다.")

    for bracket in TAX_BRACKETS:
        if bracket.upper_limit is None:
            return bracket

        if tax_base <= bracket.upper_limit:
            return bracket

    raise RuntimeError("상속세율 구간을 찾을 수 없습니다.")


def calculate_filing_tax_credit(
    calculated_inheritance_tax: int,
    generation_skipping_surcharge: int,
    other_tax_credits: int,
    filing_within_deadline: bool,
) -> int:
    """법정 신고기한 내 신고에 따른 신고세액공제를 계산한다."""

    amounts = (
        calculated_inheritance_tax,
        generation_skipping_surcharge,
        other_tax_credits,
    )

    if any(amount < 0 for amount in amounts):
        raise ValueError("신고세액공제 계산 금액은 0원 이상이어야 합니다.")

    if not filing_within_deadline:
        return 0

    credit_base = max(
        0,
        calculated_inheritance_tax + generation_skipping_surcharge - other_tax_credits,
    )

    return credit_base * FILING_TAX_CREDIT_RATE_PERCENT // 100


def calculate_base_tax(tax_base: int) -> BaseTaxResult:
    """과세표준에 세율과 누진공제를 적용한다."""

    bracket = select_tax_bracket(tax_base)

    calculated_tax = (
        tax_base * bracket.rate_percent // 100 - bracket.progressive_deduction
    )
    calculated_tax = max(0, calculated_tax)

    return BaseTaxResult(
        inheritance_tax_base=tax_base,
        tax_rate_percent=bracket.rate_percent,
        progressive_deduction=bracket.progressive_deduction,
        calculated_inheritance_tax=calculated_tax,
        rule_version=RULE_VERSION,
    )


def calculate_inheritance_tax(
    data: InheritanceTaxInput,
) -> InheritanceTaxResult:
    """입력값을 이용해 상속세 예상 납부세액을 계산한다."""

    total_inherited_property = calculate_total_inherited_property(data)

    deductible_expenses = calculate_deductible_expenses(
        data,
        total_inherited_property,
    )
    prior_gifts = calculate_prior_gifts(data)

    taxable_inheritance_value = calculate_taxable_inheritance_value(data)

    total_inheritance_deduction = calculate_total_inheritance_deduction(
        data,
        taxable_inheritance_value,
    )

    inheritance_tax_base = calculate_inheritance_tax_base(data)
    base_tax_result = calculate_base_tax(inheritance_tax_base)
    filing_tax_credit = calculate_filing_tax_credit(
        calculated_inheritance_tax=(base_tax_result.calculated_inheritance_tax),
        generation_skipping_surcharge=(data.generation_skipping_surcharge),
        other_tax_credits=data.tax_credits,
        filing_within_deadline=data.filing_within_deadline,
    )
    estimated_tax_due = max(
        0,
        base_tax_result.calculated_inheritance_tax
        + data.generation_skipping_surcharge
        - data.tax_credits
        - filing_tax_credit
        + data.penalties,
    )
    estimated_tax_due = max(0, estimated_tax_due)

    warnings = [
        (
            "현재 결과는 피상속인이 거주자인 일반 사례를 "
            "전제로 한 참고용 예상세액입니다."
        ),
        (
            "상속공제액·세액공제·할증세액·가산세는 입력된 "
            "금액을 사용하며 적용 요건을 자동 판정하지 않습니다."
        ),
    ]
    estimated_filing_deadline = None
    warnings = build_calculation_warnings(data)
    if data.inheritance_commencement_date is not None:
        estimated_filing_deadline = calculate_filing_deadline(
            data.inheritance_commencement_date
        )
        estimated_filing_deadline = None

    if data.inheritance_commencement_date is not None:
        estimated_filing_deadline = calculate_filing_deadline(
            data.inheritance_commencement_date
        )
    return InheritanceTaxResult(
        total_inherited_property=total_inherited_property,
        deductible_expenses=deductible_expenses,
        prior_gifts=prior_gifts,
        taxable_inheritance_value=taxable_inheritance_value,
        total_inheritance_deduction=total_inheritance_deduction,
        appraisal_fees=data.appraisal_fees,
        inheritance_tax_base=inheritance_tax_base,
        tax_rate_percent=base_tax_result.tax_rate_percent,
        progressive_deduction=(base_tax_result.progressive_deduction),
        calculated_inheritance_tax=(base_tax_result.calculated_inheritance_tax),
        generation_skipping_surcharge=(data.generation_skipping_surcharge),
        tax_credits=data.tax_credits,
        penalties=data.penalties,
        estimated_tax_due=estimated_tax_due,
        rule_version=RULE_VERSION,
        warnings=warnings,
        estimated_filing_deadline=estimated_filing_deadline,
        filing_tax_credit=filing_tax_credit,
    )

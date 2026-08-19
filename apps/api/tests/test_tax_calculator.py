"""상속세 계산 엔진 테스트."""

from datetime import date
import pytest

from agents.tax_calculator.calculator import (
    calculate_base_tax,
    calculate_basic_or_lump_sum_deduction,
    calculate_financial_asset_deduction,
    calculate_inheritance_tax,
    calculate_inheritance_tax_base,
    calculate_taxable_inheritance_value,
    calculate_total_inheritance_deduction,
    calculate_total_inherited_property,
    calculate_spouse_inheritance_deduction,
    calculate_funeral_expense_deduction,
    calculate_filing_deadline,
    calculate_filing_tax_credit,
    build_calculation_warnings,
)
from agents.tax_calculator.models import InheritanceTaxInput


@pytest.mark.parametrize(
    (
        "tax_base",
        "expected_rate",
        "expected_deduction",
        "expected_tax",
    ),
    [
        (0, 10, 0, 0),
        (100_000_000, 10, 0, 10_000_000),
        (300_000_000, 20, 10_000_000, 50_000_000),
        (500_000_000, 20, 10_000_000, 90_000_000),
        (1_000_000_000, 30, 60_000_000, 240_000_000),
        (3_000_000_000, 40, 160_000_000, 1_040_000_000),
        (4_000_000_000, 50, 460_000_000, 1_540_000_000),
    ],
)
def test_calculate_base_tax(
    tax_base: int,
    expected_rate: int,
    expected_deduction: int,
    expected_tax: int,
) -> None:
    result = calculate_base_tax(tax_base)

    assert result.inheritance_tax_base == tax_base
    assert result.tax_rate_percent == expected_rate
    assert result.progressive_deduction == expected_deduction
    assert result.calculated_inheritance_tax == expected_tax


def test_calculate_base_tax_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="0원 이상"):
        calculate_base_tax(-1)


def test_calculate_total_inherited_property() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=1_000_000_000,
        deemed_inherited_property=50_000_000,
        estimated_inherited_property=20_000_000,
    )

    result = calculate_total_inherited_property(data)

    assert result == 1_070_000_000


def test_calculate_taxable_inheritance_value() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=1_000_000_000,
        deemed_inherited_property=50_000_000,
        estimated_inherited_property=20_000_000,
        non_taxable_property=20_000_000,
        excluded_property=30_000_000,
        public_charges=10_000_000,
        funeral_expenses=5_000_000,
        debts=100_000_000,
        prior_gifts_to_heirs=50_000_000,
        prior_gifts_to_non_heirs=10_000_000,
    )

    result = calculate_taxable_inheritance_value(data)

    assert result == 965_000_000


def test_taxable_inheritance_value_rejects_non_resident() -> None:
    data = InheritanceTaxInput(
        decedent_is_resident=False,
        original_inherited_property=500_000_000,
    )

    with pytest.raises(ValueError, match="거주자인 경우만"):
        calculate_taxable_inheritance_value(data)


def test_calculate_inheritance_tax_base() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=1_500_000_000,
        debts=100_000_000,
        basic_or_lump_sum_deduction=500_000_000,
        spouse_inheritance_deduction=500_000_000,
        financial_asset_deduction=20_000_000,
        appraisal_fees=5_000_000,
    )

    taxable_inheritance_value = calculate_taxable_inheritance_value(data)
    total_deduction = calculate_total_inheritance_deduction(
        data,
        taxable_inheritance_value,
    )
    tax_base = calculate_inheritance_tax_base(data)

    assert taxable_inheritance_value == 1_395_000_000
    assert total_deduction == 1_020_000_000
    assert tax_base == 370_000_000


def test_inheritance_deduction_does_not_exceed_taxable_value() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=400_000_000,
        basic_or_lump_sum_deduction=500_000_000,
    )

    taxable_inheritance_value = calculate_taxable_inheritance_value(data)
    total_deduction = calculate_total_inheritance_deduction(
        data,
        taxable_inheritance_value,
    )
    tax_base = calculate_inheritance_tax_base(data)

    assert taxable_inheritance_value == 395_000_000
    assert total_deduction == 395_000_000
    assert tax_base == 0


def test_calculate_inheritance_tax_full_flow() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=1_500_000_000,
        debts=100_000_000,
        basic_or_lump_sum_deduction=500_000_000,
        spouse_inheritance_deduction=500_000_000,
        financial_asset_deduction=20_000_000,
        appraisal_fees=5_000_000,
        generation_skipping_surcharge=1_000_000,
        tax_credits=2_000_000,
        penalties=500_000,
    )

    result = calculate_inheritance_tax(data)

    assert result.total_inherited_property == 1_500_000_000
    assert result.deductible_expenses == 105_000_000
    assert result.taxable_inheritance_value == 1_395_000_000
    assert result.total_inheritance_deduction == 1_020_000_000
    assert result.inheritance_tax_base == 370_000_000

    assert result.tax_rate_percent == 20
    assert result.progressive_deduction == 10_000_000
    assert result.calculated_inheritance_tax == 64_000_000

    assert result.generation_skipping_surcharge == 1_000_000
    assert result.tax_credits == 2_000_000
    assert result.penalties == 500_000
    assert result.estimated_tax_due == 63_500_000


def test_estimated_tax_due_does_not_become_negative() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=600_000_000,
        basic_or_lump_sum_deduction=500_000_000,
        tax_credits=20_000_000,
    )

    result = calculate_inheritance_tax(data)

    assert result.inheritance_tax_base == 95_000_000
    assert result.calculated_inheritance_tax == 9_500_000
    assert result.estimated_tax_due == 0


def test_lump_sum_deduction_is_applied_automatically() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=800_000_000,
        children_count=2,
    )

    deduction = calculate_basic_or_lump_sum_deduction(data)
    tax_base = calculate_inheritance_tax_base(data)

    assert deduction == 500_000_000
    assert tax_base == 295_000_000


def test_spouse_sole_heir_uses_basic_deduction() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=800_000_000,
        spouse_exists=True,
        spouse_is_sole_heir=True,
    )

    deduction = calculate_basic_or_lump_sum_deduction(data)

    assert deduction == 200_000_000


@pytest.mark.parametrize(
    (
        "financial_assets",
        "financial_debts",
        "expected_deduction",
    ),
    [
        (0, 0, 0),
        (10_000_000, 0, 10_000_000),
        (50_000_000, 0, 20_000_000),
        (500_000_000, 0, 100_000_000),
        (2_000_000_000, 0, 200_000_000),
        (100_000_000, 40_000_000, 20_000_000),
    ],
)
def test_calculate_financial_asset_deduction(
    financial_assets: int,
    financial_debts: int,
    expected_deduction: int,
) -> None:
    data = InheritanceTaxInput(
        financial_assets=financial_assets,
        financial_debts=financial_debts,
    )

    result = calculate_financial_asset_deduction(data)

    assert result == expected_deduction


def test_spouse_deduction_is_zero_without_spouse() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=1_000_000_000,
    )

    result = calculate_spouse_inheritance_deduction(data)

    assert result == 0


def test_spouse_minimum_deduction() -> None:
    data = InheritanceTaxInput(
        spouse_exists=True,
        children_count=2,
        original_inherited_property=1_000_000_000,
        spouse_actual_inheritance=100_000_000,
    )

    result = calculate_spouse_inheritance_deduction(data)

    assert result == 500_000_000


def test_spouse_deduction_uses_legal_share_limit() -> None:
    data = InheritanceTaxInput(
        spouse_exists=True,
        children_count=2,
        original_inherited_property=2_800_000_000,
        spouse_actual_inheritance=1_500_000_000,
    )

    result = calculate_spouse_inheritance_deduction(data)

    assert result == 1_200_000_000


def test_spouse_deduction_is_capped_at_three_billion() -> None:
    data = InheritanceTaxInput(
        spouse_exists=True,
        spouse_is_sole_heir=True,
        original_inherited_property=5_000_000_000,
        spouse_actual_inheritance=4_000_000_000,
    )

    result = calculate_spouse_inheritance_deduction(data)

    assert result == 3_000_000_000


@pytest.mark.parametrize(
    (
        "funeral_expenses",
        "burial_facility_expenses",
        "expected_deduction",
    ),
    [
        (0, 0, 5_000_000),
        (3_000_000, 0, 5_000_000),
        (7_000_000, 0, 7_000_000),
        (15_000_000, 0, 10_000_000),
        (7_000_000, 3_000_000, 10_000_000),
        (15_000_000, 7_000_000, 15_000_000),
    ],
)
def test_calculate_funeral_expense_deduction(
    funeral_expenses: int,
    burial_facility_expenses: int,
    expected_deduction: int,
) -> None:
    data = InheritanceTaxInput(
        funeral_expenses=funeral_expenses,
        burial_facility_expenses=burial_facility_expenses,
    )

    result = calculate_funeral_expense_deduction(data)

    assert result == expected_deduction


def test_non_resident_cannot_use_funeral_expense_deduction() -> None:
    data = InheritanceTaxInput(
        decedent_is_resident=False,
        funeral_expenses=10_000_000,
        burial_facility_expenses=5_000_000,
    )

    result = calculate_funeral_expense_deduction(data)

    assert result == 0


def test_calculate_filing_deadline() -> None:
    deadline = calculate_filing_deadline(
        date(2021, 3, 10),
    )

    assert deadline == date(2021, 9, 30)


def test_filing_deadline_moves_past_weekend() -> None:
    deadline = calculate_filing_deadline(
        date(2021, 1, 10),
    )

    assert deadline == date(2021, 8, 2)


def test_filing_deadline_moves_past_supplied_holiday() -> None:
    deadline = calculate_filing_deadline(
        date(2021, 3, 10),
        non_business_days={date(2021, 9, 30)},
    )

    assert deadline == date(2021, 10, 1)


def test_inheritance_tax_result_includes_filing_deadline() -> None:
    data = InheritanceTaxInput(
        inheritance_commencement_date=date(2021, 3, 10),
        original_inherited_property=600_000_000,
    )

    result = calculate_inheritance_tax(data)

    assert result.estimated_filing_deadline == date(
        2021,
        9,
        30,
    )


def test_calculate_filing_tax_credit() -> None:
    credit = calculate_filing_tax_credit(
        calculated_inheritance_tax=100_000_000,
        generation_skipping_surcharge=10_000_000,
        other_tax_credits=10_000_000,
        filing_within_deadline=True,
    )

    assert credit == 3_000_000


def test_filing_tax_credit_is_zero_when_filed_late() -> None:
    credit = calculate_filing_tax_credit(
        calculated_inheritance_tax=100_000_000,
        generation_skipping_surcharge=0,
        other_tax_credits=0,
        filing_within_deadline=False,
    )

    assert credit == 0


def test_filing_tax_credit_base_does_not_go_below_zero() -> None:
    credit = calculate_filing_tax_credit(
        calculated_inheritance_tax=10_000_000,
        generation_skipping_surcharge=0,
        other_tax_credits=20_000_000,
        filing_within_deadline=True,
    )

    assert credit == 0


def test_inheritance_tax_applies_filing_tax_credit() -> None:
    data = InheritanceTaxInput(
        original_inherited_property=1_000_000_000,
        filing_within_deadline=True,
    )

    result = calculate_inheritance_tax(data)

    assert result.calculated_inheritance_tax == 89_000_000
    assert result.filing_tax_credit == 2_670_000
    assert result.estimated_tax_due == 86_330_000


def test_calculation_warnings_include_general_notice() -> None:
    data = InheritanceTaxInput()

    warnings = build_calculation_warnings(data)

    assert any("참고용" in warning for warning in warnings)


def test_calculation_warnings_include_missing_date() -> None:
    data = InheritanceTaxInput(
        filing_within_deadline=True,
    )

    warnings = build_calculation_warnings(data)

    assert any("상속개시일이 없어" in warning for warning in warnings)
    assert any("사용자가 입력한 값" in warning for warning in warnings)


def test_calculation_warnings_include_special_deduction() -> None:
    data = InheritanceTaxInput(
        cohabiting_home_deduction=100_000_000,
    )

    warnings = build_calculation_warnings(data)

    assert any("법적 요건은 판단하지 않았습니다" in warning for warning in warnings)


def test_non_heir_bequest_reduces_inheritance_deduction_limit() -> None:
    """비상속인 유증액을 상속공제 종합한도에서 차감한다."""

    data = InheritanceTaxInput(
        original_inherited_property=1_000_000_000,
        bequests_to_non_heirs=800_000_000,
        filing_within_deadline=True,
    )

    result = calculate_inheritance_tax(data)

    assert result.taxable_inheritance_value == 995_000_000
    assert result.total_inheritance_deduction == 195_000_000
    assert result.inheritance_tax_base == 800_000_000
    assert result.calculated_inheritance_tax == 180_000_000
    assert result.filing_tax_credit == 5_400_000
    assert result.estimated_tax_due == 174_600_000


def test_next_rank_inheritance_reduces_deduction_limit() -> None:
    """상속포기로 후순위 상속인이 받은 재산을 종합한도에서 차감한다."""

    data = InheritanceTaxInput(
        original_inherited_property=1_000_000_000,
        next_rank_inheritance_due_to_renunciation=800_000_000,
        filing_within_deadline=True,
    )

    result = calculate_inheritance_tax(data)

    assert result.taxable_inheritance_value == 995_000_000
    assert result.total_inheritance_deduction == 195_000_000
    assert result.inheritance_tax_base == 800_000_000
    assert result.estimated_tax_due == 174_600_000


def test_prior_gift_tax_base_reduces_deduction_limit() -> None:
    """과세가액에 포함된 사전증여 과세표준을 종합한도에서 차감한다."""

    data = InheritanceTaxInput(
        original_inherited_property=100_000_000,
        prior_gifts_to_heirs=800_000_000,
        prior_gift_tax_base_included_in_taxable_value=800_000_000,
        filing_within_deadline=True,
    )

    result = calculate_inheritance_tax(data)

    assert result.taxable_inheritance_value == 895_000_000
    assert result.total_inheritance_deduction == 95_000_000
    assert result.inheritance_tax_base == 800_000_000
    assert result.estimated_tax_due == 174_600_000

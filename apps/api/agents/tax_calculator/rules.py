"""대한민국 상속세 계산에 사용하는 세율 규칙."""

from dataclasses import dataclass
from datetime import date
from typing import Final


RULE_VERSION: Final = "kr-inheritance-tax-2026-08-20"
RULE_AS_OF_DATE: Final = date(2026, 8, 20)
RULE_SOURCE_URLS: Final[tuple[str, ...]] = (
    "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do" "?cntntsId=7720&mi=2326",
    "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do" "?cntntsId=7959&mi=6531",
    "https://mob.tbht.hometax.go.kr/jsonAction.do" "?actionId=UTBRNAAM02F001",
)

BASIC_DEDUCTION: Final = 200_000_000
LUMP_SUM_DEDUCTION: Final = 500_000_000
FINANCIAL_DEDUCTION_FULL_LIMIT: Final = 20_000_000
FINANCIAL_DEDUCTION_FIXED_LIMIT: Final = 100_000_000
FINANCIAL_DEDUCTION_FIXED_AMOUNT: Final = 20_000_000
FINANCIAL_DEDUCTION_PERCENT_LIMIT: Final = 1_000_000_000
FINANCIAL_DEDUCTION_RATE_PERCENT: Final = 20
FINANCIAL_DEDUCTION_CAP: Final = 200_000_000
SPOUSE_MINIMUM_DEDUCTION: Final = 500_000_000
SPOUSE_DEDUCTION_CAP: Final = 3_000_000_000
FUNERAL_EXPENSE_MINIMUM: Final = 5_000_000
FUNERAL_EXPENSE_MAXIMUM: Final = 10_000_000
BURIAL_FACILITY_EXPENSE_CAP: Final = 5_000_000
FILING_TAX_CREDIT_RATE_PERCENT = 3


@dataclass(frozen=True)
class TaxBracket:
    """상속세 과세표준 구간별 세율 규칙."""

    upper_limit: int | None
    rate_percent: int
    progressive_deduction: int


TAX_BRACKETS: Final[tuple[TaxBracket, ...]] = (
    TaxBracket(
        upper_limit=100_000_000,
        rate_percent=10,
        progressive_deduction=0,
    ),
    TaxBracket(
        upper_limit=500_000_000,
        rate_percent=20,
        progressive_deduction=10_000_000,
    ),
    TaxBracket(
        upper_limit=1_000_000_000,
        rate_percent=30,
        progressive_deduction=60_000_000,
    ),
    TaxBracket(
        upper_limit=3_000_000_000,
        rate_percent=40,
        progressive_deduction=160_000_000,
    ),
    TaxBracket(
        upper_limit=None,
        rate_percent=50,
        progressive_deduction=460_000_000,
    ),
)

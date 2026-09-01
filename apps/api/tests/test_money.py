"""상속세·유류분 에이전트가 공유하는 금액 파서 회귀 테스트."""

import pytest

from agents._money import parse_money
from agents.heir_share_analyzer.agent import _parse_money as parse_heir_share_money
from agents.tax_calculator.agent import _parse_money as parse_tax_money


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("3억 5천만원", 350_000_000),
        ("3억5천만원", 350_000_000),
        ("3억5천", 350_000_000),
        ("3,200만원", 32_000_000),
        ("500000000원", 500_000_000),
    ],
)
def test_demo_money_expressions(expression: str, expected: int) -> None:
    assert parse_money(expression) == expected


@pytest.mark.parametrize(
    "parser",
    [parse_tax_money, parse_heir_share_money],
)
def test_both_agents_use_the_shared_parser(parser) -> None:
    assert parser("3억 5천만원") == 350_000_000
    assert parser("3억5천") == 350_000_000
    assert parser("3,200만원") == 32_000_000


@pytest.mark.parametrize(
    "expression",
    ["3억원abc", "3억5천만원추정", "1억2억", "만원만원", ""],
)
def test_invalid_expression_is_not_partially_parsed(expression: str) -> None:
    assert parse_money(expression) is None


def test_explicit_won_suffix_keeps_literal_tail() -> None:
    assert parse_money("3억5천원") == 300_005_000

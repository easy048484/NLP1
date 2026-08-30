from __future__ import annotations

import pytest

from agents.retirement_planner.format_utils import format_krw


@pytest.mark.parametrize(
    "amount, expected",
    [
        (0, "0원"),
        (5_000, "5,000원"),
        (30_000_000, "3,000만원"),
        (250_000_000, "2억 5,000만원"),
        (1_020_000_000, "10억 2,000만원"),
        (100_003_000, "1억"),
        (-30_000_000, "-3,000만원"),
    ],
)
def test_format_krw(amount, expected):
    assert format_krw(amount) == expected

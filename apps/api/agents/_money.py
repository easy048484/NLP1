"""대화형 에이전트가 공유하는 한국어 금액 파서.

세금·유류분 계산에 전달되는 금액은 일부 문자열만 잘라 읽지 않고, 입력 전체가
지원하는 형식일 때만 원 단위 정수로 변환한다.
"""

from __future__ import annotations

import re
from decimal import Decimal


def _parse_small_korean_amount(text: str) -> Decimal | None:
    """큰 단위 사이의 숫자와 천·백·십 조합을 계산한다."""

    if not text:
        return Decimal("1")

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return Decimal(text)

    small_units = {
        "천": Decimal("1000"),
        "백": Decimal("100"),
        "십": Decimal("10"),
    }
    total = Decimal("0")
    position = 0

    for match in re.finditer(r"(\d+(?:\.\d+)?)?(천|백|십)", text):
        if match.start() != position:
            return None
        total += Decimal(match.group(1) or "1") * small_units[match.group(2)]
        position = match.end()

    tail = text[position:]
    if tail:
        if re.fullmatch(r"\d+(?:\.\d+)?", tail) is None:
            return None
        total += Decimal(tail)

    return total


def parse_money(message: str) -> int | None:
    """한국어 금액 표현을 원 단위 정수로 변환한다.

    지원 예: ``3억 5천만원``, ``3억5천``, ``3,200만원``,
    ``500000000원``. 인식하지 못한 문자가 있거나 큰 단위 순서가 틀리면
    일부 값만 추측하지 않고 ``None``을 반환한다.
    """

    normalized = message.strip().replace(",", "").replace(" ", "")

    if "없" in normalized:
        return 0
    if re.fullmatch(r"0+원?", normalized):
        return 0

    has_won_suffix = normalized.endswith("원")
    amount_text = normalized.removesuffix("원")

    if re.fullmatch(r"\d+", amount_text):
        return int(amount_text)
    if re.fullmatch(r"[0-9.조억만천백십]+", amount_text) is None:
        return None

    big_units = {
        "조": 1_000_000_000_000,
        "억": 100_000_000,
        "만": 10_000,
    }
    total = Decimal("0")
    position = 0
    previous_multiplier: int | None = None

    for match in re.finditer(r"[조억만]", amount_text):
        multiplier = big_units[match.group()]
        if previous_multiplier is not None and multiplier >= previous_multiplier:
            return None

        section = amount_text[position : match.start()]
        if not section and position != 0:
            return None

        section_value = _parse_small_korean_amount(section)
        if section_value is None:
            return None

        total += section_value * multiplier
        position = match.end()
        previous_multiplier = multiplier

    tail = amount_text[position:]
    if tail:
        tail_value = _parse_small_korean_amount(tail)
        if tail_value is None:
            return None

        # 금융 대화의 "3억5천"은 통상 "3억 5천만원"의 축약이다. 다만
        # "3억5천원"처럼 원 단위를 명시하면 문자 그대로 5천원으로 읽는다.
        is_omitted_manwon = (
            not has_won_suffix
            and previous_multiplier is not None
            and previous_multiplier >= big_units["억"]
            and re.search(r"[천백십]", tail) is not None
        )
        total += tail_value * (big_units["만"] if is_omitted_manwon else 1)

    return int(total)


__all__ = ["parse_money"]

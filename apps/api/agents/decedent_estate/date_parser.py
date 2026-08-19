"""
연월일 파서 (규칙 기반, LLM 미사용).

유언장 텍스트에서 날짜 표기를 찾아 rules/requirements.json 의 "date" 요건
조건 id(all_present / day_missing / verbal_specified / multiple_dates_mixed /
absent)와 1:1로 매핑되는 케이스를 판별한다.

지원 표기: "2026년 5월 3일" / "2026. 5. 3." / "2026-05-03" /
"이천이십육년 오월 삼일"(한글 숫자) 및 각 형식의 연월만 표기(일 누락) 버전.

⚠️ 이 모듈은 텍스트에서 값을 "추출"만 한다. 등급 판정은 requirement_checker.py
가 rules/requirements.json 을 참조해서 수행한다 (CLAUDE.md 절대 원칙 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

_KOREAN_DIGITS = {
    "영": 0,
    "일": 1,
    "이": 2,
    "삼": 3,
    "사": 4,
    "오": 5,
    "육": 6,
    "륙": 6,
    "칠": 7,
    "팔": 8,
    "구": 9,
}
_KOREAN_PLACES = {"십": 10, "백": 100, "천": 1000}
_KOREAN_NUM_CHARS = "".join(sorted(set(_KOREAN_DIGITS) | set(_KOREAN_PLACES)))
_KOREAN_NUM_FRAGMENT = f"[{_KOREAN_NUM_CHARS}]+"
_KOREAN_MONTH_FRAGMENT = f"(?:유|시|{_KOREAN_NUM_FRAGMENT})"


def _sino_korean_to_int(s: str) -> Optional[int]:
    """0~9999 범위 한글 숫자(예: '이천이십육')를 정수로 변환한다. 만 단위는 미지원."""
    total = 0
    current = 0
    for ch in s:
        if ch in _KOREAN_DIGITS:
            current = _KOREAN_DIGITS[ch]
        elif ch in _KOREAN_PLACES:
            total += (current or 1) * _KOREAN_PLACES[ch]
            current = 0
        else:
            return None
    total += current
    return total or None


def _korean_month_to_int(s: str) -> Optional[int]:
    if s == "유":  # 유월 = 6월
        return 6
    if s == "시":  # 시월 = 10월
        return 10
    return _sino_korean_to_int(s)


def _num(g: str) -> int:
    return int(g)


@dataclass(frozen=True)
class ParsedDate:
    year: Optional[int]
    month: Optional[int]
    day: Optional[int]
    raw_text: str
    case: str  # rules/requirements.json 의 date.conditions[].id 와 동일


@dataclass(frozen=True)
class DateParseResult:
    entries: list[ParsedDate]
    case: str  # 요건 판정에 쓰이는 최종(집계) 케이스


_Extractor = Callable[[re.Match[str]], tuple]

# 년-월-일 모두 있는 표기들. 우선순위 없이 전부 시도하고 겹치지 않게 마스킹한다.
_FULL_DATE_PATTERNS: list[tuple[re.Pattern[str], _Extractor]] = [
    (
        re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
        lambda m: (_num(m.group(1)), _num(m.group(2)), _num(m.group(3))),
    ),
    (
        re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?"),
        lambda m: (_num(m.group(1)), _num(m.group(2)), _num(m.group(3))),
    ),
    (
        re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
        lambda m: (_num(m.group(1)), _num(m.group(2)), _num(m.group(3))),
    ),
    (
        re.compile(
            rf"({_KOREAN_NUM_FRAGMENT})년\s*({_KOREAN_MONTH_FRAGMENT})월\s*({_KOREAN_NUM_FRAGMENT})일"
        ),
        lambda m: (
            _sino_korean_to_int(m.group(1)),
            _korean_month_to_int(m.group(2)),
            _sino_korean_to_int(m.group(3)),
        ),
    ),
]

# 년-월만 있는 표기들(일 누락). 위 FULL 매칭으로 이미 마스킹된 나머지 텍스트에서 찾는다.
_YEAR_MONTH_ONLY_PATTERNS: list[tuple[re.Pattern[str], _Extractor]] = [
    (
        re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월"),
        lambda m: (_num(m.group(1)), _num(m.group(2))),
    ),
    (
        re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.?"),
        lambda m: (_num(m.group(1)), _num(m.group(2))),
    ),
    (
        re.compile(r"(\d{4})-(\d{1,2})"),
        lambda m: (_num(m.group(1)), _num(m.group(2))),
    ),
    (
        re.compile(rf"({_KOREAN_NUM_FRAGMENT})년\s*({_KOREAN_MONTH_FRAGMENT})월"),
        lambda m: (_sino_korean_to_int(m.group(1)), _korean_month_to_int(m.group(2))),
    ),
]

# "말로 특정" 케이스: 특정 가능한 기념일·행사 표현 + 시점을 나타내는 "에"
_VERBAL_DATE_RE = re.compile(
    r"(?:칠순|팔순|구순|백수|환갑|회갑|고희|미수|백일|돌)\s*(?:잔치|기념일)?\s*에"
)


def _mask(text: str, matched: str) -> str:
    return text.replace(matched, " " * len(matched), 1)


def parse_dates(text: str) -> DateParseResult:
    entries: list[ParsedDate] = []
    remaining = text

    for pattern, extract in _FULL_DATE_PATTERNS:
        for m in pattern.finditer(text):
            year, month, day = extract(m)
            if year is None or month is None or day is None:
                continue
            entries.append(
                ParsedDate(
                    year=year,
                    month=month,
                    day=day,
                    raw_text=m.group(),
                    case="all_present",
                )
            )
            remaining = _mask(remaining, m.group())

    for pattern, extract in _YEAR_MONTH_ONLY_PATTERNS:
        for m in pattern.finditer(remaining):
            year, month = extract(m)
            if year is None or month is None:
                continue
            entries.append(
                ParsedDate(
                    year=year,
                    month=month,
                    day=None,
                    raw_text=m.group(),
                    case="day_missing",
                )
            )
            remaining = _mask(remaining, m.group())

    for m in _VERBAL_DATE_RE.finditer(remaining):
        entries.append(
            ParsedDate(
                year=None,
                month=None,
                day=None,
                raw_text=m.group(),
                case="verbal_specified",
            )
        )
        remaining = _mask(remaining, m.group())

    if not entries:
        overall_case = "absent"
    elif len(entries) == 1:
        overall_case = entries[0].case
    else:
        overall_case = "multiple_dates_mixed"

    return DateParseResult(entries=entries, case=overall_case)

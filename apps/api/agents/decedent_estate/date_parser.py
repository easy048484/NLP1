"""
연월일 파서 (규칙 기반, LLM 미사용).

유언장 텍스트에서 날짜 표기를 찾아 rules/requirements.json 의 "date" 요건
조건 id(all_present / day_missing / verbal_specified / multiple_dates_mixed /
absent)와 1:1로 매핑되는 케이스를 판별한다.

⚠️ 이 모듈은 텍스트에서 값을 "추출"만 한다. 등급 판정은 requirement_checker.py
가 rules/requirements.json 을 참조해서 수행한다 (CLAUDE.md 절대 원칙 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_FULL_DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_YEAR_MONTH_ONLY_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월")

# "말로 특정" 케이스: 특정 가능한 기념일·행사 표현 + 시점을 나타내는 "에"
_VERBAL_DATE_RE = re.compile(
    r"(?:칠순|팔순|구순|백수|환갑|회갑|고희|미수|백일|돌)\s*(?:잔치|기념일)?\s*에"
)


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


def _mask(text: str, matched: str) -> str:
    return text.replace(matched, " " * len(matched), 1)


def parse_dates(text: str) -> DateParseResult:
    entries: list[ParsedDate] = []
    remaining = text

    for m in _FULL_DATE_RE.finditer(text):
        year, month, day = (int(g) for g in m.groups())
        entries.append(
            ParsedDate(year=year, month=month, day=day, raw_text=m.group(), case="all_present")
        )
        remaining = _mask(remaining, m.group())

    for m in _YEAR_MONTH_ONLY_RE.finditer(remaining):
        year, month = (int(g) for g in m.groups())
        entries.append(
            ParsedDate(year=year, month=month, day=None, raw_text=m.group(), case="day_missing")
        )
        remaining = _mask(remaining, m.group())

    for m in _VERBAL_DATE_RE.finditer(remaining):
        entries.append(
            ParsedDate(year=None, month=None, day=None, raw_text=m.group(), case="verbal_specified")
        )
        remaining = _mask(remaining, m.group())

    if not entries:
        overall_case = "absent"
    elif len(entries) == 1:
        overall_case = entries[0].case
    else:
        overall_case = "multiple_dates_mixed"

    return DateParseResult(entries=entries, case=overall_case)

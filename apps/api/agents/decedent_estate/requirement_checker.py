"""
요건 판정기 (규칙 기반, LLM 미사용).

유언장 텍스트 + 사용자 확인 답변(전문 자서 / 날인)을 받아 rules/requirements.json
에 정의된 6개 요건(연월일·주소·성명·전문자서·날인·간인)에 대해 조건을 매칭하고,
그 조건에 연결된 등급(GREEN/YELLOW/RED/WHITE/PENDING)과 판례 카드 id를 반환한다.

⚠️ CLAUDE.md 절대 원칙:
1. 판정(어떤 등급인가)은 이 모듈 + rules/requirements.json 이 전담한다.
   텍스트에서 "값"을 뽑아내는 것(추출)만 정규식/규칙으로 하고, 등급표는 절대
   여기서 하드코딩하지 않는다 — 항상 rules/requirements.json 을 조회한다.
3. 판례 카드는 rules/requirements.json(→ precedents.json)에 있는 id만 참조한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .date_parser import parse_dates

_RULES_PATH = Path(__file__).parent / "rules" / "requirements.json"

_ADDRESS_UNIT_RE = re.compile(
    r"\d+(?:-\d+)?\s*번지|\d+\s*동\s*\d+\s*호|\d+\s*호(?=[\s,)\.]|$)"
)
_ADDRESS_DISTRICT_RE = re.compile(
    r"[가-힣]{2,8}(?:특별시|광역시|특별자치시|특별자치도|도|시)?\s+[가-힣]{2,6}(?:구|군|시|읍|면)"
)

_NAME_ALIAS_RE = re.compile(r"(?:아호|호)\s*[:：]\s*([가-힣]{1,4})")
_NAME_LABEL_RE = re.compile(r"(?:유언자|성명|이름)\s*[:：]\s*([가-힣]{2,4})")

_MULTI_PAGE_RE = re.compile(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)|(\d+)\s*페이지|총\s*(\d+)\s*장")

_HANDWRITING_CONDITION_IDS = {"yes", "no_or_partial_typed"}
_SEAL_CONDITION_IDS = {"seal_or_fingerprint", "signature_only", "absent"}


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _find_requirement(rules: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    for req in rules["requirements"]:
        if req["id"] == requirement_id:
            return req
    raise KeyError(f"알 수 없는 요건 id: {requirement_id}")


@dataclass(frozen=True)
class RequirementResult:
    requirement_id: str
    name: str
    condition_id: Optional[str]
    grade: Optional[str]
    precedent_ids: list[str] = field(default_factory=list)
    extracted: dict[str, Any] = field(default_factory=dict)


def _build_result(
    rules: dict[str, Any],
    requirement_id: str,
    condition_id: Optional[str],
    extracted: dict[str, Any],
) -> RequirementResult:
    req = _find_requirement(rules, requirement_id)

    if condition_id is None:
        return RequirementResult(
            requirement_id=requirement_id,
            name=req["name"],
            condition_id=None,
            grade=req.get("default_grade", "PENDING"),
            precedent_ids=[],
            extracted=extracted,
        )

    for cond in req["conditions"]:
        if cond["id"] == condition_id:
            return RequirementResult(
                requirement_id=requirement_id,
                name=req["name"],
                condition_id=condition_id,
                grade=cond.get("grade"),
                precedent_ids=list(cond.get("precedent_ids", [])),
                extracted=extracted,
            )

    raise KeyError(f"{requirement_id}.{condition_id} 조건이 rules/requirements.json 에 없습니다.")


@dataclass(frozen=True)
class ExtractedText:
    case: str
    raw_text: Optional[str]


def extract_address(text: str) -> ExtractedText:
    unit_match = _ADDRESS_UNIT_RE.search(text)
    if unit_match:
        return ExtractedText(case="full_address", raw_text=_line_of(text, unit_match))

    district_match = _ADDRESS_DISTRICT_RE.search(text)
    if district_match:
        return ExtractedText(case="city_district_only", raw_text=_line_of(text, district_match))

    return ExtractedText(case="absent", raw_text=None)


def extract_name(text: str) -> ExtractedText:
    alias_match = _NAME_ALIAS_RE.search(text)
    if alias_match:
        return ExtractedText(case="alias_or_pen_name", raw_text=alias_match.group())

    label_match = _NAME_LABEL_RE.search(text)
    if label_match:
        return ExtractedText(case="present", raw_text=label_match.group())

    return ExtractedText(case="absent", raw_text=None)


def detect_interseal(text: str) -> ExtractedText:
    match = _MULTI_PAGE_RE.search(text)
    if not match:
        return ExtractedText(case="single_page", raw_text=None)

    total = next((g for g in match.groups() if g), None)
    if total is not None and int(total) <= 1:
        return ExtractedText(case="single_page", raw_text=match.group())

    return ExtractedText(case="multiple_pages", raw_text=match.group())


def _line_of(text: str, match: re.Match[str]) -> str:
    start, end = match.span()
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def check_requirements(
    text: str,
    *,
    handwriting_answer: Optional[str] = None,
    seal_answer: Optional[str] = None,
) -> dict[str, RequirementResult]:
    """텍스트 + 사용자 확인 답변을 받아 요건별 판정 결과를 반환한다.

    handwriting_answer: "yes" | "no_or_partial_typed" | None(미확인)
    seal_answer: "seal_or_fingerprint" | "signature_only" | "absent" | None(미확인)
    """
    rules = _load_rules()
    results: dict[str, RequirementResult] = {}

    date_result = parse_dates(text)
    results["date"] = _build_result(
        rules,
        "date",
        date_result.case,
        extracted={
            "entries": [
                {
                    "year": e.year,
                    "month": e.month,
                    "day": e.day,
                    "raw_text": e.raw_text,
                    "case": e.case,
                }
                for e in date_result.entries
            ]
        },
    )

    address_result = extract_address(text)
    results["address"] = _build_result(
        rules, "address", address_result.case, extracted={"raw_text": address_result.raw_text}
    )

    name_result = extract_name(text)
    results["name"] = _build_result(
        rules, "name", name_result.case, extracted={"raw_text": name_result.raw_text}
    )

    handwriting_condition = (
        handwriting_answer if handwriting_answer in _HANDWRITING_CONDITION_IDS else None
    )
    results["handwriting"] = _build_result(
        rules, "handwriting", handwriting_condition, extracted={"answer": handwriting_answer}
    )

    seal_condition = seal_answer if seal_answer in _SEAL_CONDITION_IDS else None
    results["seal"] = _build_result(
        rules, "seal", seal_condition, extracted={"answer": seal_answer}
    )

    interseal_result = detect_interseal(text)
    results["interseal"] = _build_result(
        rules, "interseal", interseal_result.case, extracted={"raw_text": interseal_result.raw_text}
    )

    return results

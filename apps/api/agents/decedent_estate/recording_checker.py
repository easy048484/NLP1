"""
녹음 유언(민법 §1067) 대본 판정기.

requirement_checker.py(자필증서용 룰 엔진)와 동일한 구조를 recording에 적용한다.
녹음 유언은 음성이지만 요건은 "무엇을 구술했는가"이므로, 대본(전사 텍스트)만
있어도 5개 요건(유언 취지·유언자 성명·연월일·증인의 정확함 확인·증인 성명)은
텍스트로 점검할 수 있다. 나머지 2개(증인이 실제로 참여했는지, 증인이 결격
사유에 해당하는지)는 대본만으로는 알 수 없어 사용자 확인으로 처리한다.

⚠️ CLAUDE.md 절대 원칙:
1. 판정은 이 모듈 + rules/requirements.json 이 전담한다. 등급표를 여기서
   하드코딩하지 않는다 — requirement_checker._build_result 를 그대로 재사용해
   항상 rules/requirements.json 을 조회하게 한다.
   유언자 성명은 requirement_checker.extract_name_with_fallback 를 그대로
   재사용한다 (정규식 우선, 못 찾을 때만 LLM — 자필증서와 동일한 원칙).
3. 판례/조문 카드는 rules/requirements.json(→ precedents.json)에 있는 id만 참조한다.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .date_parser import parse_dates
from .requirement_checker import (
    ExtractedText,
    RequirementResult,
    _build_result,
    _load_rules,
    extract_name_with_fallback,
)

# 재산 처분 의사 표현(=유언의 취지) 유무. handwritten의 "재산 목적물 소재지" 문맥
# 배제 키워드와 어휘가 겹치지만, 여기서는 반대로 이 표현이 "있어야" GREEN이다.
_DISPOSITION_INTENT_RE = re.compile(
    r"상속한다|상속하며|증여한다|증여하며|물려준다|물려주며|양도한다|양도하며|"
    r"준다|드린다|넘긴다|남긴다"
)

# "증인" 언급 근처에 정확함을 확인하는 구술이 있는지 (동일 줄 기준 느슨한 근접 매칭).
_WITNESS_ACCURACY_RE = re.compile(
    r"증인[^\n]{0,30}?(정확합니다|정확함|정확하다고|틀림없습니다|틀림없음|틀림없다고)"
)

# 증인 성명: "증인: 김철수" 또는 줄 전체가 "증인 김철수"로 끝나는 경우만 인정
# (extract_name의 "이름"류 흔한 단어 오탐 수정과 동일한 원칙 — 콜론 또는 줄 시작+전체).
_WITNESS_NAME_WITH_COLON_RE = re.compile(r"증인\s*[:：]\s*([가-힣]{2,4})")
_WITNESS_NAME_LINE_START_RE = re.compile(r"^증인\s+([가-힣]{2,4})\s*$", re.MULTILINE)

_REC_WITNESS_PRESENT_CONDITION_IDS = ("yes", "no")
_REC_WITNESS_ELIGIBLE_CONDITION_IDS = ("not_disqualified", "disqualified")

_REC_CONFIRM_FIELD_ALLOWED_VALUES = {
    "rec_witness_present_answer": _REC_WITNESS_PRESENT_CONDITION_IDS,
    "rec_witness_eligible_answer": _REC_WITNESS_ELIGIBLE_CONDITION_IDS,
}

# "5가지 형식 요건"에 대응하는 recording의 "7가지 요건" — 전부 실제 민법 요건이라
# handwritten의 interseal 같은 "법정 요건 아님" 항목이 없다.
FORMAL_RECORDING_REQUIREMENT_IDS = (
    "rec_content",
    "rec_testator_name",
    "rec_date",
    "rec_witness_accuracy",
    "rec_witness_name",
    "rec_witness_present",
    "rec_witness_eligible",
)


def extract_content(text: str) -> ExtractedText:
    match = _DISPOSITION_INTENT_RE.search(text)
    if match:
        return ExtractedText(case="present", raw_text=match.group())
    return ExtractedText(case="absent", raw_text=None)


def extract_witness_accuracy(text: str) -> ExtractedText:
    match = _WITNESS_ACCURACY_RE.search(text)
    if match:
        return ExtractedText(case="present", raw_text=match.group())
    return ExtractedText(case="absent", raw_text=None)


def extract_witness_name(text: str) -> ExtractedText:
    match = _WITNESS_NAME_WITH_COLON_RE.search(text) or _WITNESS_NAME_LINE_START_RE.search(text)
    if match:
        return ExtractedText(case="present", raw_text=match.group(1))
    return ExtractedText(case="absent", raw_text=None)


def validate_recording_confirm_answers(
    *,
    rec_witness_present_answer: Optional[str] = None,
    rec_witness_eligible_answer: Optional[str] = None,
) -> list[dict[str, Any]]:
    """requirement_checker.validate_confirm_answers 와 동일한 목적 — 화이트리스트에
    없는 답변값이 오면 조용히 PENDING으로 새기 전에 경고로 알려준다."""
    provided = {
        "rec_witness_present_answer": rec_witness_present_answer,
        "rec_witness_eligible_answer": rec_witness_eligible_answer,
    }

    warnings: list[dict[str, Any]] = []
    for field, value in provided.items():
        if value is None:
            continue
        allowed = _REC_CONFIRM_FIELD_ALLOWED_VALUES[field]
        if value not in allowed:
            warnings.append({"field": field, "invalid_value": value, "allowed": list(allowed)})
    return warnings


def check_recording_requirements(
    text: str,
    *,
    rec_witness_present_answer: Optional[str] = None,
    rec_witness_eligible_answer: Optional[str] = None,
) -> dict[str, RequirementResult]:
    """대본 텍스트 + 사용자 확인 답변(증인 참여/증인 결격)을 받아 recording의
    7개 요건 판정 결과를 반환한다.

    rec_witness_present_answer: "yes" | "no" | None(미확인)
    rec_witness_eligible_answer: "not_disqualified" | "disqualified" | None(미확인)
    """
    rules = _load_rules()
    results: dict[str, RequirementResult] = {}

    content_result = extract_content(text)
    results["rec_content"] = _build_result(
        rules, "rec_content", content_result.case, extracted={"raw_text": content_result.raw_text}
    )

    name_result, name_extraction_method = extract_name_with_fallback(text)
    results["rec_testator_name"] = _build_result(
        rules,
        "rec_testator_name",
        name_result.case,
        extracted={
            "raw_text": name_result.raw_text,
            "extraction_method": name_extraction_method,
        },
    )

    date_result = parse_dates(text)
    results["rec_date"] = _build_result(
        rules,
        "rec_date",
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

    accuracy_result = extract_witness_accuracy(text)
    results["rec_witness_accuracy"] = _build_result(
        rules,
        "rec_witness_accuracy",
        accuracy_result.case,
        extracted={"raw_text": accuracy_result.raw_text},
    )

    witness_name_result = extract_witness_name(text)
    results["rec_witness_name"] = _build_result(
        rules,
        "rec_witness_name",
        witness_name_result.case,
        extracted={"raw_text": witness_name_result.raw_text},
    )

    present_condition = (
        rec_witness_present_answer
        if rec_witness_present_answer in _REC_WITNESS_PRESENT_CONDITION_IDS
        else None
    )
    results["rec_witness_present"] = _build_result(
        rules,
        "rec_witness_present",
        present_condition,
        extracted={"answer": rec_witness_present_answer},
    )

    eligible_condition = (
        rec_witness_eligible_answer
        if rec_witness_eligible_answer in _REC_WITNESS_ELIGIBLE_CONDITION_IDS
        else None
    )
    results["rec_witness_eligible"] = _build_result(
        rules,
        "rec_witness_eligible",
        eligible_condition,
        extracted={"answer": rec_witness_eligible_answer},
    )

    return results

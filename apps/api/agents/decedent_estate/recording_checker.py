"""
녹음 유언(민법 §1067) 대본 판정기.

requirement_checker.py(자필증서용 룰 엔진)와 동일한 구조를 recording에 적용한다.
녹음 유언은 음성이지만 요건은 "무엇을 구술했는가"이므로, 대본(전사 텍스트)만
있어도 5개 요건(유언 취지·유언자 성명·연월일·증인의 정확함 확인·증인 성명)은
텍스트로 점검할 수 있다. 나머지 2개(증인이 실제로 참여했는지, 증인이 결격
사유에 해당하는지)는 대본만으로는 알 수 없어 사용자 확인으로 처리한다.

구어체 대본은 정규식으로 잡기 어려운 게 구조적 한계라(docs/known_limitations.md
§6), 5개 요건 모두 "정규식 우선 → 5개 중 하나라도 못 찾으면 LLM 한 번 호출로
나머지를 보완" 구조를 쓴다. 항목별로 LLM을 따로 부르지 않는다 — 대본 전체를
한 번만 보내 5개를 함께 받아서, 이미 정규식으로 찾은 항목만 그 값을 그대로
쓴다 (LLM이 이미 찾은 값을 덮어쓰지 않는다).

⚠️ CLAUDE.md 절대 원칙:
1. 판정은 이 모듈 + rules/requirements.json 이 전담한다. 등급표를 여기서
   하드코딩하지 않는다 — requirement_checker._build_result 를 그대로 재사용해
   항상 rules/requirements.json 을 조회하게 한다. LLM(llm_client.
   extract_recording_fields)도 값/사실 여부만 반환하며, 그 값 역시 다른
   추출값과 동일하게 룰 엔진(_build_result)을 통과해야만 등급이 매겨진다.
3. 판례/조문 카드는 rules/requirements.json(→ precedents.json)에 있는 id만 참조한다.
4. LLM에는 마스킹(masking.mask_text)을 거친 텍스트만 보낸다.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .date_parser import DateParseResult, parse_dates
from .llm_client import extract_recording_fields
from .masking import mask_text
from .requirement_checker import (
    ExtractedText,
    RequirementResult,
    _build_result,
    _load_rules,
    extract_name,
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
    match = _WITNESS_NAME_WITH_COLON_RE.search(
        text
    ) or _WITNESS_NAME_LINE_START_RE.search(text)
    if match:
        return ExtractedText(case="present", raw_text=match.group(1))
    return ExtractedText(case="absent", raw_text=None)


def _resolve_text_field(
    regex_result: ExtractedText, llm_value: Optional[str]
) -> tuple[ExtractedText, str]:
    """정규식이 못 찾았을 때(absent)만 LLM 값을 쓴다. 규칙: 정규식 성공 > LLM > 둘 다 실패."""
    if regex_result.case != "absent":
        return regex_result, "regex"
    if llm_value:
        return ExtractedText(case="present", raw_text=llm_value), "llm"
    return regex_result, "none"


def _resolve_bool_field(
    regex_result: ExtractedText, llm_flag: Optional[bool]
) -> tuple[ExtractedText, str]:
    """has_disposition_intent/has_witness_accuracy 처럼 LLM이 사실 여부(bool)만
    돌려주는 항목용 — 인용할 원문 스니펫이 없으므로 raw_text 는 None으로 둔다."""
    if regex_result.case != "absent":
        return regex_result, "regex"
    if llm_flag:
        return ExtractedText(case="present", raw_text=None), "llm"
    return regex_result, "none"


def _resolve_date_field(
    regex_result: DateParseResult, llm_date_text: Optional[str]
) -> tuple[DateParseResult, str]:
    """LLM이 돌려준 date_text도 date_parser.parse_dates 에 그대로 통과시켜 일(日)
    누락 등 기존 등급 조건 구조를 그대로 유지한다 (LLM은 값만 추출, 판정은 안 함)."""
    if regex_result.case != "absent":
        return regex_result, "regex"
    if llm_date_text:
        llm_result = parse_dates(llm_date_text)
        if llm_result.case != "absent":
            return llm_result, "llm"
    return regex_result, "none"


def _date_entries_payload(date_result: DateParseResult) -> list[dict[str, Any]]:
    # ⚠️ raw_text(매칭된 원문 조각)는 의도적으로 담지 않는다 — 자세한 이유는
    # requirement_checker.check_requirements 의 같은 자리 주석 참고
    # (CLAUDE.md 절대 원칙 4, 오탐 시 원문 조각이 응답·세션으로 새는 것을 막음).
    return [
        {
            "year": e.year,
            "month": e.month,
            "day": e.day,
            "case": e.case,
        }
        for e in date_result.entries
    ]


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
            warnings.append(
                {"field": field, "invalid_value": value, "allowed": list(allowed)}
            )
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

    content_regex = extract_content(text)
    name_regex = extract_name(text)
    date_regex = parse_dates(text)
    accuracy_regex = extract_witness_accuracy(text)
    witness_name_regex = extract_witness_name(text)

    needs_llm = (
        any(
            r.case == "absent"
            for r in (content_regex, name_regex, accuracy_regex, witness_name_regex)
        )
        or date_regex.case == "absent"
    )

    llm_fields: Optional[dict[str, Any]] = (
        extract_recording_fields(mask_text(text)) if needs_llm else None
    )

    content_final, content_method = _resolve_bool_field(
        content_regex, llm_fields.get("has_disposition_intent") if llm_fields else None
    )
    results["rec_content"] = _build_result(
        rules,
        "rec_content",
        content_final.case,
        extracted={
            "raw_text": content_final.raw_text,
            "extraction_method": content_method,
        },
    )

    name_final, name_method = _resolve_text_field(
        name_regex, llm_fields.get("testator_name") if llm_fields else None
    )
    results["rec_testator_name"] = _build_result(
        rules,
        "rec_testator_name",
        name_final.case,
        extracted={"raw_text": name_final.raw_text, "extraction_method": name_method},
    )

    date_final, date_method = _resolve_date_field(
        date_regex, llm_fields.get("date_text") if llm_fields else None
    )
    results["rec_date"] = _build_result(
        rules,
        "rec_date",
        date_final.case,
        extracted={
            "entries": _date_entries_payload(date_final),
            "extraction_method": date_method,
        },
    )

    accuracy_final, accuracy_method = _resolve_bool_field(
        accuracy_regex, llm_fields.get("has_witness_accuracy") if llm_fields else None
    )
    results["rec_witness_accuracy"] = _build_result(
        rules,
        "rec_witness_accuracy",
        accuracy_final.case,
        extracted={
            "raw_text": accuracy_final.raw_text,
            "extraction_method": accuracy_method,
        },
    )

    witness_name_final, witness_name_method = _resolve_text_field(
        witness_name_regex, llm_fields.get("witness_name") if llm_fields else None
    )
    results["rec_witness_name"] = _build_result(
        rules,
        "rec_witness_name",
        witness_name_final.case,
        extracted={
            "raw_text": witness_name_final.raw_text,
            "extraction_method": witness_name_method,
        },
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

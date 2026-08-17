"""
요건 판정기 (규칙 기반, LLM 미사용).

유언장 텍스트 + 사용자 확인 답변(전문 자서 / 날인 / 주소가 RED일 때만 물어보는 봉투 확인)을
받아 rules/requirements.json
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
# 유언자 본인 주소가 아니라 상속·증여 대상 부동산 소재지를 설명하는 문장은
# 주소 요건 판정에서 제외한다 (예: "내가 소유한 OO 아파트를 ~에게 상속한다").
_ADDRESS_PROPERTY_CONTEXT_RE = re.compile(
    r"소유(?:한|하는|권)?|부동산|명의로|아파트를|주택을|토지를|건물을|"
    r"상속한다|상속하며|증여한다|증여하며|물려준다|물려주며|양도한다|양도하며"
)

_NAME_ALIAS_RE = re.compile(r"(?:아호|호)\s*[:：]\s*([가-힣]{1,4})")
# 콜론 없는 "유언자 김영수" 형태도 허용 (콜론은 선택)
_NAME_LABEL_RE = re.compile(r"(?:유언자|성명|이름)\s*[:：]?\s*([가-힣]{2,4})")
# 라벨 없이 도장 표시 앞에 이름만 적힌 경우: "김영수 (인)" / "김영수(印)"
_NAME_BEFORE_SEAL_MARK_RE = re.compile(r"([가-힣]{2,4})\s*\(\s*(?:인|印)\s*\)")
# 라벨도 도장 표시도 없이 줄 끝에 이름만 단독으로 적힌 경우 (서명란 관행)
_NAME_STANDALONE_LINE_RE = re.compile(r"^[가-힣]{2,4}$")
_NAME_STANDALONE_LINE_BLOCKLIST = {"유언장", "유언", "증인", "서명", "이상", "끝"}

_MULTI_PAGE_RE = re.compile(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)|(\d+)\s*페이지|총\s*(\d+)\s*장")

# 튜플(순서 있음)로 둔다 — validate_confirm_answers() 의 경고에 담기는 "allowed"
# 목록이 rules/requirements.json 의 conditions 선언 순서와 그대로 일치해야 하므로.
_HANDWRITING_CONDITION_IDS = ("yes", "no_or_partial_typed")
_SEAL_CONDITION_IDS = ("seal_or_fingerprint", "signature_only", "absent")
_ADDRESS_ENVELOPE_CONDITION_IDS = ("envelope_or_minor_discrepancy", "no_envelope")

# context 필드 이름 → 허용값 목록. validate_confirm_answers() 와 check_requirements()
# 양쪽이 이 하나의 매핑만 참조하도록 해서 두 곳의 화이트리스트가 어긋나지 않게 한다.
_CONFIRM_FIELD_ALLOWED_VALUES = {
    "handwriting_answer": _HANDWRITING_CONDITION_IDS,
    "seal_answer": _SEAL_CONDITION_IDS,
    "address_envelope_answer": _ADDRESS_ENVELOPE_CONDITION_IDS,
}


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
    # RED 판정 뒤에 추가로 물어봐야 할 확인 질문이 있을 때만 채워진다 (예: 주소 봉투 확인).
    followup_question: Optional[str] = None


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
            followup_question=req.get("question"),
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


def _build_address_result(
    rules: dict[str, Any],
    address_result: "ExtractedText",
    envelope_answer: Optional[str],
) -> RequirementResult:
    """주소 요건 + followup(봉투 확인 질문)을 함께 판정한다.

    followup은 본문 판정의 condition_id 가 followup.trigger_conditions 에 속할
    때만(현재는 "absent" 뿐) 트리거된다 — "본문에 주소가 아예 없어야" 봉투 질문이
    말이 된다. "city_district_only"(본문에 불완전하게라도 주소가 있음)는 이미
    본문에 주소가 있는 상태라 "봉투에 적혀 있나요?"라는 질문 자체가 성립하지
    않으므로 트리거하지 않고 RED로 확정한다.

    트리거되는 경우:
    - 답변 없음 → PENDING (자서/날인 미확인과 동일한 취급)
    - "envelope_or_minor_discrepancy" → followup 조건의 YELLOW로 승격
    - "no_envelope" → 본문 기반 RED 판정 그대로 유지
    """
    req = _find_requirement(rules, "address")
    base = _build_result(
        rules, "address", address_result.case, extracted={"raw_text": address_result.raw_text}
    )

    followup = req.get("followup")
    if not followup or base.condition_id not in followup.get("trigger_conditions", []):
        return base

    question = followup["question"]
    envelope_condition = (
        envelope_answer if envelope_answer in _ADDRESS_ENVELOPE_CONDITION_IDS else None
    )

    if envelope_condition is None:
        return RequirementResult(
            requirement_id="address",
            name=req["name"],
            condition_id=None,
            grade="PENDING",
            precedent_ids=[],
            extracted={**base.extracted, "underlying_case": base.condition_id},
            followup_question=question,
        )

    for cond in followup["conditions"]:
        if cond["id"] != envelope_condition:
            continue
        if cond.get("grade") is None:
            # "no_envelope": 본문 기반 판정을 그대로 유지한다.
            return base
        return RequirementResult(
            requirement_id="address",
            name=req["name"],
            condition_id=cond["id"],
            grade=cond["grade"],
            precedent_ids=list(cond.get("precedent_ids", [])),
            extracted={**base.extracted, "underlying_case": base.condition_id},
        )

    raise KeyError(f"address.followup.{envelope_condition} 조건이 rules/requirements.json 에 없습니다.")


@dataclass(frozen=True)
class ExtractedText:
    case: str
    raw_text: Optional[str]


def extract_address(text: str) -> ExtractedText:
    # 재산 목적물 소재지를 설명하는 줄은 유언자 주소 후보에서 제외한다.
    candidate_lines = [
        line for line in text.splitlines() if not _ADDRESS_PROPERTY_CONTEXT_RE.search(line)
    ]

    for line in candidate_lines:
        if _ADDRESS_UNIT_RE.search(line):
            return ExtractedText(case="full_address", raw_text=line.strip())

    for line in candidate_lines:
        if _ADDRESS_DISTRICT_RE.search(line):
            return ExtractedText(case="city_district_only", raw_text=line.strip())

    return ExtractedText(case="absent", raw_text=None)


def extract_name(text: str) -> ExtractedText:
    # 각 정규식의 group(1)이 라벨/도장 표시를 뺀 이름 그 자체다 — group(0)(전체 매치)을
    # 쓰면 "유언자: 홍길동"처럼 라벨까지 extracted 값에 섞여 들어간다.
    alias_match = _NAME_ALIAS_RE.search(text)
    if alias_match:
        return ExtractedText(case="alias_or_pen_name", raw_text=alias_match.group(1))

    label_match = _NAME_LABEL_RE.search(text)
    if label_match:
        return ExtractedText(case="present", raw_text=label_match.group(1))

    seal_match = _NAME_BEFORE_SEAL_MARK_RE.search(text)
    if seal_match:
        return ExtractedText(case="present", raw_text=seal_match.group(1))

    # 문서 하단(서명란)에 가까운 쪽부터 훑어 표제("유언장" 등)를 오탐하지 않도록 한다.
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped in _NAME_STANDALONE_LINE_BLOCKLIST:
            continue
        if _NAME_STANDALONE_LINE_RE.match(stripped):
            return ExtractedText(case="present", raw_text=stripped)

    return ExtractedText(case="absent", raw_text=None)


def detect_interseal(text: str) -> ExtractedText:
    match = _MULTI_PAGE_RE.search(text)
    if not match:
        return ExtractedText(case="single_page", raw_text=None)

    # group(1)은 "(N/M)"의 현재 페이지 번호 N이라 총 장수 판단에 쓰면 안 된다.
    # 총 장수는 group(2)="(N/M)"의 M, group(3)="N페이지", group(4)="총 N장" 중 하나다.
    total = match.group(2) or match.group(3) or match.group(4)
    if total is not None and int(total) <= 1:
        return ExtractedText(case="single_page", raw_text=match.group())

    return ExtractedText(case="multiple_pages", raw_text=match.group())


def validate_confirm_answers(
    *,
    handwriting_answer: Optional[str] = None,
    seal_answer: Optional[str] = None,
    address_envelope_answer: Optional[str] = None,
) -> list[dict[str, Any]]:
    """사용자 확인 답변 중 화이트리스트에 없는 값을 찾아 경고 목록으로 반환한다.

    판정 자체(check_requirements)는 그런 값을 조용히 미확인(None)으로 취급해
    PENDING을 유지한다 — 이 함수는 그 "조용한 실패"를 호출자가 알아챌 수 있게
    해줄 뿐, check_requirements 의 동작을 바꾸지 않는다.
    """
    provided = {
        "handwriting_answer": handwriting_answer,
        "seal_answer": seal_answer,
        "address_envelope_answer": address_envelope_answer,
    }

    warnings: list[dict[str, Any]] = []
    for field, value in provided.items():
        if value is None:
            continue
        allowed = _CONFIRM_FIELD_ALLOWED_VALUES[field]
        if value not in allowed:
            warnings.append(
                {"field": field, "invalid_value": value, "allowed": list(allowed)}
            )
    return warnings


def check_requirements(
    text: str,
    *,
    handwriting_answer: Optional[str] = None,
    seal_answer: Optional[str] = None,
    address_envelope_answer: Optional[str] = None,
) -> dict[str, RequirementResult]:
    """텍스트 + 사용자 확인 답변을 받아 요건별 판정 결과를 반환한다.

    handwriting_answer: "yes" | "no_or_partial_typed" | None(미확인)
    seal_answer: "seal_or_fingerprint" | "signature_only" | "absent" | None(미확인)
    address_envelope_answer: 주소가 RED로 판정된 경우에만 의미가 있다.
        "envelope_or_minor_discrepancy" | "no_envelope" | None(미확인)
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
    results["address"] = _build_address_result(rules, address_result, address_envelope_answer)

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

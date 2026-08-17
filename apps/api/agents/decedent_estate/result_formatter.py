"""
판정 결과(RequirementResult) → 화면 문구 변환기.

요건판정_문구_스펙_v1.md §3(화면 문구)를 그대로 구현한다. handwritten(자필증서)
관련 고정 문장들은 스펙 문서와 글자 하나 다르지 않아야 한다 — 문구를 바꿀 일이
있으면 스펙 문서를 먼저 고친 뒤 이 파일을 고칠 것 (§4 가드레일: 단정 표현 금지
등도 스펙 문구 안에 이미 반영되어 있으므로 별도로 재가공하지 않는다).

recording(녹음, §1067)은 스펙 문서 대상이 아니지만, §3-2의 GREEN/RED/YELLOW/WHITE
패턴과 §4 가드레일(단정 금지 등)은 그대로 따르고, §3-1 전체 요약 4케이스만
recording 전용 문구(RECORDING_SUMMARY_MESSAGES)로 별도 작성했다 — "자필증서
유언의 5가지 형식 요건" 같은 handwritten 전용 표현을 recording에 그대로 쓸 수
없기 때문이다. summarize()/pending_questions()/format_result() 는 모두
formal_ids(요약에 넣을 요건 집합)를 파라미터로 받아 handwritten/recording을
공통 로직으로 처리한다 — 기본값은 handwritten이라 기존 호출부는 안 바꿔도 된다.

{요건} 자리에는 요건 이름(RequirementResult.name)을, RED 문구의 {무엇} 자리에는
요건명 중복을 피하기 위해 rules/requirements.json 의 red_label 필드를 넣는다
(YELLOW의 {쟁점}은 그대로 요건 이름). 스펙 원문은 뒤에 오는 조사를 "이"로 고정
표기했지만 "주소이"처럼 실제로는 어색한 조합이 생겨, 받침 유무에 따라 "이/가"를
올바르게 골라 붙인다 — 그 외 문장은 전부 스펙 원문 그대로다.

RED 항목은 더 이상 "→ 법률 전문가 확인을 권합니다"로 끝나지 않는다 — 그 안내는
상단 요약(케이스 B)과 §3-3 상담 연결 줄에 이미 있어서 항목마다 반복하지 않기로
했다. 판례/조문 카드도 "[카드]" 표기 대신 실제 근거를 그대로 붙인다: precedent는
court+case_number, commentary는 "(대한법률구조공단 해설)", statute(조문 직접
인용)는 "(민법 제OOOO조)". 다만 무효 판례가 아니라 반대 취지의 참고 정보인
precedent_id(_RED_REFERENCE_NOTES)는 카드가 아니라 들여쓴 참고 문구로 따로
보여준다 (예: 날인 RED의 fingerprint_seal_valid, 증인결격 RED의
executor_not_disqualified).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .requirement_checker import RequirementResult

_PRECEDENTS_PATH = Path(__file__).parent / "rules" / "precedents.json"
_RULES_PATH = Path(__file__).parent / "rules" / "requirements.json"

# "5가지 형식 요건" — 간인은 법정 요건이 아니라서(is_legal_requirement: false) 제외한다.
_FORMAL_REQUIREMENT_IDS = ("date", "address", "name", "handwriting", "seal")


@dataclass(frozen=True)
class SummaryMessages:
    """§3-1 A/B/C/D 중 D(PENDING)를 뺀 3개 — will_type마다 문구가 다르다."""

    all_green: str
    has_red: str
    yellow_only: str


# ---------------------------------------------------------------------------
# §3-1. 전체 요약 (4케이스) — handwritten은 스펙 원문 그대로
# ---------------------------------------------------------------------------
_HANDWRITTEN_SUMMARY_MESSAGES = SummaryMessages(
    all_green=(
        "**형식 요건상 문제가 발견되지 않았습니다.** 자필증서 유언의 5가지 형식 요건"
        "(자서·연월일·주소·성명·날인)이 모두 확인됩니다. 다만 이 점검은 형식 요건에 한정되며, "
        "유언의 최종 유효성은 내용·작성 경위 등에 따라 달라질 수 있습니다."
    ),
    has_red=(
        "**확인되지 않는 요건이 있습니다.** 아래 항목은 법원이 무효로 판단해온 사례와 같은 "
        "쟁점에 해당할 수 있습니다. 법률 전문가 확인을 권합니다."
    ),
    yellow_only=(
        "**전문가 확인이 필요한 부분이 있습니다.** 형식상 명확한 문제는 발견되지 않았으나, "
        "법원 판단이 사안에 따라 갈린 쟁점이 포함되어 있습니다."
    ),
)

# recording(§1067)은 요건판정_문구_스펙_v1.md 대상이 아니라 여기서 직접 작성했다 —
# "자필증서 유언의 5가지 형식 요건" 같은 handwritten 전용 표현을 쓸 수 없어서다.
RECORDING_SUMMARY_MESSAGES = SummaryMessages(
    all_green=(
        "**형식 요건상 문제가 발견되지 않았습니다.** 녹음 유언의 7가지 요건(유언 취지·"
        "유언자 성명·연월일·증인의 정확함 확인·증인 성명·증인 참여·증인 결격 여부)이 모두 "
        "확인됩니다. 다만 이 점검은 대본(전사) 텍스트 기준이며, 실제 녹음 내용과 일치하는지는 "
        "별도로 확인이 필요합니다."
    ),
    has_red=(
        "**확인되지 않는 요건이 있습니다.** 아래 항목은 민법이 정한 녹음 유언 요건을 충족하지 "
        "못했을 수 있습니다. 법률 전문가 확인을 권합니다."
    ),
    yellow_only=(
        "**전문가 확인이 필요한 부분이 있습니다.** 형식상 명확한 문제는 발견되지 않았으나, "
        "판단이 사안에 따라 갈릴 수 있는 쟁점이 포함되어 있습니다."
    ),
)


def _summary_pending(count: int) -> str:
    """D 케이스: PENDING 개수 n으로 동적 치환 (1개면 "한 가지"). will_type 공통."""
    count_word = "한 가지" if count == 1 else f"{count}가지"
    return f"**{count_word}만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 항목입니다."


# ---------------------------------------------------------------------------
# §3-2. 요건별 문구 패턴의 고정 부분 — 스펙 원문 그대로
# ---------------------------------------------------------------------------
_RED_VERB_PHRASE = "확인되지 않습니다"
_YELLOW_VERB_PHRASE = "쟁점이 될 수 있습니다"
_YELLOW_CTA = "→ 개별 판단이 필요합니다. 법률 상담을 권합니다"
_INTERSEAL_REFERENCE_LINE = (
    "ℹ️ 참고: 간인은 법정 요건이 아니지만, 여러 장일 경우 위조 다툼 예방에 도움이 됩니다"
)
_COMMENTARY_CITATION = "(대한법률구조공단 해설)"

# RED 판정에 딸린 precedent_id 중 "무효 판례"가 아니라 반대 취지의 참고 정보인
# 것들은 카드(사건번호 인용)가 아니라 들여쓴 참고 문구로 따로 보여준다.
_RED_REFERENCE_NOTES = {
    "fingerprint_seal_valid": "   ℹ️ 참고: 지장(손도장)도 날인으로 인정됩니다",
    "executor_not_disqualified": "   ℹ️ 참고: 유언집행자라는 사정만으로는 증인 결격이 아닙니다",
}

# ---------------------------------------------------------------------------
# §3-3 / §3-4 — 스펙 원문 그대로 (will_type 공통)
# ---------------------------------------------------------------------------
_CONSULTATION_LINE = (
    "📞 무료로 확인받을 수 있는 곳: 대한법률구조공단 132 (무료 법률상담) · 각 지역 지부. "
    "유언 검인·공증 관련은 가까운 공증사무소에서 안내받을 수 있습니다."
)
_FOOTER_NOTICE = (
    "이 점검은 민법 제1066조의 형식 요건에 대한 참고용 확인이며, 법률 자문이 아닙니다. "
    "유언의 유효성에 대한 최종 판단은 법원과 법률 전문가의 영역입니다."
)


@lru_cache(maxsize=1)
def _load_precedents() -> dict[str, dict[str, Any]]:
    with _PRECEDENTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return {p["id"]: p for p in data["precedents"]}


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _has_batchim(word: str) -> bool:
    """마지막 글자에 받침이 있는지 (한글 완성형 코드 계산)."""
    if not word:
        return False
    code = ord(word[-1]) - 0xAC00
    if 0 <= code <= 11171:
        return code % 28 != 0
    return False


def _josa_i_ga(word: str) -> str:
    return "이" if _has_batchim(word) else "가"


def _precedent_citation(card: dict[str, Any]) -> str:
    if card["type"] == "commentary":
        return _COMMENTARY_CITATION
    if card["type"] == "statute":
        return f"({card['source']})"
    return f"({card['court']} {card['case_number']})"


def _precedent_card_line(precedent_id: str) -> Optional[str]:
    card = _load_precedents().get(precedent_id)
    if not card:
        return None
    return f"{card['one_liner']} {_precedent_citation(card)}"


def red_label(requirement_id: str) -> str:
    """요건 id → RED 문구용 축약 라벨 (rules/requirements.json 의 red_label 필드).

    agent.py 등 다른 모듈에서도 신호등 UI용 data 를 구조화할 때 재사용한다.
    """
    rules = _load_rules()
    for req in rules["requirements"]:
        if req["id"] == requirement_id:
            return req.get("red_label", req["name"])
    return requirement_id


# GREEN 패턴의 "(+ 추출값 표시)" 부분에서 값을 어떻게 뽑아 보여줄지 요건 id별로 분기.
_DATE_LIKE_REQUIREMENT_IDS = {"date", "rec_date"}
_RAW_TEXT_DISPLAY_REQUIREMENT_IDS = {
    "address",
    "name",
    "rec_content",
    "rec_testator_name",
    "rec_witness_accuracy",
    "rec_witness_name",
}


def _extracted_display_value(result: RequirementResult) -> Optional[str]:
    """§3-2 GREEN 패턴의 "(+ 추출값 표시)" 부분."""
    if result.requirement_id in _DATE_LIKE_REQUIREMENT_IDS:
        entries = result.extracted.get("entries") or []
        if len(entries) == 1:
            e = entries[0]
            if e.get("year") and e.get("month") and e.get("day"):
                return f"{e['year']}년 {e['month']}월 {e['day']}일"
        return None

    if result.requirement_id in _RAW_TEXT_DISPLAY_REQUIREMENT_IDS:
        return result.extracted.get("raw_text")

    return None


def format_requirement_line(result: RequirementResult) -> Optional[str]:
    """요건 하나를 §3-2 패턴 문구로 변환한다. PENDING/등급 없음은 대상이 아니다."""
    name = result.name

    if result.grade == "GREEN":
        value = _extracted_display_value(result)
        suffix = f" ({value})" if value else ""
        return f"✅ {name}: 기재 확인{suffix}"

    if result.grade == "RED":
        label = red_label(result.requirement_id)
        lines = [f"❌ {name}: {label}{_josa_i_ga(label)} {_RED_VERB_PHRASE}"]
        for precedent_id in result.precedent_ids:
            if precedent_id in _RED_REFERENCE_NOTES:
                lines.append(_RED_REFERENCE_NOTES[precedent_id])
                continue
            card_line = _precedent_card_line(precedent_id)
            if card_line:
                lines.append(card_line)
        return "\n".join(lines)

    if result.grade == "YELLOW":
        lines = [f"⚠️ {name}: {name}{_josa_i_ga(name)} {_YELLOW_VERB_PHRASE}"]
        for precedent_id in result.precedent_ids:
            card_line = _precedent_card_line(precedent_id)
            if card_line:
                lines.append(card_line)
        lines.append(_YELLOW_CTA)
        return "\n".join(lines)

    if result.grade == "WHITE":
        return _INTERSEAL_REFERENCE_LINE

    return None


def summarize(
    results: dict[str, RequirementResult],
    formal_ids: tuple[str, ...] = _FORMAL_REQUIREMENT_IDS,
    messages: SummaryMessages = _HANDWRITTEN_SUMMARY_MESSAGES,
) -> str:
    """§3-1: formal_ids 요건들의 등급 조합으로 A/B/C/D 중 하나를 고른다.

    우선순위: PENDING(아직 판정 불가) > RED > YELLOW > 전부 GREEN.
    formal_ids/messages 기본값은 handwritten — recording 호출부는 각자의
    formal_ids(FORMAL_RECORDING_REQUIREMENT_IDS)와 messages를 명시적으로 넘긴다.
    """
    grades = [results[rid].grade for rid in formal_ids]

    pending_count = grades.count("PENDING")
    if pending_count:
        return _summary_pending(pending_count)
    if "RED" in grades:
        return messages.has_red
    if "YELLOW" in grades:
        return messages.yellow_only
    return messages.all_green


def _confirm_field(requirement_id: str, req: dict[str, Any]) -> Optional[str]:
    """요건 id → context 필드 이름 (rules/requirements.json 의 confirm_field)."""
    if requirement_id == "address":
        followup = req.get("followup")
        return followup.get("confirm_field") if followup else None
    return req.get("confirm_field")


def _confirm_options(requirement_id: str, req: dict[str, Any]) -> list[dict[str, str]]:
    """PENDING 요건을 물어볼 때 프론트가 버튼으로 그릴 선택지 (label/value).

    label 문구는 rules/requirements.json 의 conditions[].label 을 그대로 쓴다 —
    여기서 문구를 새로 짓지 않는다.
    """
    conditions = req["followup"]["conditions"] if requirement_id == "address" else req["conditions"]
    return [
        {"label": cond["label"], "value": cond["id"]}
        for cond in conditions
        if "label" in cond
    ]


def pending_questions(
    results: dict[str, RequirementResult],
    formal_ids: tuple[str, ...] = _FORMAL_REQUIREMENT_IDS,
) -> list[dict[str, Any]]:
    """D 케이스에서 실제로 물어봐야 할 질문들을, 프론트가 버튼을 그릴 수 있는 형태로.

    §3 본문에는 없는 보조 기능이지만, "N가지만 직접 확인해주세요"라는 요약 문구
    뒤에 실제로 무엇을(어떤 선택지로) 물어야 하는지가 있어야 화면을 완성할 수 있어
    추가했다. question/field/label 문구는 전부 rules/requirements.json 값을 그대로
    쓴다 — 여기서 새로 짓지 않는다.

    반환 형태: [{"requirement": str, "field": str, "question": str,
                 "options": [{"label": str, "value": str}, ...]}, ...]
    """
    rules = _load_rules()
    rules_by_id = {req["id"]: req for req in rules["requirements"]}

    questions = []
    for rid in formal_ids:
        result = results[rid]
        if result.grade != "PENDING" or not result.followup_question:
            continue
        req = rules_by_id[rid]
        questions.append(
            {
                "requirement": result.name,
                "field": _confirm_field(rid, req),
                "question": result.followup_question,
                "options": _confirm_options(rid, req),
            }
        )
    return questions


def format_result(
    results: dict[str, RequirementResult],
    *,
    formal_ids: tuple[str, ...] = _FORMAL_REQUIREMENT_IDS,
    ordered_ids: Optional[list[str]] = None,
    messages: SummaryMessages = _HANDWRITTEN_SUMMARY_MESSAGES,
) -> str:
    """전체 화면 문구를 조립한다: 요약 → (확인 질문) → 요건별 문구 → 상담 연결 → 하단 고지.

    ordered_ids 를 생략하면 rules/requirements.json 전체를 order 순으로 훑되,
    results 에 실제로 있는 요건만 남긴다(handwritten 기본 동작). recording처럼
    다른 요건 집합을 렌더링하려면 ordered_ids/formal_ids/messages 를 명시한다.
    """
    if ordered_ids is None:
        rules = _load_rules()
        ordered_ids = [
            req["id"]
            for req in sorted(rules["requirements"], key=lambda r: r["order"])
            if req["id"] in results
        ]

    sections = [summarize(results, formal_ids, messages)]

    pending = pending_questions(results, formal_ids)
    if pending:
        sections.append(
            "\n".join(f"- {item['requirement']}: {item['question']}" for item in pending)
        )

    for requirement_id in ordered_ids:
        line = format_requirement_line(results[requirement_id])
        if line:
            sections.append(line)

    sections.append(_CONSULTATION_LINE)
    sections.append(_FOOTER_NOTICE)

    return "\n\n".join(sections)

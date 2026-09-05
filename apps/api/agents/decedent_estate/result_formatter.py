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
executor_not_disqualified). 이 참고 문구는 카드 인용(_precedent_citation)을
거치지 않고 여기 문자열을 그대로 쓰므로, 근거가 판례인지 조문인지에 맞는
표현을 문자열 자체에 담아야 한다.

GREEN 항목에도 같은 패턴(_GREEN_REFERENCE_NOTES)이 있다 — 날인 GREEN(지장
선택)의 fingerprint_identity_disputed_invalid: 무인 자체는 적법하므로 등급은
GREEN을 유지하되, 무인이 본인 것인지가 다투어져 무효로 판단된 사례가 있다는
참고 문구만 덧붙인다. RED 예외와 마찬가지로 카드 인용을 거치지 않는다.
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


def _summary_pending(count: int, total: int) -> str:
    """D 케이스: PENDING 개수 n으로 동적 치환 (1개면 "한 가지"). will_type 공통.

    사진 판독(#35)이 photo_draft 진행 상황을 확인 질문과 함께 노출하는 것과
    동일하게, 텍스트 경로도 진행률("확인됨/전체")을 응답 문구에 노출한다 —
    data.progress(#42)는 이미 있었지만 reply 텍스트에는 안 보이고 있었다.
    total 은 summarize() 가 넘기는 formal_ids 길이라 progress() 와 같은
    분모를 쓴다(간인처럼 법정 요건 아닌 항목은 포함 안 됨).
    """
    count_word = "한 가지" if count == 1 else f"{count}가지"
    checked = total - count
    return (
        f"**{count_word}만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 "
        f"항목입니다. ({checked}/{total} 확인됨)"
    )


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
    "fingerprint_seal_valid": "   ℹ️ 참고: 지장(손도장)을 날인으로 인정한 판례가 있습니다",
    # executor_not_disqualified는 판례가 아니라 조문(§1072 열거) 근거라, "판례가
    # 있습니다"가 아니라 "조문상" 표현을 쓴다 — precedents.json 의 note 대로 명시적
    # 대법원 판례로 확인된 해석이 아니라 열거 목록에 없다는 소극적 추론이기 때문.
    "executor_not_disqualified": "   ℹ️ 참고: 조문상 유언집행자는 증인 결격사유로 열거되어 있지 않습니다",
}

# GREEN 판정에 딸린 precedent_id 중 등급 자체는 바꾸지 않지만 별도 쟁점(본인
# 확인 등)이 있음을 알려야 하는 것들 — RED와 동일한 패턴으로 카드가 아니라
# 들여쓴 참고 문구로 보여준다.
_GREEN_REFERENCE_NOTES = {
    "fingerprint_identity_disputed_invalid": (
        "   ℹ️ 참고: 무인이 고인 본인의 것임이 다투어지는 경우 유언증서가 무효로 "
        "판단된 사례가 있습니다"
    ),
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


def closing_lines() -> list[str]:
    """모든 결과 화면 끝에 붙는 §3-3(상담 연결) · §3-4(하단 고지) 두 줄.

    format_result/format_guide 는 내부에서 알아서 붙이지만, 요건 판정을 돌지
    않는 안내 전용 화면(예: agent._run_no_will_pipeline)도 같은 두 줄로 끝나야
    해서 공개 헬퍼로 노출한다 — 문구를 그쪽에 복사해두면 스펙이 바뀔 때 한쪽만
    고쳐질 수 있다(§3-3/§3-4의 단일 출처를 이 모듈로 유지).
    """
    return [_CONSULTATION_LINE, _FOOTER_NOTICE]


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


def term_note(requirement_id: str) -> Optional[str]:
    """요건 id → 용어 설명 (rules/requirements.json 의 term_note 필드).

    GREEN(충족)에는 붙이지 않는다 — 이미 확인된 요건에 "이게 뭔가요" 설명을
    또 보여주는 건 불필요한 반복이다. RED/YELLOW(미충족·쟁점)에만
    format_requirement_line 이 이 값을 붙인다.
    """
    rules = _load_rules()
    for req in rules["requirements"]:
        if req["id"] == requirement_id:
            return req.get("term_note")
    return None


def _condition_display_note(
    requirement_id: str, condition_id: Optional[str], result: RequirementResult
) -> Optional[str]:
    """요건 id + condition id 조합에만 적용되는 조건 전용 설명 (conditions[].display_note).

    term_note는 요건 id 단위라 같은 요건의 서로 다른 condition(예: 주소의
    RED city_district_only와 YELLOW building_number_only)이 같은 문구를
    공유한다. building_number_only는 실제로 도로명·건물번호까지 정상 인식된
    상태인데 city_district_only용 term_note("구·동까지만 적으면 무효")를
    그대로 보여주면 판정 상태와 화면 설명이 어긋난다 — 이 조건에서만
    display_note로 실제 상태를 반영한 문구를 쓴다. {value} 자리에는 추출된
    주소 원문을 "(추출값)" 형태로 채운다(없으면 빈 문자열).
    """
    if condition_id is None:
        return None
    rules = _load_rules()
    for req in rules["requirements"]:
        if req["id"] != requirement_id:
            continue
        for cond in req.get("conditions", []):
            if cond.get("id") == condition_id and cond.get("display_note"):
                value = _extracted_display_value(result)
                suffix = f" ({value})" if value else ""
                return cond["display_note"].format(value=suffix)
    return None


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


def format_requirement_line(
    result: RequirementResult, *, include_precedent_cards: bool = True
) -> Optional[str]:
    """요건 하나를 §3-2 패턴 문구로 변환한다. PENDING/등급 없음은 대상이 아니다.

    include_precedent_cards=False 면 _precedent_card_line() 이 만드는 판례
    인용 줄("(대법원 2009다9768)" 류)만 뺀다 — 참고 문구(_RED_REFERENCE_NOTES/
    _GREEN_REFERENCE_NOTES, 카드로 안 만들기로 한 예외 3건용)와 term_note는
    그대로 남는다. P0-1의 body(precedents 카드와 중복 방지)가 이 옵션을 쓴다.
    """
    name = result.name

    if result.grade == "GREEN":
        value = _extracted_display_value(result)
        suffix = f" ({value})" if value else ""
        lines = [f"✅ {name}: 기재 확인{suffix}"]
        for precedent_id in result.precedent_ids:
            if precedent_id in _GREEN_REFERENCE_NOTES:
                lines.append(_GREEN_REFERENCE_NOTES[precedent_id])
        return "\n".join(lines)

    if result.grade == "RED":
        label = red_label(result.requirement_id)
        lines = [f"❌ {name}: {label}{_josa_i_ga(label)} {_RED_VERB_PHRASE}"]
        for precedent_id in result.precedent_ids:
            if precedent_id in _RED_REFERENCE_NOTES:
                lines.append(_RED_REFERENCE_NOTES[precedent_id])
                continue
            if include_precedent_cards:
                card_line = _precedent_card_line(precedent_id)
                if card_line:
                    lines.append(card_line)
        note = term_note(result.requirement_id)
        if note:
            lines.append(f"   ℹ️ {note}")
        return "\n".join(lines)

    if result.grade == "YELLOW":
        display_note = _condition_display_note(
            result.requirement_id, result.condition_id, result
        )
        if display_note:
            lines = [f"⚠️ {name}: {display_note}"]
        else:
            lines = [f"⚠️ {name}: {name}{_josa_i_ga(name)} {_YELLOW_VERB_PHRASE}"]
        if include_precedent_cards:
            for precedent_id in result.precedent_ids:
                card_line = _precedent_card_line(precedent_id)
                if card_line:
                    lines.append(card_line)
        if not display_note:
            note = term_note(result.requirement_id)
            if note:
                lines.append(f"   ℹ️ {note}")
        lines.append(_YELLOW_CTA)
        # 아직 열린 후속 질문이 있으면(예: 주소 building_number_only — 동·호수
        # 불명확) 함께 안내한다. 이미 답이 끝난 YELLOW(예: 봉투확인 승격)는
        # followup_question이 없어 이 줄이 붙지 않는다.
        if result.followup_question:
            lines.append(f"   ❓ {result.followup_question}")
        return "\n".join(lines)

    if result.grade == "WHITE":
        return _INTERSEAL_REFERENCE_LINE

    return None


# ---------------------------------------------------------------------------
# 가이드 모드 (피상속인 생전 준비, intent == "prepare") — 아직 작성 전인 사용자에게
# "이렇게 써야 합니다" + 흔한 실수 판례를 요건별로 안내한다. ✅/❌ 신호등 대신
# 📝 로 시작해 점검 결과가 아니라 안내임을 구분한다. guide 문구는 요건마다
# rules/requirements.json 의 requirements[].guide 에 있는 것만 쓴다 — 판례
# 인용도 review 모드와 동일하게 precedents.json 을 거쳐 (_precedent_citation)
# 만든다 (CLAUDE.md 원칙 3, 판례 재생성 금지).
# ---------------------------------------------------------------------------
HANDWRITTEN_GUIDE_INTRO = (
    "**자필증서 유언 작성 가이드입니다.** 아래 5가지 형식 요건을 지키면 형식 미비로 "
    "무효가 되는 것을 예방할 수 있습니다. 다만 이 안내는 형식 요건에 한정되며, 유언의 "
    "최종 유효성은 내용·작성 경위 등에 따라 달라질 수 있습니다."
)
RECORDING_GUIDE_INTRO = (
    "**녹음 유언 작성 가이드입니다.** 아래 요건을 지키면 형식 미비로 무효가 되는 것을 "
    "예방할 수 있습니다. 다만 이 안내는 형식 요건에 한정되며, 유언의 최종 유효성은 "
    "내용·작성 경위 등에 따라 달라질 수 있습니다."
)


def _find_requirement_or_none(requirement_id: str) -> Optional[dict[str, Any]]:
    rules = _load_rules()
    for req in rules["requirements"]:
        if req["id"] == requirement_id:
            return req
    return None


def guide_payload(requirement_id: str) -> Optional[dict[str, Any]]:
    """요건 하나의 가이드 정보를 구조화한다 (프론트가 카드 UI를 그릴 수 있도록).

    guide가 없는 요건(예: interseal)이면 None을 돌려준다.
    """
    req = _find_requirement_or_none(requirement_id)
    if req is None or not req.get("guide"):
        return None
    guide = req["guide"]
    return {
        "id": requirement_id,
        "name": req["name"],
        "instruction": guide["instruction"],
        "mistake_sentence": guide.get("mistake_sentence"),
        "mistake_precedent_id": guide.get("mistake_precedent_id"),
        "extra_note": guide.get("extra_note"),
    }


def format_guide_line(requirement_id: str) -> Optional[str]:
    """요건 하나를 "📝 {요건}: 이렇게 써야 합니다 + 흔한 실수 판례" 문구로 변환한다."""
    req = _find_requirement_or_none(requirement_id)
    if req is None or not req.get("guide"):
        return None
    guide = req["guide"]

    parts = [guide["instruction"]]
    precedent_id = guide.get("mistake_precedent_id")
    if precedent_id:
        card = _load_precedents().get(precedent_id)
        if card:
            parts.append(f"{guide['mistake_sentence']} {_precedent_citation(card)}.")
    if guide.get("extra_note"):
        parts.append(guide["extra_note"])

    return f"📝 {req['name']}: " + " ".join(parts)


def format_guide(
    ordered_ids: list[str], intro: str, *, include_closing: bool = True
) -> str:
    """가이드 모드 전체 화면 문구를 조립한다: 안내 인트로 → 요건별 가이드 → 상담 연결 → 하단 고지.

    include_closing=False 면 마무리 문구(§3-3 상담 연결 · §3-4 하단 고지)를 붙이지
    않는다 — 가이드 뒤에 초안 점검 결과(format_result)가 이어 붙는 경우, 그쪽에서
    이미 같은 두 줄을 붙이기 때문에 한 화면에 두 번 반복되는 것을 막기 위해서다.
    가이드만 단독으로 보여줄 때는 기본값(True) 그대로 두어야 §3-3/§3-4가 모든 결과
    화면에 들어간다는 스펙을 유지한다.
    """
    sections = [intro]
    for requirement_id in ordered_ids:
        line = format_guide_line(requirement_id)
        if line:
            sections.append(line)
    if include_closing:
        sections.append(_CONSULTATION_LINE)
        sections.append(_FOOTER_NOTICE)
    return "\n\n".join(sections)


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
        return _summary_pending(pending_count, len(formal_ids))
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
    conditions = (
        req["followup"]["conditions"]
        if requirement_id == "address"
        else req["conditions"]
    )
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


def progress(
    results: dict[str, RequirementResult],
    formal_ids: tuple[str, ...] = _FORMAL_REQUIREMENT_IDS,
) -> dict[str, int]:
    """요약 진행률: formal_ids 중 PENDING이 아닌(=이미 확인된) 요건 수 / 전체 수.

    interseal처럼 법정 요건이 아닌 항목(formal_ids 밖)은 세지 않는다 — 진행률은
    "충족 여부를 따지는 요건"이 대상이지, 참고용 항목까지 포함하면 분모가
    실제 판정 대상과 어긋난다. GREEN/RED/YELLOW는 전부 "확인됨"으로 센다 —
    등급이 무엇이든 텍스트/사용자 답변으로 판정이 끝났다는 뜻이라서다.
    """
    checked = sum(1 for rid in formal_ids if results[rid].grade != "PENDING")
    return {"checked": checked, "total": len(formal_ids)}


# body(P0-1)에서 카드로 안 만들고 참고 문구로만 남기는 판례 id — 새로 나열하지
# 않는다. _RED_REFERENCE_NOTES/_GREEN_REFERENCE_NOTES가 이미 "카드 아님"으로
# 분류해둔 것과 정확히 같은 집합이어야 하므로, 그 두 딕셔너리의 키를 그대로
# 재사용한다(단일 출처 유지 — 여기 따로 적으면 한쪽만 바뀌었을 때 어긋난다).
_EXCLUDED_FROM_PRECEDENT_LIST = frozenset(_RED_REFERENCE_NOTES) | frozenset(
    _GREEN_REFERENCE_NOTES
)


def _precedent_card(precedent_id: str) -> Optional[dict[str, str]]:
    """precedent_id → {case_no, summary} (예외 3건이거나 id 자체가 없으면 None).

    type이 commentary/statute라 case_number 가 null인 판례는 그 자리에 id를
    채운다 — 프론트가 case_no 로 필터링하며 null 항목을 통째로 버리기
    때문에, 값을 비워두면 조문·해설 근거 판례가 전부 누락된다.
    """
    if precedent_id in _EXCLUDED_FROM_PRECEDENT_LIST:
        return None
    card = _load_precedents().get(precedent_id)
    if not card:
        return None
    return {
        "case_no": card.get("case_number") or card["id"],
        "summary": card["summary"],
    }


def cited_precedents_for_requirement(
    result: RequirementResult,
) -> list[dict[str, str]]:
    """요건 하나(result)의 precedent_ids 만 반영한 {case_no, summary} 배열 (A안).

    같은 판례(예: 97다38510)를 여러 요건이 서로 다른 쟁점으로 인용해도,
    이 함수는 그 요건에 실제로 걸린 precedent_id 만 본다 — 다른 요건의
    판례가 섞여 들어오지 않는다.
    """
    seen: set[str] = set()
    precedents: list[dict[str, str]] = []
    for precedent_id in result.precedent_ids:
        if precedent_id in seen:
            continue
        seen.add(precedent_id)
        card = _precedent_card(precedent_id)
        if card:
            precedents.append(card)
    return precedents


def cited_precedents(
    results: dict[str, RequirementResult],
) -> list[dict[str, str]]:
    """이번 판정 전체에서 실제로 인용된 판례를 {case_no, summary} 배열로 모은다.

    results 의 모든 요건에서 precedent_ids 를 훑어 등장 순서대로 중복
    제거한다. _EXCLUDED_FROM_PRECEDENT_LIST(카드로 안 만들기로 한 예외
    3건)는 뺀다 — 이 셋은 format_requirement_line 이 body 안에 참고
    문구로 이미 남긴다.
    """
    seen: set[str] = set()
    precedents: list[dict[str, str]] = []
    for result in results.values():
        for precedent_id in result.precedent_ids:
            if precedent_id in seen:
                continue
            seen.add(precedent_id)
            card = _precedent_card(precedent_id)
            if card:
                precedents.append(card)
    return precedents


def format_result(
    results: dict[str, RequirementResult],
    *,
    formal_ids: tuple[str, ...] = _FORMAL_REQUIREMENT_IDS,
    ordered_ids: Optional[list[str]] = None,
    messages: SummaryMessages = _HANDWRITTEN_SUMMARY_MESSAGES,
    include_precedent_cards: bool = True,
) -> str:
    """전체 화면 문구를 조립한다: 요약 → (확인 질문) → 요건별 문구 → 상담 연결 → 하단 고지.

    ordered_ids 를 생략하면 rules/requirements.json 전체를 order 순으로 훑되,
    results 에 실제로 있는 요건만 남긴다(handwritten 기본 동작). recording처럼
    다른 요건 집합을 렌더링하려면 ordered_ids/formal_ids/messages 를 명시한다.

    include_precedent_cards=False 면 요건별 줄에서 판례 인용 카드만 뺀다
    (format_requirement_line 참고) — P0-1의 body 가 이 옵션으로
    reply 와 같은 함수를 재사용해서, 판례 카드는 precedents 배열로만
    중복 없이 나가게 한다.
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
            "\n".join(
                f"- {item['requirement']}: {item['question']}" for item in pending
            )
        )

    for requirement_id in ordered_ids:
        line = format_requirement_line(
            results[requirement_id], include_precedent_cards=include_precedent_cards
        )
        if line:
            sections.append(line)

    sections.append(_CONSULTATION_LINE)
    sections.append(_FOOTER_NOTICE)

    return "\n\n".join(sections)

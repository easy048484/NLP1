"""
판정 결과(RequirementResult) → 화면 문구 변환기.

요건판정_문구_스펙_v1.md §3(화면 문구)를 그대로 구현한다. 아래 고정 문장들은
스펙 문서와 글자 하나 다르지 않아야 한다 — 문구를 바꿀 일이 있으면 스펙 문서를
먼저 고친 뒤 이 파일을 고칠 것 (§4 가드레일: 단정 표현 금지 등도 스펙 문구 안에
이미 반영되어 있으므로 별도로 재가공하지 않는다).

{요건}/{무엇}/{쟁점} 자리에는 요건 이름(RequirementResult.name)을 넣는다. 스펙
원문은 뒤에 오는 조사를 "이"로 고정 표기했지만, "주소이"처럼 실제로는 어색한
조합이 생겨 받침 유무에 따라 "이/가"를 올바르게 골라 붙인다 — 그 외 문장은
전부 스펙 원문 그대로다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .requirement_checker import RequirementResult

_PRECEDENTS_PATH = Path(__file__).parent / "rules" / "precedents.json"
_RULES_PATH = Path(__file__).parent / "rules" / "requirements.json"

# "5가지 형식 요건" — 간인은 법정 요건이 아니라서(is_legal_requirement: false) 제외한다.
_FORMAL_REQUIREMENT_IDS = ("date", "address", "name", "handwriting", "seal")

# ---------------------------------------------------------------------------
# §3-1. 전체 요약 (4케이스) — 스펙 원문 그대로
# ---------------------------------------------------------------------------
_SUMMARY_ALL_GREEN = (
    "**형식 요건상 문제가 발견되지 않았습니다.** 자필증서 유언의 5가지 형식 요건"
    "(자서·연월일·주소·성명·날인)이 모두 확인됩니다. 다만 이 점검은 형식 요건에 한정되며, "
    "유언의 최종 유효성은 내용·작성 경위 등에 따라 달라질 수 있습니다."
)
_SUMMARY_HAS_RED = (
    "**확인되지 않는 요건이 있습니다.** 아래 항목은 법원이 무효로 판단해온 사례와 같은 "
    "쟁점에 해당할 수 있습니다. 법률 전문가 확인을 권합니다."
)
_SUMMARY_YELLOW_ONLY = (
    "**전문가 확인이 필요한 부분이 있습니다.** 형식상 명확한 문제는 발견되지 않았으나, "
    "법원 판단이 사안에 따라 갈린 쟁점이 포함되어 있습니다."
)
def _summary_pending(count: int) -> str:
    """D 케이스: PENDING 개수 n으로 동적 치환 (1개면 "한 가지")."""
    count_word = "한 가지" if count == 1 else f"{count}가지"
    return f"**{count_word}만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 항목입니다."

# ---------------------------------------------------------------------------
# §3-2. 요건별 문구 패턴의 고정 부분 — 스펙 원문 그대로
# ---------------------------------------------------------------------------
_RED_VERB_PHRASE = "확인되지 않습니다"
_RED_CTA = "→ 법률 전문가 확인을 권합니다"
_YELLOW_VERB_PHRASE = "쟁점이 될 수 있습니다"
_YELLOW_CTA = "→ 개별 판단이 필요합니다. 법률 상담을 권합니다"
_INTERSEAL_REFERENCE_LINE = (
    "ℹ️ 참고: 간인은 법정 요건이 아니지만, 여러 장일 경우 위조 다툼 예방에 도움이 됩니다"
)

# ---------------------------------------------------------------------------
# §3-3 / §3-4 — 스펙 원문 그대로
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


def _precedent_card_line(precedent_id: str) -> Optional[str]:
    card = _load_precedents().get(precedent_id)
    if not card:
        return None
    return f"{card['one_liner']} [카드]"


def _extracted_display_value(result: RequirementResult) -> Optional[str]:
    """§3-2 GREEN 패턴의 "(+ 추출값 표시)" 부분."""
    if result.requirement_id == "date":
        entries = result.extracted.get("entries") or []
        if len(entries) == 1:
            e = entries[0]
            if e.get("year") and e.get("month") and e.get("day"):
                return f"{e['year']}년 {e['month']}월 {e['day']}일"
        return None

    if result.requirement_id in ("address", "name"):
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
        lines = [f"❌ {name}: {name}{_josa_i_ga(name)} {_RED_VERB_PHRASE}"]
        for precedent_id in result.precedent_ids:
            card_line = _precedent_card_line(precedent_id)
            if card_line:
                lines.append(card_line)
        lines.append(_RED_CTA)
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


def summarize(results: dict[str, RequirementResult]) -> str:
    """§3-1: 5가지 형식 요건의 등급 조합으로 A/B/C/D 중 하나를 고른다.

    우선순위: PENDING(아직 판정 불가) > RED > YELLOW > 전부 GREEN.
    """
    grades = [results[rid].grade for rid in _FORMAL_REQUIREMENT_IDS]

    pending_count = grades.count("PENDING")
    if pending_count:
        return _summary_pending(pending_count)
    if "RED" in grades:
        return _SUMMARY_HAS_RED
    if "YELLOW" in grades:
        return _SUMMARY_YELLOW_ONLY
    return _SUMMARY_ALL_GREEN


def pending_questions(results: dict[str, RequirementResult]) -> list[tuple[str, str]]:
    """D 케이스에서 실제로 물어봐야 할 (요건 이름, 질문) 목록.

    §3 본문에는 없는 보조 기능이지만, "2가지만 직접 확인해주세요"라는 요약 문구
    뒤에 실제로 무엇을 물어야 하는지가 있어야 화면을 완성할 수 있어 추가했다.
    질문 문구 자체는 rules/requirements.json 에 이미 있는 값을 그대로 쓴다.
    """
    return [
        (results[rid].name, results[rid].followup_question)
        for rid in _FORMAL_REQUIREMENT_IDS
        if results[rid].grade == "PENDING" and results[rid].followup_question
    ]


def format_result(results: dict[str, RequirementResult]) -> str:
    """전체 화면 문구를 조립한다: 요약 → (확인 질문) → 요건별 문구 → 상담 연결 → 하단 고지."""
    rules = _load_rules()
    ordered_ids = [
        req["id"] for req in sorted(rules["requirements"], key=lambda r: r["order"])
    ]

    sections = [summarize(results)]

    pending = pending_questions(results)
    if pending:
        sections.append(
            "\n".join(f"- {name}: {question}" for name, question in pending)
        )

    for requirement_id in ordered_ids:
        line = format_requirement_line(results[requirement_id])
        if line:
            sections.append(line)

    sections.append(_CONSULTATION_LINE)
    sections.append(_FOOTER_NOTICE)

    return "\n\n".join(sections)

"""사용자 발화에서 슬롯 추출.

두 단계입니다.

1. 규칙 기반: 명시적인 날짜와 뚜렷한 진행상태 표현. LLM 없이도 동작하므로
   API 키가 없는 환경(CI 포함)에서도 에이전트가 끝에서 끝까지 돕니다.
2. Claude: "작년 이맘때쯤", "장례는 치렀고 아직 아무것도 못 했어요" 같은
   자연스러운 표현. 도구 호출을 강제해서 구조화된 dict로 받습니다.

LLM이 실패하거나 키가 없으면 1번 결과만 씁니다. 조용히 규칙 기반으로
내려가되, 지어낸 값을 채우지는 않습니다.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from llm.claude import LLMUnavailable, extract

from .procedure import StepId
from .state import SlotUpdate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 규칙 기반

_FULL_DATE = re.compile(
    r"(?P<year>\d{4})\s*[년./\-]\s*(?P<month>\d{1,2})\s*[월./\-]\s*(?P<day>\d{1,2})\s*일?"
)

_COMPLETED_PATTERNS: tuple[tuple[StepId, re.Pattern[str]], ...] = (
    (
        StepId.DEATH_REPORT,
        re.compile(r"사망\s*신고[^.\n]{0,10}(했|完|완료|끝|마쳤|접수)"),
    ),
    (
        StepId.ONE_STOP,
        re.compile(r"(안심\s*상속|원스톱)[^.\n]{0,15}(했|신청|완료|접수)"),
    ),
    (
        StepId.ASSET_SEARCH,
        re.compile(r"(재산\s*조회|조회\s*결과)[^.\n]{0,15}(했|나왔|받았|확인|왔)"),
    ),
    (
        StepId.ACCEPT_DECIDE,
        re.compile(r"(한정승인|상속\s*포기)[^.\n]{0,15}(했|신고|접수|완료)"),
    ),
    (
        StepId.DIVISION,
        re.compile(r"(분할\s*협의|협의서)[^.\n]{0,15}(했|썼|작성|완료|서명)"),
    ),
    (
        StepId.REGISTRATION,
        re.compile(r"(상속\s*등기|명의\s*이전)[^.\n]{0,15}(했|완료|끝|넘겼)"),
    ),
    (StepId.INHERIT_TAX, re.compile(r"상속세[^.\n]{0,15}(신고했|납부했|냈|완료)")),
)

_DEBT_YES = re.compile(r"(빚|채무|대출|카드값|사채)[^.\n]{0,12}(있|남았|많|딸려|껴)")
_DEBT_NO = re.compile(r"(빚|채무|대출)[^.\n]{0,12}(없|안\s*남|하나도)")

_WILL_YES = re.compile(r"유언(장|서)?[^.\n]{0,12}(있|남기셨|남겼|찾았|발견)")
_WILL_NO = re.compile(r"유언(장|서)?[^.\n]{0,12}(없|안\s*남기|못\s*찾)")

_AGREEMENT_DONE = re.compile(r"협의[^.\n]{0,12}(끝|완료|마쳤|다\s*했)")
_AGREEMENT_PROGRESS = re.compile(r"협의[^.\n]{0,12}(중|하고\s*있|진행)")


def _parse_dates(text: str) -> list[date]:
    found: list[date] = []
    for match in _FULL_DATE.finditer(text):
        try:
            found.append(
                date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    return found


def rule_based(message: str) -> SlotUpdate:
    text = message or ""
    dates = _parse_dates(text)

    update = SlotUpdate()
    if dates:
        # 발화에 날짜가 하나만 있으면 사망일로 봅니다. 여러 개면 애매하므로
        # 규칙 기반에서는 손대지 않고 LLM/되묻기에 맡깁니다.
        if len(dates) == 1:
            update.death_date = dates[0]

    update.completed_steps = [
        step_id for step_id, pattern in _COMPLETED_PATTERNS if pattern.search(text)
    ]

    if _DEBT_NO.search(text):
        update.has_debt = "no"
    elif _DEBT_YES.search(text):
        update.has_debt = "yes"

    if _WILL_NO.search(text):
        update.will_exists = "no"
    elif _WILL_YES.search(text):
        update.will_exists = "yes"

    if _AGREEMENT_DONE.search(text):
        update.agreement = "done"
    elif _AGREEMENT_PROGRESS.search(text):
        update.agreement = "in_progress"

    return update


# ------------------------------------------------------------------- Claude

_TOOL: dict[str, Any] = {
    "name": "record_heir_slots",
    "description": (
        "사용자 발화에서 상속 절차 안내에 필요한 정보를 추출한다. "
        "발화에 근거가 없는 항목은 반드시 null 또는 빈 배열로 둔다. 추측하지 않는다."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "death_date": {
                "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
                "description": (
                    "사망일(상속개시일)을 YYYY-MM-DD로. 연도나 월을 특정할 수 없으면 null. "
                    "'작년 3월'처럼 연도만 추론 가능하고 날짜를 모르면 null."
                ),
            },
            "known_date": {
                "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
                "description": (
                    "상속개시(사망) 사실을 알게 된 날. 사망일과 다르다고 명시적으로 "
                    "말했을 때만 채운다. 언급이 없으면 null."
                ),
            },
            "completed_steps": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [step.value for step in StepId],
                },
                "description": "사용자가 이미 마쳤다고 말한 절차 단계만. 예정·계획은 제외.",
            },
            "has_debt": {
                "anyOf": [
                    {"type": "string", "enum": ["yes", "no", "unknown"]},
                    {"type": "null"},
                ],
                "description": "상속재산에 빚(채무)이 포함되는지. 언급이 없으면 null.",
            },
            "will_exists": {
                "anyOf": [
                    {"type": "string", "enum": ["yes", "no", "unknown"]},
                    {"type": "null"},
                ],
                "description": "유언장 존재 여부. 언급이 없으면 null.",
            },
            "agreement": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": ["none", "in_progress", "done", "conflict"],
                    },
                    {"type": "null"},
                ],
                "description": "공동상속인 간 분할협의 진행 상태. 언급이 없으면 null.",
            },
        },
        "required": [
            "death_date",
            "known_date",
            "completed_steps",
            "has_debt",
            "will_exists",
            "agreement",
        ],
        "additionalProperties": False,
    },
}

_EXTRACT_SYSTEM = """당신은 한국 상속 절차 상담 대화에서 정보를 추출하는 도구입니다. 답변을 생성하지 말고 record_heir_slots 도구만 호출하세요.

규칙:
- 발화에 근거가 없는 값은 절대 채우지 않습니다. 확실하지 않으면 null입니다.
- 날짜는 오늘 날짜({today})를 기준으로 상대 표현("작년", "지난달", "3개월 전")을 해석합니다. 일자까지 특정할 수 없으면 null입니다.
- "~하려고 한다", "~할 예정"은 완료가 아닙니다. completed_steps에 넣지 마세요.
- 사용자가 질문만 했다면 모든 값이 null/빈 배열인 것이 정상입니다."""


def llm_based(message: str, *, today: date | None = None) -> SlotUpdate | None:
    """Claude로 슬롯 추출. 키가 없거나 실패하면 None."""
    today = today or date.today()
    try:
        raw = extract(
            system=_EXTRACT_SYSTEM.format(today=today.isoformat()),
            user_text=message,
            tool=_TOOL,
        )
    except LLMUnavailable as exc:
        logger.debug("슬롯 추출 LLM 사용 불가, 규칙 기반만 사용: %s", exc)
        return None
    except Exception:  # pragma: no cover - 네트워크/SDK 예외
        logger.exception("슬롯 추출 실패, 규칙 기반만 사용")
        return None

    try:
        return SlotUpdate.model_validate(raw)
    except Exception:
        logger.warning("슬롯 추출 결과가 스키마와 맞지 않음: %r", raw)
        return None


def _merge_updates(primary: SlotUpdate, secondary: SlotUpdate | None) -> SlotUpdate:
    """규칙 기반 결과를 우선하고, 비어 있는 자리만 LLM 결과로 채웁니다."""
    if secondary is None:
        return primary
    data = primary.model_dump()
    for field in ("death_date", "known_date", "has_debt", "will_exists", "agreement"):
        if data.get(field) is None:
            data[field] = getattr(secondary, field)
    data["completed_steps"] = sorted(
        {*(primary.completed_steps or []), *(secondary.completed_steps or [])}
    )
    return SlotUpdate.model_validate(data)


def extract_slots(
    message: str, *, today: date | None = None, use_llm: bool = True
) -> SlotUpdate:
    """한 턴의 발화에서 슬롯을 뽑습니다."""
    rules = rule_based(message)
    if not use_llm:
        return rules
    return _merge_updates(rules, llm_based(message, today=today))

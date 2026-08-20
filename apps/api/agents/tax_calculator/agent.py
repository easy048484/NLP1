"""상속세 계산·준비 에이전트.

사용자에게 필요한 정보를 순서대로 질문하고,
수집한 정보를 결정론적 상속세 계산 엔진에 전달합니다.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from schemas import AgentInput, AgentName, AgentOutput

from .calculator import calculate_inheritance_tax
from .models import InheritanceTaxInput

STATE_KEY = "tax_calculator"

BOOL_SLOTS = {
    "decedent_is_resident",
    "spouse_exists",
    "filing_within_deadline",
}

MONEY_SLOTS = {
    "original_inherited_property",
    "debts",
    "financial_assets",
    "financial_debts",
    "prior_gifts_to_heirs",
    "prior_gifts_to_non_heirs",
    "spouse_actual_inheritance",
}

QUESTIONS = {
    "decedent_is_resident": (
        "먼저 피상속인이 사망 당시 국내 거주자였는지 알려주세요. "
        "국내 거주자였다면 '네', 아니면 '아니요'라고 답해주세요."
    ),
    "spouse_exists": (
        "피상속인의 배우자가 현재 생존해 있나요? " "'네' 또는 '아니요'로 알려주세요."
    ),
    "children_count": (
        "피상속인의 생존 자녀는 몇 명인가요? " "예: '2명', 자녀가 없다면 '0명'"
    ),
    "original_inherited_property": (
        "부동산, 예금, 주식 등 본래의 상속재산은 총 얼마인가요? "
        "예: '10억원' 또는 '500000000원'"
    ),
    "debts": (
        "상속재산에서 차감할 대출이나 그 밖의 채무는 얼마인가요? "
        "없다면 '0원'이라고 입력해주세요."
    ),
    "financial_assets": (
        "예금·적금·주식·보험금 등 공제대상 금융재산은 얼마인가요? "
        "없다면 '0원'이라고 입력해주세요."
    ),
    "financial_debts": (
        "전체 채무 중 금융기관에서 빌린 금융채무는 얼마인가요? "
        "없다면 '0원'이라고 입력해주세요."
    ),
    "prior_gifts_to_heirs": (
        "사망 전 10년 이내에 상속인에게 증여한 재산이 있나요? "
        "금액을 입력하고, 없다면 '0원'이라고 입력해주세요."
    ),
    "prior_gifts_to_non_heirs": (
        "사망 전 5년 이내에 상속인이 아닌 사람에게 증여한 재산이 있나요? "
        "금액을 입력하고, 없다면 '0원'이라고 입력해주세요."
    ),
    "spouse_actual_inheritance": (
        "배우자가 실제로 상속받는 순재산은 얼마인가요? "
        "아직 정해지지 않았다면 '0원'이라고 입력해주세요."
    ),
    "filing_within_deadline": (
        "법정 신고기한 안에 상속세를 신고할 예정인가요? "
        "'네' 또는 '아니요'로 알려주세요."
    ),
}


def _empty_state() -> dict[str, Any]:
    """새로운 상속세 대화 상태를 만든다."""

    return {
        "status": "collecting",
        "values": {},
        "confirmed_fields": [],
        "asked_slot": None,
        "missing_fields": [],
        "last_result": None,
    }


def _load_state(context: dict[str, Any] | None) -> dict[str, Any]:
    """이전 대화에서 저장한 상속세 상태를 불러온다."""

    raw_state = (context or {}).get(STATE_KEY)

    if not isinstance(raw_state, dict):
        return _empty_state()

    state = _empty_state()

    if isinstance(raw_state.get("values"), dict):
        state["values"] = dict(raw_state["values"])

    if isinstance(raw_state.get("confirmed_fields"), list):
        state["confirmed_fields"] = list(raw_state["confirmed_fields"])

    if isinstance(raw_state.get("asked_slot"), str):
        state["asked_slot"] = raw_state["asked_slot"]

    if isinstance(raw_state.get("last_result"), dict):
        state["last_result"] = dict(raw_state["last_result"])

    return state


def _mark_confirmed(state: dict[str, Any], field_name: str) -> None:
    """확정된 입력 항목을 중복 없이 기록한다."""

    confirmed_fields = state["confirmed_fields"]

    if field_name not in confirmed_fields:
        confirmed_fields.append(field_name)


def _apply_structured_context(
    payload: AgentInput,
    state: dict[str, Any],
) -> None:
    """프론트나 테스트가 context로 직접 전달한 계산 입력을 반영한다."""

    tax_input = (payload.context or {}).get("tax_input")

    if not isinstance(tax_input, dict):
        return

    allowed_fields = InheritanceTaxInput.model_fields

    for field_name, value in tax_input.items():
        if field_name not in allowed_fields:
            continue

        state["values"][field_name] = value
        _mark_confirmed(state, field_name)


def _apply_family_graph(
    family_graph: dict[str, Any] | None,
    state: dict[str, Any],
) -> None:
    """가족관계 그래프의 배우자·자녀 정보를 계산 입력으로 변환한다."""

    if not isinstance(family_graph, dict):
        return

    values = state["values"]
    heirs = family_graph.get("heirs")

    if isinstance(heirs, list):
        alive_heirs = [
            heir for heir in heirs if isinstance(heir, dict) and heir.get("alive", True)
        ]

        spouse_exists = any(heir.get("relation") == "spouse" for heir in alive_heirs)
        children_count = sum(heir.get("relation") == "child" for heir in alive_heirs)
        spouse_is_sole_heir = (
            len(alive_heirs) == 1 and alive_heirs[0].get("relation") == "spouse"
        )

        values["spouse_exists"] = spouse_exists
        values["children_count"] = children_count
        values["spouse_is_sole_heir"] = spouse_is_sole_heir

        _mark_confirmed(state, "spouse_exists")
        _mark_confirmed(state, "children_count")
        _mark_confirmed(state, "spouse_is_sole_heir")
        return

    # 과거 형식의 가족관계 데이터도 임시로 지원한다.
    if "spouse_alive" in family_graph:
        values["spouse_exists"] = bool(family_graph["spouse_alive"])
        _mark_confirmed(state, "spouse_exists")

    if "num_children" in family_graph:
        try:
            values["children_count"] = int(family_graph["num_children"])
            _mark_confirmed(state, "children_count")
        except (TypeError, ValueError):
            pass


def _parse_yes_or_no(message: str) -> bool | None:
    """사용자 답변에서 네/아니요를 해석한다."""

    normalized = message.strip().lower().replace(" ", "")

    negative_words = (
        "아니",
        "아뇨",
        "없",
        "비거주",
        "기한후",
        "못해",
        "안해",
    )
    positive_words = (
        "네",
        "예",
        "응",
        "맞",
        "있",
        "거주자",
        "기한내",
        "할예정",
    )

    if any(word in normalized for word in negative_words):
        return False

    if any(word in normalized for word in positive_words):
        return True

    return None


def _parse_count(message: str) -> int | None:
    """'2명', '자녀 없음' 같은 답변을 정수로 변환한다."""

    normalized = message.strip().replace(",", "")

    if any(word in normalized for word in ("없", "영명", "0명")):
        return 0

    match = re.search(r"\d+", normalized)

    if match is None:
        return None

    return int(match.group())


def _parse_money(message: str) -> int | None:
    """'10억', '5천만원', '300000000원'을 원 단위 정수로 변환한다."""

    normalized = message.strip().replace(",", "").replace(" ", "")

    if any(word in normalized for word in ("없", "없음", "0원")):
        return 0

    multipliers = {
        "조": 1_000_000_000_000,
        "억": 100_000_000,
        "천만": 10_000_000,
        "백만": 1_000_000,
        "만": 10_000,
        "원": 1,
    }

    matches = re.findall(
        r"(\d+(?:\.\d+)?)(조|억|천만|백만|만|원)",
        normalized,
    )

    if matches:
        total = Decimal("0")

        for number, unit in matches:
            total += Decimal(number) * multipliers[unit]

        return int(total)

    plain_number = re.fullmatch(r"\d+", normalized)

    if plain_number:
        return int(normalized)

    return None


def _apply_previous_answer(
    message: str,
    state: dict[str, Any],
) -> bool:
    """직전 질문에 대한 사용자 답변을 상태에 반영한다."""

    asked_slot = state.get("asked_slot")

    if not isinstance(asked_slot, str):
        return True

    if asked_slot in BOOL_SLOTS:
        parsed_value = _parse_yes_or_no(message)
    elif asked_slot == "children_count":
        parsed_value = _parse_count(message)
    elif asked_slot in MONEY_SLOTS:
        parsed_value = _parse_money(message)
    else:
        parsed_value = None

    if parsed_value is None:
        return False

    state["values"][asked_slot] = parsed_value
    _mark_confirmed(state, asked_slot)
    state["asked_slot"] = None

    return True


def _missing_slots(values: dict[str, Any]) -> list[str]:
    """계산 전에 사용자에게 물어봐야 할 항목을 순서대로 반환한다."""

    slot_order = [
        "decedent_is_resident",
        "spouse_exists",
        "children_count",
        "original_inherited_property",
        "debts",
        "financial_assets",
        "financial_debts",
        "prior_gifts_to_heirs",
        "prior_gifts_to_non_heirs",
    ]

    if values.get("spouse_exists") is True:
        slot_order.append("spouse_actual_inheritance")

    slot_order.append("filing_within_deadline")

    return [slot for slot in slot_order if slot not in values]


def _won(value: int) -> str:
    """원 단위 금액을 읽기 쉬운 형식으로 표시한다."""

    return f"{value:,}원"


def _result_reply(result: Any) -> str:
    """계산 결과를 쉬운 말로 변환한다."""

    lines = [
        "입력하신 정보를 기준으로 상속세를 계산했습니다.",
        "",
        f"- 총상속재산가액: {_won(result.total_inherited_property)}",
        f"- 공제 가능한 비용·채무: {_won(result.deductible_expenses)}",
        f"- 상속세 과세가액: {_won(result.taxable_inheritance_value)}",
        f"- 적용된 상속공제: {_won(result.total_inheritance_deduction)}",
        f"- 상속세 과세표준: {_won(result.inheritance_tax_base)}",
        f"- 산출세액: {_won(result.calculated_inheritance_tax)}",
        f"- 신고세액공제: {_won(result.filing_tax_credit)}",
        f"- 예상 납부세액: {_won(result.estimated_tax_due)}",
    ]

    if result.estimated_filing_deadline is not None:
        lines.extend(
            [
                "",
                (
                    "예상 신고기한은 "
                    f"{result.estimated_filing_deadline.isoformat()}입니다."
                ),
            ]
        )

    if result.warnings:
        lines.append("")
        lines.append("확인할 사항:")

        for warning in result.warnings:
            lines.append(f"- {warning}")

    lines.extend(
        [
            "",
            (
                "이 결과는 현재 입력한 정보에 따른 참고용 시뮬레이션입니다. "
                "실제 신고 전에는 홈택스 또는 세무 전문가를 통해 확인해주세요."
            ),
        ]
    )

    return "\n".join(lines)


def run(payload: AgentInput) -> AgentOutput:
    """상속세 정보를 수집하고 계산 결과를 반환한다."""

    state = _load_state(payload.context)

    _apply_structured_context(payload, state)
    _apply_family_graph(payload.family_graph, state)

    if not _apply_previous_answer(payload.user_message, state):
        asked_slot = state["asked_slot"]
        state["status"] = "collecting"
        state["missing_fields"] = _missing_slots(state["values"])

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=("답변을 이해하지 못했습니다.\n\n" f"{QUESTIONS[asked_slot]}"),
            next_action=None,
            data={STATE_KEY: state},
        )

    values = state["values"]

    if values.get("decedent_is_resident") is False:
        state["status"] = "unsupported"
        state["asked_slot"] = None
        state["missing_fields"] = []

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=(
                "현재 상속세 계산기는 피상속인이 국내 거주자인 경우만 "
                "지원합니다. 비거주자 상속은 국내 재산 범위와 공제 기준이 "
                "다르므로 세무 전문가의 확인이 필요합니다."
            ),
            next_action=None,
            data={STATE_KEY: state},
        )

    missing_slots = _missing_slots(values)

    if missing_slots:
        next_slot = missing_slots[0]

        state["status"] = "collecting"
        state["asked_slot"] = next_slot
        state["missing_fields"] = missing_slots

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=QUESTIONS[next_slot],
            next_action=None,
            data={STATE_KEY: state},
        )

    try:
        tax_input = InheritanceTaxInput.model_validate(values)
        result = calculate_inheritance_tax(tax_input)
    except (ValidationError, ValueError) as exc:
        state["status"] = "needs_review"
        state["asked_slot"] = None
        state["last_error"] = str(exc)

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=(
                "입력한 정보 사이에 서로 맞지 않는 부분이 있어 계산하지 "
                "못했습니다. 재산과 채무 금액을 다시 확인해주세요.\n\n"
                f"확인 내용: {exc}"
            ),
            next_action=None,
            data={STATE_KEY: state},
        )

    state["status"] = "calculated"
    state["asked_slot"] = None
    state["missing_fields"] = []
    state["last_result"] = result.model_dump(mode="json")

    return AgentOutput(
        agent=AgentName.TAX_CALCULATOR,
        reply=_result_reply(result),
        next_action=None,
        data={STATE_KEY: state},
    )

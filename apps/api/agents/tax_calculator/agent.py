"""상속세 계산·준비 에이전트.

사용자에게 필요한 정보를 순서대로 질문하고,
수집한 정보를 결정론적 상속세 계산 엔진에 전달합니다.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from family_graph.heirs import classify_heirs
from schemas import AgentInput, AgentName, AgentOutput

from agents._money import parse_money as _parse_money

from .calculator import calculate_inheritance_tax
from .models import InheritanceTaxInput
from .presentation import result_reply, user_error_reply

STATE_KEY = "tax_calculator"

BOOL_SLOTS = {
    "decedent_is_resident",
    "spouse_exists",
    "spouse_is_sole_heir",
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
        "먼저 돌아가신 분이 사망 당시 국내에 거주하셨는지 알려주세요. "
        "국내 거주자였다면 '네', 아니면 '아니요'라고 답해주세요."
    ),
    "spouse_exists": (
        "돌아가신 분의 배우자가 현재 생존해 있나요? " "'네' 또는 '아니요'로 알려주세요."
    ),
    "children_count": (
        "돌아가신 분의 생존 자녀는 몇 명인가요? " "예: '2명', 자녀가 없다면 '0명'"
    ),
    "spouse_is_sole_heir": (
        "자녀가 없으시군요. 배우자만 상속받나요, 아니면 돌아가신 분의 "
        "부모님이나 조부모님도 함께 상속받나요? 배우자만 받는다면 '네', "
        "부모님이나 조부모님도 함께 받는다면 '아니요'로 답해주세요."
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
        "정해진 신고기한 안에 상속세를 신고할 예정인가요? "
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
        "has_grandchild_heir": False,
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

    state["has_grandchild_heir"] = raw_state.get("has_grandchild_heir") is True
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


def _apply_shared_estate(
    payload: AgentInput,
    state: dict[str, Any],
) -> None:
    """세션 공유 상속재산(financial_profile)에서 계산 슬롯을 미리 채운다.

    asset_organizer가 이미 자산·부채를 정리했으면 사용자에게 총상속재산·채무·
    금융재산을 다시 묻지 않는다. 값이 일부만 있으면 나머지 슬롯만 기존 Q&A로
    질문한다(부분 병합). 이미 사용자가 직접 확인한 값(confirmed_fields)은
    덮어쓰지 않는다.
    """
    estate = payload.financial_profile
    if estate is None:
        return

    values = state["values"]
    confirmed = state["confirmed_fields"]

    total_assets = sum(
        v
        for v in (
            estate.real_estate_value,
            estate.financial_assets,
            estate.other_assets,
        )
        if v is not None
    )
    has_any_asset_field = any(
        v is not None
        for v in (
            estate.real_estate_value,
            estate.financial_assets,
            estate.other_assets,
        )
    )

    def _prefill(field_name: str, value: int | None) -> None:
        if value is None or field_name in confirmed:
            return
        values[field_name] = value
        _mark_confirmed(state, field_name)

    if has_any_asset_field:
        _prefill("original_inherited_property", total_assets)
    _prefill("financial_assets", estate.financial_assets)
    _prefill("debts", estate.total_debts)
    _prefill("financial_debts", estate.financial_debts)


def _apply_family_graph(
    family_graph: dict[str, Any] | None,
    state: dict[str, Any],
) -> None:
    """가족관계 그래프의 배우자·자녀 정보를 계산 입력으로 변환한다.

    상속인 순위 판정은 공용 모듈(family_graph.heirs.classify_heirs)에 위임한다 —
    heir_share_analyzer·heir_navigator와 같은 규칙을 쓰기 위해서다.
    """
    classification = classify_heirs(family_graph)
    if not classification.has_family_data:
        return

    values = state["values"]
    values["spouse_exists"] = classification.spouse_exists
    values["children_count"] = classification.children_count
    state["has_grandchild_heir"] = classification.has_grandchild_heir
    _mark_confirmed(state, "spouse_exists")
    _mark_confirmed(state, "children_count")

    # spouse_is_sole_heir는 부모(2순위) 정보까지 있는 완전한 상속인 목록
    # (형태 A: {"heirs": [...]})일 때만 확정한다. 레거시 형태
    # ({"spouse_alive", "num_children"})는 부모 생존 여부를 알 수 없으므로
    # 기존처럼 사용자에게 물어본다.
    has_full_heir_list = isinstance(family_graph, dict) and isinstance(
        family_graph.get("heirs"), list
    )
    if has_full_heir_list:
        values["spouse_is_sole_heir"] = classification.spouse_is_sole_heir
        _mark_confirmed(state, "spouse_is_sole_heir")


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
    ]

    # 배우자가 있고 자녀가 없으면, 배우자가 단독상속인인지(부모님과 공동상속이
    # 아닌지) 자녀 수 바로 다음에 확인해야 한다 — 안 물어보면 spouse_is_sole_heir가
    # 기본값 False로 남아 계산이 실패한다.
    if values.get("spouse_exists") is True and values.get("children_count") == 0:
        slot_order.append("spouse_is_sole_heir")

    slot_order.extend(
        [
            "original_inherited_property",
            "debts",
            "financial_assets",
            "financial_debts",
            "prior_gifts_to_heirs",
            "prior_gifts_to_non_heirs",
        ]
    )

    if values.get("spouse_exists") is True:
        slot_order.append("spouse_actual_inheritance")

    slot_order.append("filing_within_deadline")

    return [slot for slot in slot_order if slot not in values]


def run(payload: AgentInput) -> AgentOutput:
    """상속세 정보를 수집하고 계산 결과를 반환한다."""

    state = _load_state(payload.context)

    _apply_structured_context(payload, state)
    _apply_shared_estate(payload, state)
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
                "현재 상속세 계산기는 돌아가신 분이 사망 당시 국내에 거주한 "
                "경우만 지원합니다. 해외 거주자의 상속은 국내 재산 범위와 공제 기준이 "
                "다르므로 세무 전문가의 확인이 필요합니다."
            ),
            next_action=None,
            data={STATE_KEY: state},
        )
    if state.get("has_grandchild_heir") is True:
        state["status"] = "unsupported"
        state["asked_slot"] = None
        state["missing_fields"] = []

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=(
                "자녀분이 먼저 돌아가시고 손주가 대신 상속받는 경우인가요?\n\n"
                "이 경우에는 손주가 어느 자녀분을 대신해 상속받는지에 따라 "
                "배우자와 손주의 몫이 달라질 수 있습니다. 현재 계산기에서는 "
                "이 경우의 지분 계산을 아직 지원하지 않으므로 세무 전문가의 "
                "확인이 필요합니다."
            ),
            next_action=None,
            data={STATE_KEY: state},
        )
    if (
        values.get("spouse_exists") is True
        and values.get("children_count") == 0
        and values.get("spouse_is_sole_heir") is False
    ):
        # calculator.calculate_spouse_legal_share는 배우자+자녀 공동상속 또는
        # 배우자 단독상속만 지원한다 — 배우자가 피상속인의 부모님과 함께
        # 공동상속받는 경우는 아직 계산할 수 없다. 이 경우를 계산까지 보냈다가
        # ValueError로 걸리면 "입력이 서로 안 맞는다"는 오해를 주므로 여기서
        # 먼저 걸러 정확한 이유를 안내한다.
        state["status"] = "unsupported"
        state["asked_slot"] = None
        state["missing_fields"] = []

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=(
                "현재 상속세 계산기는 배우자와 자녀의 공동상속, 또는 배우자 "
                "단독상속만 지원합니다. 배우자가 돌아가신 분의 부모님이나 "
                "조부모님과 함께 상속받는 경우는 아직 지원하지 않아 세무 "
                "전문가의 확인이 필요합니다."
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
            reply=user_error_reply(exc),
            next_action=None,
            data={STATE_KEY: state},
        )

    state["status"] = "calculated"
    state["asked_slot"] = None
    state["missing_fields"] = []
    state["last_result"] = result.model_dump(mode="json")

    reply = result_reply(result)
    will_note = _will_status_note(payload.will_status)
    if will_note:
        reply = f"{will_note}\n\n{reply}"

    return AgentOutput(
        agent=AgentName.TAX_CALCULATOR,
        reply=reply,
        next_action=None,
        data={STATE_KEY: state},
    )


def _will_status_note(will_status: Any) -> str | None:
    """decedent_estate가 같은 세션에서 유언장을 점검했으면, 상속세 계산이
    유언장 내용까지 반영한 게 아님을 한 줄로 덧붙인다(계산 자체엔 영향 없음)."""
    if will_status is None or not getattr(will_status, "checked", False):
        return None
    if getattr(will_status, "no_will", False):
        return "유언장이 없는 경우를 전제로 법정상속분 기준으로 계산했습니다."
    if getattr(will_status, "has_effect", None) is True:
        return (
            "유효한 유언장이 확인되었습니다. 아래 계산은 법정상속분 기준이며, "
            "유언에 따른 실제 분배·배우자 상속액은 유언 내용에 맞춰 다시 확인하세요."
        )
    return None

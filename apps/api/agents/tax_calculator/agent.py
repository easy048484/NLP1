"""상속세 계산·준비 에이전트.

사용자에게 필요한 정보를 순서대로 질문하고,
수집한 정보를 결정론적 상속세 계산 엔진에 전달합니다.
"""

from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from family_graph.heirs import classify_heirs
from schemas import AgentInput, AgentName, AgentOutput

from .calculator import calculate_inheritance_tax
from .models import InheritanceTaxInput
from .presentation import result_reply, user_error_reply
from .profile_bridge import profile_candidates, tax_snapshot

STATE_KEY = "tax_calculator"

BOOL_SLOTS = {
    "decedent_is_resident",
    "spouse_exists",
    "spouse_is_sole_heir",
    "filing_within_deadline",
}

MONEY_SLOTS = {
    "original_inherited_property",
    "deemed_inherited_property",
    "debts",
    "financial_assets",
    "financial_debts",
    "prior_gifts_to_heirs",
    "prior_gifts_to_non_heirs",
    "spouse_actual_inheritance",
}

DEEMED_SLOTS = {
    "insurance_proceeds": "사망으로 지급되는 보험금",
    "trust_property": "신탁재산 또는 신탁이익을 받을 권리",
    "retirement_benefits": "사망으로 지급되는 퇴직금·퇴직수당 등",
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
        "예: '10억원' 또는 '500000000원'. 보험금·신탁·퇴직금은 별도로 "
        "확인하며 같은 재산을 두 번 더하지 않도록 해야 합니다."
    ),
    "deemed_inherited_property": (
        "사망으로 받는 보험금, 신탁재산, 퇴직금처럼 상속재산으로 함께 "
        "계산되는 금액은 총 얼마인가요? 없다면 '0원'이라고 입력해주세요."
    ),
    "debts": (
        "상속재산에서 차감할 대출이나 그 밖의 채무는 얼마인가요? "
        "없다면 '0원'이라고 입력해주세요."
    ),
    "financial_assets": (
        "전체 상속재산 중 공제대상 예금·적금·주식·펀드 등의 금액은 얼마인가요? "
        "최대주주 등 보유주식이나 신고하지 않은 타인 명의 금융재산은 "
        "공제에서 제외될 수 있습니다. 보험금 등이 있다면 공제 포함 여부도 "
        "확인해주세요. 없다면 '0원', 분류가 불확실하면 '모름'으로 답해주세요."
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
        "받는 재산이 없다면 '0원', 아직 정해지지 않았다면 '모름'이라고 "
        "입력해주세요. 미정인 금액은 임의로 0원으로 계산하지 않습니다."
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
        "profile_snapshot": None,
        "profile_candidates": {},
        "profile_sources": {},
        "profile_warnings": [],
        "profile_scope_confirmed": None,
        "profile_reconfirm": [],
        "profile_changed": False,
        "deemed_items": {},
        "deemed_review_required": False,
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

    for key in (
        "profile_snapshot",
        "profile_candidates",
        "profile_sources",
        "deemed_items",
    ):
        if isinstance(raw_state.get(key), dict):
            state[key] = deepcopy(raw_state[key])
    for key in ("profile_warnings", "profile_reconfirm"):
        if isinstance(raw_state.get(key), list):
            state[key] = list(raw_state[key])
    if isinstance(raw_state.get("profile_scope_confirmed"), bool):
        state["profile_scope_confirmed"] = raw_state["profile_scope_confirmed"]
    state["deemed_review_required"] = raw_state.get("deemed_review_required") is True
    state["has_grandchild_heir"] = raw_state.get("has_grandchild_heir") is True
    return state


def _mark_confirmed(state: dict[str, Any], field_name: str) -> None:
    """확정된 입력 항목을 중복 없이 기록한다."""

    confirmed_fields = state["confirmed_fields"]

    if field_name not in confirmed_fields:
        confirmed_fields.append(field_name)


def _save_value(
    state: dict[str, Any], field_name: str, value: Any, source: str = "user"
) -> None:
    if field_name == "deemed_inherited_property" and value != 0:
        # 과거 후보 금융재산에는 새 보험금·신탁재산이 반영되지 않았을 수 있다.
        if state["profile_sources"].get("financial_assets") == "profile_confirmed":
            state["values"].pop("financial_assets", None)
            state["profile_sources"].pop("financial_assets", None)
            if "financial_assets" in state["confirmed_fields"]:
                state["confirmed_fields"].remove("financial_assets")
    state["values"][field_name] = value
    state["profile_sources"][field_name] = source
    _mark_confirmed(state, field_name)
    if field_name in state["profile_reconfirm"]:
        state["profile_reconfirm"].remove(field_name)
    state["last_result"] = None


def _apply_structured_context(payload: AgentInput, state: dict[str, Any]) -> None:
    """명시적 입력은 공유 후보보다 우선한다. None은 미확인으로 취급한다."""
    tax_input = (payload.context or {}).get("tax_input")
    if not isinstance(tax_input, dict):
        return
    for field_name, value in tax_input.items():
        if field_name not in InheritanceTaxInput.model_fields:
            continue
        if value is None:
            state["values"].pop(field_name, None)
            state["profile_sources"].pop(field_name, None)
            if field_name in state["profile_reconfirm"]:
                state["profile_reconfirm"].remove(field_name)
            if field_name in state["confirmed_fields"]:
                state["confirmed_fields"].remove(field_name)
            state["last_result"] = None
            if field_name == "deemed_inherited_property":
                state["deemed_items"] = {}
        else:
            _save_value(state, field_name, value, "explicit_tax_input")
            if field_name == "deemed_inherited_property":
                state["deemed_review_required"] = False
        # 구조화 입력과 같은 턴의 채팅을 다시 파싱해 값을 덮지 않는다.
        if state["asked_slot"] == field_name or (
            field_name == "deemed_inherited_property"
            and state["asked_slot"] in {*DEEMED_SLOTS, "deemed_amounts_confirmed"}
        ):
            state["asked_slot"] = None


def _apply_financial_profile(payload: AgentInput, state: dict[str, Any]) -> bool:
    """후보만 저장한다. 변경된 자료에는 예전 질문의 답을 적용하지 않는다."""
    if payload.financial_profile is None:
        return False
    snapshot = tax_snapshot(payload.financial_profile)
    if snapshot is None or snapshot == state["profile_snapshot"]:
        return False
    had_snapshot = state["profile_snapshot"] is not None
    candidates, warnings = profile_candidates(snapshot)
    state["profile_snapshot"] = snapshot
    state["profile_candidates"] = candidates
    state["profile_warnings"] = warnings
    state["profile_scope_confirmed"] = None
    state["profile_changed"] = had_snapshot
    state["profile_reconfirm"] = []
    for field_name, source in list(state["profile_sources"].items()):
        if source == "profile_confirmed":
            state["values"].pop(field_name, None)
            state["profile_sources"].pop(field_name, None)
            if field_name in state["confirmed_fields"]:
                state["confirmed_fields"].remove(field_name)
    if had_snapshot:
        state["profile_reconfirm"] = [
            field
            for field, value in candidates.items()
            if field in state["values"] and state["values"][field] != value
        ]
        # 공유 자료가 바뀌면 과거 '보험금 등 없음' 답변도 다시 확인한다.
        if (
            state["profile_sources"].get("deemed_inherited_property")
            == "itemized_confirmed"
        ):
            state["deemed_items"] = {}
            state["values"].pop("deemed_inherited_property", None)
            state["profile_sources"].pop("deemed_inherited_property", None)
            if "deemed_inherited_property" in state["confirmed_fields"]:
                state["confirmed_fields"].remove("deemed_inherited_property")
    state["last_result"] = None
    state["asked_slot"] = None
    return True


def _candidate_for_slot(slot: str, state: dict[str, Any]) -> int | None:
    if state["profile_scope_confirmed"] is not True:
        return None
    # 보험금·신탁이 있으면 금융공제 포함 여부까지 다시 확인한다.
    if (
        slot == "financial_assets"
        and state["values"].get("deemed_inherited_property", 0) != 0
    ):
        return None
    return state["profile_candidates"].get(slot)


def _is_unknown(message: str) -> bool:
    return any(
        word in message.replace(" ", "")
        for word in (
            "모르",
            "몰라",
            "모름",
            "미확인",
            "아직",
            "불확실",
            "확실하지",
            "알수없",
            "정보없",
            "자료없",
            "확인못",
        )
    )


def _strict_confirmation(message: str) -> bool | None:
    normalized = message.strip().replace(" ", "").rstrip(".!")
    if normalized in {"네", "예", "응", "맞아", "맞아요", "확인", "확인했어요"}:
        return True
    if normalized in {"아니", "아니요", "아뇨", "아니오"}:
        return False
    return None


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

    if _is_unknown(message):
        return None

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


def _parse_small_korean_amount(text: str) -> Decimal | None:
    """만보다 작은 구간의 천·백·십 단위를 계산한다."""

    if not text:
        return Decimal("1")

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return Decimal(text)

    small_units = {
        "천": Decimal("1000"),
        "백": Decimal("100"),
        "십": Decimal("10"),
    }

    total = Decimal("0")
    position = 0

    for match in re.finditer(r"(\d+(?:\.\d+)?)?(천|백|십)", text):
        if match.start() != position:
            return None

        number = Decimal(match.group(1) or "1")
        total += number * small_units[match.group(2)]
        position = match.end()

    tail = text[position:]

    if tail:
        if re.fullmatch(r"\d+(?:\.\d+)?", tail) is None:
            return None

        total += Decimal(tail)

    return total


def _parse_money(message: str) -> int | None:
    """'10억', '9천5백만원', '300000000원'을 원 단위 정수로 변환한다."""

    normalized = message.strip().replace(",", "").replace(" ", "")

    if _is_unknown(message):
        return None

    if normalized in {"없음", "없어요", "없습니다", "없다", "없어", "해당없음"}:
        return 0

    if re.fullmatch(r"0+원?", normalized):
        return 0

    amount_text = normalized.removesuffix("원")

    if re.fullmatch(r"\d+", amount_text):
        return int(amount_text)

    if re.fullmatch(r"[0-9.조억만천백십]+", amount_text) is None:
        return None

    big_units = {
        "조": 1_000_000_000_000,
        "억": 100_000_000,
        "만": 10_000,
    }

    total = Decimal("0")
    position = 0
    previous_multiplier: int | None = None

    for match in re.finditer(r"[조억만]", amount_text):
        multiplier = big_units[match.group()]

        # 큰 단위는 조 → 억 → 만 순서로만 입력할 수 있다.
        if previous_multiplier is not None and multiplier >= previous_multiplier:
            return None

        section = amount_text[position : match.start()]

        if not section and position != 0:
            return None

        section_value = _parse_small_korean_amount(section)

        if section_value is None:
            return None

        total += section_value * multiplier
        position = match.end()
        previous_multiplier = multiplier

    tail = amount_text[position:]

    if tail:
        tail_value = _parse_small_korean_amount(tail)

        if tail_value is None:
            return None

        total += tail_value

    return int(total)


def _apply_previous_answer(message: str, state: dict[str, Any]) -> bool:
    """공유 후보 확인과 금액 직접입력을 구분한다."""
    slot = state.get("asked_slot")
    if not isinstance(slot, str):
        return True
    if (
        slot in {*DEEMED_SLOTS, "deemed_amounts_confirmed"}
        and message.strip() == "다시 입력"
    ):
        state["deemed_items"] = {}
        state["deemed_review_required"] = False
        state["asked_slot"] = None
        state["last_result"] = None
        return True
    if _is_unknown(message):
        return False
    if slot == "profile_scope_confirmed":
        answer = _strict_confirmation(message)
        if answer is None:
            return False
        state["profile_scope_confirmed"] = answer
        if not answer:
            state["profile_reconfirm"] = []
        state["asked_slot"] = None
        return True
    if slot in DEEMED_SLOTS:
        amount = _parse_money(message)
        if amount is None:
            return False
        state["deemed_items"][slot] = amount
        state["deemed_review_required"] = False
        state["asked_slot"] = None
        state["last_result"] = None
        if len(state["deemed_items"]) == len(DEEMED_SLOTS):
            if sum(state["deemed_items"].values()) == 0:
                _save_value(state, "deemed_inherited_property", 0, "itemized_confirmed")
        return True
    if slot == "deemed_amounts_confirmed":
        answer = _strict_confirmation(message)
        if answer is not True:
            state["deemed_review_required"] = answer is False
            return False
        _save_value(
            state,
            "deemed_inherited_property",
            sum(state["deemed_items"].values()),
            "itemized_confirmed",
        )
        state["deemed_review_required"] = False
        state["asked_slot"] = None
        return True

    candidate = _candidate_for_slot(slot, state)
    if candidate is not None and _strict_confirmation(message) is True:
        value = candidate
        source = "profile_confirmed"
    else:
        source = "user"
        if slot in BOOL_SLOTS:
            value = _parse_yes_or_no(message)
        elif slot == "children_count":
            value = _parse_count(message)
        elif slot in MONEY_SLOTS:
            value = _parse_money(message)
        else:
            value = None
    if value is None:
        return False
    _save_value(state, slot, value, source)
    state["asked_slot"] = None
    return True


def _question_for_slot(slot: str, state: dict[str, Any]) -> str:
    if slot == "profile_scope_confirmed":
        prefix = (
            "공유 재무자료가 변경되어 다시 확인할게요.\n\n"
            if state["profile_changed"]
            else ""
        )
        return prefix + (
            "다른 에이전트의 재무자료가 있어요. 이 자료가 지금 계산할 "
            "돌아가신 분의 재산·채무이며, 사망일 기준으로 빠짐없이 정리한 "
            "금액인가요? 본인의 은퇴자금이나 다른 시점의 자료라면 '아니요'로 "
            "답해주세요. 맞으면 '네', 불확실하면 '모름'으로 답해주세요. "
            "보험금·신탁·퇴직금은 별도로 확인합니다."
        )
    if slot in DEEMED_SLOTS:
        prefix = ""
        if slot == "insurance_proceeds" and (state.get("profile_snapshot") or {}).get(
            "items", {}
        ).get("insurance"):
            prefix = (
                "자산정리에 보험 항목이 있지만 가입금액을 그대로 사용하지 않을게요. "
            )
        return prefix + (
            f"{DEEMED_SLOTS[slot]}이 있나요? 있다면 금액, 없다면 '0원', "
            "확인되지 않았다면 '모름'이라고 알려주세요. 입력한 금액의 "
            "과세 포함 여부와 기존 재산과의 중복은 별도로 확인합니다."
        )
    if slot == "deemed_amounts_confirmed":
        amounts = "\n".join(
            f"- {label}: {state['deemed_items'][key]:,}원"
            for key, label in DEEMED_SLOTS.items()
        )
        return (
            amounts + "\n\n이 금액은 아직 세금 계산에 반영하지 않았어요. "
            "보험은 사망 지급 여부·실제 보험료 부담자, 신탁은 권리 내용, "
            "퇴직급여는 유족연금 등 제외 항목을 확인해야 합니다. "
            "위 금액 전부가 과세대상이고 본래의 상속재산에 중복 포함되지 "
            "않았음을 신고자료 또는 세무 전문가에게 확인했나요? "
            "'네'일 때만 합산합니다. '아니요' 또는 '모름'이면 "
            "보험금 지급내역·보험료 납입내역, 신탁계약서, 퇴직급여 명세를 "
            "확인한 뒤 이어갈 수 있어요. 금액을 고치려면 '다시 입력'이라고 답해주세요."
        )
    question = QUESTIONS[slot]
    candidate = _candidate_for_slot(slot, state)
    if slot in state["profile_reconfirm"]:
        question = (
            f"기존 직접 입력은 {state['values'][slot]:,}원입니다. 자료와 달라 다시 확인합니다.\n"
            + question
        )
    if candidate is not None:
        question += (
            f"\n공유 목록으로 합산한 후보 금액은 {candidate:,}원입니다. "
            "위 조건과 금액이 맞으면 '네', 수정하려면 정확한 금액을 입력해주세요."
        )
    if slot == "financial_assets":
        question += "\n'기타'가 있다면 실제 상품 종류를 확인한 후 포함 여부를 정해주세요. 불확실하면 계산을 보류할 수 있어요."
    if slot in {
        "financial_assets",
        "financial_debts",
        "original_inherited_property",
        "debts",
    }:
        if state["profile_scope_confirmed"] is True and state["profile_warnings"]:
            question += "\n참고: " + " ".join(state["profile_warnings"])
    return question


def _missing_slots(values: dict[str, Any], state: dict[str, Any]) -> list[str]:
    slots = ["decedent_is_resident", "spouse_exists", "children_count"]
    if values.get("spouse_exists") is True and values.get("children_count") == 0:
        slots.append("spouse_is_sole_heir")
    slots.append("original_inherited_property")
    if values.get("deemed_inherited_property") is None:
        missing_items = [
            key for key in DEEMED_SLOTS if key not in state["deemed_items"]
        ]
        slots.extend(missing_items or ["deemed_amounts_confirmed"])
    slots.extend(
        [
            "debts",
            "financial_assets",
            "financial_debts",
            "prior_gifts_to_heirs",
            "prior_gifts_to_non_heirs",
        ]
    )
    if values.get("spouse_exists") is True:
        slots.append("spouse_actual_inheritance")
    slots.append("filing_within_deadline")
    return [
        slot
        for slot in slots
        if values.get(slot) is None or slot in state["profile_reconfirm"]
    ]


def run(payload: AgentInput) -> AgentOutput:
    """상속세 정보를 수집하고 계산 결과를 반환한다."""

    state = _load_state(payload.context)
    # 수집·검토·지원 불가 응답에 이전 턴의 세액이 남지 않도록 한다.
    state["last_result"] = None

    # 공유 자료는 이 경로에서 후보로만 읽는다. 별도 자동 입력을 병행하면
    # 범위 거절·자료 변경 시에도 미확인 금액이 확정값으로 되살아난다.
    profile_changed = _apply_financial_profile(payload, state)
    _apply_structured_context(payload, state)
    _apply_family_graph(payload.family_graph, state)

    if not profile_changed and not _apply_previous_answer(payload.user_message, state):
        asked_slot = state["asked_slot"]
        state["status"] = (
            "needs_review" if state["deemed_review_required"] else "collecting"
        )
        state["last_result"] = None
        state["missing_fields"] = [asked_slot]

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=(
                "확인되지 않은 정보는 0원으로 처리하지 않고 계산을 보류할게요.\n\n"
                f"{_question_for_slot(asked_slot, state)}"
            ),
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

    if (
        state["profile_snapshot"] is not None
        and state["profile_scope_confirmed"] is None
    ):
        state["status"] = "collecting"
        state["last_result"] = None
        state["asked_slot"] = "profile_scope_confirmed"
        state["missing_fields"] = ["profile_scope_confirmed"]
        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=_question_for_slot("profile_scope_confirmed", state),
            data={STATE_KEY: state},
        )

    missing_slots = _missing_slots(values, state)

    if missing_slots:
        next_slot = missing_slots[0]

        state["status"] = "collecting"
        state["last_result"] = None
        state["asked_slot"] = next_slot
        state["missing_fields"] = missing_slots

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=_question_for_slot(next_slot, state),
            next_action=None,
            data={STATE_KEY: state},
        )

    try:
        tax_input = InheritanceTaxInput.model_validate(values)
        result = calculate_inheritance_tax(tax_input)
    except (ValidationError, ValueError) as exc:
        state["status"] = "needs_review"
        state["last_result"] = None
        state["asked_slot"] = None
        state["last_error"] = str(exc)

        return AgentOutput(
            agent=AgentName.TAX_CALCULATOR,
            reply=user_error_reply(exc),
            next_action=None,
            data={STATE_KEY: state},
        )

    result.warnings.append(
        "보험금·신탁·퇴직금 등은 확인한 입력만 반영했습니다. "
        "법적 과세 자격·평가액·증빙을 자동 검증한 확정 세액이 아닙니다."
    )
    if state["profile_scope_confirmed"] is True:
        result.warnings.extend(state["profile_warnings"])
    if result.estimated_tax_due == 0:
        result.warnings.append(
            "예상세액 0원은 입력 조건의 결과이며 납세·신고 의무가 없다는 확정 판단이 아닙니다."
        )
    result.warnings = list(dict.fromkeys(result.warnings))
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

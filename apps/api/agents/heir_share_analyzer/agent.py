"""법정상속분·유류분 1차 위험 점검 에이전트.

에이전트는 필요한 정보를 질문하고 결과를 설명한다. 법정상속분과 기본
유류분 금액은 LLM이 아니라 calculator.py의 결정론적 코드만 계산한다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from schemas import AgentInput, AgentName, AgentOutput

from agents._money import parse_money as _parse_money

from .calculator import UnsupportedFamilyCase, calculate_heir_share
from .models import AnalysisStage, ComplexityFlag, HeirShareInput
from .presentation import result_reply, unsupported_reply

STATE_KEY = "heir_share_analyzer"

QUESTIONS = {
    "stage": (
        "이번 점검은 생전에 재산 배분을 준비하기 위한 것인가요, 아니면 "
        "사망 후 실제 상속을 점검하기 위한 것인가요? '생전' 또는 '사망 후'로 "
        "답해주세요."
    ),
    "estate_value": (
        "부동산·예금·주식 등 현재 확인된 재산의 총액은 얼마인가요? "
        "예: '7억원' 또는 '700000000원'"
    ),
    "inheritance_opening_date": (
        "사망 후 점검의 법 적용 기준을 확인하려고 합니다. 사망일을 "
        "'2026-08-29'처럼 연도-월-일 형식으로 입력해주세요."
    ),
    "debts": (
        "대출·임대차보증금 반환채무 등 확인된 채무는 얼마인가요? "
        "없다면 '0원'이라고 입력해주세요."
    ),
    "planned_acquisitions": (
        "유언장이나 계획상 각 사람이 받을 예정 금액을 "
        "'배우자=3억원, 자녀1=2억원'처럼 입력해주세요. 아직 정하지 않았다면 "
        "'미정'이라고 답해도 됩니다."
    ),
    "complex_case": (
        "과거 증여, 상속포기, 먼저 사망한 자녀를 대신한 손자녀 상속, "
        "특별한 부양 기여 주장, 재산가액 다툼 중 하나라도 있나요? "
        "있다면 '네', 전혀 없다면 '아니요'라고 답해주세요."
    ),
}

SLOT_ORDER = [
    "stage",
    "estate_value",
    "debts",
    "planned_acquisitions",
    "complex_case",
]


def _empty_state() -> dict[str, Any]:
    return {
        "status": "collecting",
        "values": {},
        "confirmed_fields": [],
        "asked_slot": None,
        "missing_fields": list(SLOT_ORDER),
        "last_result": None,
    }


def _load_state(context: dict[str, Any] | None) -> dict[str, Any]:
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
    if field_name not in state["confirmed_fields"]:
        state["confirmed_fields"].append(field_name)


def _apply_structured_context(payload: AgentInput, state: dict[str, Any]) -> None:
    """버튼/폼 UI가 보낸 구조화 입력을 대화 상태에 반영한다."""

    share_input = (payload.context or {}).get("share_input")
    if not isinstance(share_input, dict):
        return

    values = state["values"]
    for field_name, value in share_input.items():
        if field_name not in HeirShareInput.model_fields:
            continue
        values[field_name] = value
        _mark_confirmed(state, field_name)

    # 구조화 입력은 UI가 복잡 사례 체크박스를 이미 처리했다고 본다.
    if "complexity_flags" in share_input:
        _mark_confirmed(state, "complex_case")
    if "planned_acquisitions" in share_input:
        _mark_confirmed(state, "planned_acquisitions")


def _apply_shared_estate(payload: AgentInput, state: dict[str, Any]) -> None:
    """세션 공유 상속재산(financial_profile)에서 재산가액·채무를 미리 채운다.

    asset_organizer가 이미 자산·부채를 정리했으면 사용자에게 다시 묻지 않는다.
    사용자가 직접 확인한 값(confirmed_fields)은 덮어쓰지 않는다.
    """
    estate = payload.financial_profile
    if estate is None:
        return

    values = state["values"]
    asset_fields = (
        estate.real_estate_value,
        estate.financial_assets,
        estate.other_assets,
    )
    if (
        any(v is not None for v in asset_fields)
        and "estate_value" not in state["confirmed_fields"]
    ):
        values["estate_value"] = sum(v for v in asset_fields if v is not None)
        _mark_confirmed(state, "estate_value")

    if estate.total_debts is not None and "debts" not in state["confirmed_fields"]:
        values["debts"] = estate.total_debts
        _mark_confirmed(state, "debts")


def _parse_stage(message: str) -> str | None:
    normalized = message.replace(" ", "")
    if any(keyword in normalized for keyword in ("생전", "준비", "사망전")):
        return AnalysisStage.PRE_DEATH.value
    if any(
        keyword in normalized for keyword in ("사망후", "사후", "돌아가", "상속개시")
    ):
        return AnalysisStage.POST_DEATH.value
    return None


def _parse_yes_or_no(message: str) -> bool | None:
    normalized = message.strip().replace(" ", "")
    if normalized in {"네", "예", "응", "ㅇㅇ", "있음", "있어요", "있다"}:
        return True
    if normalized in {"아니요", "아니오", "아니", "ㄴㄴ", "없음", "없어요", "없다"}:
        return False
    return None


def _parse_date(message: str) -> str | None:
    normalized = message.strip().replace(".", "-").replace("/", "-")
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        return None


def _parse_planned_acquisitions(message: str) -> dict[str, int] | None:
    normalized = message.strip()
    if any(keyword in normalized for keyword in ("미정", "모름", "아직")):
        return {}

    result: dict[str, int] = {}
    # 숫자 사이의 콤마는 천 단위 구분자이고, 나머지 콤마는 사람별 구분자다.
    for item in re.split(r"[;\n]|(?<!\d),|,(?!\d)", normalized):
        if not item.strip():
            continue
        match = re.fullmatch(r"\s*([^=:]+?)\s*[=:]\s*(.+?)\s*", item)
        if match is None:
            return None
        name = match.group(1).strip()
        amount = _parse_money(match.group(2))
        if not name or amount is None:
            return None
        result[name] = amount
    return result or None


def _apply_previous_answer(message: str, state: dict[str, Any]) -> bool:
    asked_slot = state.get("asked_slot")
    if not isinstance(asked_slot, str):
        return True

    values = state["values"]
    if asked_slot == "stage":
        parsed: Any = _parse_stage(message)
        target_field = "stage"
    elif asked_slot in {"estate_value", "debts"}:
        parsed = _parse_money(message)
        target_field = asked_slot
    elif asked_slot == "inheritance_opening_date":
        parsed = _parse_date(message)
        target_field = asked_slot
    elif asked_slot == "planned_acquisitions":
        parsed = _parse_planned_acquisitions(message)
        target_field = asked_slot
    elif asked_slot == "complex_case":
        parsed = _parse_yes_or_no(message)
        target_field = "complexity_flags"
        if parsed is not None:
            parsed = [ComplexityFlag.USER_REPORTED_COMPLEX_CASE.value] if parsed else []
    else:
        return False

    if parsed is None:
        return False
    values[target_field] = parsed
    _mark_confirmed(state, asked_slot)
    state["asked_slot"] = None
    return True


def _missing_slots(state: dict[str, Any]) -> list[str]:
    confirmed = set(state["confirmed_fields"])
    slot_order = list(SLOT_ORDER)
    if state["values"].get("stage") == AnalysisStage.POST_DEATH.value:
        slot_order.insert(1, "inheritance_opening_date")
    return [slot for slot in slot_order if slot not in confirmed]


def _family_names(family_graph: dict[str, Any] | None) -> list[str]:
    if not isinstance(family_graph, dict):
        return []
    heirs = family_graph.get("heirs")
    if not isinstance(heirs, list):
        return []
    return [
        str(heir.get("name"))
        for heir in heirs
        if isinstance(heir, dict) and heir.get("alive", True) and heir.get("name")
    ]


def _missing_family_output(state: dict[str, Any]) -> AgentOutput:
    state["status"] = "collecting_family"
    return AgentOutput(
        agent=AgentName.HEIR_SHARE_ANALYZER,
        reply=(
            "유류분을 계산하려면 배우자·자녀·부모 등 가족관계가 먼저 필요합니다. "
            "가족관계를 등록하거나 가족관계 그래프를 연결한 뒤 다시 시도해주세요."
        ),
        next_action=None,
        data={STATE_KEY: state},
    )


def run(payload: AgentInput) -> AgentOutput:
    """정보를 수집해 유류분 부족 가능성과 전문가 전달 요약을 반환한다."""

    state = _load_state(payload.context)
    _apply_structured_context(payload, state)
    _apply_shared_estate(payload, state)

    if not _family_names(payload.family_graph):
        return _missing_family_output(state)

    if not _apply_previous_answer(payload.user_message, state):
        asked_slot = state["asked_slot"]
        return AgentOutput(
            agent=AgentName.HEIR_SHARE_ANALYZER,
            reply=f"답변 형식을 이해하지 못했습니다.\n\n{QUESTIONS[asked_slot]}",
            next_action=None,
            data={STATE_KEY: state},
        )

    missing = _missing_slots(state)
    if missing:
        next_slot = missing[0]
        state["status"] = "collecting"
        state["asked_slot"] = next_slot
        state["missing_fields"] = missing
        question = QUESTIONS[next_slot]
        if next_slot == "planned_acquisitions":
            if (
                payload.will_status is not None
                and getattr(payload.will_status, "checked", False)
                and not getattr(payload.will_status, "no_will", False)
            ):
                question = (
                    "확인된 유언장 내용을 기준으로, 각 사람이 받을 예정 금액을 "
                    "'배우자=3억원, 자녀1=2억원'처럼 입력해주세요."
                )
            question += "\n\n등록된 가족: " + ", ".join(
                _family_names(payload.family_graph)
            )
        return AgentOutput(
            agent=AgentName.HEIR_SHARE_ANALYZER,
            reply=question,
            next_action=None,
            data={STATE_KEY: state},
        )

    try:
        simulation_input = HeirShareInput.model_validate(state["values"])
        result = calculate_heir_share(simulation_input, payload.family_graph)
    except UnsupportedFamilyCase as exc:
        state["status"] = "expert_review_required"
        state["last_error"] = str(exc)
        return AgentOutput(
            agent=AgentName.HEIR_SHARE_ANALYZER,
            reply=unsupported_reply(str(exc)),
            next_action=None,
            data={STATE_KEY: state},
        )
    except (ValidationError, ValueError) as exc:
        state["status"] = "needs_input_review"
        state["last_error"] = str(exc)
        return AgentOutput(
            agent=AgentName.HEIR_SHARE_ANALYZER,
            reply=(
                "입력값 중 서로 맞지 않거나 확인이 필요한 항목이 있습니다. "
                "재산·채무·예정 취득액을 다시 확인해주세요.\n\n"
                f"확인 내용: {exc}"
            ),
            next_action=None,
            data={STATE_KEY: state},
        )

    state["status"] = result.status.value
    state["asked_slot"] = None
    state["missing_fields"] = []
    state["last_result"] = result.model_dump(mode="json")
    # 전문가 전달용 요약은 last_result 안에도 있지만, compose/프론트가 법률
    # 계산 전체를 열지 않고 바로 꺼낼 수 있도록 별도 키로 한 번 더 제공한다.
    state["expert_handoff"] = result.expert_handoff.model_dump(mode="json")

    return AgentOutput(
        agent=AgentName.HEIR_SHARE_ANALYZER,
        reply=result_reply(result),
        next_action=None,
        data={STATE_KEY: state},
    )


__all__ = ["run", "STATE_KEY"]

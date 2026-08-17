"""
피상속인 유언장·자산정리 에이전트 (담당: 정호)

먼저 유언 방식(민법 5방식, rules/will_types.json)을 확인한 뒤 분기한다:
- 방식 미확인(context.will_type 없음) → 방식을 묻는 질문 반환
- handwritten(자필증서) → 요건 판정 파이프라인(requirement_checker →
  result_formatter) 실행
- unknown(그 외·모르겠음) → 자필증서를 기본값으로 안내하며 같은 파이프라인 실행
- recording(녹음, §1067) → 대본(전사) 텍스트 기반 요건 판정 파이프라인
  (recording_checker → result_formatter) 실행
- notarial(공정증서) → 검증·검인 모두 불필요 안내 후 heir_navigator로 핸드오프
- secret/oral → 요건 요약만 안내, 자동 점검 미지원

사용자 확인 답변은 AgentInput.context 에서 읽는다 (자서/날인/주소 봉투는
handwritten, 증인 참여/증인 결격은 recording).

⚠️ CLAUDE.md 절대 원칙 4: 마스킹 이전의 원본 텍스트를 LLM API에 보내지 않는다.
   (성명 요건에 한해 llm_client.py 로 연결됨 — masking.py 를 거친 텍스트만 전송.
   recording의 유언자 성명도 동일한 extract_name_with_fallback 을 재사용한다.)
"""

from __future__ import annotations

from typing import Any, Optional

from schemas import AgentInput, AgentName, AgentOutput

from .recording_checker import (
    FORMAL_RECORDING_REQUIREMENT_IDS,
    check_recording_requirements,
    validate_recording_confirm_answers,
)
from .requirement_checker import RequirementResult, check_requirements, validate_confirm_answers
from .result_formatter import (
    RECORDING_SUMMARY_MESSAGES,
    format_result,
    pending_questions,
    red_label,
)
from .will_types import get_will_type, known_will_type_ids, selection_question, unknown_default

_FORMAL_REQUIREMENT_IDS = ("date", "address", "name", "handwriting", "seal")
_ALL_REQUIREMENT_IDS = (*_FORMAL_REQUIREMENT_IDS, "interseal")

_UNKNOWN_WILL_TYPE = "unknown"
_HANDWRITTEN_WILL_TYPE = "handwritten"
_RECORDING_WILL_TYPE = "recording"
_NOTARIAL_WILL_TYPE = "notarial"

_RECORDING_TRANSCRIPT_NOTICE = (
    "📼 녹음하신 내용을 그대로 적어주세요. 아직 녹음 전이라면, 예정된 대본으로 "
    "미리 점검할 수도 있습니다."
)

# next_action 힌트 값. 오케스트레이터/프론트가 참조하는 문자열 상수라 자유 형식이지만,
# 이 두 값만 이 에이전트가 실제로 내보낸다.
NEXT_ACTION_AWAIT_USER = "await_user_confirmation"
NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR = "handoff:heir_navigator"


def _valid_will_type_values() -> tuple[str, ...]:
    """민법 5방식 id + UI의 "모르겠음" sentinel. context.will_type 이 이 안에
    없으면(None 포함) 방식을 다시 물어본다."""
    return (*known_will_type_ids(), _UNKNOWN_WILL_TYPE)


def _requirement_payload(result: RequirementResult) -> dict[str, Any]:
    """신호등 UI를 그릴 수 있도록 요건 하나의 판정 결과를 구조화한다."""
    return {
        "id": result.requirement_id,
        "name": result.name,
        "grade": result.grade,
        "condition_id": result.condition_id,
        "red_label": red_label(result.requirement_id) if result.grade == "RED" else None,
        "precedent_ids": result.precedent_ids,
        "extracted": result.extracted,
        "followup_question": result.followup_question,
    }


def _next_action(results: dict[str, RequirementResult]) -> Optional[str]:
    """PENDING이 남아 있으면 되묻고, 전부 확정+자필증서로 확인되면 heir_navigator로 넘긴다."""
    has_pending = any(results[rid].grade == "PENDING" for rid in _FORMAL_REQUIREMENT_IDS)
    if has_pending:
        return NEXT_ACTION_AWAIT_USER

    if results["handwriting"].grade == "GREEN":
        return NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR

    return None


def _next_action_recording(results: dict[str, RequirementResult]) -> Optional[str]:
    """PENDING이 남아 있으면 되묻고, 전부 확정+증인 실제 참여가 확인되면 heir_navigator로 넘긴다."""
    has_pending = any(
        results[rid].grade == "PENDING" for rid in FORMAL_RECORDING_REQUIREMENT_IDS
    )
    if has_pending:
        return NEXT_ACTION_AWAIT_USER

    if results["rec_witness_present"].grade == "GREEN":
        return NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR

    return None


def _will_type_question_output(warnings: Optional[list[dict[str, Any]]] = None) -> AgentOutput:
    q = selection_question()
    reply = f"{q['question']}\n\n{q['promotion_notice']}"
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        next_action=NEXT_ACTION_AWAIT_USER,
        data={
            "pending_questions": [
                {
                    "requirement": "유언 방식",
                    "field": q["confirm_field"],
                    "question": q["question"],
                    "options": q["options"],
                }
            ],
            "warnings": warnings or [],
        },
    )


def _guidance_only_output(
    will_type_info: dict[str, Any],
    *,
    include_requirements_summary: bool = True,
    next_action: Optional[str] = None,
    handoff_reason: Optional[str] = None,
) -> AgentOutput:
    """검증 대상이 아니거나(notarial) 아직 자동 점검을 지원하지 않는(secret/oral)
    방식에 대해 요건 요약 + 안내 문구만 돌려주고 종료한다."""
    parts: list[str] = []
    if include_requirements_summary:
        parts.append(
            f"{will_type_info['name']}({will_type_info['article']}) 요건: "
            f"{will_type_info['requirements_summary']}"
        )
    parts.append(will_type_info["guidance"])

    data: dict[str, Any] = {"will_type": will_type_info["id"], "warnings": []}
    if handoff_reason:
        data["handoff_reason"] = handoff_reason

    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply="\n\n".join(parts),
        next_action=next_action,
        data=data,
    )


def _run_handwritten_pipeline(
    payload: AgentInput, *, prefix_notice: Optional[str] = None
) -> AgentOutput:
    """자필증서 요건 판정 파이프라인. handwritten 직접 선택과 unknown(기본값 적용)
    둘 다 여기로 온다."""
    context = payload.context
    handwriting_answer = context.get("handwriting_answer")
    seal_answer = context.get("seal_answer")
    address_envelope_answer = context.get("address_envelope_answer")

    results = check_requirements(
        payload.user_message,
        handwriting_answer=handwriting_answer,
        seal_answer=seal_answer,
        address_envelope_answer=address_envelope_answer,
    )

    next_action = _next_action(results)

    data: dict[str, Any] = {
        "will_type": _HANDWRITTEN_WILL_TYPE,
        "requirements": {
            rid: _requirement_payload(results[rid]) for rid in _ALL_REQUIREMENT_IDS
        },
        "pending_questions": pending_questions(results),
        # 화이트리스트에 없는 답변값이 와도 판정은 그대로 PENDING 유지(위 check_requirements
        # 호출과 동일 입력) — 여기서는 그 "조용한 무시"를 호출자가 알아채도록만 알려준다.
        "warnings": validate_confirm_answers(
            handwriting_answer=handwriting_answer,
            seal_answer=seal_answer,
            address_envelope_answer=address_envelope_answer,
        ),
    }
    if next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR:
        data["handoff_reason"] = "가정법원 검인 절차 안내 필요"

    reply = format_result(results)
    if prefix_notice:
        reply = f"{prefix_notice}\n\n{reply}"

    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        next_action=next_action,
        data=data,
    )


def _run_recording_pipeline(payload: AgentInput) -> AgentOutput:
    """녹음 유언(§1067) 대본 요건 판정 파이프라인."""
    context = payload.context
    rec_witness_present_answer = context.get("rec_witness_present_answer")
    rec_witness_eligible_answer = context.get("rec_witness_eligible_answer")

    results = check_recording_requirements(
        payload.user_message,
        rec_witness_present_answer=rec_witness_present_answer,
        rec_witness_eligible_answer=rec_witness_eligible_answer,
    )

    next_action = _next_action_recording(results)

    data: dict[str, Any] = {
        "will_type": _RECORDING_WILL_TYPE,
        "requirements": {
            rid: _requirement_payload(results[rid]) for rid in FORMAL_RECORDING_REQUIREMENT_IDS
        },
        "pending_questions": pending_questions(results, FORMAL_RECORDING_REQUIREMENT_IDS),
        "warnings": validate_recording_confirm_answers(
            rec_witness_present_answer=rec_witness_present_answer,
            rec_witness_eligible_answer=rec_witness_eligible_answer,
        ),
    }
    if next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR:
        data["handoff_reason"] = "가정법원 검인 절차 안내 필요"

    reply = format_result(
        results,
        formal_ids=FORMAL_RECORDING_REQUIREMENT_IDS,
        ordered_ids=list(FORMAL_RECORDING_REQUIREMENT_IDS),
        messages=RECORDING_SUMMARY_MESSAGES,
    )
    reply = f"{_RECORDING_TRANSCRIPT_NOTICE}\n\n{reply}"

    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        next_action=next_action,
        data=data,
    )


def run(payload: AgentInput) -> AgentOutput:
    will_type = payload.context.get("will_type")

    if will_type is None:
        return _will_type_question_output()

    if will_type not in _valid_will_type_values():
        return _will_type_question_output(
            warnings=[
                {
                    "field": "will_type",
                    "invalid_value": will_type,
                    "allowed": list(_valid_will_type_values()),
                }
            ]
        )

    if will_type == _HANDWRITTEN_WILL_TYPE:
        return _run_handwritten_pipeline(payload)

    if will_type == _UNKNOWN_WILL_TYPE:
        default = unknown_default()
        return _run_handwritten_pipeline(payload, prefix_notice=default["notice"])

    if will_type == _RECORDING_WILL_TYPE:
        return _run_recording_pipeline(payload)

    will_type_info = get_will_type(will_type)  # notarial / secret / oral

    if will_type == _NOTARIAL_WILL_TYPE:
        return _guidance_only_output(
            will_type_info,
            include_requirements_summary=False,
            next_action=NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
            handoff_reason="공정증서 유언 확인 완료 — 검인 절차 없이 상속 절차 안내로 연결",
        )

    # secret / oral: 요건 요약 + "자동 점검 미지원" 안내만 하고 종료.
    return _guidance_only_output(will_type_info)

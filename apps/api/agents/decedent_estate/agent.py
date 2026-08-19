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

will_type이 full 지원(handwritten/unknown/recording)이면 두 번째로 intent(이용
목적)를 확인한다: "review"(기본, 이미 있는 유언장/대본 점검) | "prepare"(아직
작성 전, 요건별 작성 가이드). context.intent 가 없으면(하위 호환) review로 조용히
기본 동작하고, 잘못된 값이면 will_type 게이트와 같은 패턴으로 재질문한다.
prepare 모드에서도 초안 텍스트가 있으면(has_draft_text) 가이드 뒤에 기존
review 파이프라인 결과를 그대로 이어붙인다(rules/requirements.json 의
requirements[].guide, CLAUDE.md 빌드 순서 5단계).

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
from .requirement_checker import (
    RequirementResult,
    check_requirements,
    validate_confirm_answers,
)
from .result_formatter import (
    HANDWRITTEN_GUIDE_INTRO,
    RECORDING_GUIDE_INTRO,
    RECORDING_SUMMARY_MESSAGES,
    format_guide,
    format_result,
    guide_payload,
    pending_questions,
    red_label,
)
from .will_types import (
    get_will_type,
    intent_question,
    known_will_type_ids,
    selection_question,
    unknown_default,
)

_FORMAL_REQUIREMENT_IDS = ("date", "address", "name", "handwriting", "seal")
_ALL_REQUIREMENT_IDS = (*_FORMAL_REQUIREMENT_IDS, "interseal")

_UNKNOWN_WILL_TYPE = "unknown"
_HANDWRITTEN_WILL_TYPE = "handwritten"
_RECORDING_WILL_TYPE = "recording"
_NOTARIAL_WILL_TYPE = "notarial"

# intent(이용 목적): "review"(기본, 이미 있는 유언장/대본 점검) | "prepare"(아직
# 작성 전, 준비 가이드). full 지원 방식(handwritten/unknown/recording)에서만 의미가
# 있다 — notarial/secret/oral은 애초에 review/prepare 구분 없이 안내만 한다.
_REVIEW_INTENT = "review"
_PREPARE_INTENT = "prepare"
_INTENT_VALUES = (_REVIEW_INTENT, _PREPARE_INTENT)
_FULL_SUPPORT_WILL_TYPES = (
    _HANDWRITTEN_WILL_TYPE,
    _UNKNOWN_WILL_TYPE,
    _RECORDING_WILL_TYPE,
)

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


def _resolve_intent(payload: AgentInput) -> tuple[Optional[str], list[dict[str, Any]]]:
    """context.intent 를 review/prepare 로 정리한다.

    will_type 게이트와 같은 패턴을 쓰되(잘못된 값이면 재질문), "미지정"의 취급만
    다르다 — will_type은 기본값이 없어 None이면 무조건 되묻지만, intent는
    review라는 합리적인 기본값이 있어서 값이 아예 없으면(context에 키 자체가
    없거나 None) 조용히 review로 판정한다(기존 호출부 하위 호환 — intent를 아직
    모르는 옛 클라이언트도 그대로 review 파이프라인을 탄다). 값이 있는데
    화이트리스트 밖이면(오타 등) will_type과 동일하게 None을 돌려줘 호출부가
    재질문(_intent_question_output)하게 한다.
    """
    intent = payload.context.get("intent")
    if intent is None:
        return _REVIEW_INTENT, []
    if intent not in _INTENT_VALUES:
        return None, [
            {
                "field": "intent",
                "invalid_value": intent,
                "allowed": list(_INTENT_VALUES),
            }
        ]
    return intent, []


def _intent_question_output(
    will_type_id: str, warnings: Optional[list[dict[str, Any]]] = None
) -> AgentOutput:
    q = intent_question()
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=q["question"],
        next_action=NEXT_ACTION_AWAIT_USER,
        data={
            "will_type": will_type_id,
            "pending_questions": [
                {
                    "requirement": "이용 목적",
                    "field": q["confirm_field"],
                    "question": q["question"],
                    "options": q["options"],
                }
            ],
            "warnings": warnings or [],
        },
    )


def _has_draft_text(payload: AgentInput) -> bool:
    """prepare 모드에서 "이미 초안(텍스트)을 갖고 있는지" 판단한다.

    context.has_draft 를 명시적으로 보내면 그 값을 그대로 쓰고, 없으면
    user_message에 내용이 있는지로 유추한다(가이드만 원하는 경우 프론트가
    user_message를 비워 보내는 것을 전제).
    """
    context_flag = payload.context.get("has_draft")
    if context_flag is not None:
        return bool(context_flag)
    return bool(payload.user_message and payload.user_message.strip())


def _requirement_payload(result: RequirementResult) -> dict[str, Any]:
    """신호등 UI를 그릴 수 있도록 요건 하나의 판정 결과를 구조화한다."""
    return {
        "id": result.requirement_id,
        "name": result.name,
        "grade": result.grade,
        "condition_id": result.condition_id,
        "red_label": (
            red_label(result.requirement_id) if result.grade == "RED" else None
        ),
        "precedent_ids": result.precedent_ids,
        "extracted": result.extracted,
        "followup_question": result.followup_question,
    }


def _next_action(results: dict[str, RequirementResult]) -> Optional[str]:
    """PENDING이 남아 있으면 되묻고, 전부 확정+자필증서로 확인되면 heir_navigator로 넘긴다."""
    has_pending = any(
        results[rid].grade == "PENDING" for rid in _FORMAL_REQUIREMENT_IDS
    )
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


def _will_type_question_output(
    warnings: Optional[list[dict[str, Any]]] = None
) -> AgentOutput:
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
            rid: _requirement_payload(results[rid])
            for rid in FORMAL_RECORDING_REQUIREMENT_IDS
        },
        "pending_questions": pending_questions(
            results, FORMAL_RECORDING_REQUIREMENT_IDS
        ),
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


_PREPARE_DRAFT_INVITE = "작성하신 초안(또는 대본)이 있다면 그대로 보내주세요. 위 요건 기준으로 바로 점검해 드립니다."


def _run_handwritten_prepare_pipeline(
    payload: AgentInput, *, prefix_notice: Optional[str] = None
) -> AgentOutput:
    """자필증서 준비 가이드(intent == "prepare"). handwritten 직접 선택과 unknown
    (기본값 적용) 둘 다 여기로 온다 — review 파이프라인과 동일한 분기 구조.

    이미 초안이 있으면(has_draft_text) 가이드 문구 뒤에 기존 review 파이프라인
    (_run_handwritten_pipeline) 결과를 그대로 이어붙인다 — 판정 로직 자체는
    중복 구현하지 않는다. 이때 가이드 쪽 마무리 문구(상담 연결·하단 고지)는
    빼고(include_closing=False) 이어 붙는 점검 결과 쪽 것만 남긴다 — 한 화면에
    같은 두 줄이 두 번 반복되지 않게 하기 위해서다.
    """
    has_draft = _has_draft_text(payload)

    reply = format_guide(
        list(_FORMAL_REQUIREMENT_IDS),
        HANDWRITTEN_GUIDE_INTRO,
        include_closing=not has_draft,
    )
    data: dict[str, Any] = {
        "will_type": _HANDWRITTEN_WILL_TYPE,
        "intent": _PREPARE_INTENT,
        "guide": {rid: guide_payload(rid) for rid in _FORMAL_REQUIREMENT_IDS},
    }

    if prefix_notice:
        reply = f"{prefix_notice}\n\n{reply}"

    if has_draft:
        review_output = _run_handwritten_pipeline(payload)
        reply = f"{reply}\n\n---\n\n**작성하신 초안을 점검한 결과입니다.**\n\n{review_output.reply}"
        data["review"] = review_output.data
        return AgentOutput(
            agent=AgentName.DECEDENT_ESTATE,
            reply=reply,
            next_action=review_output.next_action,
            data=data,
        )

    reply = f"{reply}\n\n{_PREPARE_DRAFT_INVITE}"
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE, reply=reply, next_action=None, data=data
    )


def _run_recording_prepare_pipeline(payload: AgentInput) -> AgentOutput:
    """녹음 유언(§1067) 준비 가이드(intent == "prepare"). 이미 대본이 있으면
    가이드 뒤에 기존 review 파이프라인(_run_recording_pipeline) 결과를 이어붙이고,
    이때 가이드 쪽 마무리 문구는 빼서(include_closing=False) 상담 연결·하단 고지가
    한 화면에 두 번 반복되지 않게 한다 — handwritten prepare와 동일한 처리."""
    has_draft = _has_draft_text(payload)

    reply = format_guide(
        list(FORMAL_RECORDING_REQUIREMENT_IDS),
        RECORDING_GUIDE_INTRO,
        include_closing=not has_draft,
    )
    data: dict[str, Any] = {
        "will_type": _RECORDING_WILL_TYPE,
        "intent": _PREPARE_INTENT,
        "guide": {rid: guide_payload(rid) for rid in FORMAL_RECORDING_REQUIREMENT_IDS},
    }

    if has_draft:
        review_output = _run_recording_pipeline(payload)
        reply = f"{reply}\n\n---\n\n**작성하신 대본을 점검한 결과입니다.**\n\n{review_output.reply}"
        data["review"] = review_output.data
        return AgentOutput(
            agent=AgentName.DECEDENT_ESTATE,
            reply=reply,
            next_action=review_output.next_action,
            data=data,
        )

    reply = f"{reply}\n\n{_PREPARE_DRAFT_INVITE}"
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE, reply=reply, next_action=None, data=data
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

    if will_type in _FULL_SUPPORT_WILL_TYPES:
        intent, intent_warnings = _resolve_intent(payload)
        if intent is None:  # 화이트리스트 밖 값 — will_type 게이트와 동일하게 재질문
            return _intent_question_output(will_type, warnings=intent_warnings)

        if will_type == _HANDWRITTEN_WILL_TYPE:
            if intent == _PREPARE_INTENT:
                return _run_handwritten_prepare_pipeline(payload)
            return _run_handwritten_pipeline(payload)

        if will_type == _UNKNOWN_WILL_TYPE:
            default = unknown_default()
            if intent == _PREPARE_INTENT:
                return _run_handwritten_prepare_pipeline(
                    payload, prefix_notice=default["notice"]
                )
            return _run_handwritten_pipeline(payload, prefix_notice=default["notice"])

        # will_type == _RECORDING_WILL_TYPE
        if intent == _PREPARE_INTENT:
            return _run_recording_prepare_pipeline(payload)
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

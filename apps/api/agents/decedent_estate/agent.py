"""
피상속인 유언장·자산정리 에이전트 (담당: 정호)

AgentInput.user_message 를 유언장 텍스트로 받아
requirement_checker(요건 판정) → result_formatter(화면 문구) 파이프라인을 실행한다.
사용자 확인 답변(전문 자서/날인/주소 봉투)은 AgentInput.context 에서 읽는다.

⚠️ CLAUDE.md 절대 원칙 4: 마스킹 이전의 원본 텍스트를 LLM API에 보내지 않는다.
   이 단계(빌드 순서 2)에는 아직 LLM 호출이 없으므로 해당 없음 — 3단계(마스킹)와
   4단계(LLM 추출 연결)가 이 run() 앞단에 붙을 때 지켜야 한다.
"""

from __future__ import annotations

from typing import Any, Optional

from schemas import AgentInput, AgentName, AgentOutput

from .requirement_checker import RequirementResult, check_requirements
from .result_formatter import format_result, pending_questions, red_label

_FORMAL_REQUIREMENT_IDS = ("date", "address", "name", "handwriting", "seal")
_ALL_REQUIREMENT_IDS = (*_FORMAL_REQUIREMENT_IDS, "interseal")

# next_action 힌트 값. 오케스트레이터/프론트가 참조하는 문자열 상수라 자유 형식이지만,
# 이 두 값만 이 에이전트가 실제로 내보낸다.
NEXT_ACTION_AWAIT_USER = "await_user_confirmation"
NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR = "handoff:heir_navigator"


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


def run(payload: AgentInput) -> AgentOutput:
    context = payload.context
    results = check_requirements(
        payload.user_message,
        handwriting_answer=context.get("handwriting_answer"),
        seal_answer=context.get("seal_answer"),
        address_envelope_answer=context.get("address_envelope_answer"),
    )

    next_action = _next_action(results)

    data: dict[str, Any] = {
        "requirements": {
            rid: _requirement_payload(results[rid]) for rid in _ALL_REQUIREMENT_IDS
        },
        "pending_questions": [
            {"requirement": name, "question": question}
            for name, question in pending_questions(results)
        ],
    }
    if next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR:
        data["handoff_reason"] = "가정법원 검인 절차 안내 필요"

    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=format_result(results),
        next_action=next_action,
        data=data,
    )

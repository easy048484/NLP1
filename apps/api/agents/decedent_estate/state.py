"""
세션 상태 네임스페이스 (orchestrator/handoff.py 규약 1번).

이 에이전트의 상태는 항상 ``AgentInput.context["decedent_estate"]`` 에서 읽고
``AgentOutput.data["decedent_estate"]`` 에 써서 돌려준다. heir_navigator/state.py
의 STATE_KEY 패턴을 그대로 따른 것이며, 오케스트레이터가 이 키만 보고 세션에
저장·복원해준다 (handoff.extract_state_to_persist / build_agent_context).

⚠️ 저장 정책 — C안 (docs/privacy_notes.md 확정)
--------------------------------------------------
담는 것: will_type, intent, 확인 답변, 요건별 판정 결과(등급·condition_id·
red_label·precedent_ids·추출값), pending_questions.

**담지 않는 것: 유언장 원문(user_message)과 마스킹 이전 텍스트.**
판정이 끝나면 원문은 메모리에서만 쓰고 버린다. 그래서 이 모델에는 원문을 담을
필드 자체가 없다 — 실수로라도 흘러 들어가지 않게 하기 위해서다. 추출값
(성명·주소 조각 등)은 판정 결과의 일부라 포함되지만, 전문(全文)은 포함되지
않는다.

평면(flat) 키 폴백
------------------
이 규약으로 옮기기 전까지 프론트는 context 최상위에 will_type/handwriting_answer
같은 평면 키를 직접 실어 보냈다. 그 클라이언트가 아직 살아 있을 수 있으므로
load_state 는 네임스페이스를 기본으로 삼되, **이번 턴에 평면 키가 명시적으로
들어왔으면 그 값을 우선**한다.

우선순위를 이렇게 잡은 이유: 네임스페이스 값은 "지난 턴에 저장된 상태"이고
평면 키는 "이번 턴에 클라이언트가 보낸 입력"이다. handoff.build_agent_context
독스트링도 "사용자가 이번 턴에 명시적으로 답한 값이 우선합니다"라고 못박고
있어서, 사용자가 답을 바꿔 다시 보낸 경우 지난 턴 값이 이기면 안 된다.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

#: context/data 안에서 이 에이전트가 쓰는 네임스페이스 키 (= AgentName.DECEDENT_ESTATE.value)
STATE_KEY = "decedent_estate"

#: 평면 폴백 대상 필드. 여기 없는 필드는 네임스페이스로만 주고받는다.
#: (판정 결과·pending_questions 는 애초에 클라이언트가 평면으로 보내던 값이 아니다.)
_FLAT_FALLBACK_FIELDS = (
    "will_type",
    "intent",
    "has_draft",
    "handwriting_answer",
    "seal_answer",
    "address_envelope_answer",
    "rec_witness_present_answer",
    "rec_witness_eligible_answer",
)


class DecedentState(BaseModel):
    """세션에 왕복시킬 상태. 유언장 원문을 담는 필드는 의도적으로 없다."""

    #: 유언 방식 (민법 5방식 id 또는 "unknown"). 미확인이면 None.
    will_type: Optional[str] = None
    #: 이용 목적 "review" | "prepare". 미지정이면 None(= review로 기본 동작).
    intent: Optional[str] = None
    #: prepare 모드에서 초안 보유 여부를 클라이언트가 명시한 경우.
    has_draft: Optional[bool] = None

    #: 사용자 확인 답변 — handwritten
    handwriting_answer: Optional[str] = None
    seal_answer: Optional[str] = None
    address_envelope_answer: Optional[str] = None
    #: 사용자 확인 답변 — recording
    rec_witness_present_answer: Optional[str] = None
    rec_witness_eligible_answer: Optional[str] = None

    #: 요건별 판정 결과 (_requirement_payload 결과 그대로 — 등급/condition_id/
    #: red_label/precedent_ids/추출값). 원문은 여기 들어가지 않는다.
    requirements: dict[str, Any] = Field(default_factory=dict)
    #: 아직 답을 못 받은 확인 질문들 (프론트가 버튼을 다시 그릴 수 있게).
    pending_questions: list[dict[str, Any]] = Field(default_factory=list)


def _flat_overrides(context: dict[str, Any]) -> dict[str, Any]:
    """이번 턴 평면 키 중 실제로 들어온 것만 뽑는다 (None 은 "미지정"이라 제외)."""
    return {
        field: context[field]
        for field in _FLAT_FALLBACK_FIELDS
        if context.get(field) is not None
    }


def load_state(context: Optional[dict[str, Any]]) -> DecedentState:
    """context 에서 이 에이전트의 상태를 복원한다.

    네임스페이스(context["decedent_estate"])를 기본으로 삼고, 이번 턴에 평면
    키가 들어왔으면 그 값으로 덮어쓴다.

    스키마가 안 맞거나 클라이언트가 이상한 걸 보냈으면 예외를 던지지 않고 빈
    상태로 새로 시작한다 — 상태 하나 때문에 대화가 죽지 않게 하기 위해서다
    (heir_navigator.state.load_state 와 동일한 방어).
    """
    context = context or {}

    raw = context.get(STATE_KEY)
    if isinstance(raw, dict):
        try:
            state = DecedentState.model_validate(raw)
        except Exception:
            state = DecedentState()
    else:
        state = DecedentState()

    overrides = _flat_overrides(context)
    if not overrides:
        return state

    try:
        return DecedentState.model_validate(
            {**state.model_dump(mode="json"), **overrides}
        )
    except Exception:
        # 평면 값이 이상해도(타입 불일치 등) 네임스페이스 상태는 살린다.
        return state


def dump_state(state: DecedentState) -> dict[str, Any]:
    """AgentOutput.data[STATE_KEY] 에 넣을 형태로 직렬화한다."""
    return state.model_dump(mode="json")

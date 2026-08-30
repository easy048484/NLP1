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

상태(will_type/intent/확인 답변/판정 결과)는 orchestrator/handoff.py 규약 1번에
따라 ``context["decedent_estate"]`` 에서 읽고 ``data["decedent_estate"]`` 에 써서
돌려준다 (state.py). 전환기 안전망으로 평면 키(context 최상위의 will_type 등)도
계속 읽으며, 이번 턴에 평면 키가 왔으면 그 값이 우선한다. 응답 data 에도 기존
평면 키를 당분간 함께 내보낸다.

⚠️ 세션에 담는 것은 판정 결과와 확인 답변뿐이다 — 유언장 원문은 담지 않는다
   (C안, docs/privacy_notes.md).

⚠️ CLAUDE.md 절대 원칙 4: 마스킹 이전의 원본 텍스트를 LLM API에 보내지 않는다.
   (성명 요건에 한해 llm_client.py 로 연결됨 — masking.py 를 거친 텍스트만 전송.
   recording의 유언자 성명도 동일한 extract_name_with_fallback 을 재사용한다.)
"""

from __future__ import annotations

import re
from typing import Any, Optional

from schemas import AgentInput, AgentName, AgentOutput, WillStatus

from .date_parser import parse_dates
from .image_reader import PHOTO_FIELD_IDS, extract_will_photo_fields

from .recording_checker import (
    FORMAL_RECORDING_REQUIREMENT_IDS,
    check_recording_requirements,
    validate_recording_confirm_answers,
)
from .requirement_checker import (
    RequirementResult,
    check_requirements,
    photo_confirm_templates,
    validate_confirm_answers,
)
from .result_formatter import (
    HANDWRITTEN_GUIDE_INTRO,
    RECORDING_GUIDE_INTRO,
    RECORDING_SUMMARY_MESSAGES,
    closing_lines,
    format_guide,
    format_result,
    guide_payload,
    pending_questions,
    progress,
    red_label,
)
from .state import STATE_KEY, DecedentState, dump_state, load_state
from .will_types import (
    get_will_type,
    intent_question,
    known_will_type_ids,
    no_will_guidance,
    selection_question,
    unknown_default,
)

_FORMAL_REQUIREMENT_IDS = ("date", "address", "name", "handwriting", "seal")
_ALL_REQUIREMENT_IDS = (*_FORMAL_REQUIREMENT_IDS, "interseal")

_UNKNOWN_WILL_TYPE = "unknown"
_HANDWRITTEN_WILL_TYPE = "handwritten"
_RECORDING_WILL_TYPE = "recording"
_NOTARIAL_WILL_TYPE = "notarial"
# "유언장이 없거나 찾지 못했다" — unknown과 마찬가지로 민법 5방식이 아니라 UI
# sentinel이다. unknown이 "방식을 모르겠다"(유언장은 있음)인 반면 이쪽은 "유언장
# 자체가 확인되지 않는다"라, 요건 판정을 아예 돌지 않고 법정상속 안내로 넘긴다.
_NO_WILL_TYPE = "none"

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
    """민법 5방식 id + UI sentinel 2개("모르겠음"/"없음"). context.will_type 이
    이 안에 없으면(None 포함) 방식을 다시 물어본다."""
    return (*known_will_type_ids(), _UNKNOWN_WILL_TYPE, _NO_WILL_TYPE)


def _namespaced(
    state: DecedentState, data: dict[str, Any], **updates: Any
) -> dict[str, Any]:
    """data 에 네임스페이스 상태(data["decedent_estate"])를 얹어 돌려준다.

    기존 평면 키(will_type/requirements/pending_questions/warnings)는 당분간
    그대로 둔다 — 아직 평면 응답을 읽는 프론트가 있을 수 있어서, 전환기에는
    둘 다 내보낸다(handoff.py 에서 LEGACY 목록을 빼도 응답 호환은 유지).

    ⚠️ 여기 담기는 것은 DecedentState 필드뿐이라 유언장 원문은 구조적으로
    들어갈 수 없다 (state.py 참고 — C안).
    """
    persisted = state.model_copy(update=updates)
    return {**data, STATE_KEY: dump_state(persisted)}


def _resolve_intent(
    state: DecedentState,
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """상태의 intent 를 review/prepare 로 정리한다.

    will_type 게이트와 같은 패턴을 쓰되(잘못된 값이면 재질문), "미지정"의 취급만
    다르다 — will_type은 기본값이 없어 None이면 무조건 되묻지만, intent는
    review라는 합리적인 기본값이 있어서 값이 아예 없으면(context에 키 자체가
    없거나 None) 조용히 review로 판정한다(기존 호출부 하위 호환 — intent를 아직
    모르는 옛 클라이언트도 그대로 review 파이프라인을 탄다). 값이 있는데
    화이트리스트 밖이면(오타 등) will_type과 동일하게 None을 돌려줘 호출부가
    재질문(_intent_question_output)하게 한다.
    """
    intent = state.intent
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
    state: DecedentState,
    will_type_id: str,
    warnings: Optional[list[dict[str, Any]]] = None,
) -> AgentOutput:
    q = intent_question()
    pending = [
        {
            "requirement": "이용 목적",
            "field": q["confirm_field"],
            "question": q["question"],
            "options": q["options"],
        }
    ]
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=q["question"],
        next_action=NEXT_ACTION_AWAIT_USER,
        data=_namespaced(
            state,
            {
                "will_type": will_type_id,
                "pending_questions": pending,
                "warnings": warnings or [],
            },
            will_type=will_type_id,
            # 잘못된 intent 값은 저장하지 않는다 — 다음 턴에 또 재질문하게 된다.
            intent=None,
            pending_questions=pending,
        ),
    )


# prepare 모드에서 "이 텍스트가 유언장 초안인가"를 판별하는 신호들.
#
# 단순히 user_message 가 비어 있지 않다는 것만으로 초안이라고 보면, "유언장을
# 준비하려고요" 같은 요청 문장까지 초안으로 오인해 아직 쓰지도 않은 사용자에게
# "❌ 날짜가 확인되지 않습니다"를 들이밀게 된다. 그래서 아래 신호 중 하나 이상이
# 있을 때만 초안으로 본다.
#
# 1) 재산 처분 의사 표현 — "~에게 상속한다/물려준다/준다" 처럼 처분을 선언하는
#    서술형. 명사 "상속"만으로는 인정하지 않는다("상속 준비를 하고 싶어요"가
#    초안으로 잡히면 안 되기 때문). recording_checker._DISPOSITION_INTENT_RE 와
#    목적이 비슷하지만, 그쪽은 "요건 충족 여부" 판정용이라 더 좁고 여기는
#    "초안인가" 판별용이라 구어체 어미까지 넓게 잡는다.
#
#    "상속한다"/"물려주다" 계열은 그 자체로 재산 처분 의미가 명확해 단어만으로
#    판단해도 된다. 하지만 "준다/드립니다/남깁니다" 같은 범용 어미는 "확인해
#    드립니다", "말씀 드립니다"처럼 재산과 무관한 일상 응답에도 흔히 등장한다
#    (실측 확인된 버그) — 그래서 이 그룹은 수신자 표시("에게"/"한테")나 재산
#    관련 명사가 같은 문장에 함께 있을 때만 처분 의사로 인정한다.
_DRAFT_DISPOSITION_VERB_RE = re.compile(
    r"(?:상속|증여|유증|양도)(?:한다|하며|하고|합니다|하겠|시킨다|시키며)"
    r"|물려주(?:다|고|며|겠|었|기)"
)
_DRAFT_BARE_GIVE_VERB_RE = re.compile(
    r"준다|줍니다|드린다|드립니다|넘긴다|남긴다|남깁니다|맡긴다"
)
_DRAFT_RECIPIENT_OR_PROPERTY_RE = re.compile(
    r"에게|한테|재산|통장|부동산|예금|주식|아파트|건물|집|땅|토지|돈"
)

# 3) "유언장"/"유언" 만으로 이루어진 제목 줄 (그 아래에 내용이 더 있어야 초안).
#    "유언장을 준비하려고요"처럼 문장 속에 들어간 경우는 제목이 아니라 요청이다.
_DRAFT_TITLE_LINE_RE = re.compile(r"^\s*(?:유언장|유언)\s*$")


def _looks_like_draft(text: str) -> bool:
    """유언장 초안(또는 녹음 대본)으로 볼 만한 신호가 있는지 판별한다.

    아래 셋 중 하나라도 있으면 초안으로 본다:
    1) 재산 처분 의사 표현
    2) 날짜 표기 (date_parser 가 무엇이든 잡아냄 — 일부만 있어도 초안 신호)
    3) "유언장"/"유언" 제목 줄 + 그 아래 내용

    셋 다 없으면 "유언장 쓰고 싶어요" 같은 요청 문장으로 보고 초안이 아니라고
    판단한다.
    """
    if not text or not text.strip():
        return False

    if _DRAFT_DISPOSITION_VERB_RE.search(text):
        return True

    if _DRAFT_BARE_GIVE_VERB_RE.search(text) and _DRAFT_RECIPIENT_OR_PROPERTY_RE.search(
        text
    ):
        return True

    if parse_dates(text).case != "absent":
        return True

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not _DRAFT_TITLE_LINE_RE.match(line):
            continue
        # 제목 줄 아래에 실제 내용이 있어야 초안이다 (제목만 덜렁 보낸 것은 아님).
        if any(rest.strip() for rest in lines[index + 1 :]):
            return True

    return False


def _has_draft_text(payload: AgentInput, state: DecedentState) -> bool:
    """prepare 모드에서 "이미 초안(텍스트)을 갖고 있는지" 판단한다.

    has_draft 를 명시적으로 보내면(네임스페이스든 평면 키든 state 가 이미
    합쳐서 들고 있다) 그 값을 그대로 쓰고, 없으면 user_message 를
    _looks_like_draft 로 판별한다.
    """
    if state.has_draft is not None:
        return bool(state.has_draft)
    return _looks_like_draft(payload.user_message)


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
    state: DecedentState, warnings: Optional[list[dict[str, Any]]] = None
) -> AgentOutput:
    q = selection_question()
    reply = f"{q['question']}\n\n{q['promotion_notice']}"
    pending = [
        {
            "requirement": "유언 방식",
            "field": q["confirm_field"],
            "question": q["question"],
            "options": q["options"],
        }
    ]
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        next_action=NEXT_ACTION_AWAIT_USER,
        data=_namespaced(
            state,
            {"pending_questions": pending, "warnings": warnings or []},
            # 잘못된 will_type 값은 저장하지 않는다 — 다음 턴에 또 재질문하게 된다.
            will_type=None,
            pending_questions=pending,
        ),
    )


def _run_no_will_pipeline(state: DecedentState) -> AgentOutput:
    """유언장이 없거나 찾지 못한 경우 — 요건 판정을 아예 돌지 않고 안내만 한다.

    범위를 의도적으로 좁게 잡았다:
    - **유언장 탐색 안내는 하지 않는다** (어디에 뒀는지 찾는 법 등). 유일한
      예외가 공정증서 고지인데, 이것도 "장소를 뒤져보라"는 탐색 조언이 아니라
      "아직 확인되지 않은 경로가 하나 있다"는 사실 고지다 — 공정증서는 원본이
      공증사무소에 보관되어 고인이 정본을 갖고 있지 않아도 존재할 수 있다.
    - **상속인 범위·지분·유류분은 여기서 답하지 않는다.** heir_navigator 영역이라
      침범하면 두 에이전트가 서로 다른 답을 할 위험이 있다. "법정상속 절차를
      따릅니다"까지만 말하고, 필요하면 채팅으로 돌아가 다시 물어보라고 안내한다
      (아래 router 안내 참고).
    - CLAUDE.md 절대 원칙 2(무단정)를 그대로 적용한다 — "유언장이 없으니
      법정상속입니다" 같은 단정 대신 "확인된 유언장이 없는 경우 일반적으로 ~
      따릅니다" 패턴을 쓴다. 문구는 rules/will_types.json 의 no_will 에 있다.

    ⚠️ (버그 수정) 다른 안내 전용 분기(_guidance_only_output — notarial/secret/oral)는
    전부 _namespaced()로 will_type을 세션에 기록하는데, 이 함수만 평면 dict를 그대로
    반환해서 data["decedent_estate"] 네임스페이스가 비어 있었다. 그 결과
    handoff.extract_state_to_persist가 아무것도 저장하지 못해(next turn에서
    `{}` ) will_type="none" 이 세션에서 사라지고, 나중에 다시 decedent_estate로
    라우팅되면(예: 사용자가 heir_navigator 대화 중 "유언장" 키워드를 다시 언급) 방식
    질문을 처음부터 다시 하게 되는 회귀가 있었다. _namespaced()로 감싸 다른 분기와
    동일하게 상태를 남긴다. (이 문단은 will_type="none" 세션 저장 관련 — 아래
    next_action 제거와는 무관하니 건드리지 않는다.)

    ⚠️ (2026-08-25) heir_navigator로의 직접 next_action 핸드오프를 제거했다.
    웹 UI가 "로그인 후 채팅창에서 라우터가 적합한 에이전트를 선택"하는 구조로
    확정되면서, #20에서 넣었던 handoff:heir_navigator 는 받는 쪽이 없어 막다른
    길이었다 — 사용자는 채팅으로 돌아가 다시 말하면 라우터가 알아서 보낸다.
    next_action은 이제 다른 안내 전용 분기(secret/oral)와 마찬가지로 None이다.
    """
    guidance = no_will_guidance()

    reply = "\n\n".join(
        [
            guidance["legal_succession_guidance"],
            guidance["chat_return_notice"],
            guidance["notarial_notice"],
            *closing_lines(),
        ]
    )

    data: dict[str, Any] = {
        "will_type": _NO_WILL_TYPE,
        "warnings": [],
    }

    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        data=_namespaced(state, data, will_type=_NO_WILL_TYPE, pending_questions=[]),
    )


def _guidance_only_output(
    state: DecedentState,
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
        data=_namespaced(
            state, data, will_type=will_type_info["id"], pending_questions=[]
        ),
    )


def _resolve_photo_intake(
    payload: AgentInput, state: DecedentState
) -> tuple[Optional[AgentOutput], str, DecedentState]:
    """유언장 사진 판독 개입 지점 (설계 방침 A/B/E/F).

    사진과 전혀 무관하면(이번 턴 이미지도 없고, 진행 중이던 판독도 없음)
    (None, payload.user_message, state) 를 그대로 돌려줘 기존 텍스트 경로를
    한 글자도 건드리지 않는다 — 회귀 없음.

    반환:
    - (AgentOutput, _, _): 아직 확인이 안 끝났다(또는 판독 실패). 이걸 그대로
      반환하고 요건 판정 파이프라인은 이번 턴에 돌지 않는다.
    - (None, text, state): 사진이 없었거나, 확인까지 전부 끝났다. text 를
      기존 check_requirements() 에 그대로 넘기면 된다 — 판독값을
      "유언자: OOO" 같은 텍스트로 재구성해 payload.user_message 앞에
      붙인 것뿐이라, requirement_checker.py 는 한 줄도 몰라도 된다(방침 A).
      state 는 seal_answer 가 채워졌을 수 있고, photo_draft/
      photo_confirm_answers 는 소비되어 비어 있다.

    ⚠️ 원본 이미지(payload.image_base64)는 여기서 한 번 쓰이고 버려진다 —
    state 어디에도 담기지 않는다(state.py 의 DecedentState 참고, 방침 B).
    """
    if payload.image_base64:
        fields = (
            extract_will_photo_fields(payload.image_base64, payload.image_media_type)
            if payload.image_media_type
            else None
        )
        if fields is None:
            state = state.model_copy(
                update={"photo_draft": {}, "photo_confirm_answers": {}}
            )
            reply = "사진을 판독하지 못했습니다. 유언장 내용을 직접 입력해 주세요."
            return (
                AgentOutput(
                    agent=AgentName.DECEDENT_ESTATE,
                    reply=reply,
                    next_action=NEXT_ACTION_AWAIT_USER,
                    data=_namespaced(state, {"warnings": []}),
                ),
                payload.user_message,
                state,
            )
        state = state.model_copy(
            update={"photo_draft": fields, "photo_confirm_answers": {}}
        )

    draft = state.photo_draft
    if not draft:
        return None, payload.user_message, state

    templates_section = photo_confirm_templates()
    templates = templates_section["fields"]
    options = templates_section["options"]
    answers = state.photo_confirm_answers

    pending: list[dict[str, Any]] = []
    for field_id in PHOTO_FIELD_IDS:
        field_draft = draft.get(field_id) or {}
        if field_draft.get("confidence") != "low" or field_id in answers:
            continue
        template = templates[field_id]
        pending.append(
            {
                "requirement": template["requirement_name"],
                "field": f"photo_confirm_answers.{field_id}",
                "question": template["question_template"].format(
                    value=field_draft.get("value")
                ),
                "options": options,
            }
        )

    if pending:
        reply = "사진에서 읽은 내용을 확인해 주세요.\n\n" + "\n".join(
            f"- {q['question']}" for q in pending
        )
        return (
            AgentOutput(
                agent=AgentName.DECEDENT_ESTATE,
                reply=reply,
                next_action=NEXT_ACTION_AWAIT_USER,
                data=_namespaced(
                    state,
                    {"pending_questions": pending, "warnings": []},
                    pending_questions=pending,
                ),
            ),
            payload.user_message,
            state,
        )

    # 확인이 전부 끝났다 — 값을 확정하고 기존 파이프라인용 텍스트로 재구성한다.
    lines: list[str] = []
    seal_answer = state.seal_answer
    for field_id in PHOTO_FIELD_IDS:
        field_draft = draft.get(field_id) or {}
        value = field_draft.get("value")
        confidence = field_draft.get("confidence")
        if confidence == "high":
            accepted = value
        elif confidence == "low":
            accepted = value if answers.get(field_id) == "yes" else None
        else:
            accepted = None

        if accepted is None:
            continue
        if field_id == "seal":
            seal_answer = accepted
        elif field_id == "name":
            lines.append(f"유언자: {accepted}")
        elif field_id == "address":
            lines.append(f"주소: {accepted}")
        elif field_id == "date":
            lines.append(accepted)

    reconstructed = "\n".join(lines)
    text = (
        f"{reconstructed}\n\n{payload.user_message}"
        if payload.user_message
        else reconstructed
    )
    resolved_state = state.model_copy(
        update={
            "photo_draft": {},
            "photo_confirm_answers": {},
            "seal_answer": seal_answer,
        }
    )
    return None, text, resolved_state


def _run_handwritten_pipeline(
    payload: AgentInput,
    state: DecedentState,
    *,
    prefix_notice: Optional[str] = None,
    intent: str = _REVIEW_INTENT,
) -> AgentOutput:
    """자필증서 요건 판정 파이프라인. handwritten 직접 선택과 unknown(기본값 적용)
    둘 다 여기로 온다.

    intent 는 _resolve_intent 가 정리한 "확정된" 값을 저장하기 위한 것이다 —
    클라이언트가 intent 를 아예 안 보냈을 때도 세션에는 review 로 남겨야
    "intent 미지정 == review" 가 다음 턴까지 그대로 유지된다.

    사진이 있으면(payload.image_base64) _resolve_photo_intake 가 먼저
    개입한다 — 확인이 안 끝났으면 여기서 조기 반환하고, 끝났으면 판독값이
    반영된 text 로 아래 로직이 평소와 동일하게 돈다.
    """
    photo_output, text, state = _resolve_photo_intake(payload, state)
    if photo_output is not None:
        return photo_output

    handwriting_answer = state.handwriting_answer
    seal_answer = state.seal_answer
    address_envelope_answer = state.address_envelope_answer

    results = check_requirements(
        text,
        handwriting_answer=handwriting_answer,
        seal_answer=seal_answer,
        address_envelope_answer=address_envelope_answer,
    )

    next_action = _next_action(results)

    requirements = {
        rid: _requirement_payload(results[rid]) for rid in _ALL_REQUIREMENT_IDS
    }
    pending = pending_questions(results)

    data: dict[str, Any] = {
        "will_type": _HANDWRITTEN_WILL_TYPE,
        "requirements": requirements,
        "pending_questions": pending,
        "progress": progress(results, _FORMAL_REQUIREMENT_IDS),
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
        data=_namespaced(
            state,
            data,
            will_type=_HANDWRITTEN_WILL_TYPE,
            intent=intent,
            requirements=requirements,
            pending_questions=pending,
        ),
    )


def _run_recording_pipeline(
    payload: AgentInput, state: DecedentState, *, intent: str = _REVIEW_INTENT
) -> AgentOutput:
    """녹음 유언(§1067) 대본 요건 판정 파이프라인."""
    rec_witness_present_answer = state.rec_witness_present_answer
    rec_witness_eligible_answer = state.rec_witness_eligible_answer

    results = check_recording_requirements(
        payload.user_message,
        rec_witness_present_answer=rec_witness_present_answer,
        rec_witness_eligible_answer=rec_witness_eligible_answer,
    )

    next_action = _next_action_recording(results)

    requirements = {
        rid: _requirement_payload(results[rid])
        for rid in FORMAL_RECORDING_REQUIREMENT_IDS
    }
    pending = pending_questions(results, FORMAL_RECORDING_REQUIREMENT_IDS)

    data: dict[str, Any] = {
        "will_type": _RECORDING_WILL_TYPE,
        "requirements": requirements,
        "pending_questions": pending,
        "progress": progress(results, FORMAL_RECORDING_REQUIREMENT_IDS),
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
        data=_namespaced(
            state,
            data,
            will_type=_RECORDING_WILL_TYPE,
            intent=intent,
            requirements=requirements,
            pending_questions=pending,
        ),
    )


_PREPARE_DRAFT_INVITE = (
    "초안을 작성하신 뒤 그 내용을 보내주시면 형식 요건을 점검해드릴게요."
)


def _run_handwritten_prepare_pipeline(
    payload: AgentInput, state: DecedentState, *, prefix_notice: Optional[str] = None
) -> AgentOutput:
    """자필증서 준비 가이드(intent == "prepare"). handwritten 직접 선택과 unknown
    (기본값 적용) 둘 다 여기로 온다 — review 파이프라인과 동일한 분기 구조.

    이미 초안이 있으면(has_draft_text) 가이드 문구 뒤에 기존 review 파이프라인
    (_run_handwritten_pipeline) 결과를 그대로 이어붙인다 — 판정 로직 자체는
    중복 구현하지 않는다. 이때 가이드 쪽 마무리 문구(상담 연결·하단 고지)는
    빼고(include_closing=False) 이어 붙는 점검 결과 쪽 것만 남긴다 — 한 화면에
    같은 두 줄이 두 번 반복되지 않게 하기 위해서다.
    """
    has_draft = _has_draft_text(payload, state)

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
        review_output = _run_handwritten_pipeline(payload, state)
        reply = f"{reply}\n\n---\n\n**작성하신 초안을 점검한 결과입니다.**\n\n{review_output.reply}"
        # review_output.data 에는 이미 네임스페이스 키가 들어 있다. 중첩 저장을
        # 피하려고 빼고 담고, 상태는 아래에서 한 번만 최상위에 붙인다.
        review_data = {k: v for k, v in review_output.data.items() if k != STATE_KEY}
        data["review"] = review_data
        return AgentOutput(
            agent=AgentName.DECEDENT_ESTATE,
            reply=reply,
            next_action=review_output.next_action,
            data=_namespaced(
                state,
                data,
                will_type=_HANDWRITTEN_WILL_TYPE,
                intent=_PREPARE_INTENT,
                requirements=review_data.get("requirements", {}),
                pending_questions=review_data.get("pending_questions", []),
            ),
        )

    reply = f"{reply}\n\n{_PREPARE_DRAFT_INVITE}"
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        next_action=None,
        data=_namespaced(
            state,
            data,
            will_type=_HANDWRITTEN_WILL_TYPE,
            intent=_PREPARE_INTENT,
            requirements={},
            pending_questions=[],
        ),
    )


def _run_recording_prepare_pipeline(
    payload: AgentInput, state: DecedentState
) -> AgentOutput:
    """녹음 유언(§1067) 준비 가이드(intent == "prepare"). 이미 대본이 있으면
    가이드 뒤에 기존 review 파이프라인(_run_recording_pipeline) 결과를 이어붙이고,
    이때 가이드 쪽 마무리 문구는 빼서(include_closing=False) 상담 연결·하단 고지가
    한 화면에 두 번 반복되지 않게 한다 — handwritten prepare와 동일한 처리."""
    has_draft = _has_draft_text(payload, state)

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
        review_output = _run_recording_pipeline(payload, state)
        reply = f"{reply}\n\n---\n\n**작성하신 대본을 점검한 결과입니다.**\n\n{review_output.reply}"
        review_data = {k: v for k, v in review_output.data.items() if k != STATE_KEY}
        data["review"] = review_data
        return AgentOutput(
            agent=AgentName.DECEDENT_ESTATE,
            reply=reply,
            next_action=review_output.next_action,
            data=_namespaced(
                state,
                data,
                will_type=_RECORDING_WILL_TYPE,
                intent=_PREPARE_INTENT,
                requirements=review_data.get("requirements", {}),
                pending_questions=review_data.get("pending_questions", []),
            ),
        )

    reply = f"{reply}\n\n{_PREPARE_DRAFT_INVITE}"
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=reply,
        next_action=None,
        data=_namespaced(
            state,
            data,
            will_type=_RECORDING_WILL_TYPE,
            intent=_PREPARE_INTENT,
            requirements={},
            pending_questions=[],
        ),
    )


def run(payload: AgentInput) -> AgentOutput:
    """대화형 유언장 점검 실행 + 공유 will_status 요약을 얹어 돌려준다.

    실제 파이프라인은 _run_pipeline 이 담당하고, 이 함수는 그 결과에서
    tax_calculator·heir_share_analyzer 가 참고할 compact WillStatus 를 뽑아
    AgentOutput.will_status 로 붙인다 (schemas.WillStatus).
    """
    output = _run_pipeline(payload)
    output.will_status = _derive_will_status(output)
    return output


#: 요건 판정 등급(rules/requirements.json) → 공유 WillStatus 등급.
_GRADE_MAP: dict[str, str] = {"RED": "red", "YELLOW": "yellow", "GREEN": "green"}


def _derive_will_status(output: AgentOutput) -> WillStatus:
    ns = output.data.get(STATE_KEY, {}) if isinstance(output.data, dict) else {}
    will_type = ns.get("will_type")
    requirements = ns.get("requirements") or {}
    pending_questions = ns.get("pending_questions") or []

    no_will = will_type == _NO_WILL_TYPE
    checked = bool(will_type) and will_type in _valid_will_type_values()

    grades = {
        r.get("grade")
        for r in requirements.values()
        if isinstance(r, dict) and r.get("grade")
    }
    overall_grade: Optional[str] = None
    if requirements and not pending_questions and "PENDING" not in grades:
        for raw_grade in ("RED", "YELLOW", "GREEN"):
            if raw_grade in grades:
                overall_grade = _GRADE_MAP[raw_grade]
                break

    has_effect: Optional[bool] = None
    if overall_grade == "green" or will_type == _NOTARIAL_WILL_TYPE:
        has_effect = True
    elif overall_grade == "red":
        has_effect = False

    return WillStatus(
        checked=checked,
        will_type=None if no_will else will_type,
        no_will=no_will,
        overall_grade=overall_grade,
        has_effect=has_effect,
    )


def _run_pipeline(payload: AgentInput) -> AgentOutput:
    # 상태는 네임스페이스(context["decedent_estate"])에서 읽고, 이번 턴에 평면
    # 키가 왔으면 그 값을 우선한다 (state.load_state — 전환기 안전망).
    state = load_state(payload.context)
    will_type = state.will_type

    if will_type is None:
        return _will_type_question_output(state)

    if will_type not in _valid_will_type_values():
        return _will_type_question_output(
            state,
            warnings=[
                {
                    "field": "will_type",
                    "invalid_value": will_type,
                    "allowed": list(_valid_will_type_values()),
                }
            ],
        )

    # "유언장이 없다/못 찾았다" — 요건 판정 대상이 아예 없으므로 intent 게이트보다
    # 먼저 갈라낸다 (review/prepare 구분이 의미 없다).
    if will_type == _NO_WILL_TYPE:
        return _run_no_will_pipeline(state)

    if will_type in _FULL_SUPPORT_WILL_TYPES:
        intent, intent_warnings = _resolve_intent(state)
        if intent is None:  # 화이트리스트 밖 값 — will_type 게이트와 동일하게 재질문
            return _intent_question_output(state, will_type, warnings=intent_warnings)

        if will_type == _HANDWRITTEN_WILL_TYPE:
            if intent == _PREPARE_INTENT:
                return _run_handwritten_prepare_pipeline(payload, state)
            return _run_handwritten_pipeline(payload, state)

        if will_type == _UNKNOWN_WILL_TYPE:
            default = unknown_default()
            if intent == _PREPARE_INTENT:
                return _run_handwritten_prepare_pipeline(
                    payload, state, prefix_notice=default["notice"]
                )
            return _run_handwritten_pipeline(
                payload, state, prefix_notice=default["notice"]
            )

        # will_type == _RECORDING_WILL_TYPE
        if intent == _PREPARE_INTENT:
            return _run_recording_prepare_pipeline(payload, state)
        return _run_recording_pipeline(payload, state)

    will_type_info = get_will_type(will_type)  # notarial / secret / oral

    if will_type == _NOTARIAL_WILL_TYPE:
        return _guidance_only_output(
            state,
            will_type_info,
            include_requirements_summary=False,
            next_action=NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
            handoff_reason="공정증서 유언 확인 완료 — 검인 절차 없이 상속 절차 안내로 연결",
        )

    # secret / oral: 요건 요약 + "자동 점검 미지원" 안내만 하고 종료.
    return _guidance_only_output(state, will_type_info)

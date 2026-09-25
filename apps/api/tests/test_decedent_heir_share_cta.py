"""
decedent_estate 완료된 유언 요건 review 뒤에 붙는 유류분 opt-in CTA
(suggested_actions) 테스트.

핵심 계약(agents/decedent_estate/agent.py._review_complete_for_heir_share_cta):
- 절대 자동 handoff하지 않는다 — CTA가 붙어도 handoffs==[]·next_action에
  handoff 값이 없고, pending_handoff/pending_reply_agent도 세워지지 않는다.
- 실제로 요건 점검이 끝난 handwritten/recording review에만 CTA를 낸다.
- 사용자가 버튼을 눌러 CTA.message를 새 user_message로 보내면(여기서는
  라우터가 실제로 heir_share_analyzer를 선택하는지까지 확인) 기존
  router.classify()를 그대로 통과한다 — decedent_estate 전용 강제 라우팅이
  아니다.
"""

from __future__ import annotations

from agents import decedent_estate
from agents.decedent_estate.agent import NEXT_ACTION_AWAIT_USER, _HEIR_SHARE_CTA
from orchestrator import router
from orchestrator.handoff import extract_state_to_persist
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName

_HEIR_SHARE_PROMPT = (
    "유언 내용이 상속인의 유류분에 영향을 줄 수 있는지 참고용으로 확인해 볼까요?"
)
_HEIR_SHARE_LABEL = "유류분 영향 확인하기"
_HEIR_SHARE_MESSAGE = "유언 내용이 상속인의 유류분에 영향을 줄 수 있는지 확인해 주세요."

#: 라우팅 테스트(G, 6번)에서 asset_organizer 키워드("재산"/"부동산" 등)까지
#: 후보에 끼어들지 않도록, 처분 대상은 "모든 것"으로만 쓴다("상속한다"
#: 동사만으로도 _DRAFT_DISPOSITION_VERB_RE가 처분 의사로 인식한다).
_WILL_TEXT_COMPLETE = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 모든 것을 배우자에게 상속한다."
)

_RECORDING_TRANSCRIPT_COMPLETE = "\n".join(
    [
        "유언자: 홍길동",
        "저의 모든 것을 배우자에게 상속한다.",
        "2026년 5월 3일",
        "증인: 김철수",
        "증인은 위 유언이 정확함을 확인합니다.",
    ]
)


def _run(text: str, **context):
    return decedent_estate.run(
        AgentInput(session_id="s1", user_message=text, context=context)
    )


# 계약 상수 자체가 스펙과 일치하는지(문구 오타 회귀 가드).


def test_cta_constant_matches_spec_copy() -> None:
    assert _HEIR_SHARE_CTA.prompt == _HEIR_SHARE_PROMPT
    assert _HEIR_SHARE_CTA.label == _HEIR_SHARE_LABEL
    assert _HEIR_SHARE_CTA.message == _HEIR_SHARE_MESSAGE


# A. 완료된 handwritten review


def test_completed_handwritten_review_gets_heir_share_cta() -> None:
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    for rid in ("date", "address", "name", "handwriting", "seal"):
        assert output.data["requirements"][rid]["grade"] == "GREEN"
    assert output.next_action is None

    assert len(output.suggested_actions) == 1
    action = output.suggested_actions[0]
    assert action.prompt == _HEIR_SHARE_PROMPT
    assert action.label == _HEIR_SHARE_LABEL
    assert action.message == _HEIR_SHARE_MESSAGE

    # CTA를 붙였다고 자동 handoff가 생기면 안 된다.
    assert output.handoffs == []
    assert output.next_action is None


# B. 완료된 recording review


def test_completed_recording_review_gets_heir_share_cta() -> None:
    output = _run(
        _RECORDING_TRANSCRIPT_COMPLETE,
        will_type="recording",
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
        "rec_witness_present",
        "rec_witness_eligible",
    ):
        assert output.data["requirements"][rid]["grade"] == "GREEN"
    assert output.next_action is None

    assert len(output.suggested_actions) == 1
    action = output.suggested_actions[0]
    assert action.prompt == _HEIR_SHARE_PROMPT
    assert action.label == _HEIR_SHARE_LABEL
    assert action.message == _HEIR_SHARE_MESSAGE
    assert output.handoffs == []


# C. 아직 PENDING이 남은 review — CTA 없음


def test_review_with_pending_requirement_has_no_cta() -> None:
    output = _run(_WILL_TEXT_COMPLETE, will_type="handwritten")

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert output.data["requirements"]["handwriting"]["grade"] == "PENDING"
    assert output.suggested_actions == []


def test_review_with_red_requirement_has_no_cta() -> None:
    """RED가 남으면 _next_action이 AWAIT_USER를 반환해 미종결로 취급되므로
    CTA도 붙지 않는다(#118 원칙과 동일한 근거)."""
    text = (
        "유언장\n유언자: 홍길동\n2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
    )
    output = _run(
        text,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )

    assert output.data["requirements"]["address"]["grade"] == "RED"
    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert output.suggested_actions == []


# D. prepare — CTA 없음 (초안 완료 review가 이어붙어도 최상위 intent는 prepare)


def test_prepare_with_completed_embedded_review_has_no_cta() -> None:
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="prepare",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    assert output.data["review"]["requirements"]["date"]["grade"] == "GREEN"
    assert output.next_action is None
    assert output.suggested_actions == []


# E. no-will — CTA 없음 (완료된 review 이후 no-will로 전환되는 carry-over도 방어)


def test_no_will_has_no_cta() -> None:
    output = _run("유언장이 없어요", will_type="none")

    assert output.data["will_type"] == "none"
    assert output.suggested_actions == []


def test_no_will_after_completed_review_still_has_no_cta() -> None:
    """세션에 이미 완료된 review(intent=review, requirements 가득 참)가 있는
    상태에서 이번 턴에 "유언장이 없다"로 전환되면, will_type만 none으로
    바뀌고 requirements/intent는 명시적으로 초기화되지 않는다
    (_run_no_will_pipeline). 이 stale 상태만으로 CTA 조건을 오판하면 안
    된다."""
    completed = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )
    assert completed.suggested_actions != []

    switched = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="사실 유언장이 없는 것 같아요",
            context={
                "decedent_estate": completed.data["decedent_estate"],
                "will_type": "none",
            },
        )
    )

    assert switched.data["decedent_estate"]["will_type"] == "none"
    assert switched.suggested_actions == []


# F. guidance-only(notarial 등) — CTA 없음


def test_notarial_guidance_only_has_no_cta() -> None:
    output = _run(_WILL_TEXT_COMPLETE, will_type="notarial")

    assert output.data["will_type"] == "notarial"
    assert output.next_action is None
    assert output.suggested_actions == []


def test_secret_guidance_only_has_no_cta() -> None:
    output = _run(_WILL_TEXT_COMPLETE, will_type="secret")

    assert output.data["will_type"] == "secret"
    assert output.suggested_actions == []


# G. 클릭 메시지 라우팅 — 기존 router를 통해 heir_share_analyzer로.
#
# CTA 메시지("유언 내용이 상속인의 유류분에...")에는 decedent_estate의
# 키워드("유언")도 들어 있어 규칙 경로(LLM 불가 시 폴백)에서는 후보가
# 2개(DECEDENT_ESTATE + HEIR_SHARE_ANALYZER)가 되어 Full Pipeline으로
# 돈다 — 이건 이 저장소의 기존 설계(예: test_decedent_estate_routing_scenarios
# 4번 케이스, "유언장 효력도 확인하고 상속세도 계산해줘")와 동일한 동작이라
# 새 버그가 아니다. decedent_estate가 will_status를 생산하고
# heir_share_analyzer가 그걸 요구하므로 DAG상 decedent_estate 층이 먼저
# 오고, 최종 대표 에이전트(ChatResponse.agent, primary=outputs[-1])는
# heir_share_analyzer가 된다.


def test_heir_share_cta_message_routes_to_heir_share_analyzer(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())

    turn1 = router.route(
        AgentInput(
            session_id="cta-route-1",
            user_message=_WILL_TEXT_COMPLETE,
            context={
                "decedent_estate": {
                    "will_type": "handwritten",
                    "handwriting_answer": "yes",
                    "seal_answer": "seal_or_fingerprint",
                }
            },
        )
    )
    assert turn1.agent == AgentName.DECEDENT_ESTATE
    assert turn1.next_action is None
    # 최상위 ChatResponse.suggested_actions는 compose()가 채우지 않는 평면
    # 필드라 항상 빈 배열이다 — 프론트는 contributions[]에서 읽어야 한다
    # (아래 6번 테스트, test_suggested_actions_survive_into_chat_response_contributions).
    turn1_decedent = next(
        c for c in turn1.contributions if c.agent == AgentName.DECEDENT_ESTATE
    )
    assert len(turn1_decedent.suggested_actions) == 1
    assert turn1_decedent.suggested_actions[0].message == _HEIR_SHARE_MESSAGE

    # 이전 턴이 완료된 review라 pending_handoff/pending_reply_agent가 서지
    # 않는다 — decedent_estate로 강제 고정되지 않았음을 먼저 확인한다.
    stored = router.default_store.load("cta-route-1")
    assert stored.pending_handoff is None
    assert stored.pending_reply_agent is None

    turn2 = router.route(
        AgentInput(session_id="cta-route-1", user_message=_HEIR_SHARE_MESSAGE)
    )

    assert AgentName.HEIR_SHARE_ANALYZER in turn2.agents
    assert turn2.agent == AgentName.HEIR_SHARE_ANALYZER
    decedent_idx = turn2.agents.index(AgentName.DECEDENT_ESTATE)
    heir_share_idx = turn2.agents.index(AgentName.HEIR_SHARE_ANALYZER)
    assert decedent_idx < heir_share_idx

    by_agent = {c.agent: c for c in turn2.contributions}
    assert AgentName.HEIR_SHARE_ANALYZER in by_agent


# 6. AgentOutput.suggested_actions가 ChatResponse.contributions까지 손실
# 없이 전달되는지 — router/compose 코드는 건드리지 않고, 실제 배관만 확인.


def test_suggested_actions_survive_into_chat_response_contributions(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())

    output = router.route(
        AgentInput(
            session_id="cta-contrib-1",
            user_message=_WILL_TEXT_COMPLETE,
            context={
                "decedent_estate": {
                    "will_type": "handwritten",
                    "handwriting_answer": "yes",
                    "seal_answer": "seal_or_fingerprint",
                }
            },
        )
    )

    assert output.agent == AgentName.DECEDENT_ESTATE
    assert len(output.contributions) == 1
    contribution = output.contributions[0]
    assert contribution.agent == AgentName.DECEDENT_ESTATE
    assert len(contribution.suggested_actions) == 1
    assert contribution.suggested_actions[0].message == _HEIR_SHARE_MESSAGE
    # CTA가 최상위 handoffs/next_action에 영향을 주지 않는다.
    assert output.handoffs == []
    assert output.next_action is None


def test_suggested_actions_persist_state_unaffected() -> None:
    """CTA 부착이 세션 저장 상태(_namespaced 산출물)에 새 필드를 흘려넣지
    않는지 — suggested_actions는 AgentOutput 레벨 필드일 뿐 DecedentState에는
    없다."""
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )
    persisted = extract_state_to_persist(AgentName.DECEDENT_ESTATE, output)
    assert "suggested_actions" not in persisted

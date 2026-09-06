"""
review가 이미 시작된 뒤 사용자가 확인 질문에 자연어로 답하면 document intake
gate(#103)가 다시 발동해 review가 처음으로 되돌아가던 버그.

재현 (3턴):
1턴: "아버지가 돌아가시고 집 정리하다가 손으로 직접 쓴 유언장을 발견했어요.
     이게 법적으로 효력이 있는 건지 확인하고 싶어요." → intake 요청.
2턴: "내 소유 아파트는 장남 김민수에게 주고, 은행 예금은 두 아들이 반씩
     나누어 가진다." → checker 실행, requirements 생성(#114).
3턴: "주소는 유언장 본문에 적혀 있습니다. 날짜와 아버지 성함도 적혀 있고요.
     유언장 전체를 아버지가 직접 손으로 쓰셨고, 도장도 찍혀 있습니다."
     → _looks_like_draft가 False라 다시 intake로 되돌아가던 버그.

수정: review가 이미 시작된 뒤(state.requirements 비어있지 않음)에는 intake
gate를 재적용하지 않는다. handwriting/seal의 명백한 자연어 확인은
deterministic하게 반영하고, 날짜/성명/주소는 이번 턴에 실제 근거가 없으면
이전에 이미 확정된 결과만 보존한다(추측 GREEN 금지, 유언장 원문 저장 없음).

router.build_agent_context/extract_state_to_persist 규약과 동일하게, 다음
턴 context는 항상 `{"decedent_estate": <이전 턴 output.data["decedent_estate"]>}`
로 감싸서 넘긴다 — 이게 실제 운영 경로(orchestrator)가 하는 방식이다.
"""

from agents import decedent_estate
from schemas import AgentInput

_INTAKE_REQUEST_MESSAGE = (
    "아버지가 돌아가시고 집 정리하다가 손으로 직접 쓴 유언장을 발견했어요. "
    "이게 법적으로 효력이 있는 건지 확인하고 싶어요."
)
_WILL_BODY_WITH_ASSET_KEYWORDS = (
    "내 소유 아파트는 장남 김민수에게 주고, 은행 예금은 두 아들이 반씩 나누어 가진다."
)
_NATURAL_CONFIRMATION_MESSAGE = (
    "주소는 유언장 본문에 적혀 있습니다. 날짜와 아버지 성함도 적혀 있고요. "
    "유언장 전체를 아버지가 직접 손으로 쓰셨고, 도장도 찍혀 있습니다."
)

_INTAKE_NOTICE_FRAGMENT = "유언장 사진을 올려주시거나"


def _ctx(output) -> dict:
    """실제 orchestrator(handoff.build_agent_context)가 다음 턴에 넘기는 형태로
    감싼다 — output.data["decedent_estate"] 를 같은 이름으로 다시 네임스페이스
    한다."""
    return {"decedent_estate": output.data["decedent_estate"]}


def test_exact_three_turn_repro_does_not_reenter_intake_gate() -> None:
    turn1 = decedent_estate.run(
        AgentInput(session_id="s1", user_message=_INTAKE_REQUEST_MESSAGE)
    )
    assert _INTAKE_NOTICE_FRAGMENT in turn1.reply
    assert "requirements" not in turn1.data

    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_WILL_BODY_WITH_ASSET_KEYWORDS,
            context=_ctx(turn1),
        )
    )
    assert "requirements" in turn2.data

    turn3 = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_NATURAL_CONFIRMATION_MESSAGE,
            context=_ctx(turn2),
        )
    )
    # 핵심 회귀: intake 안내가 다시 나오면 안 된다.
    assert _INTAKE_NOTICE_FRAGMENT not in turn3.reply
    assert "requirements" in turn3.data

    requirements = turn3.data["requirements"]
    # D: handwriting/seal의 명백한 자연어 확인은 반영된다.
    assert requirements["handwriting"]["grade"] == "GREEN"
    assert requirements["seal"]["grade"] == "GREEN"
    assert turn3.data["decedent_estate"]["handwriting_answer"] == "yes"
    assert turn3.data["decedent_estate"]["seal_answer"] == "seal_or_fingerprint"

    # F: 날짜/성명/주소는 "적혀 있다"는 존재 주장만으로 GREEN 처리하지 않는다 —
    # 실제 값이 없으므로 여전히 RED/PENDING(추가 확인)으로 남아야 한다.
    assert requirements["date"]["grade"] != "GREEN"
    assert requirements["name"]["grade"] != "GREEN"
    assert requirements["address"]["grade"] != "GREEN"

    # 유언장 원문은 세션 어디에도 저장되지 않는다.
    namespaced = turn3.data["decedent_estate"]
    for value in namespaced.values():
        if isinstance(value, str):
            assert _INTAKE_REQUEST_MESSAGE not in value
            assert _WILL_BODY_WITH_ASSET_KEYWORDS not in value
            assert _NATURAL_CONFIRMATION_MESSAGE not in value


def test_established_requirement_is_preserved_when_followup_lacks_evidence() -> None:
    """이전 턴에 이미 실제 근거로 GREEN까지 확정된 요건은, 이후 턴이 근거 없는
    자연어 답변이어도 되돌아가지 않는다."""
    turn1 = decedent_estate.run(
        AgentInput(
            session_id="s2",
            user_message=(
                "유언장\n유언자: 홍길동\n주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
                "2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
            ),
            context={"decedent_estate": {"will_type": "handwritten"}},
        )
    )
    assert turn1.data["requirements"]["date"]["grade"] == "GREEN"
    assert turn1.data["requirements"]["address"]["grade"] == "GREEN"
    assert turn1.data["requirements"]["name"]["grade"] == "GREEN"

    # 근거 없는 순수 확인 답변 — 날짜/주소/성명 관련 텍스트가 전혀 없다.
    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s2",
            user_message="도장도 찍혀 있습니다.",
            context=_ctx(turn1),
        )
    )
    assert _INTAKE_NOTICE_FRAGMENT not in turn2.reply
    requirements = turn2.data["requirements"]
    # 이전에 확정된 GREEN이 그대로 유지돼야 한다 — absent로 되돌아가면 안 된다.
    assert requirements["date"]["grade"] == "GREEN"
    assert requirements["address"]["grade"] == "GREEN"
    assert requirements["name"]["grade"] == "GREEN"
    assert requirements["seal"]["grade"] == "GREEN"


def test_new_value_on_followup_turn_is_still_reevaluated() -> None:
    """review 진행 중이라도 이번 턴에 실제 새 값이 오면 rule engine이 그 값으로
    재판정한다 — 이전 값을 무조건 고집하지 않는다."""
    turn1 = decedent_estate.run(
        AgentInput(session_id="s3", user_message=_INTAKE_REQUEST_MESSAGE)
    )
    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s3",
            user_message=_WILL_BODY_WITH_ASSET_KEYWORDS,
            context=_ctx(turn1),
        )
    )
    assert turn2.data["requirements"]["date"]["grade"] != "GREEN"

    turn3 = decedent_estate.run(
        AgentInput(
            session_id="s3",
            user_message="작성일은 2026년 5월 3일입니다.",
            context=_ctx(turn2),
        )
    )
    assert turn3.data["requirements"]["date"]["grade"] == "GREEN"


def test_ambiguous_followup_does_not_fabricate_handwriting_or_seal() -> None:
    """모호한 자연어는 handwriting/seal을 임의로 확정하지 않는다 — 기존
    미확인(PENDING) 질문이 그대로 남아야 한다."""
    turn1 = decedent_estate.run(
        AgentInput(session_id="s4", user_message=_INTAKE_REQUEST_MESSAGE)
    )
    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s4",
            user_message=_WILL_BODY_WITH_ASSET_KEYWORDS,
            context=_ctx(turn1),
        )
    )

    turn3 = decedent_estate.run(
        AgentInput(
            session_id="s4",
            user_message="네 맞아요, 그렇게 하면 될 것 같아요.",
            context=_ctx(turn2),
        )
    )
    assert _INTAKE_NOTICE_FRAGMENT not in turn3.reply
    assert turn3.data["decedent_estate"]["handwriting_answer"] is None
    assert turn3.data["decedent_estate"]["seal_answer"] is None
    pending_fields = {q["field"] for q in turn3.data["pending_questions"]}
    assert "handwriting_answer" in pending_fields
    assert "seal_answer" in pending_fields

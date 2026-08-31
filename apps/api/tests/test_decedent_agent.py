"""
agents.decedent_estate.agent.run() 통합 테스트 (handwritten 파이프라인).

requirement_checker → result_formatter 파이프라인이 AgentInput/AgentOutput
계약(schemas.agent_io) 위에서 실제로 맞물려 동작하는지 확인한다. 유언 방식
분기(will_type 질문/notarial/recording/secret/oral) 자체는
test_decedent_will_type.py 에서 다룬다 — 여기서는 will_type="handwritten"
이 이미 확정된 이후의 동작만 본다.
"""

from agents import decedent_estate
from agents.decedent_estate.agent import (
    NEXT_ACTION_AWAIT_USER,
    NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
)
from schemas import AgentInput, AgentName

_WILL_TEXT_COMPLETE = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 전 재산을 배우자에게 상속한다."
)

_WILL_TEXT_ADDRESS_MISSING = (
    "유언장\n유언자: 홍길동\n2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
)


def _ctx(**extra: str) -> dict[str, str]:
    """평면 키 context (전환기 폴백 경로). 기존 테스트는 이 경로를 계속 검증한다."""
    return {"will_type": "handwritten", **extra}


def _ns_ctx(**extra: str) -> dict[str, object]:
    """네임스페이스 규약 context — 같은 값을 context["decedent_estate"] 로 넣는다."""
    return {"decedent_estate": {"will_type": "handwritten", **extra}}


def test_run_returns_contract_compliant_output() -> None:
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context=_ctx()
    )
    output = decedent_estate.run(payload)

    assert output.agent == AgentName.DECEDENT_ESTATE
    assert isinstance(output.reply, str) and output.reply != ""


def test_run_handwritten_without_confirm_answers_stays_pending() -> None:
    """will_type은 확정됐지만 자서·날인 확인 답변이 없으면 여전히 PENDING이어야 한다."""
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context=_ctx()
    )
    output = decedent_estate.run(payload)

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert output.data["requirements"]["handwriting"]["grade"] == "PENDING"
    assert output.data["requirements"]["seal"]["grade"] == "PENDING"


def test_run_all_green_and_confirmed_handoffs_to_heir_navigator() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ctx(handwriting_answer="yes", seal_answer="seal_or_fingerprint"),
    )
    output = decedent_estate.run(payload)

    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
    assert output.data["handoff_reason"] == "가정법원 검인 절차 안내 필요"

    reqs = output.data["requirements"]
    for rid in ("date", "address", "name", "handwriting", "seal"):
        assert reqs[rid]["grade"] == "GREEN"
        assert reqs[rid]["red_label"] is None

    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply
    assert output.data["pending_questions"] == []


def test_run_reads_answers_from_context() -> None:
    """context 의 세 확인 답변(자서/날인/주소봉투)이 실제로 판정에 반영되는지 확인."""
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_ADDRESS_MISSING,  # 주소 없음 → 본문 판정 RED
        context=_ctx(
            handwriting_answer="yes",
            seal_answer="seal_or_fingerprint",
            address_envelope_answer="envelope_or_minor_discrepancy",
        ),
    )
    output = decedent_estate.run(payload)

    address = output.data["requirements"]["address"]
    assert address["condition_id"] == "envelope_or_minor_discrepancy"
    assert address["grade"] == "YELLOW"
    assert address["precedent_ids"] == ["address_on_envelope_valid"]
    # PENDING이 하나도 없고 자서도 확인됐으니 heir_navigator 로 넘겨야 한다.
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR


def test_run_confirmed_typed_will_has_no_handoff() -> None:
    """자필이 아니라고 확인되면(전문 자서 RED) 검인 안내로 넘길 대상 자체가 아니다."""
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ctx(
            handwriting_answer="no_or_partial_typed", seal_answer="seal_or_fingerprint"
        ),
    )
    output = decedent_estate.run(payload)

    assert output.data["requirements"]["handwriting"]["grade"] == "RED"
    assert output.data["requirements"]["handwriting"]["red_label"] == "자필 작성 여부"
    assert output.next_action is None


def test_run_requirement_payload_covers_all_six_requirements() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ctx(handwriting_answer="yes", seal_answer="seal_or_fingerprint"),
    )
    output = decedent_estate.run(payload)

    assert set(output.data["requirements"].keys()) == {
        "date",
        "address",
        "name",
        "handwriting",
        "seal",
        "interseal",
    }


def test_run_no_confirm_answers_has_no_warnings() -> None:
    """확인 답변을 아예 안 준 것은 "잘못된 값"이 아니라 "미확인"이라 경고 대상이 아니다."""
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context=_ctx()
    )

    output = decedent_estate.run(payload)

    assert output.data["warnings"] == []


def test_run_invalid_seal_answer_produces_warning_but_stays_pending() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ctx(handwriting_answer="yes", seal_answer="yes"),  # 잘못된 필드에 넣음
    )

    output = decedent_estate.run(payload)

    assert output.data["warnings"] == [
        {
            "field": "seal_answer",
            "invalid_value": "yes",
            "allowed": ["seal_or_fingerprint", "signature_only", "absent"],
        }
    ]
    # 경고는 나가지만 판정 자체는 죽지 않고 PENDING 유지, next_action도 되묻는 힌트여야 한다.
    assert output.data["requirements"]["seal"]["grade"] == "PENDING"
    assert output.next_action == NEXT_ACTION_AWAIT_USER


def test_run_pending_question_includes_field_and_options() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ctx(handwriting_answer="yes"),
    )

    output = decedent_estate.run(payload)

    assert output.data["pending_questions"] == [
        {
            "requirement": "날인",
            "field": "seal_answer",
            "question": "도장 또는 지장(손도장)이 찍혀 있나요?",
            "options": [
                {"label": "도장 또는 지장이 있다", "value": "seal_or_fingerprint"},
                {"label": "서명만 있다", "value": "signature_only"},
                {"label": "아무것도 없다", "value": "absent"},
            ],
        }
    ]


# ---------------------------------------------------------------------------
# 네임스페이스 규약 (orchestrator/handoff.py 1번)
#
# 위 테스트들은 전부 평면 키(_ctx)로 돌아 전환기 폴백 경로를 검증한다. 여기서는
# 같은 시나리오를 네임스페이스(_ns_ctx)로 돌려 두 경로가 같은 결과를 내는지 본다.
# 상태 저장 정책(C안) 자체는 test_decedent_state.py 에서 따로 다룬다.
# ---------------------------------------------------------------------------


def test_namespaced_context_produces_same_result_as_flat() -> None:
    answers = {"handwriting_answer": "yes", "seal_answer": "seal_or_fingerprint"}

    flat = decedent_estate.run(
        AgentInput(
            session_id="s1", user_message=_WILL_TEXT_COMPLETE, context=_ctx(**answers)
        )
    )
    namespaced = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_WILL_TEXT_COMPLETE,
            context=_ns_ctx(**answers),
        )
    )

    assert flat.reply == namespaced.reply
    assert flat.next_action == namespaced.next_action
    assert flat.data["decedent_estate"] == namespaced.data["decedent_estate"]


def test_namespaced_context_reads_confirm_answers() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ns_ctx(handwriting_answer="no_or_partial_typed", seal_answer="absent"),
    )

    output = decedent_estate.run(payload)

    assert output.data["requirements"]["handwriting"]["grade"] == "RED"
    assert output.data["requirements"]["seal"]["grade"] == "RED"
    assert output.next_action is None


def test_run_progress_reflects_pending_confirm_answers() -> None:
    """진행률 체크리스트: 자서·날인 확인 답변이 없으면 5개 중 3개만 확인된 상태다
    (연월일·주소·성명은 텍스트에서 바로 판정되고, 자서·날인은 PENDING)."""
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context=_ctx()
    )
    output = decedent_estate.run(payload)

    assert output.data["progress"] == {"checked": 3, "total": 5}
    # 사진 판독(#35)과 동일하게, 진행률이 reply 텍스트에도 노출돼야 한다 —
    # data.progress만 있고 화면 문구엔 안 보이던 것을 이번에 붙였다.
    assert "(3/5 확인됨)" in output.reply


def test_run_progress_all_checked_when_confirm_answers_given() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context=_ctx(handwriting_answer="yes", seal_answer="seal_or_fingerprint"),
    )
    output = decedent_estate.run(payload)

    assert output.data["progress"] == {"checked": 5, "total": 5}


# ---------------------------------------------------------------------------
# A안 (#58 P0-1 후속): body/precedents는 요건별로(requirements[rid] 안에)
# 담긴다. 통짜 최상위 body/precedents(#58 원안)는 제거했다 — 프론트가 기대한
# 건 요건마다 자기 body·precedents를 갖는 구조(RequirementSignal)였고,
# 아무도 안 쓰는 통짜 필드를 남겨두면 중복 데이터가 된다.
# ---------------------------------------------------------------------------


def test_run_requirement_body_and_precedents_are_per_requirement() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_ADDRESS_MISSING,
        context=_ctx(
            handwriting_answer="no_or_partial_typed",  # RED — typed_will_invalid
            seal_answer="seal_or_fingerprint",
            address_envelope_answer="no_envelope",  # address RED — address_missing_invalid
        ),
    )
    output = decedent_estate.run(payload)

    ns = output.data["decedent_estate"]
    reqs = ns["requirements"]

    handwriting = reqs["handwriting"]
    assert isinstance(handwriting["body"], str) and handwriting["body"]
    # body 에는 판례 인용 카드 줄이 없다 (include_precedent_cards=False).
    assert "(대법원" not in handwriting["body"]
    handwriting_case_nos = {p["case_no"] for p in handwriting["precedents"]}
    assert "97다38510" in handwriting_case_nos  # typed_will_invalid

    address = reqs["address"]
    address_case_nos = {p["case_no"] for p in address["precedents"]}
    assert "2012다71688" in address_case_nos  # address_missing_invalid

    # 요건별로 격리된다 — 서로 다른 요건의 판례가 섞이지 않는다.
    assert "97다38510" not in address_case_nos
    assert "2012다71688" not in handwriting_case_nos

    # 통짜 최상위/네임스페이스 body·precedents는 이제 없다.
    assert "body" not in output.data and "precedents" not in output.data
    assert "body" not in ns and "precedents" not in ns

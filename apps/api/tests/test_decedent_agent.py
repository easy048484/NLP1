"""
agents.decedent_estate.agent.run() 통합 테스트.

requirement_checker → result_formatter 파이프라인이 AgentInput/AgentOutput
계약(schemas.agent_io) 위에서 실제로 맞물려 동작하는지 확인한다.
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


def test_run_returns_contract_compliant_output() -> None:
    payload = AgentInput(session_id="s1", user_message=_WILL_TEXT_COMPLETE)
    output = decedent_estate.run(payload)

    assert output.agent == AgentName.DECEDENT_ESTATE
    assert isinstance(output.reply, str) and output.reply != ""


def test_run_with_no_context_defaults_confirm_answers_to_none() -> None:
    payload = AgentInput(session_id="s1", user_message=_WILL_TEXT_COMPLETE)  # context 없음
    output = decedent_estate.run(payload)

    # 자서·날인 확인 답변이 없으니 PENDING이 남아야 하고, 되묻는 힌트가 나가야 한다.
    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert output.data["requirements"]["handwriting"]["grade"] == "PENDING"
    assert output.data["requirements"]["seal"]["grade"] == "PENDING"


def test_run_all_green_and_confirmed_handoffs_to_heir_navigator() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"handwriting_answer": "yes", "seal_answer": "seal_or_fingerprint"},
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
        context={
            "handwriting_answer": "yes",
            "seal_answer": "seal_or_fingerprint",
            "address_envelope_answer": "envelope_or_minor_discrepancy",
        },
    )
    output = decedent_estate.run(payload)

    address = output.data["requirements"]["address"]
    assert address["condition_id"] == "envelope_or_minor_discrepancy"
    assert address["grade"] == "YELLOW"
    assert address["precedent_ids"] == ["fingerprint_seal_valid"]
    # PENDING이 하나도 없고 자서도 확인됐으니 heir_navigator 로 넘겨야 한다.
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR


def test_run_confirmed_typed_will_has_no_handoff() -> None:
    """자필이 아니라고 확인되면(전문 자서 RED) 검인 안내로 넘길 대상 자체가 아니다."""
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"handwriting_answer": "no_or_partial_typed", "seal_answer": "seal_or_fingerprint"},
    )
    output = decedent_estate.run(payload)

    assert output.data["requirements"]["handwriting"]["grade"] == "RED"
    assert output.data["requirements"]["handwriting"]["red_label"] == "자필 작성 여부"
    assert output.next_action is None


def test_run_requirement_payload_covers_all_six_requirements() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"handwriting_answer": "yes", "seal_answer": "seal_or_fingerprint"},
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


def test_run_no_context_has_no_warnings() -> None:
    """확인 답변을 아예 안 준 것은 "잘못된 값"이 아니라 "미확인"이라 경고 대상이 아니다."""
    payload = AgentInput(session_id="s1", user_message=_WILL_TEXT_COMPLETE)

    output = decedent_estate.run(payload)

    assert output.data["warnings"] == []


def test_run_invalid_seal_answer_produces_warning_but_stays_pending() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"handwriting_answer": "yes", "seal_answer": "yes"},  # 잘못된 필드에 넣음
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
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context={"handwriting_answer": "yes"}
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

"""
agent.run() 의 recording(녹음, §1067) 파이프라인 통합 테스트.

완전한 대본 / 연월일 누락 / 증인 성명 없음 / 증인 결격 해당 / PENDING 케이스를
agent.run() 레벨에서 확인한다. recording_checker 자체의 추출 로직 단위 테스트는
test_decedent_recording_checker.py 를 참고.
"""

import pytest

from agents import decedent_estate
from agents.decedent_estate import recording_checker
from agents.decedent_estate.agent import (
    NEXT_ACTION_AWAIT_USER,
    NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
)
from schemas import AgentInput

_TESTATOR_LINE = "유언자: 홍길동"
_CONTENT_LINE = "저의 전 재산을 배우자에게 상속한다."
_DATE_LINE = "2026년 5월 3일"
_WITNESS_NAME_LINE = "증인: 김철수"
_WITNESS_ACCURACY_LINE = "증인은 위 유언이 정확함을 확인합니다."

_COMPLETE_TRANSCRIPT = "\n".join(
    [
        _TESTATOR_LINE,
        _CONTENT_LINE,
        _DATE_LINE,
        _WITNESS_NAME_LINE,
        _WITNESS_ACCURACY_LINE,
    ]
)


def _run(text: str, **context: str):
    """평면 키 context (전환기 폴백 경로)."""
    payload = AgentInput(
        session_id="s1",
        user_message=text,
        context={"will_type": "recording", **context},
    )
    return decedent_estate.run(payload)


def _run_namespaced(text: str, **context: str):
    """네임스페이스 규약 context — 같은 값을 context["decedent_estate"] 로 넣는다."""
    payload = AgentInput(
        session_id="s1",
        user_message=text,
        context={"decedent_estate": {"will_type": "recording", **context}},
    )
    return decedent_estate.run(payload)


def test_complete_transcript_all_green_and_handoff() -> None:
    output = _run(
        _COMPLETE_TRANSCRIPT,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    assert output.data["will_type"] == "recording"
    reqs = output.data["requirements"]
    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
        "rec_witness_present",
        "rec_witness_eligible",
    ):
        assert reqs[rid]["grade"] == "GREEN", rid

    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
    assert output.data["handoff_reason"] == "가정법원 검인 절차 안내 필요"
    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply
    assert "녹음 유언의 7가지 요건" in output.reply
    # 대본 입력 안내가 항상 맨 앞에 붙는다.
    assert output.reply.startswith("📼 녹음하신 내용을 그대로 적어주세요")


def test_date_missing_is_red_with_precedent_citation() -> None:
    text = "\n".join(
        [
            _TESTATOR_LINE,
            _CONTENT_LINE,
            "2026년 5월",
            _WITNESS_NAME_LINE,
            _WITNESS_ACCURACY_LINE,
        ]
    )
    output = _run(
        text,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    assert output.data["requirements"]["rec_date"]["grade"] == "RED"
    assert output.data["requirements"]["rec_date"]["red_label"] == "구술 연월일"
    assert "❌ 연월일: 구술 연월일이 확인되지 않습니다" in output.reply
    assert "(대법원 2009다9768)" in output.reply
    assert "확인되지 않는 요건이 있습니다" in output.reply


def test_witness_name_missing_is_red_with_statute_citation() -> None:
    text = "\n".join(
        [_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_ACCURACY_LINE]
    )
    output = _run(
        text,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    witness_name = output.data["requirements"]["rec_witness_name"]
    assert witness_name["grade"] == "RED"
    assert witness_name["red_label"] == "증인 성명 구술"
    assert witness_name["precedent_ids"] == ["recording_requirements"]
    # statute 타입 인용은 "(민법 제OOOO조)" 형식으로 붙는다.
    assert "(민법 제1067조)" in output.reply


def test_witness_disqualified_is_red_with_reference_note() -> None:
    output = _run(
        _COMPLETE_TRANSCRIPT,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="disqualified",
    )

    eligible = output.data["requirements"]["rec_witness_eligible"]
    assert eligible["grade"] == "RED"
    assert eligible["red_label"] == "증인 결격 사유"
    assert eligible["precedent_ids"] == [
        "witness_disqualification",
        "executor_not_disqualified",
    ]

    assert "❌ 증인 결격 여부: 증인 결격 사유가 확인되지 않습니다" in output.reply
    assert (
        "재산을 받는 사람이나 그 배우자·직계혈족은 증인이 될 수 없습니다 (민법 제1072조 제1항)"
        in output.reply
    )
    # executor_not_disqualified는 카드가 아니라 들여쓴 참고 문구여야 한다.
    assert "   ℹ️ 참고: 유언집행자라는 사정만으로는 증인 결격이 아닙니다" in output.reply
    assert (
        "대법원 1999" not in output.reply
    )  # 카드 인용(사건번호)으로는 노출되지 않는다


def test_pending_case_lists_both_confirm_questions_with_options() -> None:
    output = _run(_COMPLETE_TRANSCRIPT)  # 증인 참여/결격 둘 다 미답변

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert (
        output.reply.count("2가지만 직접 확인해주세요") == 1
        or "2가지만 직접 확인해주세요" in output.reply
    )

    fields = {q["field"] for q in output.data["pending_questions"]}
    assert fields == {"rec_witness_present_answer", "rec_witness_eligible_answer"}

    present_question = next(
        q
        for q in output.data["pending_questions"]
        if q["field"] == "rec_witness_present_answer"
    )
    assert present_question["options"] == [
        {"label": "네, 증인이 참여했습니다", "value": "yes"},
        {"label": "아니오, 증인이 없었습니다", "value": "no"},
    ]

    eligible_question = next(
        q
        for q in output.data["pending_questions"]
        if q["field"] == "rec_witness_eligible_answer"
    )
    assert eligible_question["options"] == [
        {"label": "해당하지 않습니다", "value": "not_disqualified"},
        {"label": "해당합니다", "value": "disqualified"},
    ]


def test_invalid_recording_confirm_answer_produces_warning_but_stays_pending() -> None:
    output = _run(
        _COMPLETE_TRANSCRIPT, rec_witness_present_answer="not_disqualified"
    )  # 잘못된 필드에 넣음

    assert output.data["warnings"] == [
        {
            "field": "rec_witness_present_answer",
            "invalid_value": "not_disqualified",
            "allowed": ["yes", "no"],
        }
    ]
    assert output.data["requirements"]["rec_witness_present"]["grade"] == "PENDING"


def test_colloquial_transcript_all_five_green_via_llm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """구어체 대본 — 정규식으로는 취지/유언자 성명/증인 성명을 못 잡고, LLM 폴백
    (mock)으로 5개 요건 전부 GREEN이 되는지 agent.run() 레벨에서 확인한다."""

    def _fake_extract(masked_text: str):
        return {
            "testator_name": "홍길동",
            "witness_name": "김철수",
            "date_text": "2026년 5월 3일",
            "has_disposition_intent": True,
            "has_witness_accuracy": True,
        }

    monkeypatch.setattr(recording_checker, "extract_recording_fields", _fake_extract)

    text = (
        "저는 홍길동입니다. 제 모든 재산을 장남에게 물려주고자 합니다.\n"
        "오늘은 2026년 5월 3일입니다.\n"
        "증인 김철수입니다. 위 유언이 정확함을 확인합니다."
    )
    output = _run(
        text,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    reqs = output.data["requirements"]
    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
        "rec_witness_present",
        "rec_witness_eligible",
    ):
        assert reqs[rid]["grade"] == "GREEN", rid

    assert reqs["rec_testator_name"]["extracted"]["extraction_method"] == "llm"
    assert reqs["rec_witness_name"]["extracted"]["extraction_method"] == "llm"
    assert reqs["rec_content"]["extracted"]["extraction_method"] == "llm"
    # 이 대본에서는 날짜·증인 정확함 확인은 정규식으로 이미 잡힌다.
    assert reqs["rec_date"]["extracted"]["extraction_method"] == "regex"
    assert reqs["rec_witness_accuracy"]["extracted"]["extraction_method"] == "regex"

    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply


def test_fully_regex_catchable_transcript_never_calls_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5개 요건이 정규식으로 전부 잡히는 대본이면 agent.run() 레벨에서도 LLM이
    호출되지 않아야 한다."""

    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 다 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(recording_checker, "extract_recording_fields", _fail_if_called)

    output = _run(
        _COMPLETE_TRANSCRIPT,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    reqs = output.data["requirements"]
    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
    ):
        assert reqs[rid]["extracted"]["extraction_method"] == "regex", rid


def test_namespaced_context_produces_same_result_as_flat() -> None:
    """네임스페이스 규약으로 보낸 context도 평면 키와 동일하게 동작해야 한다."""
    answers = {
        "rec_witness_present_answer": "yes",
        "rec_witness_eligible_answer": "not_disqualified",
    }

    flat = _run(_COMPLETE_TRANSCRIPT, **answers)
    namespaced = _run_namespaced(_COMPLETE_TRANSCRIPT, **answers)

    assert flat.reply == namespaced.reply
    assert flat.next_action == namespaced.next_action
    assert flat.data["decedent_estate"] == namespaced.data["decedent_estate"]


def test_namespaced_context_reads_witness_answers() -> None:
    output = _run_namespaced(
        _COMPLETE_TRANSCRIPT,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="disqualified",
    )

    assert output.data["requirements"]["rec_witness_eligible"]["grade"] == "RED"

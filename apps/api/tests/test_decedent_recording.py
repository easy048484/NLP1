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
    _looks_like_recording_transcript,
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


# ---------------------------------------------------------------------------
# transcript intake gate (2026-09-05)
#
# 실측 재현: will_type=recording이 확정된 직후 "녹음·영상"(UI 방식 선택
# 문구)이 user_message로 그대로 들어와도 check_recording_requirements가
# 실행돼, 아직 대본을 입력하지 않았는데 "2가지만 직접 확인해주세요...
# (5/7 확인됨)"과 증인 참여/결격 질문부터 노출됐다. 실제 대본이 들어오기
# 전에는 checker를 아예 돌리지 않아야 한다.
# ---------------------------------------------------------------------------


def test_voice_memo_first_turn_goes_straight_to_transcript_intake() -> None:
    """정확한 production 재현 3턴 중 1턴 — will_type=recording 자연어 자동
    확정 + transcript intake gate가 함께 작동해야 한다(테스트 A)."""
    output = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=(
                "어머니가 돌아가신 뒤 휴대폰을 정리하다가 재산 얘기를 남긴 음성메모를 "
                "발견했어요. 이런 것도 유언으로 효력이 있는지 확인할 수 있나요?"
            ),
        )
    )

    assert output.agent.value == "decedent_estate"
    assert output.data["decedent_estate"]["will_type"] == "recording"
    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.reply == (
        "📼 녹음하신 내용을 그대로 적어주세요. 아직 녹음 전이라면, 예정된 대본으로 "
        "미리 점검할 수도 있습니다."
    )
    assert "requirements" not in output.data
    assert output.data["decedent_estate"]["requirements"] == {}
    assert output.data["decedent_estate"]["pending_questions"] == []
    assert "5/7" not in output.reply
    assert "증인" not in output.reply


def test_ui_will_type_selection_phrase_is_not_treated_as_transcript() -> None:
    """테스트 B — 기존 UI 방식 선택 경로. 모호한 첫 턴 → 방식 선택 질문 →
    "녹음·영상" 버튼 선택. 실제 버튼 클릭은 라벨 텍스트(user_message)와 함께
    구조화 필드(context.will_type)도 명시적으로 보낸다 — 그 선택 문구 자체가
    user_message로 들어와도 대본으로 오인해 checker를 돌리면 안 된다."""
    ambiguous = decedent_estate.run(
        AgentInput(session_id="s1", user_message="유언장이 있는데 효력이 있나요?")
    )
    assert "어떤 형태의 유언인가요?" in ambiguous.reply

    selected = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="녹음·영상",
            context={
                "will_type": "recording",
                "decedent_estate": ambiguous.data["decedent_estate"],
            },
        )
    )

    assert selected.data["decedent_estate"]["will_type"] == "recording"
    assert selected.reply == (
        "📼 녹음하신 내용을 그대로 적어주세요. 아직 녹음 전이라면, 예정된 대본으로 "
        "미리 점검할 수도 있습니다."
    )
    assert "requirements" not in selected.data
    assert "5/7" not in selected.reply
    assert "증인" not in selected.reply


def test_recording_description_sentence_does_not_trigger_checker() -> None:
    """ "녹음 유언이에요" 같은 방식 설명 문장도 대본이 아니다."""
    output = _run("녹음 유언이에요")

    assert "requirements" not in output.data
    assert output.reply.startswith("📼 녹음하신 내용을 그대로 적어주세요")


def test_actual_transcript_after_intake_runs_checker_normally() -> None:
    """intake 턴 다음에 실제 대본이 오면 그때 처음 checker가 돌아야 한다
    (테스트 C 앞부분 — 나머지 5/7·증인 질문 구조는 기존
    test_pending_case_lists_both_confirm_questions_with_options로 이미
    확인됨)."""
    intake = _run("녹음·영상")
    assert "requirements" not in intake.data

    reviewed = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_COMPLETE_TRANSCRIPT,
            context={"decedent_estate": intake.data["decedent_estate"]},
        )
    )

    reqs = reviewed.data["requirements"]
    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
    ):
        assert reqs[rid]["grade"] in ("GREEN", "RED", "YELLOW"), rid  # PENDING 아님
    assert reqs["rec_witness_present"]["grade"] == "PENDING"
    assert reqs["rec_witness_eligible"]["grade"] == "PENDING"
    assert reviewed.data["progress"] == {"checked": 5, "total": 7}


def test_witness_answer_turn_does_not_reset_transcript_derived_grades() -> None:
    """테스트 D — continuation. 대본을 한 번 입력해 5개 text-derived 요건이
    판정된 뒤, 증인 참여/결격만 답하는 짧은 후속 턴이 와도(대본을 다시 보내지
    않음) 그 5개 판정이 absent/RED로 되돌아가면 안 된다 — intake gate로도
    돌아가면 안 된다(2026-09-05, _preserve_established_requirements를
    recording의 5개 text-derived 요건에도 적용)."""
    transcript_turn = _run(_COMPLETE_TRANSCRIPT)
    before = transcript_turn.data["requirements"]

    witness_turn = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="네, 실제로 참여했고 결격 사유는 없습니다",
            context={"decedent_estate": transcript_turn.data["decedent_estate"]},
        )
    )

    # 두 번째 턴은 답변만 담겨 있고 대본을 다시 보내지 않았지만, intake gate로
    # 돌아가지 않고(대본 재요청 없음) review가 계속된다.
    assert witness_turn.reply != (
        "📼 녹음하신 내용을 그대로 적어주세요. 아직 녹음 전이라면, 예정된 대본으로 "
        "미리 점검할 수도 있습니다."
    )
    after = witness_turn.data["requirements"]
    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
    ):
        assert after[rid]["grade"] == before[rid]["grade"], rid


def test_witness_structured_answers_after_transcript_yield_final_seven() -> None:
    """구조화 답변(버튼 클릭 방식, context 필드)으로 증인 참여/결격을 확정하면
    최종 7개 요건이 모두 판정된다."""
    payload = AgentInput(
        session_id="s1",
        user_message="",
        context={
            "decedent_estate": {
                "will_type": "recording",
                "requirements": {
                    rid: {
                        "id": rid,
                        "name": rid,
                        "grade": "GREEN",
                        "condition_id": "present",
                    }
                    for rid in (
                        "rec_content",
                        "rec_testator_name",
                        "rec_date",
                        "rec_witness_accuracy",
                        "rec_witness_name",
                    )
                },
                "rec_witness_present_answer": "yes",
                "rec_witness_eligible_answer": "not_disqualified",
            }
        },
    )
    output = decedent_estate.run(payload)

    reqs = output.data["requirements"]
    assert reqs["rec_witness_present"]["grade"] == "GREEN"
    assert reqs["rec_witness_eligible"]["grade"] == "GREEN"
    for rid in (
        "rec_content",
        "rec_testator_name",
        "rec_date",
        "rec_witness_accuracy",
        "rec_witness_name",
    ):
        assert reqs[rid]["grade"] == "GREEN", rid


# ---------------------------------------------------------------------------
# _looks_like_recording_transcript 단위 테스트
# ---------------------------------------------------------------------------

_NOT_TRANSCRIPT_MESSAGES = [
    "녹음·영상",
    "녹음 유언이에요",
    "음성메모예요",
    "녹음으로 유언 남기고 싶어요",
    "",
    "   ",
]

_TRANSCRIPT_MESSAGES = [
    _COMPLETE_TRANSCRIPT,
    "저의 전 재산을 배우자에게 상속한다.",  # 처분 의사 구술
    "2026년 5월 3일",  # 날짜 구술
    "증인: 김철수",  # 증인 성명 구술
    "증인은 위 유언이 정확함을 확인합니다.",  # 증인 정확함 구술
]


@pytest.mark.parametrize("message", _NOT_TRANSCRIPT_MESSAGES)
def test_message_without_transcript_signal_is_not_treated_as_transcript(
    message: str,
) -> None:
    assert _looks_like_recording_transcript(message) is False


@pytest.mark.parametrize("message", _TRANSCRIPT_MESSAGES)
def test_message_with_transcript_signal_is_treated_as_transcript(
    message: str,
) -> None:
    assert _looks_like_recording_transcript(message) is True


def test_complete_transcript_all_green_does_not_auto_handoff() -> None:
    """모든 요건이 GREEN으로 종결돼도 더 이상 자동으로 heir_navigator에
    handoff하지 않는다(2026-09-05, handwritten과 동일 원칙) — 점검 완료
    직후의 결과 후속 질문이 heir_navigator에 가로채이지 않도록 한다."""
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

    assert output.next_action is None
    assert "handoff_reason" not in output.data
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
    assert (
        "   ℹ️ 참고: 조문상 유언집행자는 증인 결격사유로 열거되어 있지 않습니다"
        in output.reply
    )
    # 판례가 아니라 조문 근거이므로 "판례가 있습니다" 식으로 표현되면 안 된다.
    assert "유언집행자" in output.reply
    assert (
        "유언집행자라는 사정만으로는 증인 결격이 아니라고 본 판례" not in output.reply
    )


def test_pending_case_lists_both_confirm_questions_with_options() -> None:
    output = _run(_COMPLETE_TRANSCRIPT)  # 증인 참여/결격 둘 다 미답변

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert (
        output.reply.count("2가지만 직접 확인해주세요") == 1
        or "2가지만 직접 확인해주세요" in output.reply
    )
    # 진행률(#42의 data.progress와 같은 분모)이 reply 텍스트에도 노출된다 —
    # 녹음은 7요건이라 나머지 5개는 이미 확인된 상태.
    assert "(5/7 확인됨)" in output.reply
    assert output.data["progress"] == {"checked": 5, "total": 7}

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

    assert output.next_action is None  # 종결돼도 더 이상 자동 handoff 없음(2026-09-05)
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


def test_progress_pending_witness_answers_counted_as_unchecked() -> None:
    """증인 참여/결격 확인 답변이 없으면 7개 중 5개(대본에서 바로 판정되는
    항목)만 확인된 상태다."""
    output = _run(_COMPLETE_TRANSCRIPT)  # witness_present/eligible 답변 없음

    assert output.data["requirements"]["rec_witness_present"]["grade"] == "PENDING"
    assert output.data["requirements"]["rec_witness_eligible"]["grade"] == "PENDING"
    assert output.data["progress"] == {"checked": 5, "total": 7}


def test_progress_all_checked_when_witness_answers_given() -> None:
    output = _run(
        _COMPLETE_TRANSCRIPT,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    assert output.data["progress"] == {"checked": 7, "total": 7}


def test_requirement_body_and_precedents_for_recording() -> None:
    """A안: 녹음 파이프라인도 handwritten과 동일하게 요건별로 body/precedents를
    채운다 — 예외 3건 중 executor_not_disqualified는 참고 문구로만 남고
    precedents 배열에는 없어야 한다."""
    output = _run(
        _COMPLETE_TRANSCRIPT,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="disqualified",  # RED — witness_disqualification +
        # executor_not_disqualified(참고 문구 예외) 둘 다 precedent_ids 에 포함됨
    )

    eligible = output.data["decedent_estate"]["requirements"]["rec_witness_eligible"]
    assert isinstance(eligible["body"], str) and eligible["body"]
    assert (
        "조문상 유언집행자는 증인 결격사유로 열거되어 있지 않습니다" in eligible["body"]
    )
    assert "(민법 제1072조 제1항)" not in eligible["body"]

    case_nos = {p["case_no"] for p in eligible["precedents"]}
    assert "executor_not_disqualified" not in case_nos  # 예외 3건 중 하나 — 카드 아님

"""
recording_checker.py 단위/통합 테스트 (녹음 유언, 민법 §1067).

test_decedent_requirement_checker.py 와 같은 스타일로, 대본(전사) 텍스트에서
5개 요건(유언 취지/유언자 성명/연월일/증인의 정확함/증인 성명)이 규칙 기반으로
잘 추출되는지, 사용자 확인 2개(증인 참여/증인 결격)가 PENDING↔GREEN/RED로 잘
넘어가는지 확인한다.
"""

from agents.decedent_estate.recording_checker import (
    check_recording_requirements,
    extract_content,
    extract_witness_accuracy,
    extract_witness_name,
    validate_recording_confirm_answers,
)

_TESTATOR_LINE = "유언자: 홍길동"
_CONTENT_LINE = "저의 전 재산을 배우자에게 상속한다."
_DATE_LINE = "2026년 5월 3일"
_WITNESS_NAME_LINE = "증인: 김철수"
_WITNESS_ACCURACY_LINE = "증인은 위 유언이 정확함을 확인합니다."


def _transcript(*lines: str) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 추출 함수 단위 테스트
# ---------------------------------------------------------------------------


def test_extract_content_present() -> None:
    assert extract_content(_CONTENT_LINE).case == "present"


def test_extract_content_absent() -> None:
    assert extract_content("오늘 날씨가 좋습니다.").case == "absent"


def test_extract_witness_accuracy_present() -> None:
    assert extract_witness_accuracy(_WITNESS_ACCURACY_LINE).case == "present"


def test_extract_witness_accuracy_absent() -> None:
    assert extract_witness_accuracy("증인이 옆에 있었습니다.").case == "absent"


def test_extract_witness_name_with_colon() -> None:
    result = extract_witness_name(_WITNESS_NAME_LINE)
    assert result.case == "present"
    assert result.raw_text == "김철수"


def test_extract_witness_name_absent() -> None:
    assert extract_witness_name("증인이 참여했습니다.").case == "absent"


# ---------------------------------------------------------------------------
# check_recording_requirements 통합 테스트
# ---------------------------------------------------------------------------


def test_complete_transcript_all_text_derivable_requirements_green() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text)

    assert results["rec_content"].grade == "GREEN"
    assert results["rec_testator_name"].grade == "GREEN"
    assert results["rec_testator_name"].extracted["raw_text"] == "홍길동"
    assert results["rec_date"].grade == "GREEN"
    assert results["rec_witness_accuracy"].grade == "GREEN"
    assert results["rec_witness_name"].grade == "GREEN"
    assert results["rec_witness_name"].extracted["raw_text"] == "김철수"


def test_date_day_missing_is_red_like_handwritten() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, "2026년 5월", _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text)

    assert results["rec_date"].condition_id == "day_missing"
    assert results["rec_date"].grade == "RED"
    assert results["rec_date"].precedent_ids == ["date_missing_day_invalid"]


def test_witness_name_missing_is_red() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text)

    assert results["rec_witness_name"].condition_id == "absent"
    assert results["rec_witness_name"].grade == "RED"
    assert results["rec_witness_name"].precedent_ids == ["recording_requirements"]


def test_witness_present_and_eligible_default_to_pending() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text)

    assert results["rec_witness_present"].condition_id is None
    assert results["rec_witness_present"].grade == "PENDING"
    assert results["rec_witness_present"].followup_question == "녹음에 증인이 실제로 참여했나요?"

    assert results["rec_witness_eligible"].condition_id is None
    assert results["rec_witness_eligible"].grade == "PENDING"


def test_witness_present_yes_is_green() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text, rec_witness_present_answer="yes")

    assert results["rec_witness_present"].condition_id == "yes"
    assert results["rec_witness_present"].grade == "GREEN"


def test_witness_present_no_is_red() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text, rec_witness_present_answer="no")

    assert results["rec_witness_present"].condition_id == "no"
    assert results["rec_witness_present"].grade == "RED"
    assert results["rec_witness_present"].precedent_ids == ["recording_requirements"]


def test_witness_disqualified_is_red_with_both_precedents() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text, rec_witness_eligible_answer="disqualified")

    assert results["rec_witness_eligible"].condition_id == "disqualified"
    assert results["rec_witness_eligible"].grade == "RED"
    assert results["rec_witness_eligible"].precedent_ids == [
        "witness_disqualification",
        "executor_not_disqualified",
    ]


def test_witness_not_disqualified_is_green() -> None:
    text = _transcript(_TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE)

    results = check_recording_requirements(text, rec_witness_eligible_answer="not_disqualified")

    assert results["rec_witness_eligible"].condition_id == "not_disqualified"
    assert results["rec_witness_eligible"].grade == "GREEN"


# ---------------------------------------------------------------------------
# validate_recording_confirm_answers
# ---------------------------------------------------------------------------


def test_validate_recording_confirm_answers_flags_wrong_field_value() -> None:
    warnings = validate_recording_confirm_answers(rec_witness_present_answer="not_disqualified")

    assert warnings == [
        {
            "field": "rec_witness_present_answer",
            "invalid_value": "not_disqualified",
            "allowed": ["yes", "no"],
        }
    ]


def test_validate_recording_confirm_answers_no_warnings_when_valid_or_missing() -> None:
    warnings = validate_recording_confirm_answers(
        rec_witness_present_answer="yes", rec_witness_eligible_answer=None
    )

    assert warnings == []

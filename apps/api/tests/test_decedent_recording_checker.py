"""
recording_checker.py 단위/통합 테스트 (녹음 유언, 민법 §1067).

test_decedent_requirement_checker.py 와 같은 스타일로, 대본(전사) 텍스트에서
5개 요건(유언 취지/유언자 성명/연월일/증인의 정확함/증인 성명)이 규칙 기반으로
잘 추출되는지, 사용자 확인 2개(증인 참여/증인 결격)가 PENDING↔GREEN/RED로 잘
넘어가는지 확인한다.
"""

import pytest

from agents.decedent_estate import recording_checker
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


# ---------------------------------------------------------------------------
# LLM 폴백 — 실제 네트워크 호출 없이 recording_checker.extract_recording_fields
# 를 몽키패치해서 확인한다.
# ---------------------------------------------------------------------------

_COLLOQUIAL_TRANSCRIPT = (
    "저는 홍길동입니다. 제 모든 재산을 장남에게 물려주고자 합니다.\n"
    "오늘은 2026년 5월 3일입니다.\n"
    "증인 김철수입니다. 위 유언이 정확함을 확인합니다."
)


def test_regex_success_on_all_five_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """5개 요건이 정규식으로 전부 잡히면 LLM은 아예 호출되지 않아야 한다."""

    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 다 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(recording_checker, "extract_recording_fields", _fail_if_called)

    text = _transcript(
        _TESTATOR_LINE, _CONTENT_LINE, _DATE_LINE, _WITNESS_NAME_LINE, _WITNESS_ACCURACY_LINE
    )
    results = check_recording_requirements(text)

    assert results["rec_content"].extracted["extraction_method"] == "regex"
    assert results["rec_testator_name"].extracted["extraction_method"] == "regex"
    assert results["rec_date"].extracted["extraction_method"] == "regex"
    assert results["rec_witness_accuracy"].extracted["extraction_method"] == "regex"
    assert results["rec_witness_name"].extracted["extraction_method"] == "regex"


def test_llm_fallback_resolves_colloquial_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    """구어체 대본에서 정규식이 못 잡는 항목(취지/유언자 성명/증인 성명)이 LLM
    한 번의 호출로 함께 해결되는지 확인한다. 날짜·증인 정확함 확인은 이 대본에서
    이미 정규식으로 잡히므로 LLM 값이 있어도 무시돼야 한다."""
    calls: list[str] = []

    def _fake_extract(masked_text: str):
        calls.append(masked_text)
        return {
            "testator_name": "홍길동",
            "witness_name": "김철수",
            "date_text": "2099년 1월 1일",  # 정규식이 이미 찾았으니 무시돼야 함
            "has_disposition_intent": True,
            "has_witness_accuracy": False,  # 정규식이 이미 찾았으니 무시돼야 함
        }

    monkeypatch.setattr(recording_checker, "extract_recording_fields", _fake_extract)

    results = check_recording_requirements(_COLLOQUIAL_TRANSCRIPT)

    assert len(calls) == 1  # 항목별로 나눠 부르지 않고 한 번만 호출

    assert results["rec_content"].grade == "GREEN"
    assert results["rec_content"].extracted["extraction_method"] == "llm"

    assert results["rec_testator_name"].grade == "GREEN"
    assert results["rec_testator_name"].extracted["raw_text"] == "홍길동"
    assert results["rec_testator_name"].extracted["extraction_method"] == "llm"

    assert results["rec_witness_name"].grade == "GREEN"
    assert results["rec_witness_name"].extracted["raw_text"] == "김철수"
    assert results["rec_witness_name"].extracted["extraction_method"] == "llm"

    # 이 대본에서는 날짜와 증인 정확함 확인이 정규식으로 이미 잡히므로 LLM 값 무시.
    assert results["rec_date"].extracted["extraction_method"] == "regex"
    assert results["rec_date"].grade == "GREEN"
    assert results["rec_witness_accuracy"].extracted["extraction_method"] == "regex"
    assert results["rec_witness_accuracy"].grade == "GREEN"


def test_llm_receives_masked_text_not_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[str] = []

    def _capture(masked_text: str):
        received.append(masked_text)
        return None

    monkeypatch.setattr(recording_checker, "extract_recording_fields", _capture)

    text = "저는 홍길동입니다. 주민등록번호 901231-1234567. 재산을 장남에게 물려주고자 합니다."
    check_recording_requirements(text)

    assert len(received) == 1
    assert "901231-1234567" not in received[0]
    assert "[주민등록번호]" in received[0]


def test_llm_date_text_still_goes_through_date_parser_for_day_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 돌려준 date_text도 date_parser를 그대로 거쳐 일(日) 누락 판정이 유지된다."""

    def _fake_extract(masked_text: str):
        return {
            "testator_name": "홍길동",
            "witness_name": "김철수",
            "date_text": "2026년 5월",  # 일(日) 누락
            "has_disposition_intent": True,
            "has_witness_accuracy": True,
        }

    monkeypatch.setattr(recording_checker, "extract_recording_fields", _fake_extract)

    text = "저는 홍길동입니다. 재산을 장남에게 물려주고자 합니다. 증인 김철수입니다."
    results = check_recording_requirements(text)

    assert results["rec_date"].condition_id == "day_missing"
    assert results["rec_date"].grade == "RED"
    assert results["rec_date"].extracted["extraction_method"] == "llm"


def test_llm_failure_falls_back_to_absent_without_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recording_checker, "extract_recording_fields", lambda masked_text: None)

    results = check_recording_requirements(_COLLOQUIAL_TRANSCRIPT)

    assert results["rec_content"].condition_id == "absent"
    assert results["rec_content"].extracted["extraction_method"] == "none"
    assert results["rec_testator_name"].condition_id == "absent"
    assert results["rec_testator_name"].extracted["extraction_method"] == "none"

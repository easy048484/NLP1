"""
판정 결과(API 응답)에 개인정보 조각이 남지 않는지 확인하는 회귀 테스트.

`test_decedent_state.py::test_*_excludes_will_text` 계열과 같은 성격의
"경계 방어" 테스트다 — 개별 함수의 동작이 아니라, **최종적으로 밖으로 나가는
값 전체**를 문자열로 훑어 민감정보가 섞이지 않았는지 본다.

배경: date_parser 의 `(\\d{4})-(\\d{1,2})` 패턴이 주민등록번호
"901231-1234567" 의 중간 조각 "1231-12" 를 연월 표기로 오탐했다. 그 조각은
생년월일(12월 31일)과 성별 식별 숫자를 담고 있는데, 판정 결과(extracted)에
실려 API 응답·세션 저장까지 흘러가 마스킹을 우회했다 — masking.mask_text 는
LLM 호출 직전에만 돌기 때문에 이 경로를 막지 못한다 (CLAUDE.md 절대 원칙 4 위반).

두 겹으로 막았고 이 파일이 둘 다 검증한다:
1. 근본 원인 — date_parser 의 숫자 가드로 애초에 매칭되지 않게 함
2. 2차 방어 — 날짜 entries 페이로드에서 raw_text(원문 조각)를 아예 제외
"""

import json

import pytest

from agents import decedent_estate
from agents.decedent_estate.recording_checker import check_recording_requirements
from agents.decedent_estate.requirement_checker import check_requirements
from schemas import AgentInput

_RRN = "901231-1234567"
_PHONE = "010-1234-5678"

#: 원문 전체뿐 아니라 "오탐으로 잘려 나오던 조각"까지 함께 확인한다 —
#: 전체 문자열만 검사하면 부분 노출을 놓친다(실제로 이 버그가 그랬다).
_FORBIDDEN_FRAGMENTS = (
    _RRN,
    "1231-12",  # 주민번호가 연월로 오탐될 때 잘려 나오던 조각
    _PHONE,
    "1234-56",  # 전화번호가 연월로 오탐될 때 잘려 나오던 조각
)

_WILL_WITH_PII = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    f"주민등록번호 {_RRN}\n"
    f"연락처 {_PHONE}\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 전 재산을 배우자에게 상속한다."
)

_TRANSCRIPT_WITH_PII = "\n".join(
    [
        "유언자: 홍길동",
        f"주민등록번호 {_RRN} 입니다.",
        f"연락처는 {_PHONE} 입니다.",
        "저의 전 재산을 배우자에게 상속한다.",
        "2026년 5월 3일",
        "증인: 김철수",
        "증인은 위 유언이 정확함을 확인합니다.",
    ]
)


def _assert_no_pii(blob: str, label: str) -> None:
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert fragment not in blob, f"{label} 에 개인정보 조각이 노출됐다: {fragment}"


def test_check_requirements_result_has_no_pii_fragments() -> None:
    results = check_requirements(
        _WILL_WITH_PII,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    blob = json.dumps(
        {rid: r.extracted for rid, r in results.items()}, ensure_ascii=False
    )
    _assert_no_pii(blob, "check_requirements().extracted")


def test_recording_result_has_no_pii_fragments() -> None:
    results = check_recording_requirements(
        _TRANSCRIPT_WITH_PII,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    blob = json.dumps(
        {rid: r.extracted for rid, r in results.items()}, ensure_ascii=False
    )
    _assert_no_pii(blob, "check_recording_requirements().extracted")


@pytest.mark.parametrize("will_type", ["handwritten", "recording"])
def test_agent_output_data_has_no_pii_fragments(will_type: str) -> None:
    """오케스트레이터·프론트로 실제로 나가는 data 전체를 훑어 확인한다."""
    text = _WILL_WITH_PII if will_type == "handwritten" else _TRANSCRIPT_WITH_PII
    output = decedent_estate.run(
        AgentInput(session_id="s1", user_message=text, context={"will_type": will_type})
    )

    _assert_no_pii(json.dumps(output.data, ensure_ascii=False), "AgentOutput.data")
    _assert_no_pii(output.reply, "AgentOutput.reply")


def test_pii_does_not_produce_a_false_date_judgment() -> None:
    """주민번호·전화번호만 있고 진짜 날짜가 없으면 연월일은 absent(RED)여야 한다.

    오탐 시절에는 주민번호가 day_missing 으로 잡혀 "날짜를 찾았다"는 잘못된
    판정이 나왔다 — 개인정보 노출과 별개로 판정 정확도 문제이기도 했다.
    """
    text = (
        "유언장\n"
        "유언자: 홍길동\n"
        f"주민등록번호 {_RRN}\n"
        f"연락처 {_PHONE}\n"
        "나의 전 재산을 배우자에게 상속한다."
    )
    results = check_requirements(text)

    assert results["date"].condition_id == "absent"
    assert results["date"].extracted["entries"] == []


def test_real_date_still_judged_when_pii_present() -> None:
    """PII 가드가 같은 문서 안의 진짜 날짜까지 막아버리면 안 된다 (회귀 방지)."""
    results = check_requirements(_WILL_WITH_PII)

    assert results["date"].condition_id == "all_present"
    entries = results["date"].extracted["entries"]
    assert len(entries) == 1
    assert (entries[0]["year"], entries[0]["month"], entries[0]["day"]) == (2026, 5, 3)


def test_date_entries_payload_omits_raw_text() -> None:
    """2차 방어: 날짜 entries 에는 매칭된 원문 조각(raw_text)을 담지 않는다.

    화면 표시(result_formatter)는 year/month/day 만 쓰므로 손실이 없다.
    """
    results = check_requirements("2026년 5월 3일에 작성함")

    entries = results["date"].extracted["entries"]
    assert entries and "raw_text" not in entries[0]
    assert set(entries[0]) == {"year", "month", "day", "case"}

"""
연월일·주소 요건의 "정규식 우선 → 못 찾으면(absent) LLM 폴백" 오케스트레이션 테스트.

test_decedent_name_llm_fallback.py 와 동일한 구조를 그대로 복제한다:
requirement_checker.extract_will_date/extract_will_address 를 가짜로 바꿔치기해서
실제 네트워크 호출 없이 (1) 정규식이 성공하면(absent 가 아니면, 등급이 낮아도)
LLM을 아예 부르지 않는지, (2) absent 인 케이스가 LLM으로 해결되는지, (3) LLM도
실패하면 정직하게 absent 로 남는지, (4) LLM에는 마스킹된 텍스트가 전달되는지,
(5) LLM이 돌려준 문자열이 등급까지 직접 정하지 않고 규칙 기반 재파싱을 거치는지를
확인한다.

날짜의 multiple_dates_mixed(정규식이 이미 뭔가 찾은 상태)는 LLM 폴백 대상이
아니다 — 팀 결정(2026-08-21, docs/known_limitations.md 3-4)으로 이번 범위에서
제외됐다. 이 파일에서도 그 배제를 명시적으로 검증한다.
"""

import pytest

from agents.decedent_estate import requirement_checker
from agents.decedent_estate.requirement_checker import (
    check_requirements,
    extract_address_with_fallback,
    extract_date_with_fallback,
)

_NAME_LINE = "유언자: 홍길동"
_ADDRESS_LINE = "주소: 서울특별시 강남구 테헤란로 123, 45동 678호"
_DATE_LINE = "2026년 5월 3일"
_BODY = "나의 전 재산을 배우자에게 상속한다."


def _will_text(*lines: str) -> str:
    return "\n".join([*lines, "", _BODY])


# ---------------------------------------------------------------------------
# 날짜
# ---------------------------------------------------------------------------


def test_date_regex_success_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(requirement_checker, "extract_will_date", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    result, method = extract_date_with_fallback(text)

    assert result.case == "all_present"
    assert method == "regex"


def test_date_multiple_dates_mixed_skips_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """여러 날짜가 섞여도(=absent 가 아님) LLM은 호출되지 않는다 — 작성일 "선별"은
    이번 폴백의 대상이 아니다(팀 결정, known_limitations.md 3-4)."""

    def _fail_if_called(masked_text: str):
        raise AssertionError(
            "multiple_dates_mixed 는 absent 가 아니므로 LLM을 호출하면 안 된다"
        )

    monkeypatch.setattr(requirement_checker, "extract_will_date", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "2020년 1월 1일", "2026년 5월 3일")
    result, method = extract_date_with_fallback(text)

    assert result.case == "multiple_dates_mixed"
    assert method == "regex"


def test_date_llm_fallback_resolves_verbal_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """다른 날짜 표기가 전혀 없어 absent 로 떨어지는 케이스가 LLM으로 해결되는지."""
    monkeypatch.setattr(
        requirement_checker, "extract_will_date", lambda masked_text: "칠순 잔치에"
    )

    # 날짜 표기가 텍스트 어디에도 없어야 정규식 단독 결과가 absent 가 된다
    # (아래에서 전제로 확인한다) — "제 칠순 잔치에..."를 본문에 그대로 넣으면
    # 정규식이 이미 잡아버려 LLM이 호출되지 않는다.
    text = _will_text(_NAME_LINE, _ADDRESS_LINE)
    assert requirement_checker.parse_dates(text).case == "absent"  # 전제 확인

    result, method = extract_date_with_fallback(text)

    assert result.case == "verbal_specified"
    assert result.entries[0].raw_text == "칠순 잔치에"
    assert method == "llm"


def test_date_llm_returns_case_it_does_not_decide_the_grade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM은 문자열만 반환하고, 등급(day_missing)은 date_parser.parse_dates 가
    다시 매긴다 — LLM이 case 를 직접 정하지 않는다는 CLAUDE.md 원칙 확인."""
    monkeypatch.setattr(
        requirement_checker, "extract_will_date", lambda masked_text: "2026년 5월"
    )

    text = _will_text(_NAME_LINE, _ADDRESS_LINE)
    assert requirement_checker.parse_dates(text).case == "absent"  # 전제 확인

    result, method = extract_date_with_fallback(text)

    assert result.case == "day_missing"  # 규칙 엔진(parse_dates)이 매긴 등급
    assert method == "llm"


def test_date_llm_fallback_failure_keeps_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requirement_checker, "extract_will_date", lambda masked_text: None
    )

    text_without_date = _will_text(_NAME_LINE, _ADDRESS_LINE)  # 날짜 언급 자체가 없음
    result, method = extract_date_with_fallback(text_without_date)

    assert result.case == "absent"
    assert method == "none"


def test_date_llm_unsupported_keyword_reparse_falls_back_to_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 뭔가 찾아 돌려줘도, date_parser 가 인식 못 하는 표현(예: "생신")이면
    재파싱 결과가 absent 이므로 그대로 폐기된다 — LLM 값을 무조건 신뢰하지 않는다."""
    monkeypatch.setattr(
        requirement_checker, "extract_will_date", lambda masked_text: "생신날"
    )

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "제 생신날에 이 글을 남깁니다.")
    result, method = extract_date_with_fallback(text)

    assert result.case == "absent"
    assert method == "none"


def test_date_llm_receives_masked_text_not_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM에는 계좌번호 등이 마스킹된 텍스트가 전달돼야 한다 (CLAUDE.md 원칙 4).

    (주민등록번호·전화번호는 "6자리-7자리"/"3~4자리-4자리" 형식이 date_parser의
    `\\d{4}-\\d{1,2}` 패턴과 우연히 겹쳐 그 자체로 day_missing 오탐을 유발한다 —
    이 테스트는 "정규식이 absent일 때만 LLM 호출"이 전제라, 그 오탐과 안 겹치는
    계좌번호로 마스킹 여부만 확인한다. 오탐 자체는 date_parser 의 기존 결함이라
    이번 작업 범위 밖이다.)
    """
    received: list[str] = []

    def _capture(masked_text: str):
        received.append(masked_text)
        return "칠순 잔치에"

    monkeypatch.setattr(requirement_checker, "extract_will_date", _capture)

    text = "유언장\n계좌번호 110123456789\n나의 전 재산을 배우자에게 상속한다."
    assert requirement_checker.parse_dates(text).case == "absent"  # 전제 확인
    extract_date_with_fallback(text)

    assert len(received) == 1
    assert "110123456789" not in received[0]
    assert "[계좌번호]" in received[0]


def test_check_requirements_end_to_end_date_llm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requirement_checker, "extract_will_date", lambda masked_text: "칠순 잔치에"
    )

    text = (
        "유언장\n주소: 서울 강남구 테헤란로 123\n유언자: 홍길동\n" "전 재산을 상속한다."
    )
    assert requirement_checker.parse_dates(text).case == "absent"  # 전제 확인
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["date"].condition_id == "verbal_specified"
    assert results["date"].grade == "YELLOW"
    assert results["date"].extracted["extraction_method"] == "llm"


def test_check_requirements_date_regex_hit_reports_regex_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(requirement_checker, "extract_will_date", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(text)

    assert results["date"].extracted["extraction_method"] == "regex"


# ---------------------------------------------------------------------------
# 주소
# ---------------------------------------------------------------------------


def test_address_regex_success_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(requirement_checker, "extract_will_address", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    result, method = extract_address_with_fallback(text)

    assert result.case == "full_address"
    assert method == "regex"


def test_address_city_district_only_skips_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2012다71688(동만 기재 무효) 판정은 이미 "찾은" 결과라 LLM이 절대 개입하지
    않는다 — 잘못된 값으로 이 판정을 덮어쓰는 일을 원천 차단한다."""

    def _fail_if_called(masked_text: str):
        raise AssertionError("city_district_only 는 absent 가 아니므로 LLM 호출 금지")

    monkeypatch.setattr(requirement_checker, "extract_will_address", _fail_if_called)

    text = _will_text(_NAME_LINE, "주소: 서울 강남구", _DATE_LINE)
    result, method = extract_address_with_fallback(text)

    assert result.case == "city_district_only"
    assert method == "regex"


def test_address_llm_fallback_resolves_full_address_excluded_by_property_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """known_limitations.md 2-1 — 유언자 주소가 재산 문맥과 같은 줄에 있어 통째로
    제외된(absent) 케이스가 LLM으로 해결되는지."""
    monkeypatch.setattr(
        requirement_checker,
        "extract_will_address",
        lambda masked_text: "서울 강남구 테헤란로 123, 45동 678호",
    )

    text = "유언장\n서울 강남구 테헤란로 123, 45동 678호에 사는 나는 내 아파트를 장남에게 상속한다."
    assert requirement_checker.extract_address(text).case == "absent"  # 전제 확인

    result, method = extract_address_with_fallback(text)

    assert result.case == "full_address"
    assert result.raw_text == "서울 강남구 테헤란로 123, 45동 678호"
    assert method == "llm"


def test_address_llm_fallback_resolves_city_district_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 구·동 수준만 찾아줘도 regex 재검증을 거쳐 city_district_only 로
    정확히 강등된다 — LLM 값을 "찾음=GREEN"으로 그냥 믿지 않는다."""
    monkeypatch.setattr(
        requirement_checker, "extract_will_address", lambda masked_text: "서울 강남구"
    )

    text = "유언장\n서울 강남구에 사는 나는 내 아파트를 장남에게 상속한다."
    assert requirement_checker.extract_address(text).case == "absent"  # 전제 확인

    result, method = extract_address_with_fallback(text)

    assert result.case == "city_district_only"
    assert result.raw_text == "서울 강남구"
    assert method == "llm"


def test_address_llm_returns_text_regex_cannot_classify_falls_back_to_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 뭔가 찾아 돌려줘도, 우리 주소 판별 정규식(번지/동호수/시·구) 어디에도
    안 걸리면 등급을 만들어내지 않고 absent 로 남긴다."""
    monkeypatch.setattr(
        requirement_checker,
        "extract_will_address",
        lambda masked_text: "저 산 너머 마을",
    )

    text = _will_text(_NAME_LINE, _DATE_LINE)
    result, method = extract_address_with_fallback(text)

    assert result.case == "absent"
    assert method == "none"


def test_address_llm_fallback_failure_keeps_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requirement_checker, "extract_will_address", lambda masked_text: None
    )

    text_without_address = _will_text(_NAME_LINE, _DATE_LINE)
    result, method = extract_address_with_fallback(text_without_address)

    assert result.case == "absent"
    assert result.raw_text is None
    assert method == "none"


def test_address_llm_receives_masked_text_not_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM에는 주민등록번호 등이 마스킹된 텍스트가 전달돼야 한다 (CLAUDE.md 원칙 4)."""
    received: list[str] = []

    def _capture(masked_text: str):
        received.append(masked_text)
        return "서울 강남구 테헤란로 123, 45동 678호"

    monkeypatch.setattr(requirement_checker, "extract_will_address", _capture)

    text = (
        "유언장\n주민등록번호 901231-1234567\n"
        "서울 강남구 테헤란로 123, 45동 678호에 사는 나는 내 아파트를 상속한다."
    )
    extract_address_with_fallback(text)

    assert len(received) == 1
    assert "901231-1234567" not in received[0]
    assert "[주민등록번호]" in received[0]


def test_check_requirements_end_to_end_address_llm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requirement_checker,
        "extract_will_address",
        lambda masked_text: "서울 강남구 테헤란로 123, 45동 678호",
    )

    text = (
        "유언장\n유언자: 홍길동\n2026년 5월 3일\n"
        "서울 강남구 테헤란로 123, 45동 678호에 사는 나는 내 아파트를 상속한다."
    )
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["address"].condition_id == "full_address"
    assert results["address"].grade == "GREEN"
    assert (
        results["address"].extracted["raw_text"]
        == "서울 강남구 테헤란로 123, 45동 678호"
    )
    assert results["address"].extracted["extraction_method"] == "llm"


def test_check_requirements_address_regex_hit_reports_regex_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(requirement_checker, "extract_will_address", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(text)

    assert results["address"].extracted["extraction_method"] == "regex"


# ---------------------------------------------------------------------------
# known_limitations.md §2-1 실측 (실제 Anthropic API 호출, --live 필요)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_known_limitations_2_1_example_still_returns_absent_on_real_api() -> None:
    """known_limitations.md §2-1 대표 예시("서울 강남구에 사는 나는 내
    아파트를 장남에게 상속한다")를 실제 API로 재측정한 결과를 고정한다.

    2026-08-25(코드펜스 수정 직후), 2026-08-28(#36 도로명주소 수정 반영 후)
    두 세션에 걸쳐 총 6회 반복 호출 전부 동일하게 `{"address_text": null}`을
    반환했다 — 유언자 본인 주소와 재산(아파트) 소재지가 한 문장에 섞여 있을 때
    모델이 확신 없이 보수적으로 null을 돌려주는 것으로 보인다. 이 테스트가
    깨진다면(=이제 주소를 추출한다면) known_limitations.md §2-1 을 "해결됨"으로
    되돌려야 한다는 신호다 — 문서와 코드가 다시 어긋나지 않도록 여기 고정해둔다.

    `pytest -q`(기본 실행)에서는 --live 가 없어 deselect되어 돌지 않는다 —
    ANTHROPIC_API_KEY 가 필요하고 실제 과금이 발생한다.
    """
    text = "서울 강남구에 사는 나는 내 아파트를 장남에게 상속한다."
    assert requirement_checker.extract_address(text).case == "absent"  # 전제 확인

    result, method = extract_address_with_fallback(text)

    assert method == "none"
    assert result.case == "absent"

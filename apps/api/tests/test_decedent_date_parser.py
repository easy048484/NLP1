"""
decedent_estate.date_parser 단위 테스트.

케이스는 rules/requirements.json 의 date.conditions[].id 와 1:1 대응한다.
"""

import pytest

from agents.decedent_estate.date_parser import parse_dates


def test_all_present() -> None:
    result = parse_dates("2026년 5월 3일 유언자 홍길동이 이 유언장을 작성한다.")

    assert result.case == "all_present"
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert (entry.year, entry.month, entry.day) == (2026, 5, 3)
    assert entry.case == "all_present"


def test_day_missing() -> None:
    result = parse_dates("2026년 5월 유언자 홍길동이 이 유언장을 작성한다.")

    assert result.case == "day_missing"
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert (entry.year, entry.month, entry.day) == (2026, 5, None)


def test_absent() -> None:
    result = parse_dates("유언자 홍길동이 이 유언장을 작성한다.")

    assert result.case == "absent"
    assert result.entries == []


def test_verbal_specified() -> None:
    result = parse_dates("아버지 칠순 기념일에 이 유언장을 남긴다.")

    assert result.case == "verbal_specified"
    assert len(result.entries) == 1
    assert result.entries[0].year is None


def test_multiple_dates_mixed() -> None:
    result = parse_dates(
        "2025년 12월 25일에 작성하였으나 2026년 1월 1일로 다시 적는다."
    )

    assert result.case == "multiple_dates_mixed"
    assert len(result.entries) == 2
    assert {(e.year, e.month, e.day) for e in result.entries} == {
        (2025, 12, 25),
        (2026, 1, 1),
    }


def test_dot_separated_full_date() -> None:
    result = parse_dates("2026. 5. 3.\n유언자 김영수 (인)")

    assert result.case == "all_present"
    assert len(result.entries) == 1
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        5,
        3,
    )


def test_dot_separated_day_missing() -> None:
    result = parse_dates("2026. 5.\n유언자 김영수 (인)")

    assert result.case == "day_missing"
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        5,
        None,
    )


def test_hyphen_separated_full_date() -> None:
    result = parse_dates("작성일: 2026-05-03")

    assert result.case == "all_present"
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        5,
        3,
    )


def test_hyphen_separated_day_missing() -> None:
    result = parse_dates("작성일: 2026-05")

    assert result.case == "day_missing"
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        5,
        None,
    )


def test_korean_numeral_full_date() -> None:
    result = parse_dates("이천이십육년 오월 삼일 작성함")

    assert result.case == "all_present"
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        5,
        3,
    )


def test_korean_numeral_day_missing() -> None:
    result = parse_dates("이천이십육년 오월 작성함")

    assert result.case == "day_missing"
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        5,
        None,
    )


def test_korean_numeral_irregular_month_names() -> None:
    result = parse_dates("이천이십육년 유월 십일")

    assert result.case == "all_present"
    assert (result.entries[0].year, result.entries[0].month, result.entries[0].day) == (
        2026,
        6,
        10,
    )


# ---------------------------------------------------------------------------
# 개인정보 오탐 방지 (CLAUDE.md 절대 원칙 4)
#
# 주민등록번호 "901231-1234567" 은 `(\d{4})-(\d{1,2})` 패턴에 중간 조각
# "1231-12" 가 걸려 day_missing 으로 오탐됐다. 그 조각은 생년월일(12월 31일)과
# 성별 식별 숫자를 담고 있는데, 판정 결과에 실려 API 응답·세션 저장까지
# 흘러가 마스킹(masking.mask_text)을 우회했다 — mask_text 는 LLM 호출 직전에만
# 돌기 때문에 이 경로를 막지 못한다.
#
# date_parser._NO_DIGIT_BEFORE/_NO_DIGIT_AFTER 가드로 "네 자리 연도가 더 긴
# 숫자열의 일부이면 날짜가 아니다"를 강제해 근본 차단했다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pii_text",
    [
        "901231-1234567",  # 주민등록번호 (원래 "1231-12" 로 오탐되던 값)
        "주민등록번호 901231-1234567",
        "010-1234-5678",  # 휴대전화 (원래 "1234-56" 으로 오탐되던 값)
        "02-123-4567",  # 지역번호 유선전화
        "0212345678",  # 구분자 없는 전화번호
        "110-123-456789",  # 계좌번호류 긴 숫자열
    ],
)
def test_pii_digit_runs_are_not_parsed_as_dates(pii_text: str) -> None:
    result = parse_dates(f"연락처는 {pii_text} 입니다.")

    assert result.case == "absent"
    assert result.entries == []


def test_ssn_fragment_never_appears_in_parsed_entries() -> None:
    """오탐이 나더라도 주민번호 조각이 결과에 남지 않아야 한다 (회귀 방지)."""
    result = parse_dates("유언장\n주민등록번호 901231-1234567\n전 재산을 상속한다.")

    assert result.entries == []
    # 어떤 필드로도 조각이 새지 않는지 값 전체를 훑어 확인한다.
    for entry in result.entries:  # pragma: no cover - 위 단언으로 비어 있음
        assert "1231" not in str(entry.raw_text)
        assert entry.year != 1231


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-05", (2026, 5)),
        ("2026-5", (2026, 5)),
        ("2026. 5", (2026, 5)),
        ("2026.05", (2026, 5)),
        ("2026년 5월", (2026, 5)),
    ],
)
def test_valid_year_month_still_parses(text: str, expected: tuple[int, int]) -> None:
    """PII 가드 추가로 정상 "연-월" 표기가 깨지지 않아야 한다 (회귀 방지)."""
    result = parse_dates(f"{text}에 작성함")

    assert result.case == "day_missing"
    entry = result.entries[0]
    assert (entry.year, entry.month) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-05-03", (2026, 5, 3)),
        ("2026-5-3", (2026, 5, 3)),
        ("2026. 5. 3.", (2026, 5, 3)),
        ("2026년 5월 3일", (2026, 5, 3)),
    ],
)
def test_valid_full_date_still_parses(
    text: str, expected: tuple[int, int, int]
) -> None:
    """PII 가드 추가로 정상 "연-월-일" 표기가 깨지지 않아야 한다 (회귀 방지)."""
    result = parse_dates(f"{text}에 작성함")

    assert result.case == "all_present"
    entry = result.entries[0]
    assert (entry.year, entry.month, entry.day) == expected

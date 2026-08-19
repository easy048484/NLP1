"""
decedent_estate.date_parser 단위 테스트.

케이스는 rules/requirements.json 의 date.conditions[].id 와 1:1 대응한다.
"""

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

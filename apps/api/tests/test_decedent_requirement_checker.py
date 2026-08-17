"""
decedent_estate.requirement_checker 통합 테스트.

유언장 샘플 8개로 rules/requirements.json 의 요건별 조건이 올바르게
매칭되고, 그 조건에 연결된 등급·판례 카드 id가 그대로 반환되는지 확인한다.
① 5요건 완비  ② 일 누락  ③ 말로 특정(칠순 기념일)  ④ 주소 누락
⑤ 성명 누락  ⑥ 주소가 시·구 수준까지만  ⑦ 날짜 2개 혼재  ⑧ 날인 없이 서명만
"""

from agents.decedent_estate.requirement_checker import check_requirements

_NAME_LINE = "유언자: 홍길동"
_ADDRESS_LINE = "주소: 서울특별시 강남구 테헤란로 123, 45동 678호"
_DATE_LINE = "2026년 5월 3일"
_BODY = "나의 전 재산을 배우자에게 상속한다."


def _will_text(*lines: str) -> str:
    return "\n".join([*lines, "", _BODY])


def test_sample1_all_five_requirements_complete() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["date"].condition_id == "all_present"
    assert results["date"].grade == "GREEN"
    assert results["address"].condition_id == "full_address"
    assert results["address"].grade == "GREEN"
    assert results["name"].condition_id == "present"
    assert results["name"].grade == "GREEN"
    assert results["handwriting"].grade == "GREEN"
    assert results["seal"].grade == "GREEN"


def test_sample2_day_missing() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "2026년 5월")

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["date"].condition_id == "day_missing"
    assert results["date"].grade == "RED"
    assert results["date"].precedent_ids == ["date_missing_day_invalid"]


def test_sample3_verbal_specified() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "아버지 칠순 기념일에")

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["date"].condition_id == "verbal_specified"
    assert results["date"].grade == "YELLOW"
    assert results["date"].precedent_ids == ["date_missing_day_invalid", "date_specifiable_valid"]


def test_sample4_address_missing() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["address"].condition_id == "absent"
    assert results["address"].grade == "RED"
    assert results["address"].precedent_ids == ["address_missing_invalid"]


def test_sample5_name_missing() -> None:
    text = _will_text(_ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["name"].condition_id == "absent"
    assert results["name"].grade == "RED"


def test_sample6_address_city_district_only() -> None:
    text = _will_text(_NAME_LINE, "주소: 서울 강남구", _DATE_LINE)

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["address"].condition_id == "city_district_only"
    assert results["address"].grade == "RED"
    assert results["address"].precedent_ids == ["address_missing_invalid"]


def test_sample7_multiple_dates_mixed() -> None:
    text = _will_text(
        _NAME_LINE,
        _ADDRESS_LINE,
        "2025년 12월 25일에 작성하였으나 2026년 1월 1일로 다시 적는다.",
    )

    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["date"].condition_id == "multiple_dates_mixed"
    assert results["date"].grade == "YELLOW"


def test_sample8_seal_signature_only() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(text, handwriting_answer="yes", seal_answer="signature_only")

    assert results["seal"].condition_id == "signature_only"
    assert results["seal"].grade == "RED"
    assert results["seal"].precedent_ids == ["signature_only_insufficient", "fingerprint_seal_valid"]


def test_unanswered_user_confirm_fields_are_pending() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(text)

    assert results["handwriting"].condition_id is None
    assert results["handwriting"].grade == "PENDING"
    assert results["seal"].condition_id is None
    assert results["seal"].grade == "PENDING"


def test_name_label_without_colon() -> None:
    text = _will_text("유언자 홍길동", _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(text)

    assert results["name"].condition_id == "present"
    assert "홍길동" in results["name"].extracted["raw_text"]


def test_name_before_seal_mark_without_label() -> None:
    text = _will_text(_ADDRESS_LINE, _DATE_LINE, "홍길동 (인)")

    results = check_requirements(text)

    assert results["name"].condition_id == "present"
    assert "홍길동" in results["name"].extracted["raw_text"]


def test_name_standalone_line_at_signature() -> None:
    text = "유언장\n" + _will_text(_ADDRESS_LINE, _DATE_LINE, "홍길동")

    results = check_requirements(text)

    assert results["name"].condition_id == "present"
    assert results["name"].extracted["raw_text"] == "홍길동"


def test_property_address_is_not_mistaken_for_testator_address() -> None:
    """상속 대상 부동산 소재지는 유언자 주소가 아니므로 absent 로 판정되어야 한다."""
    text = _will_text(
        _NAME_LINE,
        "나는 내가 소유한 서울특별시 강남구 테헤란로 123, 456동 789호 아파트를 장남 김철수에게 상속한다.",
        _DATE_LINE,
    )

    results = check_requirements(text)

    assert results["address"].condition_id == "absent"
    assert results["address"].grade == "RED"

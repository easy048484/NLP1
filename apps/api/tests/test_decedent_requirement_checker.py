"""
decedent_estate.requirement_checker 통합 테스트.

유언장 샘플 8개로 rules/requirements.json 의 요건별 조건이 올바르게
매칭되고, 그 조건에 연결된 등급·판례 카드 id가 그대로 반환되는지 확인한다.
① 5요건 완비  ② 일 누락  ③ 말로 특정(칠순 기념일)  ④ 주소 누락
⑤ 성명 누락  ⑥ 주소가 시·구 수준까지만  ⑦ 날짜 2개 혼재  ⑧ 날인 없이 서명만
"""

from agents.decedent_estate.requirement_checker import (
    check_requirements,
    extract_address,
    validate_confirm_answers,
)

_NAME_LINE = "유언자: 홍길동"
_ADDRESS_LINE = "주소: 서울특별시 강남구 테헤란로 123, 45동 678호"
_DATE_LINE = "2026년 5월 3일"
_BODY = "나의 전 재산을 배우자에게 상속한다."


def _will_text(*lines: str) -> str:
    return "\n".join([*lines, "", _BODY])


def test_sample1_all_five_requirements_complete() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

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

    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["date"].condition_id == "day_missing"
    assert results["date"].grade == "RED"
    assert results["date"].precedent_ids == ["date_missing_day_invalid"]


def test_sample3_verbal_specified() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "아버지 칠순 기념일에")

    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["date"].condition_id == "verbal_specified"
    assert results["date"].grade == "YELLOW"
    assert results["date"].precedent_ids == [
        "date_missing_day_invalid",
        "date_specifiable_valid",
    ]


def test_sample4_address_missing() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)

    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )

    assert results["address"].condition_id == "absent"
    assert results["address"].grade == "RED"
    assert results["address"].precedent_ids == ["address_missing_invalid"]


def test_sample5_name_missing() -> None:
    text = _will_text(_ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["name"].condition_id == "absent"
    assert results["name"].grade == "RED"


def test_sample6_address_city_district_only() -> None:
    text = _will_text(_NAME_LINE, "주소: 서울 강남구", _DATE_LINE)

    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )

    assert results["address"].condition_id == "city_district_only"
    assert results["address"].grade == "RED"
    assert results["address"].precedent_ids == ["address_missing_invalid"]


def test_city_district_only_does_not_trigger_envelope_followup() -> None:
    """본문에 불완전하게라도 주소가 있으면(city_district_only) 봉투 질문은 말이 안 되므로
    PENDING으로 새지 않고 곧바로 RED로 확정돼야 한다 — 봉투 확인 답변 없이도."""
    text = _will_text(_NAME_LINE, "주소: 서울 강남구", _DATE_LINE)

    results = check_requirements(text)  # address_envelope_answer 를 아예 안 줌

    assert results["address"].condition_id == "city_district_only"
    assert results["address"].grade == "RED"
    assert results["address"].followup_question is None


def test_absent_address_still_triggers_envelope_followup() -> None:
    """주소가 아예 없는(absent) 경우에는 여전히 봉투 질문이 트리거돼 PENDING이어야 한다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 언급 자체가 없음

    results = check_requirements(text)  # address_envelope_answer 를 아예 안 줌

    assert results["address"].condition_id is None
    assert results["address"].grade == "PENDING"
    assert (
        results["address"].followup_question
        == "주소가 유언장 본문이 아니라 봉투에 적혀 있나요?"
    )
    assert results["address"].extracted["underlying_case"] == "absent"


def test_sample7_multiple_dates_mixed() -> None:
    text = _will_text(
        _NAME_LINE,
        _ADDRESS_LINE,
        "2025년 12월 25일에 작성하였으나 2026년 1월 1일로 다시 적는다.",
    )

    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["date"].condition_id == "multiple_dates_mixed"
    assert results["date"].grade == "YELLOW"


def test_sample8_seal_signature_only() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="signature_only"
    )

    assert results["seal"].condition_id == "signature_only"
    assert results["seal"].grade == "RED"
    assert results["seal"].precedent_ids == [
        "signature_only_insufficient",
        "fingerprint_seal_valid",
    ]


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


def test_name_extracted_value_excludes_label() -> None:
    """GREEN extracted 값은 "유언자: 홍길동"이 아니라 이름만("홍길동")이어야 한다."""
    text = _will_text(
        _NAME_LINE, _ADDRESS_LINE, _DATE_LINE
    )  # _NAME_LINE = "유언자: 홍길동"

    results = check_requirements(text)

    assert results["name"].extracted["raw_text"] == "홍길동"


def test_name_label_word_in_ordinary_sentence_is_not_misdetected() -> None:
    """ "이름"이 라벨이 아니라 평범한 단어로 쓰인 문장에서 오추출되면 안 된다."""
    text = _will_text(_ADDRESS_LINE, _DATE_LINE, "특별한 이름 없음")

    results = check_requirements(text)

    assert results["name"].condition_id == "absent"
    assert results["name"].extracted["raw_text"] is None


def test_name_label_word_followed_by_more_prose_is_not_misdetected() -> None:
    text = _will_text(_ADDRESS_LINE, _DATE_LINE, "이름 없는 사람에게 준다.")

    results = check_requirements(text)

    assert results["name"].condition_id == "absent"
    assert results["name"].extracted["raw_text"] is None


def test_name_before_seal_mark_without_label() -> None:
    text = _will_text(_ADDRESS_LINE, _DATE_LINE, "홍길동 (인)")

    results = check_requirements(text)

    assert results["name"].condition_id == "present"
    assert results["name"].extracted["raw_text"] == "홍길동"


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

    results = check_requirements(text, address_envelope_answer="no_envelope")

    assert results["address"].condition_id == "absent"
    assert results["address"].grade == "RED"


def test_address_red_without_envelope_answer_is_pending() -> None:
    """RED 판정 뒤에는 봉투 확인 질문을 먼저 띄워야 하므로, 미답변 시 PENDING이어야 한다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음 → 본문 판정은 absent(RED)

    results = check_requirements(text)

    address = results["address"]
    assert address.condition_id is None
    assert address.grade == "PENDING"
    assert (
        address.followup_question == "주소가 유언장 본문이 아니라 봉투에 적혀 있나요?"
    )
    assert address.extracted["underlying_case"] == "absent"


def test_address_missing_but_envelope_confirmed_upgrades_to_yellow() -> None:
    """주소 없음 + 봉투에 있다고 확인 → envelope_or_minor_discrepancy(YELLOW)로 승격."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음

    results = check_requirements(
        text, address_envelope_answer="envelope_or_minor_discrepancy"
    )

    address = results["address"]
    assert address.condition_id == "envelope_or_minor_discrepancy"
    assert address.grade == "YELLOW"
    assert address.precedent_ids == ["address_on_envelope_valid"]
    assert address.followup_question is None


def test_address_red_with_no_envelope_answer_stays_red() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음

    results = check_requirements(text, address_envelope_answer="no_envelope")

    address = results["address"]
    assert address.condition_id == "absent"
    assert address.grade == "RED"
    assert address.precedent_ids == ["address_missing_invalid"]
    assert address.followup_question is None


def test_address_green_ignores_envelope_answer() -> None:
    """본문 판정이 GREEN이면 봉투 질문 자체가 트리거되지 않는다 (답을 줘도 무시)."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)  # full_address

    results = check_requirements(
        text, address_envelope_answer="envelope_or_minor_discrepancy"
    )

    address = results["address"]
    assert address.condition_id == "full_address"
    assert address.grade == "GREEN"
    assert address.followup_question is None


def test_validate_confirm_answers_flags_value_from_wrong_field() -> None:
    """seal_answer 에 handwriting_answer 의 값("yes")을 잘못 넣은 경우를 잡아내야 한다."""
    warnings = validate_confirm_answers(seal_answer="yes")

    assert warnings == [
        {
            "field": "seal_answer",
            "invalid_value": "yes",
            "allowed": ["seal_or_fingerprint", "signature_only", "absent"],
        }
    ]


def test_validate_confirm_answers_no_warnings_for_valid_or_missing() -> None:
    warnings = validate_confirm_answers(
        handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )  # address_envelope_answer 는 아예 안 줌

    assert warnings == []


def test_validate_confirm_answers_multiple_invalid_fields() -> None:
    warnings = validate_confirm_answers(
        handwriting_answer="maybe",
        seal_answer="yes",
        address_envelope_answer="예",
    )

    assert {w["field"] for w in warnings} == {
        "handwriting_answer",
        "seal_answer",
        "address_envelope_answer",
    }


def test_invalid_confirm_answer_still_results_in_pending_not_crash() -> None:
    """CLAUDE.md 원칙: 잘못된 입력이 와도 판정은 죽지 않고 PENDING으로 남는다."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)

    results = check_requirements(text, seal_answer="yes")

    assert results["seal"].condition_id is None
    assert results["seal"].grade == "PENDING"


# ---------------------------------------------------------------------------
# 도로명주소 / 라벨 없는 지번 인식 (2026-08-26)
#
# _ADDRESS_UNIT_RE 가 "번지"라는 리터럴 단어에 의존해, 완전한 도로명주소
# ("테헤란로 123")와 "번지" 글자 없는 지번("역삼동 123-45")이 전부
# city_district_only(RED)로 오판정되던 문제를 고쳤다. 아래는 사진 판독
# 기능 검증 중 실측한 8건 그대로다 — 도로명 4건 중 2건, 지번 2건 중 1건이
# 수정 전에는 오판정이었다(정확히는: 도로명 2건 + 지번 2건, 총 4건).
# ---------------------------------------------------------------------------


def test_address_lot_number_with_label() -> None:
    """지번 + '번지' 라벨 — 기존에도 정상 동작하던 케이스(회귀 확인용)."""
    result = extract_address("주소: 서울특별시 강남구 역삼동 123번지")
    assert result.case == "full_address"


def test_address_lot_number_without_label() -> None:
    """지번인데 '번지' 글자가 없는 표기 — 수정 전엔 city_district_only로 오판정됐다."""
    result = extract_address("주소: 서울특별시 강남구 역삼동 123-45")
    assert result.case == "full_address"


def test_address_dong_only_stays_red() -> None:
    """🔴 회귀: '동만 기재'(2012다71688) — 완화 이후에도 반드시 RED로 남아야 한다."""
    result = extract_address("주소: 서울시 강남구 역삼동")
    assert result.case == "city_district_only"


def test_address_road_name_basic() -> None:
    """도로명주소 기본형 — 수정 전엔 city_district_only로 오판정됐다."""
    result = extract_address("주소: 서울특별시 강남구 테헤란로 123")
    assert result.case == "full_address"


def test_address_road_name_with_apartment_unit() -> None:
    result = extract_address("주소: 서울특별시 강남구 테헤란로 123, 45동 678호")
    assert result.case == "full_address"


def test_address_road_name_without_number_stays_red() -> None:
    """🔴 회귀: 번지 없는 도로명 — 완화 이후에도 반드시 RED로 남아야 한다."""
    result = extract_address("주소: 서울특별시 강남구 테헤란로")
    assert result.case == "city_district_only"


def test_address_road_name_compound_beonggil() -> None:
    """간선로 + 번길(지선) + 건물번호 복합 표기."""
    result = extract_address("주소: 경기도 성남시 분당구 판교로 256번길 12")
    assert result.case == "full_address"


def test_address_lot_number_without_label_alt_district() -> None:
    result = extract_address("주소: 부산광역시 해운대구 우동 1234")
    assert result.case == "full_address"


def test_address_district_only_stays_red() -> None:
    """🔴 회귀: 구까지만 기재 — 완화 이후에도 반드시 RED로 남아야 한다."""
    result = extract_address("주소: 서울특별시 강남구")
    assert result.case == "city_district_only"


def test_address_road_name_sub_number() -> None:
    """부번 표기("123-4") — 지번의 '-45'와 동일한 패턴을 도로명에도 적용."""
    result = extract_address("주소: 서울특별시 강남구 테헤란로 123-4")
    assert result.case == "full_address"


def test_amount_in_will_body_is_not_mistaken_for_address() -> None:
    """유언 내용의 금액·수량이 새 정규식 대안(로/길/동/읍/면/리)에 걸려
    주소로 오인되지 않아야 한다 — '-(으)로' 조사, '동/개월' 등 단위 표현이
    실제 주소 패턴처럼 보일 수 있는 문장들."""
    for text in (
        "장남에게 5000만원을 준다.",
        "이유로 3개월 이내에 처리한다.",
        "나는 매일 운동 30분씩 한다.",
        "회의 안건으로 3가지를 정했다.",
    ):
        result = extract_address(text)
        assert result.case == "absent", f"오탐: {text!r} -> {result.case}"


def test_property_location_road_address_still_excluded_by_context() -> None:
    """재산 소재지(도로명주소)가 유언자 본인 주소로 오인되지 않는지 —
    _ADDRESS_PROPERTY_CONTEXT_RE 필터가 도로명주소 대안 추가 이후에도
    그대로 작동하는지 확인한다."""
    text = _will_text(
        _NAME_LINE,
        "나는 내가 소유한 서울특별시 강남구 테헤란로 456 아파트를 장남에게 상속한다.",
        _DATE_LINE,
    )

    results = check_requirements(text, address_envelope_answer="no_envelope")

    assert results["address"].condition_id == "absent"
    assert results["address"].grade == "RED"


# ---------------------------------------------------------------------------
# 도로명주소 건물번호 뒤 한국어 조사 경계 (2026-09-05)
#
# _ADDRESS_UNIT_RE의 도로명주소 대안이 건물번호 뒤에 공백/쉼표/마침표/문자열
# 끝만 허용해서, "테헤란로 123이라고 적혀 있어요"처럼 review 자연어 확인
# 답변에서 건물번호에 조사가 바로 붙는 문장은 도로명주소를 통째로 놓치고
# city_district_only(RED)로 오판정됐다. "로/길" 토큰 문맥 제한은 그대로 두고
# 건물번호 뒤 경계에 명시적 조사 화이트리스트(이라고/라고/에/으로/입니다)만
# 추가했다 — 숫자 뒤 한글을 전부 허용하지 않는다.
# ---------------------------------------------------------------------------


def test_address_road_name_with_narrative_particle_ida_go() -> None:
    result = extract_address(
        "주소는 서울특별시 강남구 테헤란로 123이라고 적혀 있습니다."
    )
    assert result.case == "full_address"


def test_address_road_name_with_narrative_particle_e() -> None:
    result = extract_address("서울특별시 강남구 테헤란로 123에 살았습니다.")
    assert result.case == "full_address"


def test_address_road_name_with_narrative_particle_eseo() -> None:
    result = extract_address("서울특별시 강남구 테헤란로 123에서 작성했습니다.")
    assert result.case == "full_address"


def test_address_road_name_with_narrative_particle_euro() -> None:
    result = extract_address("서울특별시 강남구 테헤란로 123으로 이사했습니다.")
    assert result.case == "full_address"


def test_address_road_name_with_narrative_particle_ipnida() -> None:
    result = extract_address("주소는 서울특별시 강남구 테헤란로 123입니다.")
    assert result.case == "full_address"


def test_address_road_name_with_detail_and_narrative_particle() -> None:
    """상세주소(동/호)까지 포함해 서술형으로 끝나는 문장 — 기존 상세주소 판정과
    새 조사 경계가 함께 정상 동작해야 한다."""
    result = extract_address(
        "주소는 서울특별시 강남구 테헤란로 123, 101동 1203호라고 적혀 있습니다."
    )
    assert result.case == "full_address"


def test_address_road_name_narrative_particles_do_not_regress_existing_cases() -> None:
    """조사 경계를 넓히기 전 기존 표기(공백/쉼표/부번/복합 도로명)는 그대로
    통과해야 한다 — 회귀 확인용."""
    for text, expected_case in (
        ("주소: 서울특별시 강남구 테헤란로 123", "full_address"),
        ("주소: 서울특별시 강남구 테헤란로 123-4", "full_address"),
        ("주소: 경기도 성남시 분당구 판교로 256번길 12", "full_address"),
        ("주소: 서울특별시 강남구 테헤란로 123, 45동 678호", "full_address"),
    ):
        result = extract_address(text)
        assert result.case == expected_case, f"{text!r} -> {result.case}"


def test_address_road_name_without_detail_is_yellow_with_detail_question() -> None:
    """도로명 건물번호까지는 있지만 동·호수 등 세부 거주 단위가 없으면 무효로
    단정하지 않고 YELLOW(building_number_only) + 후속 질문으로 처리한다
    (2026-09-05)."""
    results = check_requirements(
        "주소는 서울특별시 강남구 테헤란로 123이라고 적혀 있습니다."
    )
    address = results["address"]
    assert address.grade == "YELLOW"
    assert address.condition_id == "building_number_only"
    assert (
        address.followup_question == "유언장에 동·호수 등 더 상세한 주소도 적혀 있나요?"
    )


def test_address_road_name_with_detail_is_green_via_check_requirements() -> None:
    """세부 거주 단위(동·호수)까지 있으면 기존처럼 GREEN — 후속 질문 없음."""
    results = check_requirements(
        "주소는 서울특별시 강남구 테헤란로 123, 101동 1203호라고 적혀 있습니다."
    )
    address = results["address"]
    assert address.grade == "GREEN"
    assert address.condition_id == "full_address"
    assert address.followup_question is None


def test_address_narrative_particle_boundary_does_not_widen_false_positives() -> None:
    """조사 화이트리스트를 추가해도 '로/길' 토큰이 없는 금액·수량·기간·날짜
    표현은 여전히 주소로 오인되면 안 된다 — 오탐 증가 없음 확인."""
    for text in (
        "예금 123만원",
        "3개월",
        "2026년",
        "주식 123주",
        "빚이 123만원 있습니다.",
        "이 유언장은 2026년입니다.",
    ):
        result = extract_address(text)
        assert result.case == "absent", f"오탐: {text!r} -> {result.case}"

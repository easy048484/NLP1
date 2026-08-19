"""
decedent_estate.masking 단위 테스트.

주민등록번호·계좌번호·전화번호는 지우고, 성명·주소·날짜는 판정에 필요하므로
그대로 통과시켜야 한다 (CLAUDE.md 절대 원칙 4).
"""

from agents.decedent_estate.masking import _PHONE_RE, _RRN_RE, mask_text


def test_masks_resident_registration_number() -> None:
    text = "유언자 주민등록번호: 901231-1234567"

    masked = mask_text(text)

    assert "901231-1234567" not in masked
    assert "[주민등록번호]" in masked


def test_masks_mobile_phone_number() -> None:
    text = "연락처: 010-1234-5678"

    masked = mask_text(text)

    assert "010-1234-5678" not in masked
    assert "[전화번호]" in masked


def test_masks_landline_phone_number() -> None:
    text = "연락처: 02-123-4567"

    masked = mask_text(text)

    assert "02-123-4567" not in masked
    assert "[전화번호]" in masked


def test_masks_labeled_account_number() -> None:
    text = "계좌번호: 110-123-456789 로 입금 바람"

    masked = mask_text(text)

    assert "110-123-456789" not in masked
    assert "계좌번호: [계좌번호]" in masked


def test_does_not_mask_unlabeled_digit_sequences() -> None:
    """라벨 없는 숫자·하이픈 조합(계좌번호로 오인하기 쉬운 것)은 건드리지 않는다."""
    text = "45동 678호"

    masked = mask_text(text)

    assert masked == text


def test_preserves_name_address_and_dates() -> None:
    text = (
        "유언장\n"
        "유언자: 홍길동\n"
        "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
        "2026년 5월 3일\n"
        "작성일: 2026-05-03\n"
        "\n"
        "나의 전 재산을 배우자에게 상속한다."
    )

    masked = mask_text(text)

    assert masked == text


def test_masks_multiple_sensitive_values_in_one_document() -> None:
    text = (
        "유언자: 홍길동 (주민등록번호 901231-1234567)\n"
        "연락처: 010-1234-5678\n"
        "계좌번호: 110-123-456789\n"
        "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
        "2026년 5월 3일"
    )

    masked = mask_text(text)

    assert "901231-1234567" not in masked
    assert "010-1234-5678" not in masked
    assert "110-123-456789" not in masked
    assert "홍길동" in masked
    assert "서울특별시 강남구 테헤란로 123, 45동 678호" in masked
    assert "2026년 5월 3일" in masked


# ---------------------------------------------------------------------------
# 교차 오탐 회귀 테스트: 주민등록번호(_RRN_RE)·전화번호(_PHONE_RE)·날짜가
# 서로의 패턴을 잘못 집어삼키지 않는지 확인한다.
# ---------------------------------------------------------------------------


def test_dashed_date_is_not_masked_as_rrn_or_phone() -> None:
    text = "2026-05-03"

    assert _RRN_RE.search(text) is None
    assert _PHONE_RE.search(text) is None
    assert mask_text(text) == text


def test_korean_style_date_is_not_masked() -> None:
    text = "2026년 5월 3일"

    assert mask_text(text) == text


def test_phone_number_matches_only_phone_pattern_not_rrn() -> None:
    text = "010-1234-5678"

    assert _PHONE_RE.search(text) is not None
    assert _RRN_RE.search(text) is None
    assert mask_text(text) == "[전화번호]"


def test_rrn_matches_only_rrn_pattern_not_phone() -> None:
    text = "901225-1234567"

    assert _RRN_RE.search(text) is not None
    assert _PHONE_RE.search(text) is None
    assert mask_text(text) == "[주민등록번호]"


def test_six_and_seven_digit_numbers_near_each_other_are_not_masked() -> None:
    """주민번호처럼 보일 수 있는 6자리·7자리 숫자가 하이픈으로 안 이어져 있으면
    (우연히 근처에 있을 뿐이면) 마스킹하지 않는다."""
    text = "생년월일 900101, 문서번호 1234567"

    assert _RRN_RE.search(text) is None
    assert mask_text(text) == text

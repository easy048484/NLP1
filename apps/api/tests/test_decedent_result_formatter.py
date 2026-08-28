"""
decedent_estate.result_formatter 테스트.

요건판정_문구_스펙_v1.md §3 이 그대로 구현됐는지 확인한다. 고정 문구는
스펙 원문과 글자 단위로 비교하고, {요건}/{쟁점} 자리에 들어가는 판례 카드
문구는 rules/precedents.json 의 one_liner 를 그대로 로드해서 대조한다
(문자열을 테스트 파일에 다시 베껴 적으면 두 파일이 따로 놀 수 있으므로).
"""

import json
from pathlib import Path

from agents.decedent_estate.requirement_checker import check_requirements
from agents.decedent_estate.result_formatter import (
    format_requirement_line,
    format_result,
    pending_questions,
    summarize,
)

_PRECEDENTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "decedent_estate"
    / "rules"
    / "precedents.json"
)


def _precedent(precedent_id: str) -> dict:
    with _PRECEDENTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return next(p for p in data["precedents"] if p["id"] == precedent_id)


def _one_liner(precedent_id: str) -> str:
    return _precedent(precedent_id)["one_liner"]


def _citation(precedent_id: str) -> str:
    p = _precedent(precedent_id)
    if p["type"] == "commentary":
        return "(대한법률구조공단 해설)"
    return f"({p['court']} {p['case_number']})"


_NAME_LINE = "유언자: 홍길동"
_ADDRESS_LINE = "주소: 서울특별시 강남구 테헤란로 123, 45동 678호"
_DATE_LINE = "2026년 5월 3일"
_BODY = "나의 전 재산을 배우자에게 상속한다."


def _will_text(*lines: str) -> str:
    return "\n".join([*lines, "", _BODY])


def test_case_a_all_green_summary() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert summarize(results) == (
        "**형식 요건상 문제가 발견되지 않았습니다.** 자필증서 유언의 5가지 형식 요건"
        "(자서·연월일·주소·성명·날인)이 모두 확인됩니다. 다만 이 점검은 형식 요건에 한정되며, "
        "유언의 최종 유효성은 내용·작성 경위 등에 따라 달라질 수 있습니다."
    )

    output = format_result(results)
    assert "✅ 연월일: 기재 확인 (2026년 5월 3일)" in output
    assert "✅ 주소: 기재 확인" in output
    assert "✅ 성명: 기재 확인" in output
    assert "✅ 전문 자서: 기재 확인" in output
    assert "✅ 날인: 기재 확인" in output
    assert "❌" not in output
    assert "⚠️" not in output


def test_case_b_red_present_summary_and_card() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )

    assert summarize(results) == (
        "**확인되지 않는 요건이 있습니다.** 아래 항목은 법원이 무효로 판단해온 사례와 같은 "
        "쟁점에 해당할 수 있습니다. 법률 전문가 확인을 권합니다."
    )

    line = format_requirement_line(results["address"])
    assert line == "\n".join(
        [
            "❌ 주소: 유언자 주소가 확인되지 않습니다",
            f"{_one_liner('address_missing_invalid')} {_citation('address_missing_invalid')}",
        ]
    )
    assert "→ 법률 전문가 확인을 권합니다" not in line


def test_case_c_yellow_only_summary_and_two_cards() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "아버지 칠순 기념일에")
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert summarize(results) == (
        "**전문가 확인이 필요한 부분이 있습니다.** 형식상 명확한 문제는 발견되지 않았으나, "
        "법원 판단이 사안에 따라 갈린 쟁점이 포함되어 있습니다."
    )

    line = format_requirement_line(results["date"])
    assert line == "\n".join(
        [
            "⚠️ 연월일: 연월일이 쟁점이 될 수 있습니다",
            f"{_one_liner('date_missing_day_invalid')} {_citation('date_missing_day_invalid')}",
            f"{_one_liner('date_specifiable_valid')} {_citation('date_specifiable_valid')}",
            "→ 개별 판단이 필요합니다. 법률 상담을 권합니다",
        ]
    )
    assert _citation("date_specifiable_valid") == "(대한법률구조공단 해설)"


def test_case_d_pending_summary_lists_question() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, seal_answer="seal_or_fingerprint"
    )  # handwriting만 미답변 → 1개

    assert summarize(results) == (
        "**한 가지만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 항목입니다."
    )

    questions = pending_questions(results)
    assert questions == [
        {
            "requirement": "전문 자서",
            "field": "handwriting_answer",
            "question": "유언장 전체를 직접 손으로 쓰셨나요? (타이핑·워드 출력 아님)",
            "options": [
                {"label": "직접 손으로 썼다", "value": "yes"},
                {
                    "label": "타이핑했거나 일부만 손으로 썼다",
                    "value": "no_or_partial_typed",
                },
            ],
        }
    ]

    output = format_result(results)
    assert "전문 자서: 유언장 전체를 직접 손으로 쓰셨나요?" in output


def test_pending_question_options_for_seal() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(text, handwriting_answer="yes")  # seal만 미답변

    questions = pending_questions(results)
    assert questions == [
        {
            "requirement": "날인",
            "field": "seal_answer",
            "question": "도장 또는 지장(손도장)이 찍혀 있나요?",
            "options": [
                {"label": "도장 또는 지장이 있다", "value": "seal_or_fingerprint"},
                {"label": "서명만 있다", "value": "signature_only"},
                {"label": "아무것도 없다", "value": "absent"},
            ],
        }
    ]


def test_pending_question_options_for_address_envelope() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음(absent) → 봉투 확인 트리거
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    questions = pending_questions(results)
    assert questions == [
        {
            "requirement": "주소",
            "field": "address_envelope_answer",
            "question": "주소가 유언장 본문이 아니라 봉투에 적혀 있나요?",
            "options": [
                {"label": "봉투에 적혀 있다", "value": "envelope_or_minor_discrepancy"},
                {"label": "봉투에도 없다", "value": "no_envelope"},
            ],
        }
    ]


def test_pending_takes_priority_over_red() -> None:
    """PENDING 항목이 하나라도 있으면 RED가 섞여 있어도 D 요약이 우선한다."""
    text = _will_text(
        _NAME_LINE, _DATE_LINE
    )  # 주소 없음(RED) + handwriting/seal 미답변 → 2개
    results = check_requirements(text, address_envelope_answer="no_envelope")

    assert results["address"].grade == "RED"
    assert results["handwriting"].grade == "PENDING"
    assert results["seal"].grade == "PENDING"
    assert summarize(results) == (
        "**2가지만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 항목입니다."
    )


def test_summary_pending_count_scales_with_three_pending_items() -> None:
    """주소 봉투 확인까지 겹치면 PENDING이 3개까지 늘어날 수 있다."""
    text = _will_text(
        _NAME_LINE, _DATE_LINE
    )  # 주소 없음(RED, 봉투 미답변) + handwriting/seal 미답변

    results = check_requirements(text)

    assert results["address"].grade == "PENDING"
    assert results["handwriting"].grade == "PENDING"
    assert results["seal"].grade == "PENDING"
    assert summarize(results) == (
        "**3가지만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 항목입니다."
    )


def test_josa_selection_no_batchim_for_address() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)
    results = check_requirements(text, address_envelope_answer="no_envelope")

    line = format_requirement_line(results["address"])
    assert line.startswith("❌ 주소: 유언자 주소가 확인되지 않습니다")


def test_josa_selection_batchim_for_date_and_name_and_seal() -> None:
    text = _will_text(_DATE_LINE)  # 성명·주소 없음, 날짜만 있음
    results = check_requirements(text, seal_answer="signature_only")

    name_line = format_requirement_line(results["name"])
    assert name_line.startswith("❌ 성명: 성명이 확인되지 않습니다")

    seal_line = format_requirement_line(results["seal"])
    assert seal_line.startswith("❌ 날인: 도장·지장이 확인되지 않습니다")


def test_seal_red_shows_fingerprint_note_not_card() -> None:
    """날인 RED에서 fingerprint_seal_valid는 카드가 아니라 들여쓴 참고 문구여야 한다."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="signature_only"
    )

    line = format_requirement_line(results["seal"])
    assert "   ℹ️ 참고: 지장(손도장)을 날인으로 인정한 판례가 있습니다" in line
    assert _one_liner("fingerprint_seal_valid") not in line
    assert "[카드]" not in line


def test_seal_green_shows_fingerprint_identity_note() -> None:
    """날인 GREEN(지장 선택)에도 본인 확인 관련 참고 문구가 딸려 나온다 — 등급은 GREEN 유지."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["seal"].grade == "GREEN"
    line = format_requirement_line(results["seal"])
    assert line.startswith("✅ 날인: 기재 확인")
    assert (
        "   ℹ️ 참고: 무인이 고인 본인의 것임이 다투어지는 경우 유언증서가 무효로 "
        "판단된 사례가 있습니다"
    ) in line
    assert "[카드]" not in line
    for assertive in ("무효입니다", "유효합니다"):
        assert assertive not in line


def test_red_lines_never_contain_removed_cta() -> None:
    text = _will_text(_DATE_LINE)  # 주소·성명 없음
    results = check_requirements(
        text,
        handwriting_answer="no_or_partial_typed",
        seal_answer="signature_only",
        address_envelope_answer="no_envelope",
    )

    output = format_result(results)
    assert "→ 법률 전문가 확인을 권합니다" not in output
    assert "[카드]" not in output


def test_white_interseal_reference_line() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE, "(1/2)")
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["interseal"].grade == "WHITE"
    line = format_requirement_line(results["interseal"])
    assert line == (
        "ℹ️ 참고: 간인은 법정 요건이 아니지만, 여러 장일 경우 위조 다툼 예방에 도움이 됩니다"
    )
    assert line in format_result(results)


def test_consultation_and_footer_lines_always_present() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    output = format_result(results)
    assert (
        "📞 무료로 확인받을 수 있는 곳: 대한법률구조공단 132 (무료 법률상담) · 각 지역 지부. "
        "유언 검인·공증 관련은 가까운 공증사무소에서 안내받을 수 있습니다."
    ) in output
    assert (
        "이 점검은 민법 제1066조의 형식 요건에 대한 참고용 확인이며, 법률 자문이 아닙니다. "
        "유언의 유효성에 대한 최종 판단은 법원과 법률 전문가의 영역입니다."
    ) in output


def test_executor_not_disqualified_is_statute_not_unverified_precedent() -> None:
    """유언집행자 항목은 확인되지 않은 판례가 아니라 조문(§1072 열거) 근거다.

    사건번호를 검증하지 못해 precedent → statute 로 전환한 항목이라, 다시
    precedent 로 되돌아가거나 사건번호가 붙는 것을 막는다.
    """
    card = _precedent("executor_not_disqualified")

    assert card["type"] == "statute"
    assert card["source"] == "민법 제1072조 제1항"
    assert card["verified"] is True
    # 사건번호·법원·선고일은 검증 못 해 제거한 필드다.
    for removed in ("case_number", "court", "date"):
        assert removed not in card, removed
    # 화면 문구가 "판례"를 근거로 내세우면 안 된다.
    assert "판례" not in card["one_liner"]


def test_all_precedent_type_cards_are_verified_with_case_number() -> None:
    """type이 precedent 인 카드는 사건번호가 있고 미검증 표시가 없어야 한다.

    사건번호를 확인하지 못한 항목은 statute/commentary 로 내리거나 검증을
    마쳐야 한다는 규칙을 고정한다.
    """
    with _PRECEDENTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    for card in data["precedents"]:
        if card["type"] != "precedent":
            continue
        assert card.get("case_number"), card["id"]
        assert "확인 필요" not in card["case_number"], card["id"]
        assert card.get("verified", True) is True, card["id"]


def test_97da38510_cards_share_the_same_source_url() -> None:
    """97다38510 세 카드(typed_will_invalid/fingerprint_seal_valid/

    address_on_envelope_valid)는 같은 판례라 source_url을 통일한다 — 예전엔
    두 카드가 빈 문자열이었다.
    """
    ids = ("typed_will_invalid", "fingerprint_seal_valid", "address_on_envelope_valid")
    urls = {pid: _precedent(pid)["source_url"] for pid in ids}
    for pid, url in urls.items():
        assert url, pid
    assert len(set(urls.values())) == 1, urls


def test_fingerprint_identity_disputed_invalid_has_source_url() -> None:
    card = _precedent("fingerprint_identity_disputed_invalid")
    assert card["source_url"], card["id"]
    assert card["case_number"] == "2005누1600"
    assert card["court"] == "대전고등법원"

"""
decedent_estate.result_formatter 테스트.

요건판정_문구_스펙_v1.md §3 이 그대로 구현됐는지 확인한다. 고정 문구는
스펙 원문과 글자 단위로 비교하고, {요건}/{쟁점} 자리에 들어가는 판례 카드
문구는 rules/precedents.json 의 one_liner 를 그대로 로드해서 대조한다
(문자열을 테스트 파일에 다시 베껴 적으면 두 파일이 따로 놀 수 있으므로).
"""

import json
import re
from pathlib import Path

from agents.decedent_estate.requirement_checker import check_requirements
from agents.decedent_estate.result_formatter import (
    cited_precedents,
    cited_precedents_for_requirement,
    format_requirement_line,
    format_result,
    pending_questions,
    progress,
    summarize,
    term_note,
)

_PRECEDENTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "decedent_estate"
    / "rules"
    / "precedents.json"
)
_RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "decedent_estate"
    / "rules"
    / "requirements.json"
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
    # term_note 는 GREEN에 안 붙는다 — 날인 GREEN의 기존 참고 문구(ℹ️, 무인 관련,
    # _GREEN_REFERENCE_NOTES)와는 별개다. 그 케이스와 섞이지 않게 GREEN/RED 가
    # 함께 있는 결과로 별도 확인한다: test_term_note_excluded_for_green_included_for_red_in_mixed_result.


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
            f"   ℹ️ {term_note('address')}",
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
            f"   ℹ️ {term_note('date')}",
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
        "**한 가지만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 "
        "항목입니다. (4/5 확인됨)"
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
        "**2가지만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 "
        "항목입니다. (3/5 확인됨)"
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
        "**3가지만 직접 확인해주세요.** 텍스트만으로는 판별할 수 없는 "
        "항목입니다. (2/5 확인됨)"
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


def test_all_precedent_type_cards_have_source_url() -> None:
    """type이 precedent 인 카드는 모두 source_url이 비어있지 않아야 한다.

    (P1-4) 전수 재확인 회귀 테스트 — 사건번호가 존재해도 법령정보센터
    조회 링크가 깨져 있으면 사용자가 원문을 확인할 방법이 없다.
    """
    with _PRECEDENTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    for card in data["precedents"]:
        if card["type"] != "precedent":
            continue
        assert card.get("source_url"), card["id"]


def test_date_missing_day_invalid_uses_working_evtno_url() -> None:
    """(P1-4) precSeq=132717 은 "해당 판례가 존재하지 않습니다" 오류를 냈다.

    evtNo 파라미터 형태로 교체했으며(2026-08-31 확인), 이 형태로 회귀를
    막는다 — precSeq 파라미터로 되돌아가면 다시 깨진 링크가 된다.
    """
    card = _precedent("date_missing_day_invalid")
    assert card["case_number"] == "2009다9768"
    assert "evtNo=" in card["source_url"], card["source_url"]
    assert "precSeq=132717" not in card["source_url"]


# ---------------------------------------------------------------------------
# term_note (미충족 요건 용어 설명) — GREEN 제외, RED/YELLOW 만
# ---------------------------------------------------------------------------


def test_term_note_present_for_every_requirement() -> None:
    """자필증서 6요건 + 녹음 7요건 전부 term_note 가 채워져 있는지 (데이터 누락 방지)."""
    with _RULES_PATH.open(encoding="utf-8") as f:
        rules = json.load(f)

    handwritten = [r for r in rules["requirements"] if r["will_type"] == "handwritten"]
    recording = [r for r in rules["requirements"] if r["will_type"] == "recording"]
    assert len(handwritten) == 6
    assert len(recording) == 7

    for req in handwritten + recording:
        assert req.get("term_note"), req["id"]


def test_term_note_excluded_for_green_included_for_red_in_mixed_result() -> None:
    """같은 결과 집합 안에 GREEN 과 RED 가 섞여 있어도, term_note 는 RED 에만 붙는다
    — test_case_a(전부 GREEN)만으로는 "애초에 RED 가 없어서 안 보이는 것"과
    "GREEN 이라 걸러진 것"을 구분할 수 없어 별도로 확인한다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음 → RED, 나머지는 GREEN
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )

    green_line = format_requirement_line(results["name"])
    red_line = format_requirement_line(results["address"])

    assert results["name"].grade == "GREEN"
    assert "ℹ️" not in green_line

    assert results["address"].grade == "RED"
    assert term_note("address") in red_line


def test_term_note_included_for_yellow() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, "아버지 칠순 기념일에")
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert results["date"].grade == "YELLOW"
    line = format_requirement_line(results["date"])
    assert term_note("date") in line


# ---------------------------------------------------------------------------
# progress (진행률 체크리스트)
# ---------------------------------------------------------------------------


def test_progress_all_confirmed() -> None:
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert progress(results) == {"checked": 5, "total": 5}


def test_progress_counts_pending_as_unchecked() -> None:
    """handwriting/seal 확인 답변을 아예 안 주면 그 둘은 PENDING — 진행률에서 빠져야 한다."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(text)  # handwriting_answer/seal_answer 없음

    assert results["handwriting"].grade == "PENDING"
    assert results["seal"].grade == "PENDING"
    assert progress(results) == {"checked": 3, "total": 5}


def test_progress_counts_red_and_yellow_as_checked() -> None:
    """PENDING 이 아니면(GREEN/RED/YELLOW 무엇이든) "확인됨"으로 센다 — 등급이
    나쁘다고 진행률에서 빠지지 않는다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음 → RED
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )

    assert results["address"].grade == "RED"
    assert progress(results) == {"checked": 5, "total": 5}


def test_progress_interseal_not_counted() -> None:
    """interseal 은 법정 요건이 아니라(_FORMAL_REQUIREMENT_IDS 밖) 분모에 안 들어간다."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text, handwriting_answer="yes", seal_answer="seal_or_fingerprint"
    )

    assert "interseal" in results  # 결과 자체엔 있지만
    assert progress(results)["total"] == 5  # 분모에는 안 들어간다


def test_progress_recording_total_is_seven() -> None:
    from agents.decedent_estate.recording_checker import (
        FORMAL_RECORDING_REQUIREMENT_IDS,
        check_recording_requirements,
    )

    text = (
        "나는 다음과 같이 유언한다. 이 집을 아들에게 물려준다. "
        "유언자: 홍길동. 2026년 5월 3일. "
        "증인은 이 내용이 정확합니다. 증인: 김철수."
    )
    results = check_recording_requirements(text)

    result = progress(results, FORMAL_RECORDING_REQUIREMENT_IDS)
    assert result["total"] == 7
    assert 0 <= result["checked"] <= 7


# ---------------------------------------------------------------------------
# P0-1: body(판례 인용 줄 제외) / precedents(실제 인용된 판례만) 배열
# ---------------------------------------------------------------------------

_CITATION_LINE_RE = re.compile(
    r"\((?:대법원|서울고법|대전고법|민법|대한법률구조공단)[^)]*\)"
)


def test_body_has_no_precedent_citation_lines() -> None:
    """body 는 요건별 문구를 그대로 쓰되 판례 인용 줄만 뺀다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음(RED)
    results = check_requirements(
        text,
        handwriting_answer="no_or_partial_typed",  # RED — typed_will_invalid 인용
        seal_answer="signature_only",  # RED — signature_only_insufficient 인용
        address_envelope_answer="no_envelope",
    )

    reply = format_result(results)
    body = format_result(results, include_precedent_cards=False)

    # 전제 확인: reply 에는 인용 줄이 있어야 한다(이 텍스트가 실제로 RED를 낸다는 것).
    assert _CITATION_LINE_RE.search(reply)
    # body 에는 없어야 한다.
    assert _CITATION_LINE_RE.search(body) is None


def test_body_keeps_term_note_and_reference_notes() -> None:
    """판례 인용 줄만 빠지고, term_note·참고 문구(예외 3건)는 body에 그대로 남는다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="signature_only",  # RED — fingerprint_seal_valid(예외) 참고 문구 포함
        address_envelope_answer="no_envelope",
    )

    body = format_result(results, include_precedent_cards=False)

    assert term_note("address") in body
    assert "ℹ️ 참고: 지장(손도장)을 날인으로 인정한 판례가 있습니다" in body


def test_cited_precedents_collects_unique_ids_across_requirements() -> None:
    text = _will_text(_NAME_LINE, _DATE_LINE)
    results = check_requirements(
        text,
        handwriting_answer="no_or_partial_typed",
        seal_answer="signature_only",
        address_envelope_answer="no_envelope",
    )

    precedents = cited_precedents(results)
    case_nos = [p["case_no"] for p in precedents]

    assert len(case_nos) == len(set(case_nos))  # 중복 없음
    assert _precedent("typed_will_invalid")["case_number"] in case_nos
    assert _precedent("address_missing_invalid")["case_number"] in case_nos
    assert _precedent("signature_only_insufficient")["case_number"] in case_nos


def test_cited_precedents_excludes_the_three_reference_note_ids() -> None:
    """카드로 안 만들기로 한 예외 3건은 precedents 배열에 절대 없어야 한다."""
    text = _will_text(_NAME_LINE, _DATE_LINE)
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="signature_only",  # fingerprint_seal_valid 이 precedent_ids 에 포함됨
    )
    assert "fingerprint_seal_valid" in results["seal"].precedent_ids  # 전제 확인

    precedents = cited_precedents(results)
    excluded_case_nos = {
        _precedent("fingerprint_seal_valid")["case_number"],
        _precedent("fingerprint_identity_disputed_invalid")["case_number"],
    }
    assert not any(p["case_no"] in excluded_case_nos for p in precedents)


def test_cited_precedents_statute_case_no_falls_back_to_id() -> None:
    """case_number 가 null 인 statute 판례는 case_no 자리에 id 가 채워져야 한다
    (프론트가 case_no==null 인 항목을 필터링해서 버리는 문제 방지)."""
    from agents.decedent_estate.recording_checker import check_recording_requirements

    text = "\n".join(
        [
            "유언자: 홍길동",
            "저의 전 재산을 배우자에게 상속한다.",
            "2026년 5월 3일",
            "증인: 김철수",
            "증인은 위 유언이 정확함을 확인합니다.",
        ]
    )
    results = check_recording_requirements(
        text,
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="disqualified",  # witness_disqualification 인용
    )
    assert _precedent("witness_disqualification")["case_number"] is None  # 전제 확인

    precedents = cited_precedents(results)
    entry = next(
        p
        for p in precedents
        if p["summary"] == _precedent("witness_disqualification")["summary"]
    )
    assert entry["case_no"] == "witness_disqualification"


# ---------------------------------------------------------------------------
# A안 (#58 P0-1 후속): cited_precedents_for_requirement — 요건 하나 단위
# ---------------------------------------------------------------------------


def test_cited_precedents_for_requirement_only_returns_that_requirements_own_ids() -> (
    None
):
    """다른 요건의 판례가 섞여 들어오면 안 된다 — date/address가 각자 RED라도
    date 쪽 결과에는 address 판례가, address 쪽 결과에는 date 판례가 없어야 한다."""
    text = _will_text(_NAME_LINE)  # 주소·연월일 둘 다 없음
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",  # absent만으로는 PENDING이라 확정 필요
    )
    assert results["date"].grade == "RED"
    assert results["address"].grade == "RED"

    date_precedents = cited_precedents_for_requirement(results["date"])
    address_precedents = cited_precedents_for_requirement(results["address"])

    date_case_nos = {p["case_no"] for p in date_precedents}
    address_case_nos = {p["case_no"] for p in address_precedents}

    assert _precedent("date_missing_day_invalid")["case_number"] in date_case_nos
    assert _precedent("address_missing_invalid")["case_number"] in address_case_nos
    # 격리 확인 — 서로의 판례가 섞이지 않는다.
    assert date_case_nos.isdisjoint(address_case_nos)


def test_cited_precedents_for_requirement_excludes_reference_note_ids() -> None:
    """예외 3건(카드로 안 만들기로 한 것)은 요건 단위에서도 여전히 제외된다."""
    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="signature_only",  # RED — fingerprint_seal_valid(예외) 포함
    )
    assert "fingerprint_seal_valid" in results["seal"].precedent_ids  # 전제 확인

    seal_precedents = cited_precedents_for_requirement(results["seal"])
    assert not any(p["case_no"] == "97다38510" for p in seal_precedents)


def test_requirement_body_has_no_precedent_citation_lines() -> None:
    """format_requirement_line(include_precedent_cards=False)로 만드는 요건별
    body에는 판례 인용 카드 줄이 없어야 한다 — precedents 배열과 중복 방지."""
    text = _will_text(_NAME_LINE, _DATE_LINE)  # 주소 없음(RED)
    results = check_requirements(
        text,
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
        address_envelope_answer="no_envelope",
    )
    line_with_cards = format_requirement_line(results["address"])
    line_without_cards = format_requirement_line(
        results["address"], include_precedent_cards=False
    )

    assert _CITATION_LINE_RE.search(line_with_cards)  # 전제 확인
    assert _CITATION_LINE_RE.search(line_without_cards) is None

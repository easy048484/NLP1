"""답변 품질 채점기(evals/quality/score.py)의 코드 검사가 실제로 잡아내는지.

LLM 심사는 호출하지 않는다. 1층 숫자 추적·2층 코드 규칙·3층 존댓말 판정이
조작된 답변을 실패로, 정상 답변을 통과로 판정하는지만 본다 — 채점기가 "다 통과"를
내는 것이 검사가 느슨해서가 아님을 보이는 용도.
"""

from __future__ import annotations

from evals.quality.score import (
    _boundary_code,
    _precedent_case_numbers,
    _tone_code,
    _trace_numbers,
)

_DATA = {
    "plan": {
        "death_date": "2026-09-23",
        "deadlines": [
            {"step": "death_report", "due_date": "2026-10-23"},
            {"step": "accept_or_renounce", "due_date": "2026-12-23"},
        ],
    }
}
_USER = ["아버지가 어제 돌아가셨어요. 예금은 8천만원 있어요."]
_CONSTANTS = "일괄공제 5억원, 세율 10%~50%, 상속개시일이 속한 달의 말일부터 6개월"


def test_trace_passes_when_numbers_come_from_user_data_or_constants():
    reply = "사망신고 기한은 2026년 10월 23일입니다. 예금 8,000만원은 일괄공제 5억원 이내입니다."
    out = _trace_numbers(
        reply, user_messages=_USER, session_facts=[_DATA], constants_text=_CONSTANTS
    )
    assert out["ok"], out
    assert out["facts_total"] >= 3


def test_trace_fails_on_fabricated_date_amount_percent():
    reply = "신고 기한은 2027년 1월 9일이고 예상 세액은 4,370만원, 세율은 37%입니다."
    out = _trace_numbers(
        reply, user_messages=_USER, session_facts=[_DATA], constants_text=_CONSTANTS
    )
    assert not out["ok"]
    assert {"2027년1월9일", "4370만원", "37%"} <= set(out["mismatches"])


def test_trace_accepts_notation_variants():
    """'2026-10-23' 이 data 에 있으면 '10월 23일' 표기도 인정(값 비교)."""
    reply = "사망신고는 10월 23일까지입니다."
    out = _trace_numbers(
        reply, user_messages=[], session_facts=[_DATA], constants_text=""
    )
    assert out["ok"], out


def test_boundary_catches_choice_recommendation_and_pii():
    reply = "빚이 많으니 한정승인을 추천드립니다. 문의는 010-1234-5678 로 주세요."
    rules = {
        v["rule"]
        for v in _boundary_code(
            "heir_navigator", reply, data={}, forbid_hit=[], precedents=set()
        )
    }
    assert "navigator:choice_recommendation" in rules
    assert "pii:전화번호" in rules
    assert "pii:계좌번호" not in rules  # 전화번호는 계좌번호로 중복 판정하지 않는다


def test_boundary_does_not_flag_consequence_explanation():
    """'단순승인한 것으로 볼 수 있으니 주의하세요' 는 결과 설명이지 추천이 아니다."""
    reply = "3개월이 지나면 단순승인한 것으로 볼 수 있으니, 재산 처분은 주의하세요."
    assert (
        _boundary_code(
            "heir_navigator", reply, data={}, forbid_hit=[], precedents=set()
        )
        == []
    )


def test_boundary_requires_disclaimer_when_deadlines_present():
    reply = "사망신고 기한은 2026년 10월 23일입니다."
    rules = {
        v["rule"]
        for v in _boundary_code(
            "heir_navigator", reply, data=_DATA, forbid_hit=[], precedents=set()
        )
    }
    assert "navigator:disclaimer_missing" in rules
    ok = reply + "\n\n안내 기준입니다. 확정 전 전문가에게 확인하세요."
    assert (
        _boundary_code(
            "heir_navigator", ok, data=_DATA, forbid_hit=[], precedents=set()
        )
        == []
    )


def test_boundary_flags_unverified_case_number():
    precedents = _precedent_case_numbers()
    assert precedents, "precedents.json 에 사건번호가 있어야 한다"
    known = next(iter(precedents))
    reply = f"대법원 {known} 판결과 2015다12345 판결이 있습니다."
    quotes = [
        v["quote"]
        for v in _boundary_code(
            "decedent_estate", reply, data={}, forbid_hit=[], precedents=precedents
        )
    ]
    assert quotes == ["2015다12345"]


def test_boundary_tax_requires_expert_note_when_amount_shown():
    reply = "예상 상속세는 4,370만원입니다."
    rules = {
        v["rule"]
        for v in _boundary_code(
            "tax_calculator", reply, data={}, forbid_hit=[], precedents=set()
        )
    }
    assert "tax:expert_check_missing" in rules
    assert (
        _boundary_code(
            "tax_calculator",
            reply + " 세무 전문가 확인이 필요합니다.",
            data={},
            forbid_hit=[],
            precedents=set(),
        )
        == []
    )


def test_tone_honorific_ignores_parenthetical_tail_and_label_lines():
    reply = (
        "기한은 2026년 10월 23일까지입니다(29일 남음).\n"
        "아직 말씀 안 하신 항목이 있어요: 펀드, 자동차.\n"
        "📞 무료로 확인받을 수 있는 곳: 대한법률구조공단 132.\n"
        "- 어디서: 주민센터\n"
    )
    out = _tone_code(reply)
    assert out["honorific_ratio"] == 1.0, out


def test_tone_honorific_fails_on_plain_style():
    reply = "사망신고를 해야 한다. 기한은 한 달이다. 서류를 챙겨라."
    out = _tone_code(reply)
    assert out["honorific_ratio"] == 0.0
    assert not out["honorific_ok"]

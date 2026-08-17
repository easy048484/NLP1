"""
성명 요건의 "정규식 우선 → 못 찾으면 LLM 폴백" 오케스트레이션 테스트.

requirement_checker.extract_testator_name 을 가짜로 바꿔치기해서 실제 네트워크
호출 없이: (1) 정규식이 성공하면 LLM을 아예 부르지 않는지, (2) 정규식이 실패한
"서울 강남구 거주 김영수" 같은 케이스가 LLM으로 해결되는지, (3) LLM도 실패하면
정직하게 absent(RED)로 남는지, (4) LLM에는 마스킹된 텍스트가 전달되는지를 확인한다.
"""

import pytest

from agents.decedent_estate import requirement_checker
from agents.decedent_estate.requirement_checker import check_requirements, extract_name_with_fallback

_NAME_LINE = "유언자: 홍길동"
_ADDRESS_LINE = "주소: 서울특별시 강남구 테헤란로 123, 45동 678호"
_DATE_LINE = "2026년 5월 3일"
_BODY = "나의 전 재산을 배우자에게 상속한다."


def _will_text(*lines: str) -> str:
    return "\n".join([*lines, "", _BODY])


def test_regex_success_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(requirement_checker, "extract_testator_name", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    result, method = extract_name_with_fallback(text)

    assert result.case == "present"
    assert result.raw_text == "홍길동"
    assert method == "regex"


def test_llm_fallback_resolves_name_buried_in_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    """"서울 강남구 거주 김영수" 처럼 라벨 없이 문장 속에 묻힌 이름 케이스."""
    monkeypatch.setattr(requirement_checker, "extract_testator_name", lambda masked_text: "김영수")

    text = "유언장\n내 명의 통장에 있는 돈은 모두 딸에게 준다.\n서울 강남구 거주 김영수"
    result, method = extract_name_with_fallback(text)

    assert result.case == "present"
    assert result.raw_text == "김영수"
    assert method == "llm"


def test_llm_fallback_failure_keeps_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(requirement_checker, "extract_testator_name", lambda masked_text: None)

    text_without_name = _will_text(_ADDRESS_LINE, _DATE_LINE)  # 이름 언급 자체가 없음
    result, method = extract_name_with_fallback(text_without_name)

    assert result.case == "absent"
    assert result.raw_text is None
    assert method == "none"


def test_llm_receives_masked_text_not_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM에는 주민등록번호 등이 마스킹된 텍스트가 전달돼야 한다 (CLAUDE.md 원칙 4)."""
    received: list[str] = []

    def _capture(masked_text: str):
        received.append(masked_text)
        return "김영수"

    monkeypatch.setattr(requirement_checker, "extract_testator_name", _capture)

    text = "유언장\n주민등록번호 901231-1234567\n서울 강남구 거주 김영수"
    extract_name_with_fallback(text)

    assert len(received) == 1
    assert "901231-1234567" not in received[0]
    assert "[주민등록번호]" in received[0]


def test_check_requirements_end_to_end_with_llm_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_requirements() 전체 파이프라인에서도 등급까지 정상적으로 이어지는지."""
    monkeypatch.setattr(requirement_checker, "extract_testator_name", lambda masked_text: "김영수")

    text = "유언장\n주소: 서울 강남구\n2026년 5월 3일\n서울 강남구 거주 김영수"
    results = check_requirements(text, handwriting_answer="yes", seal_answer="seal_or_fingerprint")

    assert results["name"].condition_id == "present"
    assert results["name"].grade == "GREEN"
    assert results["name"].extracted["raw_text"] == "김영수"
    assert results["name"].extracted["extraction_method"] == "llm"


def test_check_requirements_regex_hit_reports_regex_method(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_if_called(masked_text: str):
        raise AssertionError("정규식이 이미 찾았으면 LLM을 호출하면 안 된다")

    monkeypatch.setattr(requirement_checker, "extract_testator_name", _fail_if_called)

    text = _will_text(_NAME_LINE, _ADDRESS_LINE, _DATE_LINE)
    results = check_requirements(text)

    assert results["name"].extracted["extraction_method"] == "regex"

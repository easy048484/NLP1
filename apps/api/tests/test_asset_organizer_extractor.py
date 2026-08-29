"""
extractor.extract_financial_slots() 테스트.

기획서 4-3절 데모 시나리오 문장을 회귀 케이스로 쓴다. 실제 네트워크 호출은
절대 하지 않는다 — decedent_estate/tests/test_decedent_llm_client.py와 동일한
패턴으로 anthropic.Anthropic을 가짜로 바꿔치기한다.
"""

from __future__ import annotations

import json

import pytest

from agents.asset_organizer import extractor


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContent(text)]


class _FakeMessages:
    def __init__(
        self, *, text: str | None = None, exc: Exception | None = None
    ) -> None:
        self._text = text
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._text)


class _FakeAnthropicClient:
    def __init__(
        self, *, text: str | None = None, exc: Exception | None = None, **_kwargs
    ) -> None:
        self.messages = _FakeMessages(text=text, exc=exc)


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str | None = None,
    exc: Exception | None = None,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        extractor.anthropic,
        "Anthropic",
        lambda **kwargs: _FakeAnthropicClient(text=text, exc=exc),
    )


# ------------------------------------------------ 1) 데모 시나리오: 복합 발화


def test_house_deposit_and_insurance_in_one_sentence():
    """ "집 한 채, 예금 3천 정도, 보험도 하나요." (기획서 4-3절 데모 문장)

    - 예금 3천 -> 정규식만으로 3,000만원 확정
    - 집 한 채 -> 부동산으로 유형은 알아보지만 금액이 없어 Asset을 만들지
      않고 missing으로만 남긴다 (조용한 실패 금지 — Asset.value는 엔진
      계산에 직접 쓰이므로 임의로 0을 채우면 안 됨)
    - 보험도 하나요 -> 금액 없이도 InsuranceTag(value=0, note="금액 미언급")
      생성. 보험은 engine.py 계산에서 아예 제외되는 태그라 0이어도 안전함.
    """
    result = extractor.extract_financial_slots(
        "집 한 채, 예금 3천 정도, 보험도 하나요."
    )

    assert result.status == "needs_clarification"  # 부동산 금액 후속 질문 필요

    assert any(a.type == "예금" and a.value == 30_000_000 for a in result.assets)
    assert not any(a.type == "부동산" for a in result.assets)

    assert len(result.insurance_tags) == 1
    assert result.insurance_tags[0].type == "보험"
    assert result.insurance_tags[0].value == 0
    assert result.insurance_tags[0].note == "금액 미언급"

    assert any(
        m["kind"] == "asset_value" and m["asset_type"] == "부동산"
        for m in result.missing
    )


# ------------------------------------------------------- 2) 월 생활비 후속 답변


def test_monthly_expense_followup_answer_parses_amount():
    assert (
        extractor.parse_monthly_expense_answer("생활비는 200만원 정도예요.")
        == 2_000_000
    )


def test_monthly_expense_followup_answer_returns_none_when_unparseable():
    assert extractor.parse_monthly_expense_answer("글쎄요, 그때그때 달라요.") is None


# --------------------------------------- 3) 유형·금액 모두 불명확 -> 재질문 회귀


def test_fully_ambiguous_message_requires_clarification_without_silent_defaults(
    monkeypatch: pytest.MonkeyPatch,
):
    """ "돈이 좀 있어요" -> 유형도 금액도 알 수 없다. LLM 폴백도 실패한다고
    가정했을 때(키 없음) 0이나 빈 값으로 조용히 채워지지 않고 재질문으로
    가는지 확인한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = extractor.extract_financial_slots("돈이 좀 있어요")

    assert result.status == "needs_clarification"
    assert result.assets == []
    assert result.incomes == []
    assert result.insurance_tags == []
    assert any(m["kind"] == "unrecognized_segment" for m in result.missing)


def test_llm_exception_falls_back_to_clarification_not_silent_default(
    monkeypatch: pytest.MonkeyPatch,
):
    """LLM 호출 자체가 예외를 던져도(네트워크 오류 등) 예외가 새어나가지 않고
    재질문으로 수렴해야 한다."""
    _install_fake_llm(monkeypatch, exc=TimeoutError("network timeout"))

    result = extractor.extract_financial_slots("목돈이 좀 있어요")

    assert result.status == "needs_clarification"
    assert result.assets == []


def test_llm_fallback_resolves_segment_regex_could_not_classify(
    monkeypatch: pytest.MonkeyPatch,
):
    """ "목돈"은 키워드 사전에 없어 정규식이 유형을 못 잡는다 — LLM 폴백이
    성공하면 그 결과를 반영해야 한다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "assets": [{"type": "펀드", "value": 50_000_000}],
                "incomes": [],
                "insurance": [],
                "unclear": [],
            }
        ),
    )

    result = extractor.extract_financial_slots("굴리고 있는 목돈이 5천만원 정도 있어요")

    assert result.status == "ok"
    assert any(a.type == "펀드" and a.value == 50_000_000 for a in result.assets)


# ------------------------------------------------------ 4) 애매한 수치 표현


def test_vague_amount_expression_still_parses_via_regex():
    """ "한 3천쯤"처럼 근사치 표현이어도 정규식이 노이즈 단어("한", "쯤")를
    걷어내고 금액을 확정할 수 있어야 한다 — 이 경우는 재질문 없이 성공한다."""
    result = extractor.extract_financial_slots("예금이 한 3천쯤 있어요.")

    assert result.status == "ok"
    assert len(result.assets) == 1
    assert result.assets[0].type == "예금"
    assert result.assets[0].value == 30_000_000
    assert result.missing == []


def test_vague_amount_expression_without_recognizable_type_requires_clarification(
    monkeypatch: pytest.MonkeyPatch,
):
    """근사치 표현이라도 자산 유형 자체를 못 알아보면(키워드 없음) LLM 폴백을
    타고, 그마저 실패하면 재질문으로 간다 — "성공하거나 재질문하거나" 둘 중
    하나만 있고 조용한 0 처리는 없다는 걸 보여주는 대조군."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = extractor.extract_financial_slots("아무튼 한 3천쯤 있어요.")

    assert result.status == "needs_clarification"
    assert result.assets == []


# ------------------------------------------------------------- 5) 이미지 판독


def test_extract_from_image_success_parses_assets_liabilities_insurance(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [{"type": "예금", "value": 50_000_000}],
                "liabilities": [{"type": "대출", "remaining_balance": 20_000_000}],
                "insurance": [{"value": 10_000_000}],
                "unclear": [],
            }
        ),
    )

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert result.status == "ok"
    assert result.assets[0].type == "예금" and result.assets[0].value == 50_000_000
    assert result.insurance_tags[0].value == 10_000_000
    assert (
        liabilities[0].type == "대출" and liabilities[0].remaining_balance == 20_000_000
    )
    assert liability_missing == []


def test_extract_from_image_unreadable_flag_requires_clarification_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    """모델 스스로 "unreadable": true라고 답하면 추측 없이 재질문 대상으로
    수렴해야 한다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps({"unreadable": True, "assets": [], "unclear": ["흐릿함"]}),
    )

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert result.status == "needs_clarification"
    assert result.assets == []
    assert liabilities == []
    assert any(item["kind"] == "image_unreadable" for item in result.missing)


def test_extract_from_image_api_failure_requires_clarification_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    """네트워크 오류·타임아웃 등 어떤 이유로 호출이 실패해도 조용히 삼키지
    않고 image_unreadable로 수렴해야 한다."""
    _install_fake_llm(monkeypatch, exc=TimeoutError("network timeout"))

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert result.status == "needs_clarification"
    assert any(item["kind"] == "image_unreadable" for item in result.missing)


def test_extract_from_image_without_api_key_requires_clarification(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert result.status == "needs_clarification"
    assert any(item["kind"] == "image_unreadable" for item in result.missing)


def test_extract_from_image_liability_without_amount_is_flagged_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [],
                "liabilities": [{"type": "카드론"}],  # remaining_balance 없음
                "unclear": [],
            }
        ),
    )

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert liabilities == []
    assert liability_missing[0]["kind"] == "liability_value"
    assert liability_missing[0]["liability_type"] == "카드론"


def test_extract_from_image_rejects_liability_type_containing_pii(
    monkeypatch: pytest.MonkeyPatch,
):
    """모델이 프롬프트 지시를 무시하고 계좌번호·예금주명이 섞인 문자열을
    "type"에 채워 보내는 경우를 흉내낸다 — 은행 앱 스크린샷은 잔액 외에
    계좌번호·예금주명이 함께 찍혀 있는 경우가 흔해서 실제로 일어날 수 있는
    입력이다. 화이트리스트 밖 값은 조용히 건너뛰어야지, 그대로 통과시키면
    개인정보가 financial_profile.extra로 새어나간다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [],
                "liabilities": [
                    {
                        "type": "국민은행 대출(계좌 110-123-456789, 예금주 홍길동)",
                        "remaining_balance": 20_000_000,
                    },
                    {"type": "대출", "remaining_balance": 10_000_000},
                ],
                "unclear": [],
            }
        ),
    )

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    # 화이트리스트 안(대출/카드론/전세자금대출/기타)만 통과 — PII가 섞인
    # 항목은 조용히 건너뛰고, 정상 항목("대출")만 남는다.
    assert len(liabilities) == 1
    assert liabilities[0].type == "대출"
    assert liabilities[0].remaining_balance == 10_000_000
    assert not any("계좌" in liability.type for liability in liabilities)
    assert not any("홍길동" in liability.type for liability in liabilities)

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
    - 보험도 하나요 -> 유형은 알아보지만 금액이 없어 이제는 Asset/Liability와
      동일하게 즉시 InsuranceTag를 만들지 않고 missing(kind="insurance_value")
      으로만 남긴다 — agent.py가 한 번 후속 질문을 던진 뒤에야 확정한다.
    """
    result = extractor.extract_financial_slots(
        "집 한 채, 예금 3천 정도, 보험도 하나요."
    )

    assert result.status == "needs_clarification"  # 부동산·보험 금액 후속 질문 필요

    assert any(a.type == "예금" and a.value == 30_000_000 for a in result.assets)
    assert not any(a.type == "부동산" for a in result.assets)

    assert result.insurance_tags == []
    assert any(
        m["kind"] == "insurance_value" and m["asset_type"] == "보험"
        for m in result.missing
    )
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


# --------------------------------------------------- 4-2) 천 단위 콤마 (P0-3)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3,200만원", 32_000_000),
        ("1,020,000원", 1_020_000),
        ("5,000만원", 50_000_000),
        # 콤마 없는 기존 표현도 여전히 정상 동작해야 한다(회귀 방지).
        ("3200만원", 32_000_000),
        ("5000만원", 50_000_000),
    ],
)
def test_thousands_comma_parsed_as_single_number(text, expected):
    """실측 버그: "3,200만원"을 콤마 뒤 "200만원"(2,000,000원)으로만 읽고
    앞자리 "3,"를 통째로 날려버렸다 — 콤마가 천 단위 구분자일 뿐 세그먼트
    구분자가 아니라는 걸 반영해 하나의 숫자로 합쳐 읽어야 한다."""
    assert extractor._parse_amount(text) == expected


def test_thousands_comma_amount_flows_through_full_extraction():
    result = extractor.extract_financial_slots("예금 3,200만원 있어요")

    assert result.status == "ok"
    assert result.assets[0].type == "예금"
    assert result.assets[0].value == 32_000_000


# ---------------------------------------- 4-3) 천/백 혼합·공백 변형 (Round 15)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3,200만원", 32_000_000),
        ("3,200만 원", 32_000_000),
        ("3200만원", 32_000_000),
        ("3천200만원", 32_000_000),
        ("3천200만", 32_000_000),
        ("3천 200만원", 32_000_000),
        ("3천 200만 원", 32_000_000),
        ("3천2백만원", 32_000_000),
        ("3천2백만 원", 32_000_000),
        # 이 둘은 위 항목들과 의미가 다른 별개 금액(320만원이 아니라
        # 3,200,000원/32,000,000원 그 자체) — 콤마가 순수 원단위 표기에서도
        # 안 잘리는지 확인하는 대조군.
        ("3,200,000원", 3_200_000),
        ("32,000,000원", 32_000_000),
    ],
)
def test_demo_amount_expressions_parsed_consistently(text, expected):
    """데모에서 실제로 쓰이는 "3,200만원" 의미의 모든 표현(천/백 혼합 단위,
    공백 유무)이 같은 값으로 파싱되는지 확인하는 회귀 테스트(Round 15)."""
    assert extractor._parse_amount(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("예금 3천200만원 있어요", 32_000_000),
        ("예금 3천 200만 원 있어요", 32_000_000),
        ("예금 3천2백만원 있어요", 32_000_000),
    ],
)
def test_demo_amount_expressions_flow_through_full_extraction(text, expected):
    """parser 단위 테스트뿐 아니라 실제 agent 입력 경로(extract_financial_slots)
    까지 통과시켜 최종 저장 금액이 맞는지 확인(Round 15)."""
    result = extractor.extract_financial_slots(text)

    assert result.status == "ok"
    assert result.assets[0].type == "예금"
    assert result.assets[0].value == expected


# ------------------------------------------- 4-4) 부정 표현 오탐 (Round 15 B5)


@pytest.mark.parametrize(
    "text,expected_kind,type_key,type_value",
    [
        ("예금은 없어요", "asset_absent", "asset_type", "예금"),
        ("예금 없어요", "asset_absent", "asset_type", "예금"),
    ],
)
def test_negated_asset_segment_marked_absent_not_missing_value(
    text, expected_kind, type_key, type_value
):
    """실측 재현된 버그(Round 15): "예금은 없어요"가 "예금 유형은 확인됐지만
    금액을 모른다"(asset_value)로 잘못 분류돼 방금 없다고 답한 예금의 금액을
    재질문했다. 부정 표현이 같이 있으면 asset_absent로 구분해야 한다."""
    result = extractor.extract_financial_slots(text)

    assert result.assets == []
    assert len(result.missing) == 1
    assert result.missing[0]["kind"] == expected_kind
    assert result.missing[0][type_key] == type_value


@pytest.mark.parametrize("text", ["대출은 없어요", "대출 없어요"])
def test_negated_liability_segment_marked_absent_not_missing_value(text):
    """extract_liabilities의 같은 클래스 버그 — "대출은 없어요"가 대출 존재를
    확정하고 금액만 되묻던 걸(liability_value) liability_absent로 구분."""
    liabilities, missing = extractor.extract_liabilities(text)

    assert liabilities == []
    assert len(missing) == 1
    assert missing[0]["kind"] == "liability_absent"
    assert missing[0]["liability_type"] == "대출"


# --------------------------------------- 4-5) 나열 범위 부정 표현 (D-01)


def _absent_types(result: extractor.ExtractionResult) -> set[str]:
    return {
        item["asset_type"] for item in result.missing if item["kind"] == "asset_absent"
    }


def _value_missing_types(result: extractor.ExtractionResult) -> set[str]:
    return {
        item["asset_type"] for item in result.missing if item["kind"] == "asset_value"
    }


def test_comma_list_trailing_negation_marks_every_listed_type_absent():
    """실측 재현된 버그(D-01): "주식, 펀드, 자동차, 퇴직연금, 보험은
    없어요."에서 쉼표로 나열된 앞 항목들("주식","펀드","자동차","퇴직연금")은
    자기 세그먼트에 부정 표현이 없어(맨 명사 나열) "유형은 확인, 금액만
    모름"으로 잘못 분류되고 금액을 무한 재질문했다. 나열 끝의 "보험은
    없어요"가 나열 전체에 걸리는 부정임을 인식해야 한다 — "보험"도
    asset_absent로 걸려야 한다(이번 라운드에서 함께 고친 지점: 예전엔
    부정된 보험도 InsuranceTag(value=0)로 잘못 확정됐었다, 아래 참고)."""
    result = extractor.extract_financial_slots(
        "주식, 펀드, 자동차, 퇴직연금, 보험은 없어요."
    )

    assert result.assets == []
    assert _absent_types(result) == {"주식", "펀드", "자동차", "퇴직연금", "보험"}
    assert _value_missing_types(result) == set()
    assert result.insurance_tags == []


def test_and_conjunction_negation_marks_both_types_absent():
    """ "주식과 펀드는 없어요."는 쉼표 없이 한 세그먼트에 유형 두 개가
    같이 있다 — 기존 _match_asset_type(첫 매칭만 반환)로는 두 번째 유형을
    놓쳤다."""
    result = extractor.extract_financial_slots("주식과 펀드는 없어요.")

    assert result.assets == []
    assert _absent_types(result) == {"주식", "펀드"}


def test_first_item_negated_second_item_has_amount_in_one_segment():
    """ "주식은 없고 펀드는 1000만원" — "없고"로 이어진 한 문장에 부정된
    유형과 금액이 있는 유형이 섞여 있다. "없고" 분리 없이는 전체가 한
    세그먼트로 남아 펀드의 금액이 주식에 잘못 배정됐다."""
    result = extractor.extract_financial_slots("주식은 없고 펀드는 1000만원")

    assert result.assets == [extractor.Asset(type="펀드", value=10_000_000)]
    assert _absent_types(result) == {"주식"}


def test_amount_then_comma_then_negated_type_only_negates_the_second():
    """ "주식 1000만원, 펀드는 없어요" — 대조군: 앞 항목이 확정 금액을
    가지므로 나열 부정 전파 로직이 여기까지 거슬러 올라가면 안 된다."""
    result = extractor.extract_financial_slots("주식 1000만원, 펀드는 없어요")

    assert result.assets == [extractor.Asset(type="주식", value=10_000_000)]
    assert _absent_types(result) == {"펀드"}


def test_bare_list_without_trailing_predicate_falls_back_to_value_missing():
    """나열이 부정으로 끝나지 않고 문장이 끝나면(서술어 없음) 기존처럼
    개별 금액 재질문 대상으로 남아야 한다 — 조용히 흡수되거나 absent로
    잘못 확정되면 안 된다."""
    result = extractor.extract_financial_slots("주식, 펀드")

    assert result.assets == []
    assert _absent_types(result) == set()
    assert _value_missing_types(result) == {"주식", "펀드"}


def test_single_bare_type_mention_still_asks_amount_normally():
    """단건 "집 한 채 있어요"(서술어 있음, 부정 아님)는 이번 수정과 무관하게
    기존처럼 금액 재질문 대상이어야 한다(회귀 방지)."""
    result = extractor.extract_financial_slots("집 한 채 있어요")

    assert result.assets == []
    assert _value_missing_types(result) == {"부동산"}
    assert _absent_types(result) == set()


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


def test_extract_from_image_liability_type_with_pii_is_kept_as_gita_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
):
    """모델이 프롬프트 지시를 무시하고 계좌번호·예금주명이 섞인 문자열을
    "type"에 채워 보내는 경우를 흉내낸다 — 은행 앱 스크린샷은 잔액 외에
    계좌번호·예금주명이 함께 찍혀 있는 경우가 흔해서 실제로 일어날 수 있는
    입력이다.

    화이트리스트 밖의 오염된 원문 문자열은 버리지만, 부채 항목 자체(금액이
    정상이면)까지 통째로 드롭하면 안 된다 — 그러면 실제로 있는 부채가
    사용자 재무 상태에서 사라져 순자산이 실제보다 좋아 보이게 왜곡된다.
    "기타"(이미 검증된 정상 카테고리)로 보존해야 한다."""
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

    assert len(liabilities) == 2  # 둘 다 보존됨 — 부채 자체는 사라지지 않는다
    assert not any("계좌" in liability.type for liability in liabilities)
    assert not any("홍길동" in liability.type for liability in liabilities)

    tainted = next(
        liability
        for liability in liabilities
        if liability.remaining_balance == 20_000_000
    )
    assert tainted.type == "기타"  # 오염된 원문 대신 정상 카테고리로 대체

    normal = next(
        liability
        for liability in liabilities
        if liability.remaining_balance == 10_000_000
    )
    assert normal.type == "대출"


def test_extract_from_image_lease_deposit_liability_type_passes_whitelist(
    monkeypatch: pytest.MonkeyPatch,
):
    """_VALID_LIABILITY_TYPES는 _LIABILITY_KEYWORDS.keys()에서 자동
    파생되지만, 이미지 판독 검증(_apply_llm_liabilities)이 실제로 그
    목록을 보고 새 부채 유형을 정상 값으로 통과시키는지("기타"로
    뭉개지지 않는지)는 회귀로 따로 고정해둔다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [],
                "liabilities": [
                    {"type": "임대보증금반환채무", "remaining_balance": 200_000_000}
                ],
                "unclear": [],
            }
        ),
    )

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert liability_missing == []
    assert liabilities[0].type == "임대보증금반환채무"
    assert liabilities[0].remaining_balance == 200_000_000


def test_extract_from_image_vehicle_and_pension_assets_recognized(
    monkeypatch: pytest.MonkeyPatch,
):
    """_VALID_ASSET_TYPES는 _ASSET_KEYWORDS.keys()에서 자동 파생되지만,
    이미지 판독 경로(_apply_llm_payload)가 실제로 그 목록을 보고 새
    자산 유형을 정상 값으로 통과시키는지(=자동차/퇴직연금이 "기타"로
    뭉개지지 않는지)는 회귀로 따로 고정해둬야 한다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "unreadable": False,
                "assets": [
                    {"type": "자동차", "value": 30_000_000},
                    {"type": "퇴직연금", "value": 80_000_000},
                ],
                "liabilities": [],
                "insurance": [],
                "unclear": [],
            }
        ),
    )

    result, liabilities, liability_missing = extractor.extract_from_image(
        "base64-image-data", "image/png"
    )

    assert result.status == "ok"
    assert any(a.type == "자동차" and a.value == 30_000_000 for a in result.assets)
    assert any(a.type == "퇴직연금" and a.value == 80_000_000 for a in result.assets)


def test_llm_fallback_asset_type_with_pii_is_kept_as_gita_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
):
    """_apply_llm_payload()는 extract_from_image()와 extract_financial_slots()
    LLM 폴백 양쪽이 공유한다 — 부채와 동일한 이유로, 화이트리스트 밖 자산
    유형도 통째로 드롭하면 안 되고 "기타"로 보존해야 한다(드롭하면 실제
    자산이 사라져 순자산이 실제보다 적어 보이게 왜곡됨)."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "assets": [
                    {
                        "type": "국민은행 예금(계좌 110-123-456789, 홍길동)",
                        "value": 30_000_000,
                    }
                ],
                "incomes": [],
                "insurance": [],
                "unclear": [],
            }
        ),
    )

    result = extractor.extract_financial_slots("목돈이 좀 있어요")

    assert len(result.assets) == 1
    assert result.assets[0].type == "기타"
    assert result.assets[0].value == 30_000_000
    assert not any("계좌" in a.type for a in result.assets)


def test_vehicle_and_pension_recognized_by_regex_without_llm_fallback():
    """자동차/퇴직연금은 키워드 사전에 있으니 LLM 폴백 없이 정규식만으로
    확정돼야 한다 — API 키가 없어도(delenv) 성공해야 함을 확인한다."""
    result = extractor.extract_financial_slots(
        "자동차 3천만원, 퇴직연금 8천만원 있어요"
    )

    assert result.status == "ok"
    assert any(a.type == "자동차" and a.value == 30_000_000 for a in result.assets)
    assert any(a.type == "퇴직연금" and a.value == 80_000_000 for a in result.assets)


def test_lease_deposit_liability_recognized_by_regex():
    liabilities, missing = extractor.extract_liabilities(
        "임대보증금 반환채무 2억 있어요"
    )

    assert any(
        liability.type == "임대보증금반환채무"
        and liability.remaining_balance == 200_000_000
        for liability in liabilities
    )
    assert missing == []


def test_new_asset_types_are_automatically_covered_by_pii_whitelist():
    """_VALID_ASSET_TYPES는 _ASSET_KEYWORDS.keys()에서 자동 파생되므로,
    새 자산 유형을 키워드 사전에 추가하기만 하면 별도 코드 수정 없이
    화이트리스트 방어(LLM payload 검증)에도 자동으로 포함돼야 한다."""
    assert "자동차" in extractor._VALID_ASSET_TYPES
    assert "퇴직연금" in extractor._VALID_ASSET_TYPES


def test_new_liability_types_are_automatically_covered_by_pii_whitelist():
    """_VALID_LIABILITY_TYPES도 이제 자산 쪽과 같은 패턴으로
    _LIABILITY_KEYWORDS.keys()에서 자동 파생된다 — 새 부채 유형을 키워드
    사전에 추가하기만 하면 별도로 화이트리스트 튜플을 손으로 갱신하지
    않아도 이미지 판독 검증에 자동으로 포함돼야 한다."""
    assert "임대보증금반환채무" in extractor._VALID_LIABILITY_TYPES
    assert set(extractor._VALID_LIABILITY_TYPES) == {
        *extractor._LIABILITY_KEYWORDS.keys(),
        "기타",
    }


def test_llm_fallback_income_type_outside_whitelist_is_kept_as_gita_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "assets": [],
                "incomes": [{"type": "퇴직연금", "monthly": 500_000, "start_age": 65}],
                "insurance": [],
                "unclear": [],
            }
        ),
    )

    result = extractor.extract_financial_slots("목돈이 좀 있어요")

    assert len(result.incomes) == 1
    assert result.incomes[0].type == "기타"
    assert result.incomes[0].monthly == 500_000
    assert result.incomes[0].start_age == 65


# ------------------------------------------- 6) 사후 모드: 다기관 조회 결과 해석


def test_disclosures_split_confirmed_and_unknown_amount_by_institution(
    monkeypatch: pytest.MonkeyPatch,
):
    """기획서 패턴 그대로: 기관마다 공개 수준이 다르다 — 예금은 금액까지,
    투자상품(증권)은 계좌만(잔고 유무만) 확인되는 식. 기관명 자체는
    결과에 안 담긴다(수집 최소화 원칙, extract_from_image()와 동일)."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "disclosures": [
                    {"type": "예금", "confidence": "confirmed", "value": 50_000_000},
                    {"type": "주식", "confidence": "unknown_amount", "value": None},
                ]
            }
        ),
    )

    items = extractor.extract_disclosures(
        "OO은행은 예금 5천만원까지 나왔고 OO증권은 계좌만 확인됐어요"
    )

    assert items is not None
    assert len(items) == 2
    confirmed = next(i for i in items if i.confidence == "confirmed")
    assert confirmed.asset_type == "예금"
    assert confirmed.value == 50_000_000
    unknown = next(i for i in items if i.confidence == "unknown_amount")
    assert unknown.asset_type == "주식"
    assert unknown.value is None

    # DisclosureItem에는 institution 필드 자체가 없다 — dataclass 필드
    # 목록으로 직접 확인(우연히 통과하는 게 아니라 구조적으로 없다는 것).
    from dataclasses import fields

    field_names = {f.name for f in fields(extractor.DisclosureItem)}
    assert "institution" not in field_names
    assert field_names == {"asset_type", "confidence", "value"}


def test_disclosures_confirmed_without_valid_value_downgrades_to_unknown_amount(
    monkeypatch: pytest.MonkeyPatch,
):
    """모델이 지시를 무시하고 confirmed인데 값을 안 채우거나 이상한 값을
    보내면, 금액을 지어내지 않고 안전한 쪽(unknown_amount)으로 강등한다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "disclosures": [
                    {"type": "부동산", "confidence": "confirmed", "value": None},
                ]
            }
        ),
    )

    items = extractor.extract_disclosures("부동산은 금액까지 나왔어요")

    assert items[0].confidence == "unknown_amount"
    assert items[0].value is None


def test_disclosures_ambiguous_confidence_falls_back_to_unknown_amount(
    monkeypatch: pytest.MonkeyPatch,
):
    """confidence 값 자체가 화이트리스트 밖("unclear" 등)이면 애매한 쪽으로
    본다 — 안전한 기본값(unknown_amount)으로 떨어진다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "disclosures": [
                    {"type": "보험", "confidence": "maybe", "value": 10_000_000},
                ]
            }
        ),
    )

    items = extractor.extract_disclosures("보험은 가입 여부만 확인됐어요")

    assert items[0].confidence == "unknown_amount"
    assert items[0].value is None


def test_disclosures_type_outside_whitelist_kept_as_gita_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
):
    """자산 추출과 동일한 PII 방어 원칙 — 화이트리스트 밖 유형(오염
    가능성 있는 원문)은 드롭하지 않고 "기타"로 보존한다."""
    _install_fake_llm(
        monkeypatch,
        text=json.dumps(
            {
                "disclosures": [
                    {
                        "type": "국민은행 예금(계좌 110-123-456789)",
                        "confidence": "confirmed",
                        "value": 10_000_000,
                    },
                ]
            }
        ),
    )

    items = extractor.extract_disclosures("어떤 조회 결과 문장")

    assert items[0].asset_type == "기타"
    assert not any("계좌" in str(v) for v in items[0].__dict__.values())


def test_disclosures_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch):
    """LLM을 쓸 수 없으면 None을 돌려준다 — 호출부(agent.py)가 이 신호를
    보고 기존 일반 추출 경로로 폴백한다(조용히 빈 결과로 확정하지 않음)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert extractor.extract_disclosures("아무 문장") is None


def test_disclosures_returns_none_on_llm_failure(monkeypatch: pytest.MonkeyPatch):
    _install_fake_llm(monkeypatch, exc=TimeoutError("network timeout"))

    assert extractor.extract_disclosures("아무 문장") is None


def test_disclosures_prompt_instructs_excluding_institution_names():
    """수집 최소화 원칙이 프롬프트에 실제로 박혀 있는지 — 나중에 문구가
    실수로 빠지는 걸 막는 회귀 잠금."""
    prompt = extractor._build_disclosure_system_prompt()
    assert "은행" in prompt and "결과에 포함하지 마라" in prompt


# ==================== "빚" 포괄 상담 의도 vs 실제 부채 존재 오탐 (실측 재현)


def test_generic_organize_intent_with_bit_keyword_is_not_treated_as_liability():
    """실측 재현된 버그: 사후 모드 첫 턴에서 "재산이랑 빚을 정리해두려고
    해요"라고만 말해도 "빚" 키워드가 대출 존재로 잡혀 곧바로 대출 금액을
    되물었다 — 구체적 보유 항목이 없는 포괄적 상담 의도일 뿐이다."""
    liabilities, missing = extractor.extract_liabilities(
        "어머니가 돌아가셔서 재산이랑 빚을 한번 정리해두려고 해요."
    )
    assert liabilities == []
    assert missing == []


@pytest.mark.parametrize(
    "text",
    [
        "재산이랑 빚 정리하고 싶어요",
        "자산과 부채를 확인하고 싶어요",
        "재산이랑 빚을 정리해볼까 해요",
    ],
)
def test_various_generic_organize_intent_phrasings_find_no_liability(text: str):
    liabilities, missing = extractor.extract_liabilities(text)
    assert liabilities == []
    assert missing == []


def test_bit_keyword_with_explicit_amount_still_confirms_liability():
    """ "빚이 4천만원 있어요"처럼 금액까지 말하면 포괄 의도 가드와 무관하게
    그대로 확정돼야 한다 — 회귀 방지 불변식."""
    liabilities, missing = extractor.extract_liabilities("빚이 4천만원 있어요")
    assert len(liabilities) == 1
    assert liabilities[0].type == "대출"
    assert liabilities[0].remaining_balance == 40_000_000
    assert missing == []


def test_bit_keyword_with_existence_verb_still_asks_amount_even_with_organize_intent():
    """ "빚이 좀 있는데 정리하고 싶어요"처럼 존재를 실제로 진술하는 구절이
    같이 있으면, 포괄 의도 표현이 섞여 있어도 억제하지 않는다 — 금액
    되묻기 대상으로 남아야 한다."""
    liabilities, missing = extractor.extract_liabilities(
        "빚이 좀 있는데 정리하고 싶어요"
    )
    assert liabilities == []
    assert missing == [
        {
            "kind": "liability_value",
            "liability_type": "대출",
            "segment": "빚이 좀 있는데 정리하고 싶어요",
            "reason": "대출 금액이 언급되지 않음",
        }
    ]


@pytest.mark.parametrize(
    ("text", "expected_kind"),
    [
        ("대출이 있어요", "liability_value"),
        ("카드대출이 남아 있어요", "liability_value"),
        ("대출은 없어요", "liability_absent"),
    ],
)
def test_specific_loan_keywords_are_unaffected_by_bit_generic_intent_guard(
    text: str, expected_kind: str
):
    """ "대출"/"카드론" 등 구체적 금융상품 명사는 "빚"과 달리 포괄 의도
    가드의 영향을 받지 않는다 — 기존 동작 그대로 유지되는지 확인하는
    회귀 잠금."""
    liabilities, missing = extractor.extract_liabilities(text)
    assert liabilities == []
    assert missing[0]["kind"] == expected_kind

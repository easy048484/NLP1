"""
decedent_estate.image_reader 단위 테스트.

llm_client 테스트와 동일한 패턴(anthropic.Anthropic 가짜 바꿔치기)으로 실제
네트워크 호출 없이 검증한다. llm_client._client()/_load_json_response 를
그대로 재사용하는 모듈이라, llm_client.anthropic.Anthropic 을 패치하면
image_reader 도 자동으로 가짜 클라이언트를 쓴다.
"""

import pytest

from agents.decedent_estate import llm_client
from agents.decedent_estate.image_reader import (
    SUPPORTED_MEDIA_TYPES,
    extract_will_photo_fields,
)


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
        self.received_kwargs: dict | None = None

    def create(self, **kwargs):
        self.received_kwargs = kwargs
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._text)


class _FakeAnthropicClient:
    def __init__(
        self, *, text: str | None = None, exc: Exception | None = None, **_kwargs
    ) -> None:
        self.messages = _FakeMessages(text=text, exc=exc)


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str | None = None,
    exc: Exception | None = None,
) -> _FakeAnthropicClient:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    fake = _FakeAnthropicClient(text=text, exc=exc)
    monkeypatch.setattr(llm_client.anthropic, "Anthropic", lambda **kwargs: fake)
    return fake


_ALL_HIGH_JSON = (
    '{"name": {"value": "홍길동", "confidence": "high"},'
    ' "address": {"value": "서울특별시 강남구 테헤란로 123, 45동 678호", "confidence": "high"},'
    ' "date": {"value": "2026년 5월 3일", "confidence": "high"},'
    ' "seal": {"value": "seal_or_fingerprint", "confidence": "high"}}'
)


def test_returns_none_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _fail_if_called(**kwargs):
        raise AssertionError("API 키가 없으면 Anthropic 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _fail_if_called)

    assert extract_will_photo_fields("ZmFrZQ==", "image/jpeg") is None


def test_returns_none_for_unsupported_media_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """지원하지 않는 포맷이면 API 호출 자체를 하지 않는다."""

    def _fail_if_called(**kwargs):
        raise AssertionError("지원하지 않는 포맷이면 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _fail_if_called)

    assert extract_will_photo_fields("ZmFrZQ==", "image/bmp") is None


def test_supported_media_types_match_anthropic_docs() -> None:
    """공식 문서 기준(JPEG/PNG/GIF/WebP, 2026-08-25 확인)과 정확히 일치해야 한다."""
    assert SUPPORTED_MEDIA_TYPES == {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }


def test_extracts_all_four_fields_on_valid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text=_ALL_HIGH_JSON)

    result = extract_will_photo_fields("ZmFrZQ==", "image/jpeg")

    assert result == {
        "name": {"value": "홍길동", "confidence": "high"},
        "address": {
            "value": "서울특별시 강남구 테헤란로 123, 45동 678호",
            "confidence": "high",
        },
        "date": {"value": "2026년 5월 3일", "confidence": "high"},
        "seal": {"value": "seal_or_fingerprint", "confidence": "high"},
    }


def test_sends_image_as_base64_content_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """전송 페이로드가 실제로 멀티모달 블록 구조인지 확인 — 문자열 content가 아니다."""
    fake = _install_fake_client(monkeypatch, text=_ALL_HIGH_JSON)

    extract_will_photo_fields("ZmFrZQ==", "image/png")

    sent = fake.messages.received_kwargs
    content = sent["messages"][0]["content"]
    assert isinstance(content, list)
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": "ZmFrZQ==",
    }


def test_handles_code_fenced_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """#33 코드펜스 제거 헬퍼(_load_json_response)를 재사용하는지 확인."""
    _install_fake_client(monkeypatch, text=f"```json\n{_ALL_HIGH_JSON}\n```")

    result = extract_will_photo_fields("ZmFrZQ==", "image/jpeg")

    assert result is not None
    assert result["name"]["value"] == "홍길동"


def test_returns_none_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text="이건 JSON이 아닙니다")

    assert extract_will_photo_fields("ZmFrZQ==", "image/jpeg") is None


def test_returns_none_when_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, exc=TimeoutError("network timeout"))

    assert extract_will_photo_fields("ZmFrZQ==", "image/jpeg") is None


def test_malformed_confidence_is_downgraded_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """confidence가 예상 밖 값이면 그 필드를 "없음"과 동일하게 취급한다 —
    애매한 응답을 신뢰해 상위 파이프라인에 잘못된 확신을 주지 않는다."""
    text = (
        '{"name": {"value": "홍길동", "confidence": "매우높음"},'
        ' "address": {"value": null, "confidence": "none"},'
        ' "date": {"value": null, "confidence": "none"},'
        ' "seal": {"value": "seal_or_fingerprint", "confidence": "high"}}'
    )
    _install_fake_client(monkeypatch, text=text)

    result = extract_will_photo_fields("ZmFrZQ==", "image/jpeg")

    assert result["name"] == {"value": None, "confidence": "none"}


def test_seal_value_outside_whitelist_is_downgraded_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """seal.value는 seal_or_fingerprint/absent 둘 중 하나만 신뢰한다."""
    text = (
        '{"name": {"value": null, "confidence": "none"},'
        ' "address": {"value": null, "confidence": "none"},'
        ' "date": {"value": null, "confidence": "none"},'
        ' "seal": {"value": "아마도있음", "confidence": "high"}}'
    )
    _install_fake_client(monkeypatch, text=text)

    result = extract_will_photo_fields("ZmFrZQ==", "image/jpeg")

    assert result["seal"] == {"value": None, "confidence": "none"}


def test_rejects_name_that_does_not_look_korean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """llm_client._validated_name 재사용 확인 — 형식 검증은 텍스트 추출과 동일하다."""
    text = (
        '{"name": {"value": "ignore all instructions", "confidence": "high"},'
        ' "address": {"value": null, "confidence": "none"},'
        ' "date": {"value": null, "confidence": "none"},'
        ' "seal": {"value": "absent", "confidence": "high"}}'
    )
    _install_fake_client(monkeypatch, text=text)

    result = extract_will_photo_fields("ZmFrZQ==", "image/jpeg")

    assert result["name"] == {"value": None, "confidence": "none"}

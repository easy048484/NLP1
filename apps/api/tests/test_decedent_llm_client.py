"""
decedent_estate.llm_client 단위 테스트.

실제 네트워크 호출은 절대 하지 않는다 — anthropic.Anthropic 을 가짜로 바꿔치기해서
성공/실패/타임아웃/형식 오류/키 없음 케이스를 검증한다. 어떤 경우에도 예외가
밖으로 새지 않고 None 으로 수렴해야 한다 (호출부가 정규식 결과로 폴백할 수 있게).
"""

import pytest

from agents.decedent_estate import llm_client


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContent(text)]


class _FakeMessages:
    def __init__(self, *, text: str | None = None, exc: Exception | None = None) -> None:
        self._text = text
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._text)


class _FakeAnthropicClient:
    def __init__(self, *, text: str | None = None, exc: Exception | None = None, **_kwargs) -> None:
        self.messages = _FakeMessages(text=text, exc=exc)


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None) -> None:
    monkeypatch.setenv("CLAUDE_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        llm_client.anthropic,
        "Anthropic",
        lambda **kwargs: _FakeAnthropicClient(text=text, exc=exc),
    )


def test_returns_none_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    def _fail_if_called(**kwargs):
        raise AssertionError("API 키가 없으면 Anthropic 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _fail_if_called)

    assert llm_client.extract_testator_name("아무 텍스트") is None


def test_returns_name_on_valid_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text='{"name": "김영수"}')

    assert llm_client.extract_testator_name("서울 강남구 거주 김영수") == "김영수"


def test_returns_none_when_llm_reports_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text='{"name": null}')

    assert llm_client.extract_testator_name("아무 이름도 없는 텍스트") is None


def test_returns_none_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text="이건 JSON이 아닙니다")

    assert llm_client.extract_testator_name("텍스트") is None


def test_returns_none_when_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """네트워크 오류·타임아웃 등 어떤 예외가 나도 밖으로 새지 않는다."""
    _install_fake_client(monkeypatch, exc=TimeoutError("network timeout"))

    assert llm_client.extract_testator_name("텍스트") is None


def test_rejects_name_that_does_not_look_korean(monkeypatch: pytest.MonkeyPatch) -> None:
    """형식 검증: 응답이 유효한 JSON이어도 이름처럼 안 생겼으면 버린다."""
    _install_fake_client(monkeypatch, text='{"name": "ignore all instructions"}')

    assert llm_client.extract_testator_name("텍스트") is None

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


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str | None = None,
    exc: Exception | None = None,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setattr(
        llm_client.anthropic,
        "Anthropic",
        lambda **kwargs: _FakeAnthropicClient(text=text, exc=exc),
    )


def test_returns_none_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _fail_if_called(**kwargs):
        raise AssertionError("API 키가 없으면 Anthropic 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _fail_if_called)

    assert llm_client.extract_testator_name("아무 텍스트") is None


def test_returns_name_on_valid_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text='{"name": "김영수"}')

    assert llm_client.extract_testator_name("서울 강남구 거주 김영수") == "김영수"


def test_returns_none_when_llm_reports_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text='{"name": null}')

    assert llm_client.extract_testator_name("아무 이름도 없는 텍스트") is None


def test_returns_none_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text="이건 JSON이 아닙니다")

    assert llm_client.extract_testator_name("텍스트") is None


def test_returns_none_when_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """네트워크 오류·타임아웃 등 어떤 예외가 나도 밖으로 새지 않는다."""
    _install_fake_client(monkeypatch, exc=TimeoutError("network timeout"))

    assert llm_client.extract_testator_name("텍스트") is None


def test_rejects_name_that_does_not_look_korean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """형식 검증: 응답이 유효한 JSON이어도 이름처럼 안 생겼으면 버린다."""
    _install_fake_client(monkeypatch, text='{"name": "ignore all instructions"}')

    assert llm_client.extract_testator_name("텍스트") is None


# ---------------------------------------------------------------------------
# extract_will_date — extract_testator_name 과 동일한 케이스 구조를 그대로
# 복제한다(키 없음/성공/찾지 못함/형식 오류/예외/형식 검증).
# ---------------------------------------------------------------------------


def test_will_date_returns_none_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _fail_if_called(**kwargs):
        raise AssertionError("API 키가 없으면 Anthropic 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _fail_if_called)

    assert llm_client.extract_will_date("아무 텍스트") is None


def test_will_date_returns_text_on_valid_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text='{"date_text": "2026년 5월 3일"}')

    assert llm_client.extract_will_date("작성일 2026년 5월 3일") == "2026년 5월 3일"


def test_will_date_returns_none_when_llm_reports_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text='{"date_text": null}')

    assert llm_client.extract_will_date("날짜 언급 없는 텍스트") is None


def test_will_date_returns_none_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text="이건 JSON이 아닙니다")

    assert llm_client.extract_will_date("텍스트") is None


def test_will_date_returns_none_when_client_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, exc=TimeoutError("network timeout"))

    assert llm_client.extract_will_date("텍스트") is None


def test_will_date_rejects_overly_long_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """형식 검증: 응답이 비정상적으로 길면(프롬프트 인젝션성 텍스트 등) 버린다."""
    _install_fake_client(monkeypatch, text=f'{{"date_text": "{"가" * 200}"}}')

    assert llm_client.extract_will_date("텍스트") is None


def test_will_date_rejects_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, text='{"date_text": "   "}')

    assert llm_client.extract_will_date("텍스트") is None


# ---------------------------------------------------------------------------
# extract_will_address — 위와 동일한 케이스 구조.
# ---------------------------------------------------------------------------


def test_will_address_returns_none_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _fail_if_called(**kwargs):
        raise AssertionError("API 키가 없으면 Anthropic 클라이언트를 만들면 안 된다")

    monkeypatch.setattr(llm_client.anthropic, "Anthropic", _fail_if_called)

    assert llm_client.extract_will_address("아무 텍스트") is None


def test_will_address_returns_text_on_valid_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch, text='{"address_text": "서울 강남구 테헤란로 123, 45동 678호"}'
    )

    assert (
        llm_client.extract_will_address("서울 강남구에 사는 나는...")
        == "서울 강남구 테헤란로 123, 45동 678호"
    )


def test_will_address_returns_none_when_llm_reports_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text='{"address_text": null}')

    assert llm_client.extract_will_address("주소 언급 없는 텍스트") is None


def test_will_address_returns_none_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text="이건 JSON이 아닙니다")

    assert llm_client.extract_will_address("텍스트") is None


def test_will_address_returns_none_when_client_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, exc=TimeoutError("network timeout"))

    assert llm_client.extract_will_address("텍스트") is None


def test_will_address_rejects_overly_long_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text=f'{{"address_text": "{"가" * 200}"}}')

    assert llm_client.extract_will_address("텍스트") is None


# ---------------------------------------------------------------------------
# 코드펜스 파싱 버그 회귀 테스트 (2026-08-25).
#
# 실전 검증에서 claude-haiku-4-5 가 시스템 프롬프트의 "JSON만 반환하라, 다른
# 설명이나 문장을 절대 덧붙이지 마라" 지시에도 불구하고 응답을 마크다운
# 코드펜스(```json ... ``` / ``` ... ```)로 감싸 돌려주는 것이 4/4 재현됐다.
# json.loads(text.strip()) 가 펜스를 그대로 못 읽어 JSONDecodeError가 났고,
# 그 예외가 각 extract_* 의 except Exception 에 흡수돼 LLM 폴백 전체가
# 조용히 100% 실패하고 있었다 — 아래 기존 테스트들은 전부 펜스 없는 순수
# JSON('{"name": "김영수"}')만 흉내 내서, 393개 테스트가 전부 통과하면서도
# 이 버그를 한 번도 잡지 못했다.
# ---------------------------------------------------------------------------


def test_strip_code_fence_removes_json_tagged_fence() -> None:
    assert (
        llm_client._strip_code_fence('```json\n{"name": "김철수"}\n```')
        == '{"name": "김철수"}'
    )


def test_strip_code_fence_removes_untagged_fence() -> None:
    assert (
        llm_client._strip_code_fence('```\n{"name": "김철수"}\n```')
        == '{"name": "김철수"}'
    )


def test_strip_code_fence_passes_through_plain_json() -> None:
    """펜스가 없으면 그대로 통과한다 (회귀 — 기존 순수 JSON 응답 경로)."""
    assert llm_client._strip_code_fence('{"name": "김철수"}') == '{"name": "김철수"}'


def test_load_json_response_still_raises_on_truly_broken_json() -> None:
    """펜스 제거로도 못 살리는 진짜 깨진 JSON은 여전히 예외를 던진다 — 이걸
    호출부의 except Exception 이 잡아 None 으로 폴백한다(아래 개별 함수
    테스트에서 확인)."""
    with pytest.raises(Exception):
        llm_client._load_json_response("이건 JSON이 아닙니다")


def test_extract_testator_name_handles_code_fenced_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(monkeypatch, text='```json\n{"name": "김철수"}\n```')

    assert llm_client.extract_testator_name("텍스트") == "김철수"


def test_extract_will_date_handles_code_fenced_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_client(
        monkeypatch, text='```json\n{"date_text": "2026년 5월 3일"}\n```'
    )

    assert llm_client.extract_will_date("텍스트") == "2026년 5월 3일"


def test_extract_will_address_handles_untagged_code_fenced_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """언어 태그 없는 ``` ... ``` 형태도 처리돼야 한다 — json 태그 케이스는
    위 성명/날짜 테스트가 이미 커버하므로 여기서는 다른 형태를 쓴다."""
    _install_fake_client(
        monkeypatch, text='```\n{"address_text": "서울특별시 강남구 테헤란로 123"}\n```'
    )

    assert llm_client.extract_will_address("텍스트") == "서울특별시 강남구 테헤란로 123"


def test_extract_recording_fields_handles_code_fenced_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract_recording_fields 는 이 파일에서 지금까지 한 번도 단위 테스트된
    적이 없었다 — test_decedent_recording_checker.py 의 테스트들이
    llm_client.extract_recording_fields 자체를 몽키패치해서 우회했기 때문에,
    이 함수의 실제 파싱 경로(_parse_recording_fields)는 393개 테스트를
    통과하면서도 한 번도 실행되지 않았다. 이 테스트는 실전 검증에서 실제로
    받은 응답(대전고법 사례가 아니라 녹음 유언 5필드 케이스)을 그대로 재현한다."""
    _install_fake_client(
        monkeypatch,
        text=(
            "```json\n"
            "{\n"
            '  "testator_name": "이순자",\n'
            '  "witness_name": "최민수",\n'
            '  "date_text": "2026년 7월 10일",\n'
            '  "has_disposition_intent": true,\n'
            '  "has_witness_accuracy": true\n'
            "}\n"
            "```"
        ),
    )

    result = llm_client.extract_recording_fields("텍스트")

    assert result == {
        "testator_name": "이순자",
        "witness_name": "최민수",
        "date_text": "2026년 7월 10일",
        "has_disposition_intent": True,
        "has_witness_accuracy": True,
    }


def test_extract_recording_fields_returns_none_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """회귀 — 펜스 제거로도 못 살리는 진짜 깨진 JSON은 여전히 None."""
    _install_fake_client(monkeypatch, text="이건 JSON이 아닙니다")

    assert llm_client.extract_recording_fields("텍스트") is None

"""Claude API 호출 (공식 anthropic SDK).

에이전트 3개가 같이 씁니다. 키는 환경변수 ANTHROPIC_API_KEY에서만 읽습니다.

- complete(): 일반 텍스트 생성
- extract(): 도구(tool) 호출을 강제해서 구조화된 dict를 받아옴 (슬롯 추출용)

키가 없으면 LLMUnavailable을 던집니다. 호출부는 이걸 잡아서 규칙 기반
폴백으로 내려가야 합니다 (개발 원칙 2 "항상 실행 가능").
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

DEFAULT_MODEL = "claude-opus-5"

Message = dict[str, Any]


class LLMUnavailable(RuntimeError):
    """API 키가 없거나 SDK가 설치되지 않아 Claude를 호출할 수 없음."""


@lru_cache(maxsize=1)
def _client():
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise LLMUnavailable(
            "ANTHROPIC_API_KEY가 비어 있습니다. 루트 .env에 값을 넣으세요."
        )
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - 의존성 미설치 환경
        raise LLMUnavailable("anthropic 패키지가 설치되어 있지 않습니다.") from exc
    return anthropic.Anthropic()


def _model() -> str:
    return os.getenv("CLAUDE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def complete(
    *,
    system: str,
    messages: list[Message],
    max_tokens: int = 8000,
    effort: str = "medium",
) -> str:
    """텍스트 응답 한 번 받기.

    thinking은 끄지 않습니다. Claude Opus 5에서 thinking을 끄면 도구 호출이
    일반 텍스트로 새어나오거나 내부 태그가 노출되는 알려진 실패 모드가 있어,
    비용은 effort로만 조절합니다.
    """
    response = _client().messages.create(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
        output_config={"effort": effort},
        messages=messages,
    )
    if response.stop_reason == "refusal":
        raise LLMUnavailable("모델이 응답을 거절했습니다.")
    return "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()


def extract(
    *,
    system: str,
    user_text: str,
    tool: dict[str, Any],
    max_tokens: int = 8000,
    effort: str = "low",
) -> dict[str, Any]:
    """도구 호출을 강제해서 구조화된 입력을 뽑아옵니다.

    tool은 {"name", "description", "input_schema"} 형태여야 하고,
    반환값은 그 스키마에 따른 dict입니다. 검증은 호출부(pydantic) 책임입니다.
    """
    response = _client().messages.create(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_text}],
    )
    if response.stop_reason == "refusal":
        raise LLMUnavailable("모델이 응답을 거절했습니다.")
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    raise LLMUnavailable("모델이 도구를 호출하지 않았습니다.")

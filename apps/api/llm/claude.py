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


def normalize_messages(messages: list[Message]) -> list[Message]:
    """Messages API가 받아들이는 형태로 다듬습니다.

    - 첫 메시지는 반드시 user 여야 합니다. 이력을 상한에 맞춰 앞에서부터 자르면
      assistant 로 시작할 수 있어서, 앞쪽 assistant 를 떼어냅니다.
    - 같은 role 이 연달아 오면 하나로 합칩니다 (빈 답변으로 assistant 한 줄이
      빠졌을 때 user 가 두 번 연속으로 남는 경우 대비).
    """
    normalized: list[Message] = []
    for message in messages:
        if not normalized and message.get("role") != "user":
            continue
        if normalized and normalized[-1]["role"] == message.get("role"):
            joined = normalized[-1]["content"] + "\n" + message.get("content", "")
            normalized[-1] = {"role": normalized[-1]["role"], "content": joined}
            continue
        normalized.append(
            {"role": message["role"], "content": message.get("content", "")}
        )
    return normalized


def extract(
    *,
    system: str,
    tool: dict[str, Any],
    user_text: str | None = None,
    messages: list[Message] | None = None,
    max_tokens: int = 8000,
    effort: str = "low",
    model: str | None = None,
) -> dict[str, Any]:
    """도구 호출을 강제해서 구조화된 입력을 뽑아옵니다.

    tool은 {"name", "description", "input_schema"} 형태여야 하고,
    반환값은 그 스키마에 따른 dict입니다. 검증은 호출부(pydantic) 책임입니다.

    model 을 주면 그 모델로, 비우면 CLAUDE_MODEL(기본값)로 호출합니다 — 라우팅
    분류처럼 호출부가 모델을 따로 고르고 싶을 때 씁니다(orchestrator/llm_policy
    의 router_model 참고).

    messages 로 대화 이력 전체를 넘기면 그걸 쓰고, user_text 하나만 넘기면
    단일 턴으로 처리합니다. 이력이 필요한 이유는 슬롯 추출 때문입니다 —
    "돌아가신 날짜가 언제인가요?" 다음의 "어제"는 앞 문맥 없이는 해석할 수
    없습니다. user_text 만 받던 기존 호출부(orchestrator/planner.py)는 그대로
    동작합니다.
    """
    if messages is None:
        if user_text is None:
            raise ValueError("user_text 또는 messages 중 하나는 있어야 합니다.")
        messages = [{"role": "user", "content": user_text}]
    payload_messages = normalize_messages(messages)
    if not payload_messages:
        raise LLMUnavailable("추출에 쓸 user 메시지가 없습니다.")

    response = _client().messages.create(
        model=model or _model(),
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        output_config={"effort": effort},
        messages=payload_messages,
    )
    if response.stop_reason == "refusal":
        raise LLMUnavailable("모델이 응답을 거절했습니다.")
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    raise LLMUnavailable("모델이 도구를 호출하지 않았습니다.")

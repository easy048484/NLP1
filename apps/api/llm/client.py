"""에이전트 3개가 같이 쓰는 LLM 호출.

키는 환경변수에서만 읽습니다. 에이전트는 chat()만 호출하면 됩니다.
지금은 mock 에이전트가 이 모듈을 쓰지 않습니다. 4단계에서 연결하세요.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

Message = dict[str, str]


def chat(messages: list[Message], *, provider: str | None = None) -> str:
    name = (provider or os.getenv("LLM_PROVIDER", "upstage")).strip().lower()
    if name == "upstage":
        return _openai_compatible(
            base_url=os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1"),
            api_key=_require("UPSTAGE_API_KEY"),
            model=os.getenv("UPSTAGE_MODEL", "solar-pro4"),
            messages=messages,
        )
    if name in {"k-exaone", "k_exaone", "exaone"}:
        return _openai_compatible(
            base_url=os.getenv("K_EXAONE_BASE_URL", "https://api.friendli.ai/dedicated/v1"),
            api_key=_require("K_EXAONE_API_KEY"),
            model=_require("K_EXAONE_ENDPOINT_ID"),
            messages=messages,
        )
    raise ValueError(f"지원하지 않는 LLM_PROVIDER: {name}")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name}가 비어 있습니다. 루트 .env에 값을 넣으세요.")
    return value


def _openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[Message],
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {"model": model, "messages": messages}
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]

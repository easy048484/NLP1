"""
LLM 추출 클라이언트 — 성명(유언자 본인) 전용 (CLAUDE.md 빌드 순서 4단계 최초 착수분).

⚠️ CLAUDE.md 절대 원칙:
1. 판정은 하지 않는다. 이 모듈은 "유언자 본인 성명" 값 하나만 추출한다 —
   요건 충족 여부·유효/무효 판단은 requirement_checker.py + rules/requirements.json
   의 몫이며, 이 모듈이 반환한 값도 그 판정 파이프라인을 그대로 통과한다.
4. 호출부(requirement_checker.py)가 masking.mask_text() 를 거친 텍스트만 이
   함수에 넘긴다는 전제로 동작한다. 이 모듈 자체는 마스킹을 하지 않는다.
6. 요청/응답을 저장하지 않는다. 실패 시에도 원문이 담긴 예외 메시지를
   로깅하지 않고 그냥 None 을 반환한다 — 호출부가 정규식 결과로 폴백한다.

API 키는 팀 공용 키(.env 의 CLAUDE_API_KEY)를 쓴다. 키가 없거나, 네트워크
오류·타임아웃·응답 형식 오류가 나면 예외를 던지지 않고 조용히 None 을 반환한다.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import anthropic

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 64
_TIMEOUT_SECONDS = 8.0

# LLM이 돌려준 이름이 정말 "이름처럼" 생겼는지 최소한으로 검증한다 — 응답 형식
# 오류나 프롬프트 인젝션성 텍스트를 그대로 신뢰하지 않기 위한 방어선.
_VALID_NAME_RE = re.compile(r"^[가-힣]{2,10}$")

_SYSTEM_PROMPT = (
    "너는 자필증서 유언장 텍스트에서 유언자 본인의 성명만 추출하는 도구다.\n"
    "절대 판정하지 마라 — 요건 충족 여부, 유효/무효 여부는 이 도구의 역할이 아니고 "
    "다른 시스템이 처리한다. 너는 오직 값 추출만 한다.\n"
    "재산을 받는 사람(수증자·상속인·배우자·자녀 등)의 이름과, 유언장을 작성한 "
    "유언자 본인의 이름을 혼동하지 마라. 유언자 본인의 이름은 보통 '유언자', "
    "'나는' 같은 표현과 함께 나오거나 문서 하단 서명란에 등장한다.\n"
    "반드시 아래 JSON 형식으로만 답하라. 다른 설명이나 문장을 절대 덧붙이지 마라.\n"
    '유언자 이름을 찾았으면: {"name": "홍길동"}\n'
    '찾을 수 없으면: {"name": null}'
)


def _client() -> Optional[anthropic.Anthropic]:
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _parse_name(raw_response_text: str) -> Optional[str]:
    parsed = json.loads(raw_response_text.strip())
    name = parsed.get("name") if isinstance(parsed, dict) else None

    if not isinstance(name, str):
        return None
    name = name.strip()
    if not _VALID_NAME_RE.match(name):
        return None
    return name


def extract_testator_name(masked_text: str) -> Optional[str]:
    """마스킹된 유언장 텍스트에서 유언자 본인 성명을 LLM으로 추출한다.

    호출부(requirement_checker.extract_name_with_fallback)가 정규식으로
    이름을 못 찾았을 때만(fallback) 이 함수를 부른다. 이 함수 자체는 성공/실패를
    구분하지 않고 항상 str(찾음) | None(못 찾음 또는 실패) 만 반환한다.
    """
    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": masked_text}],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_name(response.content[0].text)
    except Exception:
        # 네트워크 오류·타임아웃·응답 형식 오류 등 어떤 이유든 정규식 폴백으로
        # 넘긴다. 원문이 섞일 수 있는 예외 메시지는 로깅하지 않는다.
        return None

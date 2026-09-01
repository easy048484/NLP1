"""오케스트레이터의 LLM 사용 정책 — ORCHESTRATOR_USE_LLM 해석 한곳.

planner.py 와 compose.py 에 중복돼 있던 _llm_enabled() 를 모았습니다.

값 해석:
  off  (0/false/no/off)   LLM 안 씀 — 항상 키워드/이어붙이기 경로
  on   (1/true/yes/on)    LLM 시도 — 실패하면 조용히 폴백 (기존 동작)
  auto (기본값)            ANTHROPIC_API_KEY 가 있을 때만 on 과 동일
  required                LLM 시도 — 실패하면 폴백하지 않고 예외를 올림.
                          데모·운영 환경 전용: "조용한 열화" 대신 시끄럽게
                          실패해서 키 누락·네트워크 문제를 즉시 드러냅니다.
                          main.py 가 기동 시점에 키 존재도 검사합니다.
"""

from __future__ import annotations

import os

_OFF = {"0", "false", "no", "off"}
_ON = {"1", "true", "yes", "on"}


def llm_mode() -> str:
    """환경변수를 "off" | "on" | "auto" | "required" 로 정규화합니다."""
    flag = os.getenv("ORCHESTRATOR_USE_LLM", "auto").strip().lower()
    if flag in _OFF:
        return "off"
    if flag in _ON:
        return "on"
    if flag == "required":
        return "required"
    return "auto"


def llm_enabled() -> bool:
    """이번 호출에서 LLM 을 시도할지."""
    mode = llm_mode()
    if mode == "off":
        return False
    if mode in {"on", "required"}:
        return True
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def llm_required() -> bool:
    """LLM 실패 시 폴백 대신 예외를 올려야 하는 환경인지."""
    return llm_mode() == "required"


def llm_status() -> str:
    """/health 노출용 상태 — "on" | "off" | "unconfigured".

    unconfigured: 플래그상 LLM 을 쓰려 하지만 ANTHROPIC_API_KEY 가 비어 있어
    실제로는 전부 규칙 기반 폴백으로 동작하는 상태(조용한 열화 상태)입니다.
    """
    if llm_mode() == "off":
        return "off"
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "unconfigured"
    return "on"

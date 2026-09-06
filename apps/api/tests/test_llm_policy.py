"""orchestrator/llm_policy 단위 테스트 + required 모드가 폴백 대신 예외를 올리는지.

배경: LLM 실패 시 조용히 규칙 기반으로 열화되는 설계(개발 원칙 2)는 CI·키 없는
로컬에는 맞지만, 데모·운영에서는 키 누락이 티 안 나게 품질을 떨어뜨렸다
("어제" 미해석 피드백). ORCHESTRATOR_USE_LLM=required 는 그 환경에서 폴백을
금지하고 시끄럽게 실패시키는 스위치다.
"""

from __future__ import annotations

import pytest

from orchestrator import compose, planner
from orchestrator.llm_policy import llm_enabled, llm_mode, llm_required, llm_status
from schemas import AgentName, AgentOutput


# ------------------------------------------------------------------ 값 해석


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", "off"),
        ("false", "off"),
        ("off", "off"),
        ("1", "on"),
        ("true", "on"),
        ("ON", "on"),
        ("required", "required"),
        ("REQUIRED", "required"),
        ("auto", "auto"),
        ("뭔가이상한값", "auto"),
        ("", "auto"),
    ],
)
def test_llm_mode(monkeypatch, raw: str, expected: str) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", raw)
    assert llm_mode() == expected


def test_enabled_auto_follows_key(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_enabled() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm_enabled() is True


def test_enabled_required_even_without_key(monkeypatch) -> None:
    # required 는 키가 없어도 "시도"한다 — 그래야 호출부에서 예외가 나서
    # 조용히 폴백하지 않는다 (기동 시점 검사는 main.py 몫).
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "required")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_enabled() is True
    assert llm_required() is True


def test_status(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "off")
    assert llm_status() == "off"
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_status() == "unconfigured"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm_status() == "on"


# ------------------------------------------------- required 는 폴백하지 않는다


def _outputs() -> list[AgentOutput]:
    return [
        AgentOutput(agent=AgentName.TAX_CALCULATOR, reply="상속세 1,000만원"),
        AgentOutput(agent=AgentName.HEIR_NAVIGATOR, reply="사망신고부터"),
    ]


def test_compose_required_raises_instead_of_concat(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "required")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # 키가 없으므로 llm.claude 가 LLMUnavailable → required 는 그대로 올린다.
    with pytest.raises(Exception):
        compose.llm_synthesize(_outputs(), "상속세와 절차 알려줘")


def test_compose_auto_falls_back_silently(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # 기존 동작 회귀 방지: required 가 아니면 실패해도 None(폴백)이다.
    assert compose.llm_synthesize(_outputs(), "상속세와 절차 알려줘") is None


def test_planner_required_raises(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "required")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(Exception):
        planner._llm_route(
            "상속세랑 유언장 다",
            last_agent=None,
            pending_handoff=None,
            last_assistant_message=None,
            axis=None,
            keyword_hits=[AgentName.TAX_CALCULATOR, AgentName.DECEDENT_ESTATE],
        )


def test_planner_on_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert (
        planner._llm_route(
            "상속세랑 유언장 다",
            last_agent=None,
            pending_handoff=None,
            last_assistant_message=None,
            axis=None,
            keyword_hits=[AgentName.TAX_CALCULATOR, AgentName.DECEDENT_ESTATE],
        )
        is None
    )

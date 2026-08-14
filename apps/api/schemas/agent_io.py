"""
AgentInput / AgentOutput 공통 계약.

개발 원칙 3 "계약(스키마)은 코드보다 먼저"에 따라, 오케스트레이터와 각 에이전트는
이 스키마로만 서로 대화합니다. 각 에이전트 내부 구현은 자유롭게 바꿔도 되지만,
이 인터페이스를 깨면 오케스트레이터가 즉시 실패하도록 해서 계약 변경을 팀 전체가
알아차릴 수 있게 합니다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    HEIR_NAVIGATOR = "heir_navigator"  # 상속인 절차 내비게이터
    DECEDENT_ESTATE = "decedent_estate"  # 피상속인 유언장·자산정리
    TAX_CALCULATOR = "tax_calculator"  # 상속세 계산·설계


class AgentInput(BaseModel):
    session_id: str
    user_message: str
    family_graph: Optional[dict[str, Any]] = Field(
        default=None, description="가족관계 그래프 엔진이 계산한 현재 상태"
    )
    context: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    agent: AgentName
    reply: str
    next_action: Optional[str] = Field(
        default=None,
        description="오케스트레이터에게 다음에 무엇을 할지 힌트 (예: 다른 에이전트로 전환)",
    )
    data: dict[str, Any] = Field(default_factory=dict)

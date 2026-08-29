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
    HEIR_SHARE_ANALYZER = "heir_share_analyzer"  # 법정상속분·유류분 위험 점검


class AgentInput(BaseModel):
    session_id: str
    user_message: str
    family_graph: Optional[dict[str, Any]] = Field(
        default=None, description="가족관계 그래프 엔진이 계산한 현재 상태"
    )
    family_graph_id: Optional[str] = Field(
        default=None,
        description=(
            "DB에 저장된 family_graph의 식별자. 오케스트레이터가 이 값으로 "
            "family_graph 테이블을 조회해서 위 family_graph 필드를 채웁니다 — "
            "family_graph를 직접 채워 보내면(테스트/레거시 클라이언트) 그 값이 "
            "우선합니다. 프론트는 이 값을 세션과 별도로 (localStorage 등에) "
            "저장해뒀다가 매 요청에 실어 보내야 재방문 시 가족관계를 다시 "
            "입력하지 않아도 됩니다."
        ),
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

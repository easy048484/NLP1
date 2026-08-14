"""
오케스트레이터 (라우팅·상태관리·전환, 담당: 지원)

2단계 "오케스트레이터 최소 뼈대"에 해당하는 mock 구현입니다.
지금은 사용자 메시지에 포함된 키워드로 단순 분기하지만, 실제로는 LangGraph 기반
상태 머신으로 교체될 예정입니다 (4단계에서 각 에이전트가 실제 로직으로 바뀔 때
이 라우팅 로직도 함께 다듬습니다).
"""

from __future__ import annotations

from agents import decedent_estate, heir_navigator, tax_calculator
from schemas import AgentInput, AgentOutput

_KEYWORD_ROUTES = {
    "유언": decedent_estate.run,
    "자산정리": decedent_estate.run,
    "상속세": tax_calculator.run,
    "세금": tax_calculator.run,
}

_DEFAULT_AGENT = heir_navigator.run


def route(payload: AgentInput) -> AgentOutput:
    for keyword, handler in _KEYWORD_ROUTES.items():
        if keyword in payload.user_message:
            return handler(payload)
    return _DEFAULT_AGENT(payload)

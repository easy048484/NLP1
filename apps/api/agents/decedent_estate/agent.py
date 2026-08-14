"""
피상속인 유언장·자산정리 에이전트 (담당: 정호)

2단계(오케스트레이터 최소 뼈대) 기준의 mock 구현입니다.
"""

from schemas import AgentInput, AgentName, AgentOutput


def run(payload: AgentInput) -> AgentOutput:
    return AgentOutput(
        agent=AgentName.DECEDENT_ESTATE,
        reply=(
            "[mock] 피상속인 유언장·자산정리 에이전트입니다. "
            "실제 로직이 들어오기 전까지는 안내 문구만 반환합니다."
        ),
        next_action=None,
        data={"received": payload.user_message},
    )

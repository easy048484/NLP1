"""
상속인 절차 내비게이터 (담당: 정민)

2단계(오케스트레이터 최소 뼈대) 기준의 mock 구현입니다.
실제 로직으로 교체할 때도 run(input: AgentInput) -> AgentOutput 시그니처는 유지해주세요.
"""

from schemas import AgentInput, AgentName, AgentOutput


def run(payload: AgentInput) -> AgentOutput:
    return AgentOutput(
        agent=AgentName.HEIR_NAVIGATOR,
        reply=(
            "[mock] 상속인 절차 내비게이터입니다. "
            "실제 로직이 들어오기 전까지는 안내 문구만 반환합니다."
        ),
        next_action=None,
        data={"received": payload.user_message},
    )

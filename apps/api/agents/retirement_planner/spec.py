"""retirement_planner 의 라우팅 선언. 구현이 채워지면 is_stub=False 로 바꾸세요."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.RETIREMENT_PLANNER,
    axis=AgentAxis.PRE_NEED,
    description="은퇴 시점까지 필요한 자금과 현재 준비 자금의 갭을 계산하고 보완 방향을 제안",
    example_utterances=[
        "은퇴 준비 자금이 얼마나 필요해요?",
        "노후 자금이 부족한지 봐주세요",
        "연금으로 생활비가 충당되나요?",
    ],
    keywords=["은퇴", "노후", "연금"],
    requires=[],
    produces=["retirement_gap"],
    entrypoint=run,
    is_stub=True,
)

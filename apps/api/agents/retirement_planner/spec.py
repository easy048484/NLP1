"""retirement_planner 의 라우팅 선언.

⚠️ 데모 비핵심 (2026-08-30 — 서비스는 "상속"). 엔진은 검증돼 있으나(PR #45)
데모 시나리오엔 없다. "연금" 키워드는 뺐다 — "퇴직연금/국민연금" 같은 자산
카테고리 발화가 asset_organizer 대신 이쪽으로 새는 충돌이 있었다.
"""

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
    keywords=["은퇴", "노후"],
    requires=[],
    produces=["retirement_gap"],
    entrypoint=run,
    is_stub=False,
)

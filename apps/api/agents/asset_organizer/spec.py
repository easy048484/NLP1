"""asset_organizer 의 라우팅 선언. 구현이 채워지면 is_stub=False 로 바꾸세요."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.ASSET_ORGANIZER,
    axis=AgentAxis.PRE_NEED,
    description="보유 자산·부채를 한눈에 정리한 목록을 만들고 빠진 항목을 찾아냄",
    example_utterances=[
        "내 재산 목록을 정리해줘",
        "자산 현황을 한 번에 보고 싶어요",
        "부채까지 포함해서 재산을 정리해주세요",
    ],
    keywords=["자산목록", "재산목록", "자산현황", "재산현황"],
    requires=[],
    produces=["asset_inventory"],
    entrypoint=run,
    is_stub=False,
)

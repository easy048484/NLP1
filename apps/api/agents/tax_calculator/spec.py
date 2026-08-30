"""tax_calculator 의 라우팅 선언 (orchestrator/registry.py 참고). agent.py 는 건드리지 않습니다."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.TAX_CALCULATOR,
    axis=AgentAxis.PRE_NEED,  # 생전 시뮬레이션과 사후 계산 모두 담당 — 기본 축은 생전준비
    description="상속재산·공제 정보를 받아 상속세를 계산하거나 생전에 미리 시뮬레이션",
    example_utterances=[
        "상속세 얼마나 나와요?",
        "배우자 공제 받으면 세금이 얼마나 줄어요?",
        "은퇴 준비하면서 상속세도 궁금해요",
    ],
    keywords=["상속세", "세금"],
    # decedent_estate 와 같은 턴에 뽑히면 유언장 판정(will_status) 뒤에 돕니다.
    # 뽑히지 않았으면 그냥 첫 층에서 돕니다 (requires 는 soft 의존성).
    requires=["will_status"],
    produces=["tax_estimate"],
    entrypoint=run,
)

"""decedent_estate 의 라우팅 선언 (orchestrator/registry.py 참고). agent.py 는 건드리지 않습니다."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.DECEDENT_ESTATE,
    axis=AgentAxis.POST_DEATH,
    description="유언장의 종류·법적 요건을 점검하고 유언장 유무에 따른 자산정리 방향을 안내",
    example_utterances=[
        "유언장이 있는데 효력이 있는지 봐주세요",
        "자필 유언장 요건이 뭔가요?",
        "유언장 없이 돌아가셨는데 재산은 어떻게 나누나요?",
    ],
    keywords=["유언", "자산정리"],
    requires=[],
    # 유언장 유무/유효성 판정 — tax_calculator 가 같은 턴에 뽑히면 이 결과를 본 뒤에 돕니다.
    produces=["will_status"],
    entrypoint=run,
)

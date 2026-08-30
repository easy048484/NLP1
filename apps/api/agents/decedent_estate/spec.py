"""decedent_estate 의 라우팅 선언 (orchestrator/registry.py 참고). agent.py 는 건드리지 않습니다."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.DECEDENT_ESTATE,
    axis=AgentAxis.POST_DEATH,
    description="유언장의 종류·법적 요건·효력을 점검 (자산 목록 정리는 asset_organizer 담당)",
    example_utterances=[
        "유언장이 있는데 효력이 있는지 봐주세요",
        "자필 유언장 요건이 뭔가요?",
        "유언장 없이 돌아가셨는데 절차가 어떻게 되나요?",
    ],
    # "자산정리"는 asset_organizer 로 넘겼다 — 이 에이전트는 유언장 자체만 본다.
    keywords=["유언", "유언장", "유언 요건", "유언 효력", "자필증서", "공정증서"],
    requires=[],
    # 유언장 유무/유효성 판정(will_status) — tax_calculator·heir_share_analyzer 가
    # 같은 턴에 뽑히면 이 결과 뒤에 돌고, AgentInput.will_status 로 판정 요약을 받는다.
    produces=["will_status"],
    entrypoint=run,
)

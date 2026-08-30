"""heir_share_analyzer의 라우팅 선언 (orchestrator/registry.py 참고)."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.HEIR_SHARE_ANALYZER,
    axis=AgentAxis.PRE_NEED,
    description=(
        "가족관계와 예정 재산 배분을 바탕으로 법정상속분과 유류분 부족 가능성을 "
        "참고용으로 점검"
    ),
    example_utterances=[
        "유류분이 부족할 가능성이 있나요?",
        "법정상속분과 유언장 배분을 비교해줘",
        "한 자녀에게만 재산을 주면 분쟁 위험이 있나요?",
    ],
    keywords=["유류분", "법정상속분"],
    # 유언장 점검 에이전트가 같은 턴에 선택되면 그 결과 뒤에 실행합니다.
    # 단독 선택 시에는 soft 의존성이므로 바로 실행됩니다.
    requires=["will_status"],
    produces=["heir_share_analysis"],
    entrypoint=run,
)

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
    keywords=[
        "유류분",
        "법정상속분",
        # "유류분"/"법정상속분" 같은 법률 용어 없이 평범한 말로 물어보는 경우가
        # 실제로 더 많다(예: "한 자녀에게만 남기면 어떻게 되나요") — 이 경우
        # 후보가 0개(또는 asset_organizer의 "재산"만 매칭)가 되어 다른
        # 에이전트에 계속 붙잡히는 문제가 있었다(실측 재현, example_utterances
        # 3번째 항목 자체가 이미 이 문제를 보여주고 있었음).
        "자녀에게만",
        "분쟁",
        "몰아주",
        "치우쳐",
        "형평",
    ],
    # 유언장 점검 에이전트가 같은 턴에 선택되면 그 결과 뒤에 실행합니다.
    # 단독 선택 시에는 soft 의존성이므로 바로 실행됩니다.
    requires=["will_status"],
    produces=["heir_share_analysis"],
    entrypoint=run,
)

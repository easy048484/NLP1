"""heir_navigator 의 라우팅 선언 (orchestrator/registry.py 참고). agent.py 는 건드리지 않습니다."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.HEIR_NAVIGATOR,
    axes=[AgentAxis.POST_DEATH],
    description="사망 이후 상속인이 밟아야 할 절차(사망신고·상속포기/한정승인·신고기한)를 단계별로 안내",
    example_utterances=[
        "아버지가 어제 돌아가셨어요. 뭐부터 해야 하나요?",
        "상속포기 기한이 언제까지예요?",
        "사망신고는 어디서 하나요?",
    ],
    # 기존 라우팅 정책 유지: 키워드가 없으면 기본 에이전트로 이 에이전트가 선택되므로
    # 키워드는 절차성 단어만 최소로 둡니다.
    keywords=["돌아가셨", "사망신고", "상속포기", "한정승인", "절차"],
    requires=[],
    produces=["procedure_plan"],
    entrypoint=run,
)

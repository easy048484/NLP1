"""tax_calculator 의 라우팅 선언 (orchestrator/registry.py 참고). agent.py 는 건드리지 않습니다."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.TAX_CALCULATOR,
    axes=[AgentAxis.PRE_NEED, AgentAxis.POST_DEATH],
    description=(
        "생전에는 현재 보유 자산을 기준으로 예상 상속세를 미리 시뮬레이션하고, "
        "사후에는 고인의 상속재산·채무·가족관계·공제 정보를 반영해 신고 전 "
        "참고용 상속세를 시산. 재산 목록 정리는 asset_organizer, 법정상속분·"
        "유류분 점검은 heir_share_analyzer가 담당"
    ),
    # planner._classify_prompt()는 앞 3개만 LLM few-shot으로 사용한다. 따라서
    # 사후 계산/생전 시뮬레이션/공제 적용을 앞쪽에 하나씩 배치하고, 짧은 표현과
    # 실제 조회 결과 기반 표현은 뒤에 보존해 라우팅 실험 사례로 활용한다.
    example_utterances=[
        (
            "아버지가 돌아가셨고 아파트 5억 원, 예금 8천만 원, 카드대출 "
            "2천만 원이 있습니다. 어머니와 자녀 둘이 상속받으면 예상 "
            "상속세가 얼마인가요?"
        ),
        (
            "제가 살아 있을 때 미리 계산해보고 싶습니다. 아파트 7억 원, "
            "예금 3천만 원, 보험금 1억 원을 두 딸에게 남기면 상속세가 "
            "얼마나 나올까요?"
        ),
        (
            "배우자와 자녀 두 명이 상속인입니다. 일괄공제와 배우자공제를 "
            "반영한 과세표준과 예상 납부세액을 알려주세요."
        ),
        "상속세 얼마나 나와요?",
        "배우자 공제 받으면 세금이 얼마나 줄어요?",
        (
            "안심상속 조회 결과 예금 8천만 원과 아파트 5억 원이 확인됐고 "
            "부채는 2천만 원입니다. 이 내용을 기준으로 상속세를 계산해 주세요."
        ),
    ],
    keywords=["상속세", "세금"],
    # decedent_estate 와 같은 턴에 뽑히면 유언장 판정(will_status) 뒤에 돕니다.
    # 뽑히지 않았으면 그냥 첫 층에서 돕니다 (requires 는 soft 의존성).
    requires=["will_status"],
    produces=["tax_estimate"],
    entrypoint=run,
)

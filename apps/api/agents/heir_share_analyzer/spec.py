"""heir_share_analyzer의 라우팅 선언 (orchestrator/registry.py 참고)."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.HEIR_SHARE_ANALYZER,
    axes=[AgentAxis.PRE_NEED, AgentAxis.POST_DEATH],
    description=(
        "생전 유언·증여·예정 배분 또는 사후 상속재산 분할 상황을 가족관계와 "
        "재산 정보에 비교해 법정상속분과 기본 유류분 부족 가능성을 참고용으로 "
        "1차 점검. 상속세는 tax_calculator가 담당하며 특별수익·기여분·대습상속·"
        "실제 청구 가능성 및 소송 결과는 확정하지 않고 전문가 검토를 안내"
    ),
    # planner._classify_prompt()는 앞 3개만 LLM few-shot으로 사용한다. 따라서
    # 사후 사전증여/생전 유언 배분/사후 분할안 비교를 앞쪽에 하나씩 배치한다.
    example_utterances=[
        (
            "아버지가 3년 전에 여동생에게 2억 원을 증여했고 최근 돌아가셨습니다. "
            "남은 재산을 여동생과 반씩 나누면 제 유류분이 부족할 수 있나요?"
        ),
        (
            "제가 살아 있을 때 유언장을 작성해 첫째에게 재산의 80%, 둘째에게 "
            "20%를 남기려고 합니다. 둘째의 유류분 부족 가능성을 확인해 주세요."
        ),
        (
            "어머니와 자녀 두 명이 공동상속인이고 순상속재산은 5억 6천만 원입니다. "
            "각자의 법정상속분과 합의한 실제 분할액을 비교해 주세요."
        ),
        "유류분이 부족할 가능성이 있나요?",
        "법정상속분과 유언장 배분을 비교해줘",
        "한 자녀에게만 재산을 주면 분쟁 위험이 있나요?",
        "형제자매만 상속인인 경우에도 유류분을 청구할 수 있나요?",
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

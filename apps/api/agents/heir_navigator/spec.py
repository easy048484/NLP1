"""heir_navigator 의 라우팅 선언 (orchestrator/registry.py 참고). agent.py 는 건드리지 않습니다."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.HEIR_NAVIGATOR,
    # 절차 안내는 본질적으로 사후다. "부모님 돌아가시면 뭐부터 해야 하나요"처럼
    # 생전에 미리 묻는 발화도 있지만 axes 는 하드 필터가 아니라(LLM 프롬프트
    # 표시 + LLM 불가 시 폴백 기본 에이전트 선택에만 쓰임) 사후 하나로 충분하다.
    axes=[AgentAxis.POST_DEATH],
    # LLM-first 라우팅(orchestrator/planner._classify_prompt)은 이 description 과
    # example_utterances[:3] 만 보고 에이전트를 고른다. 이 에이전트는 사후 절차
    # 질문의 포괄 담당이라 다른 에이전트와 맞닿는 경계가 가장 많다 — "무엇을
    # 하는지"와 함께 "무엇을 안 하는지"를 적어 둬야 (1) "빚이 많은데 상속포기
    # 해야 하나요" 같은 절차 상담이 asset_organizer 로 새지 않고(실측 오탐 사례,
    # asset_organizer/spec.py 참고), (2) 반대로 유언장 효력·재산 목록화·세액
    # 계산·상속분 계산을 이 에이전트가 떠안지 않는다.
    #
    # 담당 범위는 agents/heir_navigator/procedure/steps.py 의 절차 단계
    # (사망신고 → 안심상속 신청 → 재산 조회 결과 확인 → 유언장 존재 확인 →
    # 단순승인/한정승인/상속포기 결정 → 분할협의 → 상속등기 → 취득세 → 상속세
    # 신고)와 deadlines.py 의 기한 계산에서 그대로 가져왔다. 한정승인/상속포기
    # 중 "무엇을 고를지" 추천은 guardrails.py 가 코드로 막는 경계라 여기서도
    # 명시한다 — 선택지와 기한·결과는 설명하되 결정은 대신하지 않는다.
    description=(
        "사망 이후 상속인이 밟아야 할 절차를 순서대로 안내하는 에이전트. "
        "사망신고, 안심상속 원스톱 조회 신청, 유언장 존재 확인, 단순승인·한정승인·"
        "상속포기 신고 기한(사망일·인지일 기준 3개월/6개월 계산), 상속재산분할협의, "
        "상속등기·명의이전, 취득세·상속세 신고 기한과 각 단계의 서류·기관을 "
        "알려주고 일정으로 정리한다. 한정승인·상속포기 중 무엇을 고를지 대신 "
        "결정하거나 추천하지는 않고 선택지와 결과를 설명한다. 유언장의 효력 판정은 "
        "decedent_estate, 재산·부채 목록화는 asset_organizer, 상속세 금액 계산은 "
        "tax_calculator, 법정상속분·유류분 계산은 heir_share_analyzer 가 담당한다."
    ),
    # 앞 3개만 few-shot 으로 쓰인다 — (1) 사망 직후 "뭐부터" 형 포괄 질문,
    # (2) 빚 언급이 있어도 재산 목록화가 아니라 상속포기 여부·기한을 묻는
    # 절차 질문(asset_organizer 와의 경계), (3) 유언장이 없다는 말이 있어도
    # 유언장 점검이 아니라 절차를 묻는 질문(decedent_estate 와의 경계).
    # 뒤 3개는 단일 단계 질문(기한·사망신고·서류) 보조 예시.
    example_utterances=[
        "아버지가 어제 돌아가셨어요. 뭐부터 해야 하나요?",
        "빚이 많을 것 같은데 상속포기를 해야 하나요? 기한은 언제까지예요?",
        "유언장 없이 돌아가셨는데 상속 절차가 어떻게 되나요?",
        "한정승인 신고 기한이 언제까지예요?",
        "사망신고는 어디서 하나요?",
        "상속등기 하려면 서류가 뭐가 필요해요?",
    ],
    # 키워드는 LLM 불가/실패 시 폴백 후보로만 쓰인다(LLM-first 전환 이후).
    # 절차성 단어만 최소로 둔다 — "절차"는 일반적이지만 사후 절차 질문의
    # 대표 표현이라 유지한다.
    keywords=["돌아가셨", "사망신고", "상속포기", "한정승인", "절차"],
    requires=[],
    produces=["procedure_plan"],
    entrypoint=run,
)

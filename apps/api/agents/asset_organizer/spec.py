"""asset_organizer 의 라우팅 선언. 구현이 채워지면 is_stub=False 로 바꾸세요."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.ASSET_ORGANIZER,
    # AgentAxis에 pre_need/post_death 겸용을 표현할 값이 없고(tax_calculator도
    # 같은 이유로 양쪽 기능을 PRE_NEED 기본축 하나로 선언해둔 전례가 있다),
    # 이 필드는 "키워드 후보 0개일 때만" 개입하는 라우팅 폴백 힌트일 뿐이라
    # (orchestrator/planner.py._axis_default_agent 참고) 실제 사후 모드
    # 진입은 이 값과 무관하게 keywords/mode로 이미 정상 동작한다 — shared
    # schema/orchestrator 확장은 이번 작업 범위 밖.
    axis=AgentAxis.PRE_NEED,
    description=(
        "생전 본인 또는 사후 고인의 재산·부채를 목록화하고, 확인되지 않은"
        " 항목과 금액을 정리"
    ),
    # _classify_prompt(orchestrator/planner.py)는 example_utterances[:3]만
    # few-shot으로 쓴다 — 그래서 생전/사후/안심상속 각 시나리오를 대표하는
    # 예시 3개를 반드시 앞쪽에 두고, 기존 예시는 그 뒤에 유지한다(단순
    # append 금지 — 뒤에 붙이면 LLM 분류에 반영되지 않는다).
    example_utterances=[
        "가진 재산과 부채가 뭐가 있는지 한 번 정리하고 싶어요",
        "돌아가신 가족의 재산과 빚부터 파악하고 싶어요",
        "안심상속 조회했는데 은행 잔액은 나오고 증권은 계좌만 확인됐어요",
        "내 재산 목록을 정리해줘",
        "자산 현황을 한 번에 보고 싶어요",
        "부채까지 포함해서 재산을 정리해주세요",
    ],
    keywords=[
        "자산목록",
        "재산목록",
        "자산현황",
        "재산현황",
        "자산",
        "재산",
        # "정리"는 제거했다 — 너무 일반적인 동사라 "상속 절차를 정리해
        # 주세요"처럼 재산 목록화와 무관한 절차/상속포기 상담에도 후보로
        # 잘못 끼어들었다(실측 재현, routing false positive). "자산"/"재산"
        # 등 구체적인 키워드는 이미 있어서 빠져도 정상 진입 문장은 그대로
        # 후보가 된다.
        # 안심상속 원스톱 조회결과·생전 자산 언급은 "자산/재산" 같은 요약어 없이
        # 기관·유형명만으로 오는 경우가 실제로 훨씬 많다(예: "은행은 잔액이
        # 나왔고 증권은 계좌만 확인됐어요", "예금 3200만원, 부동산 3억5천만원,
        # 대출 1억2천만원 있어요") — 위 요약어만으로는 후보가 0개가 되어
        # last_agent(직전 에이전트)에 계속 붙잡히는 문제가 있었다(실측 재현).
        "은행",
        "예금",
        "적금",
        "증권",
        "펀드",
        "부동산",
        "자동차",
        "퇴직연금",
        "보험",
        "대출",
        "채무",
        "빚",
        "잔액",
        "계좌",
        # 사후 모드 명시적 진입 — "안심상속"이라는 단어만으로도 후보가 돼야
        # 한다(예: "안심상속 조회 결과를 정리하고 싶어요"처럼 구체 기관·금액
        # 없이 조회결과 자체를 언급하는 경우).
        "안심상속",
    ],
    requires=[],
    produces=["asset_inventory"],
    entrypoint=run,
    is_stub=False,
)

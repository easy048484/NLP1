"""asset_organizer 의 라우팅 선언. 구현이 채워지면 is_stub=False 로 바꾸세요."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.ASSET_ORGANIZER,
    axis=AgentAxis.PRE_NEED,
    description="보유 자산·부채를 한눈에 정리한 목록을 만들고 빠진 항목을 찾아냄",
    example_utterances=[
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
        "정리",
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
    ],
    requires=[],
    produces=["asset_inventory"],
    entrypoint=run,
    is_stub=False,
)

"""retirement_planner 의 라우팅 선언. 구현이 채워지면 is_stub=False 로 바꾸세요."""

from orchestrator.registry import AgentSpec
from schemas import AgentAxis, AgentName

from .agent import run

SPEC = AgentSpec(
    name=AgentName.RETIREMENT_PLANNER,
    axis=AgentAxis.PRE_NEED,
    description="은퇴 시점까지 필요한 자금과 현재 준비 자금의 갭을 계산하고 보완 방향을 제안",
    example_utterances=[
        "은퇴 준비 자금이 얼마나 필요해요?",
        "노후 자금이 부족한지 봐주세요",
        "연금으로 생활비가 충당되나요?",
    ],
    # ⚠️ 단독 "연금"은 쓰지 않는다 — orchestrator/registry.py의 match_keywords()가
    # 단순 substring 매칭이라 asset_organizer 체크리스트 중 "퇴직연금"(자산 유형)
    # 이나, 그 에이전트의 퇴직연금 수령방식 후속질문에 대한 답변("연금으로
    # 65살부터 월 100만원씩 받을 거예요" 등)에도 걸려 대화가 중간에 이쪽으로
    # 튕겨나가며 그 턴 데이터가 유실되는 게 실측 재현됐다(asset_organizer/
    # CLAUDE.md 빌드 히스토리 참고). "연금으로"도 같은 이유로 위험하다 —
    # 퇴직연금 후속질문 답변이 전부 "연금으로 ..."로 시작한다. 근본 원인
    # (오케스트레이터의 substring 매칭 방식)은 팀 논의 대상이라 안 건드리고,
    # 여기서는 이 특정 충돌만 좁혀서 임시 방어한다 — "연금 계산"/"예상 연금"은
    # 위 두 문구 어디에도 부분 문자열로 나타나지 않으면서 실제 라우팅 테스트
    # (tests/test_retirement_planner_keyword_collision.py)로 "은퇴"/"노후" 커버
    # 범위 밖의 순수 연금 질의도 여전히 걸리는 걸 확인했다. 이 좁힌 키워드
    # 밖에 있는 "연금으로 생활비가 충당되나요?"(아래 example_utterances) 같은
    # 표현은 이제 단독 키워드로는 안 걸린다 — 완전한 해결책이 아니라는 뜻.
    keywords=["은퇴", "노후", "연금 계산", "예상 연금"],
    requires=[],
    produces=["retirement_gap"],
    entrypoint=run,
    is_stub=False,
)

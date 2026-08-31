"""retirement_planner 의 라우팅 선언.

⚠️ 데모 범위에서 제외 (2026-08-30, 팀 계획서 결정 — 서비스는 "상속"). 엔진·
대화 로직은 그대로 보존한다(engine.py 등 삭제하지 않음 — 로드맵/발표자료용).
막은 건 **라우팅 진입점뿐**이다:

- `keywords=[]`로 비웠다 — `orchestrator.registry.match_keywords()`는
  키워드가 하나도 없으면 이 에이전트를 후보에 아예 넣지 않으므로, "은퇴
  준비가 걱정돼요" 같은 발화로 사용자가 직접 이 에이전트에 도달할 방법이
  없어진다(실제 `router.route()`로 재검증함).
- `is_stub=True`로도 되돌렸다 — 다만 **이것만으로는 라우팅이 안 막힌다는
  걸 실측으로 확인했다**: `orchestrator/planner.classify()`의 Standard
  경로(`len(candidates) == 1`)는 `is_stub`을 아예 확인하지 않는다. 이
  플래그는 (a) 키워드 후보가 2개 이상일 때 LLM 분류 프롬프트에 "준비 중"
  힌트를 주는 것과, (b) 축(axis) 기본 에이전트 폴백에서 스텁을 건너뛰는
  것에만 쓰인다 — 둘 다 이 에이전트에는 해당 안 되지만(축 기본 에이전트가
  아니고, 단독 키워드 매칭은 이 체크를 안 거침), 상태를 정직하게 남겨두는
  차원에서 같이 되돌려뒀다. `keywords=[]`가 실질적인 차단 장치다.
- ⚠️ **asset_organizer → retirement_planner 핸드오프(Fast Path)는 그대로
  동작한다** — `classify()`가 `pending_handoff`를 키워드 매칭보다 먼저
  확인하고, `registry.get_optional()`로만 대상 존재 여부를 보기 때문에
  `keywords=[]`의 영향을 안 받는다. 즉 자산 정리 체크리스트를 끝내면
  여전히 이 에이전트로 자동 연결된다 — "사용자가 먼저 말을 걸어서
  도달"만 막혔지 "체크리스트 완료 후 자연스럽게 이어짐"은 안 막혔다.
  이게 "데모 제외" 의도와 맞는지는 판단이 필요해 보여 그대로 보고한다.
"""

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
    keywords=[],
    requires=[],
    produces=["retirement_gap"],
    entrypoint=run,
    is_stub=True,
)

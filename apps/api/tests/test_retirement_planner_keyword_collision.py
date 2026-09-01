"""
retirement_planner 라우팅 진입점 회귀 테스트.

역사:
1. retirement_planner의 라우팅 키워드가 처음엔 단독 "연금"이었는데,
   orchestrator.registry.match_keywords()가 단순 substring 매칭이라
   asset_organizer의 자산 유형 "퇴직연금"과, 그 에이전트의 퇴직연금
   수령방식 후속질문 답변("연금으로 65살부터 월 100만원씩 받을 거예요" 등)
   에도 걸려서 체크리스트 도중 대화가 retirement_planner로 튕겨나가며 그
   턴 데이터가 유실되는 게 실측 재현됐다.
2. 이 충돌은 PR #45 병합 직후 develop에 직접 커밋된 후속 수정(45253e9,
   "데모 비핵심"이라는 스코프 결정과 함께)으로 "연금" 키워드를 완전히
   제거하는 방식(keywords=["은퇴", "노후"])으로 고쳐졌다.
3. 팀 계획서에 "retirement_planner는 데모 범위에서 제외"라고 명시돼 있는데
   코드는 여전히 "은퇴"/"노후" 키워드로 라우팅 가능한 상태였다(실측 확인).
   `spec.py`의 keywords를 완전히 비워서(`[]`) 이 에이전트가 어떤 키워드
   로도 후보가 될 수 없게 막았다 — 근본 원인(오케스트레이터의 substring
   매칭 방식 자체)은 여전히 손대지 않음(agents/retirement_planner/
   CLAUDE.md 참고).
4. keywords=[]만으로는 "사용자가 먼저 말 걸어서 도달"만 막히고,
   asset_organizer._finalize()의 핸드오프(Fast Path)는 keywords와 무관해서
   (pending_handoff를 키워드 매칭보다 먼저 확인) 여전히 동작했다(실측
   확인). "데모 제외" 의도를 완전히 반영하기 위해 이 핸드오프도 마저
   비활성화했다(agent.py의 _finalize() 참고 — 주석 처리해서 나중에
   복원 가능하게 남겨둠). 이제는 체크리스트 완료 후에도 asset_organizer
   에서 그냥 끝난다.

⚠️ `is_stub=True`도 같이 되돌렸지만, 이것만으로는 라우팅이 안 막힌다는 걸
실측으로 확인했다 — orchestrator.planner.classify()의 Standard 경로
(키워드 후보 1개)는 is_stub을 아예 확인하지 않는다. 실질적인 차단 장치는
`keywords=[]`다.
"""

from __future__ import annotations

import pytest

from orchestrator import registry, router
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.mark.parametrize(
    "message",
    [
        "퇴직연금 5억 있어요",
        "예금 1억, 퇴직연금 8천만원 있어요",
        "연금으로 받을게요",
        "연금으로 65살부터 월 100만원씩 받을 거예요",
        "연금으로 받고 싶긴 한데 아직 잘 모르겠어요",
        "노후 준비가 잘 되고 있는지 궁금해요",
        "은퇴 준비 자금이 얼마나 필요해요?",
        "연금 계산해줘",
        "제 예상 연금이 얼마나 될까요",
    ],
)
def test_no_message_matches_retirement_planner_keywords_anymore(message):
    """데모 범위 제외 — keywords=[]라 어떤 문구도 키워드 후보가 될 수 없다.
    "은퇴"/"노후"가 들어간 문구까지 포함해서, 사용자가 먼저 말을 걸어
    이 에이전트에 도달할 방법이 전부 없어야 한다."""
    assert AgentName.RETIREMENT_PLANNER not in registry.match_keywords(message)


def test_pension_mention_mid_checklist_stays_on_asset_organizer():
    """실제 오케스트레이터로 실행: 체크리스트 도중 "퇴직연금"을 언급해도
    더 이상 retirement_planner로 튕기지 않고, 그 턴에 말한 자산이 정상
    반영돼야 한다(실측 재현됐던 회귀 시나리오)."""
    session = "kw-collision-1"
    router.route(AgentInput(session_id=session, user_message="자산 정리해줘"))

    output = router.route(
        AgentInput(session_id=session, user_message="예금 1억, 퇴직연금 5억 있어요")
    )

    assert output.agent == AgentName.ASSET_ORGANIZER
    assets = output.data[AgentName.ASSET_ORGANIZER.value]["assets"]
    assert any(a["type"] == "예금" and a["value"] == 100_000_000 for a in assets)
    assert any(a["type"] == "퇴직연금" and a["value"] == 500_000_000 for a in assets)


def test_pure_pension_query_falls_through_to_default_agent():
    """ "연금 계산해줘"는 키워드 후보가 0개라 직전 에이전트도 없는 새
    세션에서는 default_agent(heir_navigator)로 빠진다 — retirement_planner
    가 전혀 실행되지 않는다."""
    output = router.route(
        AgentInput(session_id="kw-collision-2", user_message="연금 계산해줘")
    )
    assert output.agent == AgentName.HEIR_NAVIGATOR


def test_nohu_euntoe_phrases_no_longer_reach_retirement_planner():
    """⚠️ 데모 제외 반영 확인: 예전엔 "은퇴"/"노후"가 들어간 문구가
    retirement_planner로 정상 라우팅됐지만, keywords=[]로 비운 뒤로는
    다른 곳(여기서는 키워드 후보가 없어 default_agent)으로 빠져야 한다."""
    output = router.route(
        AgentInput(
            session_id="kw-collision-3",
            user_message="노후 준비가 잘 되고 있는지 궁금해요",
        )
    )
    assert output.agent != AgentName.RETIREMENT_PLANNER
    assert output.agent == AgentName.HEIR_NAVIGATOR


def test_asset_organizer_handoff_no_longer_reaches_retirement_planner():
    """⚠️ 이전엔 keywords=[]로 "사용자가 먼저 말 걸어서 도달"만 막고
    asset_organizer._finalize()의 핸드오프(Fast Path)는 keywords와 무관해서
    그대로 동작했다 — 2026-08-30 그 핸드오프 자체도 마저 비활성화하면서
    (agent.py 참고, "데모 제외" 의도를 완전히 반영) 체크리스트 완료 후에도
    더 이상 retirement_planner로 자동으로 이어지지 않는다."""
    session = "kw-collision-4"
    router.route(AgentInput(session_id=session, user_message="자산 정리해줘"))
    router.route(AgentInput(session_id=session, user_message="예금 1억 있어요"))
    done = router.route(AgentInput(session_id=session, user_message="없어요"))
    assert done.handoffs == []

    output = router.route(AgentInput(session_id=session, user_message="네 감사합니다"))
    assert output.agent != AgentName.RETIREMENT_PLANNER
    assert output.agent == AgentName.ASSET_ORGANIZER

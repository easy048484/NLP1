"""
retirement_planner 라우팅 키워드와 asset_organizer 자산 유형/대화 문구 사이의
substring 충돌 회귀 테스트.

배경: retirement_planner의 라우팅 키워드가 예전엔 단독 "연금"이었는데,
orchestrator.registry.match_keywords()가 단순 substring 매칭이라 asset_organizer
의 자산 유형 "퇴직연금"과, 그 에이전트의 퇴직연금 수령방식 후속질문 답변
("연금으로 65살부터 월 100만원씩 받을 거예요" 등)에도 걸려서 체크리스트 도중
대화가 retirement_planner로 튕겨나가며 그 턴 데이터가 유실되는 게 실측
재현됐다. "연금 계산"/"예상 연금"으로 좁혀서 임시 방어한다(근본 원인인
substring 매칭 방식 자체는 오케스트레이터 레벨 결정이라 여기서 고치지 않음
— agents/retirement_planner/CLAUDE.md, agents/asset_organizer/CLAUDE.md 참고).

이 좁힌 키워드로 완전히 해결되는 건 아니다 — 예: "연금으로 생활비가
충당되나요?"(retirement_planner/spec.py의 example_utterances)는 이제 단독
키워드로는 안 걸린다. 이건 알려진 트레이드오프다.
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
    ],
)
def test_asset_organizer_phrases_no_longer_match_retirement_planner_keywords(message):
    """자산 유형 언급·퇴직연금 후속질문 답변은 더 이상 retirement_planner
    키워드에 걸리지 않아야 한다(예전엔 단독 "연금"에 전부 걸렸었음)."""
    assert AgentName.RETIREMENT_PLANNER not in registry.match_keywords(message)


@pytest.mark.parametrize(
    "message",
    [
        "연금 계산해줘",
        "제 예상 연금이 얼마나 될까요",
        "노후 준비가 잘 되고 있는지 궁금해요",
        "은퇴 준비 자금이 얼마나 필요해요?",
    ],
)
def test_genuine_retirement_intent_still_matches(message):
    """좁혀도 진짜 은퇴/노후/연금 계산 요청은 여전히 걸려야 한다 — 과하게
    좁혀서 정상 케이스까지 막으면 안 된다."""
    assert AgentName.RETIREMENT_PLANNER in registry.match_keywords(message)


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


def test_genuine_pension_calculation_request_still_routes_via_real_router():
    output = router.route(
        AgentInput(session_id="kw-collision-2", user_message="연금 계산해줘")
    )
    assert output.agent == AgentName.RETIREMENT_PLANNER


def test_existing_nohu_phrase_still_routes_via_real_router():
    output = router.route(
        AgentInput(
            session_id="kw-collision-3",
            user_message="노후 준비가 잘 되고 있는지 궁금해요",
        )
    )
    assert output.agent == AgentName.RETIREMENT_PLANNER

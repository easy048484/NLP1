"""
retirement_planner 라우팅 키워드와 asset_organizer 자산 유형/대화 문구 사이의
substring 충돌 회귀 테스트.

배경: retirement_planner의 라우팅 키워드가 예전엔 단독 "연금"이었는데,
orchestrator.registry.match_keywords()가 단순 substring 매칭이라 asset_organizer
의 자산 유형 "퇴직연금"과, 그 에이전트의 퇴직연금 수령방식 후속질문 답변
("연금으로 65살부터 월 100만원씩 받을 거예요" 등)에도 걸려서 체크리스트 도중
대화가 retirement_planner로 튕겨나가며 그 턴 데이터가 유실되는 게 실측
재현됐다.

이 충돌은 PR #45 병합 직후 develop에 직접 커밋된 후속 수정(45253e9, "데모
비핵심"이라는 스코프 결정과 함께)으로 "연금" 키워드를 완전히 제거하는 방식으로
이미 고쳐졌다 — 근본 원인인 substring 매칭 방식 자체는 오케스트레이터 레벨
결정이라 손대지 않음(agents/asset_organizer/CLAUDE.md,
agents/retirement_planner/CLAUDE.md 참고).

⚠️ 이 해결 방식은 완전하지 않다 — "연금"을 대체 없이 통째로 빼서, "연금
계산해줘"/"제 예상 연금이 얼마나 될까요" 같은 순수 연금 질의도 이제 키워드
후보 0개가 되어 default_agent(heir_navigator)로 새는 걸 실측으로 확인했다
(아래 테스트가 이 회귀를 그대로 고정해둔다 — "은퇴"/"노후"로 커버되지 않는
순수 연금 질의는 지금 라우팅이 안 된다는 뜻. "데모 비핵심" 스코프 결정상
당장은 허용된 트레이드오프로 보이지만, 재논의 여지가 있다).
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
        "노후 준비가 잘 되고 있는지 궁금해요",
        "은퇴 준비 자금이 얼마나 필요해요?",
    ],
)
def test_nohu_euntoe_phrases_still_match(message):
    """ "은퇴"/"노후"가 들어간 문구는 여전히 걸려야 한다."""
    assert AgentName.RETIREMENT_PLANNER in registry.match_keywords(message)


@pytest.mark.parametrize(
    "message",
    [
        "연금 계산해줘",
        "제 예상 연금이 얼마나 될까요",
        "연금으로 생활비가 충당되나요?",
    ],
)
def test_known_gap_pure_pension_queries_no_longer_route_by_keyword(message):
    """⚠️ 알려진 회귀: "연금"을 대체 없이 통째로 뺀 해결 방식이라, "은퇴"/"노후"가
    없는 순수 연금 질의는 이제 키워드 후보가 0개가 된다 — 이 테스트는 그
    사실을 고정해둔다(개선을 요구하는 실패가 아니라, 회귀를 명시적으로
    드러내는 문서화 목적)."""
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


def test_pure_pension_query_now_falls_through_to_default_agent():
    """⚠️ 알려진 회귀를 실제 오케스트레이터로도 재현: "연금 계산해줘"는 키워드
    후보가 0개라 직전 에이전트도 없는 새 세션에서는 default_agent
    (heir_navigator)로 빠진다 — retirement_planner가 전혀 실행되지 않는다."""
    output = router.route(
        AgentInput(session_id="kw-collision-2", user_message="연금 계산해줘")
    )
    assert output.agent == AgentName.HEIR_NAVIGATOR


def test_existing_nohu_phrase_still_routes_via_real_router():
    output = router.route(
        AgentInput(
            session_id="kw-collision-3",
            user_message="노후 준비가 잘 되고 있는지 궁금해요",
        )
    )
    assert output.agent == AgentName.RETIREMENT_PLANNER

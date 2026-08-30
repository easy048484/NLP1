"""
asset_organizer -> retirement_planner 실제 연결(핸드오프) 테스트.

이 프로젝트에서 "코드는 있는데 실제 대화로는 도달 불가능"한 패턴이 여러 번
반복됐다 — retirement_planner가 extra["asset_organizer"]를 읽을 준비가
됐다는 것과, 체크리스트 대화가 실제로 거기까지 이어진다는 것은 별개다.
그래서 여기서는 가짜 에이전트가 아니라 실제 asset_organizer/retirement_planner
run()과 실제 orchestrator.router.route()를 그대로 통해서 검증한다
(test_orchestrator.py는 가짜 에이전트로 라우팅 규약만 보는 다른 담당자
영역이라 이 통합 테스트는 별도 파일로 둔다).
"""

from __future__ import annotations

import pytest

from orchestrator import router
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_checklist_completion_auto_handoffs_to_retirement_planner_next_turn():
    """체크리스트가 끝나면 다음 턴은 사용자가 은퇴/노후/연금 키워드를
    새로 말하지 않아도 자동으로 retirement_planner로 넘어가야 한다
    (orchestrator의 Fast Path — pending_handoff). 이게 없으면 체크리스트가
    끝난 뒤에도 asset_organizer가 같은 요약을 반복하며 대화가 거기서
    멈춘다(실측으로 확인된 회귀 시나리오)."""
    session = "handoff-e2e-1"

    output = router.route(AgentInput(session_id=session, user_message="자산 정리해줘"))
    assert output.agent == AgentName.ASSET_ORGANIZER

    output = router.route(
        AgentInput(
            session_id=session,
            user_message=(
                "예금 1억, 주식 5천만원, 펀드 2천만원, 부동산 5억, "
                "자동차 3천만원, 대출 3천만원, 보험 5천만원 있어요"
            ),
        )
    )
    assert output.agent == AgentName.ASSET_ORGANIZER

    output = router.route(AgentInput(session_id=session, user_message="없어요"))
    assert output.agent == AgentName.ASSET_ORGANIZER

    output = router.route(AgentInput(session_id=session, user_message="몰라요"))
    assert output.agent == AgentName.ASSET_ORGANIZER
    assert any(h.target == AgentName.RETIREMENT_PLANNER for h in output.handoffs)

    # 키워드가 전혀 없는 평범한 발화인데도 Fast Path로 자동 전환돼야 한다.
    output = router.route(AgentInput(session_id=session, user_message="네 감사합니다"))
    assert output.agent == AgentName.RETIREMENT_PLANNER
    assert output.path == "fast"
    assert "나이" in output.reply


def test_itemized_checklist_data_actually_reaches_simulation():
    """핸드오프 이후 실제로 이어지는 대화에서, asset_organizer가 모은
    itemized 자산·부채(유동성, 부채 모드)가 시뮬레이션 결과에 실제로
    반영되는지 끝까지 실행해서 확인한다 — 단위 테스트로 각 조각(추출,
    변환, 계산)이 맞더라도 전체가 실제로 이어 붙는지는 별개 문제다."""
    session = "handoff-e2e-2"

    router.route(AgentInput(session_id=session, user_message="자산 정리해줘"))
    router.route(
        AgentInput(
            session_id=session,
            user_message="예금 1억, 부동산 5억, 대출 3천만원 있어요",
        )
    )
    router.route(AgentInput(session_id=session, user_message="없어요"))
    done = router.route(AgentInput(session_id=session, user_message="몰라요"))
    assert any(h.target == AgentName.RETIREMENT_PLANNER for h in done.handoffs)

    # retirement_planner의 첫 턴은 (핸드오프로 왔든 키워드로 왔든) 질문을
    # 던지는 턴이라 이 메시지 자체에서 나이를 파싱하지 않는다(기존 설계
    # — test_asks_current_age_then_monthly_expense_then_simulates와 동일).
    output = router.route(AgentInput(session_id=session, user_message="네 감사합니다"))
    assert output.agent == AgentName.RETIREMENT_PLANNER
    assert "나이" in output.reply

    output = router.route(AgentInput(session_id=session, user_message="60살이에요"))
    assert "생활비" in output.reply

    output = router.route(
        AgentInput(session_id=session, user_message="생활비는 200만원 정도예요")
    )

    # 유동자산(예금 1억) - 단순모드 부채(3천만원) = 7천만원, 연 2400만원
    # 생활비면 3년을 못 버틴다 — 부동산(비유동) 5억이 실제로 계산에서
    # 빠지지 않았다면 고갈되지 않아야 정상인데 반대로 나와야 버그다.
    assert "고갈될 것으로 예상됩니다" in output.reply

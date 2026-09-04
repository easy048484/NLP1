"""
asset_organizer -> retirement_planner 연결 테스트.

⚠️ 2026-08-30 데모 제외 결정으로 이 연결은 비활성화됐다(agent.py의
_finalize() 참고 — 핸드오프를 주석 처리해서 나중에 복원 가능하게 남겨둠,
retirement_planner/spec.py의 keywords=[]와 같은 결정 계열). 이 파일은
원래 실제 asset_organizer/retirement_planner run()과 실제
orchestrator.router.route()를 그대로 통해서 "체크리스트 완료 → 자동으로
시뮬레이션까지 이어짐"을 검증했는데(이 프로젝트에서 "코드는 있는데 실제
대화로는 도달 불가능"한 패턴이 여러 번 반복됐어서), 이제는 반대로
"체크리스트 완료 후 정말 거기서 끝나는지"를 검증한다.

retirement_planner 자체의 엔진·itemized 데이터 소비 로직(유동성, 부채
정밀/단순 모드 등)은 여전히 유효한 코드이고 test_retirement_planner_agent.py
가 agent.run()을 직접 호출해서 계속 검증한다 — 없어진 건 "도달 경로"뿐이라
그 테스트들은 손대지 않았다.
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


def test_checklist_completion_no_longer_hands_off_and_ends_at_asset_organizer():
    """⚠️ 예전엔 체크리스트가 끝나면 다음 턴이 키워드 없이도 자동으로
    retirement_planner로 넘어갔다(Fast Path). 데모 제외 결정 이후에는
    handoffs가 비어 있어야 하고, 다음 턴도 계속 asset_organizer(또는
    키워드 없는 평범한 발화라면 last_agent 규칙에 따라 여전히
    asset_organizer)에 머물러야 한다 — retirement_planner로 넘어가면
    안 된다."""
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

    # 대출은 remaining_balance만 확인되면 수집 완료다(상환 정보 후속질문
    # 없음) — 나머지 카테고리도 이번 턴에 다 확인됐으니 "없어요" 한 번으로
    # 바로 마무리된다.
    output = router.route(AgentInput(session_id=session, user_message="없어요"))
    assert output.agent == AgentName.ASSET_ORGANIZER
    assert output.data[AgentName.ASSET_ORGANIZER.value]["status"] == "done"
    assert output.handoffs == []  # 예전엔 여기서 retirement_planner 핸드오프가 걸렸다
    assert "순자산" in output.reply

    # 키워드 없는 평범한 발화를 보내도 retirement_planner로 튕기면 안 된다
    # — pending_handoff가 비어 있으므로 last_agent 규칙에 따라
    # asset_organizer에 머물러야 한다.
    output = router.route(AgentInput(session_id=session, user_message="네 감사합니다"))
    assert output.agent == AgentName.ASSET_ORGANIZER
    assert output.agent != AgentName.RETIREMENT_PLANNER


@pytest.mark.skip(
    reason=(
        "2026-08-30 데모 제외 결정으로 asset_organizer -> retirement_planner "
        "핸드오프가 비활성화되면서, 이 테스트가 검증하던 '체크리스트 완료 후 "
        "대화가 자동으로 시뮬레이션까지 이어진다'는 시나리오 자체가 더 이상 "
        "일어나지 않는다. retirement_planner의 itemized 데이터 소비 로직 "
        "자체는 여전히 유효하고 test_retirement_planner_agent.py의 "
        "test_uses_itemized_asset_organizer_extra_when_present 등이 agent.run() "
        "직접 호출로 계속 검증한다 — 없어진 건 라우터를 통한 '도달 경로'뿐이라 "
        "억지로 라우팅 우회 검증으로 바꾸지 않고 스킵으로 남겨둔다(핸드오프가 "
        "복원되면 이 테스트도 그대로 복원 가능)."
    )
)
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

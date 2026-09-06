"""heir_navigator — 사용자가 특정 단계를 물으면 그 단계부터 답한다.

배경: 절차 플랜은 "지금 할 수 있는 단계"의 서류·기관만 사실 블록에 실었고,
사용자 질문은 재료 선택에 영향을 주지 않았다. 그래서 "상속등기 서류가 뭐가
필요해요?"에도 매번 "먼저 할 일: 사망신고"로 시작하는 같은 답이 나갔다(실측).
knowledge.py 에 등기 서류가 이미 있는데 꺼내는 경로가 없었던 것.

여기서는 (1) 별칭 매칭이 질문만 잡는지, (2) 플랜에 asked_step 이 선행 단계
체인과 함께 실리는지, (3) 사망일이 없어도 되묻기 대신 답부터 하고 사망일은 뒤에
묻는지를 LLM 없이 검증한다.
"""

from __future__ import annotations

import os
from datetime import date

os.environ["HEIR_NAVIGATOR_DISABLE_LLM"] = "1"

from agents import heir_navigator  # noqa: E402
from agents.heir_navigator import prompts  # noqa: E402
from agents.heir_navigator.planner import build_plan  # noqa: E402
from agents.heir_navigator.procedure import (  # noqa: E402
    STEP_BY_ID,
    StepId,
    find_asked_step,
    prerequisite_chain,
)
from agents.heir_navigator.state import STATE_KEY, HeirState  # noqa: E402
from schemas import AgentInput  # noqa: E402

TODAY = date(2026, 9, 6)


# ------------------------------------------------------------- 별칭 매칭


def test_find_asked_step_matches_question_about_registration():
    step = find_asked_step("상속등기 하려면 서류가 뭐가 필요해요?")
    assert step is not None and step.id is StepId.REGISTRATION


def test_find_asked_step_ignores_progress_reports():
    """단계 이름이 나와도 질문 신호가 없으면 잡지 않는다 — 진행 보고는 slots.py
    완료 패턴의 몫이고, 여기서 잡으면 '상속세 신고했어요'에 상속세 안내가 붙는다."""
    assert find_asked_step("상속세 신고했어요") is None
    assert find_asked_step("사망신고는 어제 했어요") is None


def test_find_asked_step_prefers_specific_alias():
    # "유언장 존재 여부 확인" 단계의 별칭("유언장")과 "포기"(약한 별칭)가 같이
    # 있어도 더 구체적인 쪽을 고른다.
    step = find_asked_step("유언장이 있는지 확인하려면 어떻게 해요?")
    assert step is not None and step.id is StepId.WILL_CHECK


def test_find_asked_step_none_for_general_question():
    assert find_asked_step("아버지가 어제 돌아가셨어요. 뭐부터 해야 하나요?") is None


# ------------------------------------------------------------- 플랜


def test_prerequisite_chain_follows_requirements_transitively():
    chain = prerequisite_chain(STEP_BY_ID[StepId.REGISTRATION], completed=set())
    assert [s.id for s in chain] == [StepId.DIVISION, StepId.ACCEPT_DECIDE]
    # 승인/포기 결정을 끝냈으면 분할협의만 남는다.
    chain = prerequisite_chain(
        STEP_BY_ID[StepId.REGISTRATION], completed={StepId.ACCEPT_DECIDE}
    )
    assert [s.id for s in chain] == [StepId.DIVISION]


def test_plan_carries_asked_step_even_when_blocked():
    state = HeirState(death_date=date(2026, 8, 10))
    plan = build_plan(state, today=TODAY, asked_step=StepId.REGISTRATION)
    asked = plan.asked_step
    assert asked is not None
    assert asked.status == "blocked"
    assert asked.prerequisites == [
        "상속재산분할협의",
        "단순승인 / 한정승인 / 상속포기 결정",
    ]
    assert "소유권이전등기 신청서" in asked.documents
    assert any("등기소" in a for a in asked.agencies)
    # 등기는 next_actions(지금 할 수 있는 일)에는 여전히 없다 — 그건 상태 기반.
    assert all(a.step is not StepId.REGISTRATION for a in plan.next_actions)


def test_plan_without_asked_step_is_unchanged():
    state = HeirState(death_date=date(2026, 8, 10))
    assert build_plan(state, today=TODAY).asked_step is None


# ------------------------------------------------------------- 렌더링


def test_facts_block_puts_asked_step_before_next_actions():
    state = HeirState(death_date=date(2026, 8, 10))
    plan = build_plan(state, today=TODAY, asked_step=StepId.REGISTRATION)
    facts = prompts.facts_block(plan, state, today=TODAY)
    assert "[질문하신 단계: 상속등기·명의이전]" in facts
    assert facts.index("[질문하신 단계") < facts.index("[지금 할 수 있는 일]")
    assert "소유권이전등기 신청서" in facts
    assert "단순승인 / 한정승인 / 상속포기 결정 → 상속재산분할협의" in facts


def test_deterministic_reply_answers_asked_step_first():
    state = HeirState(death_date=date(2026, 8, 10))
    plan = build_plan(state, today=TODAY, asked_step=StepId.REGISTRATION)
    reply = prompts.deterministic_reply(plan, state)
    assert reply.startswith("**상속등기·명의이전**")
    assert "소유권이전등기 신청서" in reply
    assert "먼저 끝내야 하는 것" in reply
    # 현재 할 일(사망신고)은 뒤에 붙는다 — 사라지진 않는다.
    assert reply.index("소유권이전등기 신청서") < reply.index("사망신고")


# ------------------------------------------------------------- run() 통합


def test_run_answers_registration_question_without_death_date():
    """사망일을 모르는 첫 턴이어도 '돌아가신 날짜가 언제인가요?'만 돌려주지 않고,
    물어본 등기 서류부터 답한 뒤 맨 끝에 사망일을 묻는다."""
    out = heir_navigator.run(
        AgentInput(
            session_id="asked-1",
            user_message="상속등기 하려면 서류가 뭐가 필요해요?",
            context={"today": TODAY.isoformat()},
        )
    )
    reply = out.reply
    assert "소유권이전등기 신청서" in reply
    assert "돌아가신 날짜" in reply
    assert reply.index("소유권이전등기 신청서") < reply.index("돌아가신 날짜")
    # 사망일을 물어봤다고 표시돼 다음 턴에 같은 질문을 반복하지 않는다.
    assert out.data["asked_slot"] == "death_date"
    assert "death_date" in out.data[STATE_KEY]["asked"]


def test_run_answers_registration_question_with_death_date_known():
    first = heir_navigator.run(
        AgentInput(
            session_id="asked-2",
            user_message="아버지가 2026년 8월 10일에 돌아가셨어요",
            context={"today": TODAY.isoformat()},
        )
    )
    assert "돌아가신 날짜" not in first.reply  # 사망일이 잡혀 일반 안내가 나감
    second = heir_navigator.run(
        AgentInput(
            session_id="asked-2",
            user_message="상속등기 하려면 서류가 뭐가 필요해요?",
            context={"today": TODAY.isoformat(), STATE_KEY: first.data[STATE_KEY]},
        )
    )
    reply = second.reply
    assert reply.startswith("**상속등기·명의이전**")
    assert "소유권이전등기 신청서" in reply
    assert "돌아가신 날짜" not in reply  # 이미 아는 걸 다시 묻지 않는다
    # 기한 정보(사망신고 등)는 등기 답변 뒤에 그대로 이어진다.
    assert "사망신고" in reply


def test_general_question_still_asks_death_date_first():
    """asked_step 이 없는 일반 질문은 예전 동작 그대로 — 사망일부터 묻는다."""
    out = heir_navigator.run(
        AgentInput(
            session_id="asked-3",
            user_message="아버지가 돌아가셨어요. 뭐부터 해야 하나요?",
            context={"today": TODAY.isoformat()},
        )
    )
    assert out.reply.startswith("안내를 드리려면 먼저 여쭐 게 있습니다")


def test_llm_compose_gets_death_date_question_appended_when_model_omits_it(monkeypatch):
    """LLM 경로: 모델이 '끝에 사망일을 물으라'는 지시를 빠뜨려도 코드가 붙인다."""
    from agents.heir_navigator import graph

    monkeypatch.delenv("HEIR_NAVIGATOR_DISABLE_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        graph, "complete", lambda **kw: "등기에는 이런 서류가 필요합니다."
    )
    # 슬롯 추출기의 LLM 폴백은 규칙이 실패할 때만 부르므로, 여기서는 규칙으로 끝난다.
    monkeypatch.setattr("agents.heir_navigator.slots.llm_based", lambda *a, **k: None)
    out = heir_navigator.run(
        AgentInput(
            session_id="asked-llm",
            user_message="상속등기 하려면 서류가 뭐가 필요해요?",
            context={"today": TODAY.isoformat()},
        )
    )
    assert out.reply.startswith("등기에는 이런 서류가 필요합니다.")
    assert "돌아가신 날짜" in out.reply
    assert out.reply.index("돌아가신 날짜") < out.reply.index("안내 기준입니다")

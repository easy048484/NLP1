"""상속인 절차 내비게이터 테스트.

기한 계산이 이 에이전트에서 가장 잘 틀리고 가장 크게 다치는 부분이라
거기에 테스트를 집중했습니다. LLM은 태우지 않습니다(use_llm=False 경로).
"""

from __future__ import annotations

import os
from datetime import date

import pytest

# 테스트에서는 LLM을 절대 태우지 않습니다.
os.environ["HEIR_NAVIGATOR_DISABLE_LLM"] = "1"

from agents import heir_navigator  # noqa: E402
from agents.heir_navigator import guardrails, ics, slots  # noqa: E402
from agents.heir_navigator.consent import build_checklist  # noqa: E402
from agents.heir_navigator.planner import build_plan  # noqa: E402
from agents.heir_navigator.procedure import (
    StepId,
    add_months,
    compute_deadlines,
    month_end,
)  # noqa: E402
from agents.heir_navigator.state import (
    STATE_KEY,
    HeirState,
    SlotUpdate,
    load_state,
)  # noqa: E402
from schemas import AgentInput, AgentName  # noqa: E402


# --------------------------------------------------------------- 날짜 산술


@pytest.mark.parametrize(
    "base,months,expected",
    [
        (date(2026, 1, 10), 3, date(2026, 4, 10)),
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # 해당 일이 없으면 말일로
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # 윤년
        (date(2025, 11, 30), 3, date(2026, 2, 28)),  # 해를 넘김
        (date(2025, 12, 31), 6, date(2026, 6, 30)),
    ],
)
def test_add_months(base, months, expected):
    assert add_months(base, months) == expected


def test_month_end():
    assert month_end(date(2026, 2, 5)) == date(2026, 2, 28)
    assert month_end(date(2024, 2, 5)) == date(2024, 2, 29)
    assert month_end(date(2026, 12, 1)) == date(2026, 12, 31)


# ----------------------------------------------------------------- 기한 계산


def test_no_death_date_means_no_deadlines():
    assert compute_deadlines(death_date=None) == []


def test_accept_decide_counts_from_known_date_not_death_date():
    """민법 1019조의 기산점은 사망일이 아니라 '상속개시를 안 날'."""
    items = {
        item.step: item
        for item in compute_deadlines(
            death_date=date(2026, 1, 10),
            known_date=date(2026, 3, 2),
            today=date(2026, 3, 5),
        )
    }
    accept = items[StepId.ACCEPT_DECIDE]
    assert accept.due_date == date(2026, 6, 2)
    assert accept.base_date == date(2026, 3, 2)
    assert accept.base_estimated is False


def test_known_date_falls_back_to_death_date_and_is_flagged():
    items = {
        item.step: item
        for item in compute_deadlines(
            death_date=date(2026, 1, 10), today=date(2026, 1, 15)
        )
    }
    accept = items[StepId.ACCEPT_DECIDE]
    assert accept.due_date == date(2026, 4, 10)
    assert accept.base_estimated is True


def test_tax_deadlines_count_from_month_end():
    """상속세·취득세는 '상속개시일이 속하는 달의 말일'부터 6개월."""
    items = {
        item.step: item
        for item in compute_deadlines(
            death_date=date(2026, 1, 10), today=date(2026, 1, 15)
        )
    }
    for step in (StepId.INHERIT_TAX, StepId.ACQ_TAX):
        assert items[step].base_date == date(2026, 1, 31)
        assert items[step].due_date == date(2026, 7, 31)


def test_death_report_is_one_month():
    items = {
        item.step: item
        for item in compute_deadlines(
            death_date=date(2026, 3, 5), today=date(2026, 3, 6)
        )
    }
    assert items[StepId.DEATH_REPORT].due_date == date(2026, 4, 5)


def test_days_left_and_overdue():
    items = {
        item.step: item
        for item in compute_deadlines(
            death_date=date(2026, 1, 10), today=date(2026, 5, 1)
        )
    }
    accept = items[StepId.ACCEPT_DECIDE]  # 2026-04-10 만료
    assert accept.days_left == -21
    assert accept.overdue is True


def test_every_deadline_carries_a_disclaimer_and_law():
    for item in compute_deadlines(
        death_date=date(2026, 1, 10), today=date(2026, 1, 11)
    ):
        assert item.disclaimer, "안내 기준 문구는 항상 붙어야 합니다"
        assert item.law, "근거 조문 없는 기한을 내보내면 안 됩니다"


def test_completed_steps_sort_last():
    items = compute_deadlines(
        death_date=date(2026, 1, 10),
        completed={StepId.DEATH_REPORT},
        today=date(2026, 1, 11),
    )
    assert items[-1].completed is True


# ------------------------------------------------------------------- 절차 DAG


def test_accept_decide_is_not_blocked_by_asset_search():
    """3개월 시계는 재산조회를 기다리는 동안에도 흐릅니다. 병렬이어야 합니다."""
    plan = build_plan(HeirState(death_date=date(2026, 1, 10)), today=date(2026, 1, 15))
    ready = {entry.step for entry in plan.timeline if entry.status == "ready"}
    assert StepId.ACCEPT_DECIDE in ready
    assert StepId.ONE_STOP in ready


def test_division_is_blocked_until_accept_decide():
    plan = build_plan(HeirState(death_date=date(2026, 1, 10)), today=date(2026, 1, 15))
    division = next(entry for entry in plan.timeline if entry.step == StepId.DIVISION)
    assert division.status == "blocked"
    assert division.blocked_by


def test_debt_branches_only_appear_when_debt_confirmed():
    state = HeirState(death_date=date(2026, 1, 10), completed={StepId.ASSET_SEARCH})
    assert build_plan(state, today=date(2026, 2, 1)).branches == []

    with_debt = state.model_copy(update={"has_debt": "yes"})
    branches = build_plan(with_debt, today=date(2026, 2, 1)).branches
    assert {branch.title for branch in branches} == {"단순승인", "한정승인", "상속포기"}


def test_handoff_to_tax_calculator_after_asset_search():
    state = HeirState(death_date=date(2026, 1, 10), completed={StepId.ASSET_SEARCH})
    assert build_plan(state, today=date(2026, 2, 1)).handoff == "tax_calculator"


def test_handoff_to_decedent_estate_when_will_exists():
    state = HeirState(death_date=date(2026, 1, 10), will_exists="yes")
    assert build_plan(state, today=date(2026, 2, 1)).handoff == "decedent_estate"


# ------------------------------------------------------------------- 경계


@pytest.mark.parametrize(
    "message",
    [
        "한정승인이랑 상속포기 중에 뭐가 나아요?",
        "상속포기를 해야 할까요?",
        "한정승인 추천해 주세요",
    ],
)
def test_choice_recommendation_is_blocked(message):
    hit = guardrails.check_input(message)
    assert hit is not None
    assert hit.boundary is guardrails.Boundary.CHOICE_RECOMMENDATION
    # 막되, 선택지와 결과는 전부 제공해야 합니다.
    for option in ("단순승인", "한정승인", "상속포기"):
        assert option in hit.reply


def test_plain_explanation_request_is_not_blocked():
    """설명 요청까지 막으면 안 됩니다."""
    assert guardrails.check_input("한정승인이 뭔가요?") is None
    assert guardrails.check_input("사망신고는 어디서 하나요?") is None


def test_division_and_conflict_are_blocked():
    assert (
        guardrails.check_input("형이랑 얼마씩 나눠야 하나요?").boundary
        is guardrails.Boundary.DIVISION_INTERVENTION
    )
    assert (
        guardrails.check_input("동생이 도장을 안 찍어줘서 싸우고 있어요").boundary
        is guardrails.Boundary.FAMILY_CONFLICT
    )


def test_output_guardrail_catches_recommendation():
    leaked = "상황을 보니 한정승인을 하시는 게 좋겠습니다."
    assert guardrails.check_output(leaked) is guardrails.Boundary.CHOICE_RECOMMENDATION
    assert (
        guardrails.check_output("한정승인은 재산 범위에서만 빚을 갚는 제도입니다.")
        is None
    )


# ------------------------------------------------------------------- 슬롯


def test_rule_based_extracts_explicit_date():
    assert slots.rule_based("2026년 1월 10일에 돌아가셨어요").death_date == date(
        2026, 1, 10
    )
    assert slots.rule_based("2026-01-10에 돌아가셨습니다").death_date == date(
        2026, 1, 10
    )


def test_rule_based_detects_completed_steps():
    update = slots.rule_based("사망신고는 했고 안심상속도 신청했어요")
    assert StepId.DEATH_REPORT in update.completed_steps
    assert StepId.ONE_STOP in update.completed_steps


def test_rule_based_detects_debt():
    assert slots.rule_based("대출이 좀 남아있다고 하네요").has_debt == "yes"
    assert slots.rule_based("빚은 없는 걸로 확인됐어요").has_debt == "no"


def test_merge_does_not_erase_known_values():
    state = HeirState(death_date=date(2026, 1, 10), has_debt="yes")
    merged = state.merge(SlotUpdate())
    assert merged.death_date == date(2026, 1, 10)
    assert merged.has_debt == "yes"


# ------------------------------------------------------------------- 협의


def test_consent_checklist_from_minimal_family_graph():
    checklist = build_checklist({"spouse_alive": True, "num_children": 2})
    assert checklist.heir_count == 3
    assert any("전원" in note for note in checklist.notes)


def test_consent_checklist_flags_minor_heir():
    checklist = build_checklist(
        {"heirs": [{"name": "김민수", "relation": "child", "minor": True}]}
    )
    assert checklist.needs_special_representative is True


def test_consent_checklist_degrades_without_graph():
    assert build_checklist(None).available is False


# ------------------------------------------------------------------- 캘린더


def test_ics_has_one_event_per_pending_deadline():
    deadlines = compute_deadlines(death_date=date(2026, 1, 10), today=date(2026, 1, 15))
    text = ics.build_calendar(deadlines, session_id="s1")
    assert text.startswith("BEGIN:VCALENDAR")
    assert text.count("BEGIN:VEVENT") == len(deadlines)
    assert "END:VCALENDAR" in text


# ------------------------------------------------------------------- 계약


def test_first_turn_asks_for_death_date():
    output = heir_navigator.run(
        AgentInput(session_id="t1", user_message="상속 절차 알려주세요")
    )
    assert output.agent == AgentName.HEIR_NAVIGATOR
    assert "날짜" in output.reply
    assert STATE_KEY in output.data


def test_state_round_trips_across_turns():
    first = heir_navigator.run(
        AgentInput(session_id="t2", user_message="2026년 1월 10일에 돌아가셨어요")
    )
    second = heir_navigator.run(
        AgentInput(
            session_id="t2",
            user_message="사망신고는 했어요",
            context={**first.data, "today": "2026-02-01"},
        )
    )
    state = load_state(second.data)
    assert state.death_date == date(2026, 1, 10)
    assert StepId.DEATH_REPORT in state.completed


def test_reply_includes_deadline_and_disclaimer_once_date_known():
    output = heir_navigator.run(
        AgentInput(
            session_id="t3",
            user_message="2026년 1월 10일에 돌아가셨고 사망신고랑 안심상속 신청도 했어요",
            context={"today": "2026-02-01"},
        )
    )
    assert "안내 기준" in output.reply
    assert output.data["plan"]["deadlines"]
    assert "calendar_ics" in output.data


def test_guidance_comes_before_follow_up_question():
    """질문 세 개를 연달아 던지지 않고, 안내를 먼저 준 뒤 하나만 되물어야 합니다."""
    output = heir_navigator.run(
        AgentInput(
            session_id="t6",
            user_message="2026년 1월 10일에 돌아가셨고 사망신고랑 안심상속 신청도 했어요",
            context={"today": "2026-02-01"},
        )
    )
    # 안내가 먼저 나오고
    assert "안내 기준" in output.reply
    assert output.data["plan"]["next_actions"]
    # 되묻는 건 뒤에 하나만
    assert output.data["plan"]["blocking_slot"] is None
    assert output.data["asked_slot"] == output.data["plan"]["follow_up"]
    # 그 질문은 답변 본문이 아니라 별도 질문 블록(pending_questions)으로 나간다
    pending = output.data["pending_questions"]
    assert len(pending) == 1
    assert pending[0]["requirement"] == output.data["plan"]["follow_up"]
    assert pending[0]["options"]
    from agents.heir_navigator.prompts import QUESTIONS

    assert QUESTIONS[output.data["plan"]["follow_up"]] not in output.reply


def test_non_urgent_deadlines_are_still_shown():
    """3개월·6개월짜리는 '아직 멀었다'고 숨기면 존재 자체를 모르고 지나갑니다."""
    output = heir_navigator.run(
        AgentInput(
            session_id="t8",
            user_message="2026년 1월 10일에 돌아가셨어요",
            context={"today": "2026-02-20"},  # 3개월 기한까지 49일 = 임박 범위 밖
        )
    )
    assert "한정승인·상속포기 신고 기한" in output.reply
    assert "2026-04-10" in output.reply


def test_only_death_date_blocks_guidance():
    plan_missing = heir_navigator.run(
        AgentInput(session_id="t7", user_message="어떻게 해야 하죠")
    )
    assert "날짜" in plan_missing.reply
    assert "plan" in plan_missing.data
    assert plan_missing.data["plan"]["blocking_slot"] == "death_date"


def test_boundary_question_short_circuits_without_plan():
    output = heir_navigator.run(
        AgentInput(session_id="t4", user_message="한정승인이랑 포기 중에 뭐가 나아요?")
    )
    assert output.data.get("boundary") == "choice_recommendation"
    assert "plan" not in output.data  # 절차 계산을 돌리지 않고 바로 빠져야 함


def test_pre_planning_hands_back_to_decedent_estate():
    output = heir_navigator.run(
        AgentInput(
            session_id="t5", user_message="아직 돌아가시진 않았고 미리 준비하고 싶어요"
        )
    )
    assert output.next_action == "handoff:decedent_estate"

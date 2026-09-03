"""세션 대화 이력 + 확정 슬롯 보호 테스트.

배경: 슬롯 추출기가 "이번 턴 발화 한 줄"만 받던 시절에는, 에이전트가
"돌아가신 날짜가 언제인가요?"라고 묻고 사용자가 "어제"라고 답하면 그 "어제"가
무엇의 날짜인지 알 근거가 없어 null 이 나왔고, 같은 질문이 무한히 반복됐습니다.
그래서 세션에 대화 원문을 쌓아 추출기에 함께 넘기게 바꿨습니다.

그 대가로 새로 생기는 위험이 하나 있습니다. 이력을 보면 추출기가 매 턴 같은
슬롯을 재발행하고, HeirState.merge 가 그때마다 덮어씁니다. 대부분은 같은 값이라
티가 안 나지만 상대 날짜는 다릅니다 — 이력에 남은 "어제"는 매번 그날의 today
기준으로 다시 계산되므로 자정을 넘겨 대화가 이어지면 death_date 가 하루 밀립니다.
HeirState.confirmed 가 그걸 막습니다.

LLM 은 태우지 않습니다. 전부 순수 파이썬 경로입니다.
"""

from __future__ import annotations

from datetime import date

import pytest

from agents.heir_navigator.state import HeirState, SlotUpdate
from llm.claude import normalize_messages
from orchestrator import router
from orchestrator.session_store import (
    _HISTORY_MAX_CHARS_ASSISTANT,
    _HISTORY_MAX_CHARS_TOTAL,
    _HISTORY_MAX_CHARS_USER,
    _HISTORY_MAX_MESSAGES,
    InMemorySessionStore,
    SessionState,
)
from schemas import AgentInput, AgentName, AgentOutput

# --------------------------------------------------------- SessionState.history


def test_append_history_keeps_order_and_skips_blank():
    state = SessionState()
    state.append_history("user", "어제 부모님이 돌아가셨어요")
    state.append_history("assistant", "상심이 크시겠습니다.")
    state.append_history("user", "   ")  # 공백만 있는 발화는 남기지 않는다

    assert state.history == [
        {"role": "user", "content": "어제 부모님이 돌아가셨어요"},
        {"role": "assistant", "content": "상심이 크시겠습니다."},
    ]


def test_append_history_rejects_unknown_role():
    state = SessionState()
    with pytest.raises(ValueError):
        state.append_history("system", "안 됩니다")


def test_assistant_message_is_truncated_from_the_front_keeping_the_question():
    """에이전트 답변은 뒤를 남긴다 — 되묻는 질문이 항상 끝에 붙기 때문."""
    question = "돌아가신 날짜가 언제인가요?"
    long_reply = ("절차 안내가 길게 이어집니다. " * 500) + question
    assert len(long_reply) > _HISTORY_MAX_CHARS_ASSISTANT

    state = SessionState()
    state.append_history("assistant", long_reply)

    stored = state.history[0]["content"]
    assert stored.endswith(question)
    assert len(stored) <= _HISTORY_MAX_CHARS_ASSISTANT + 1  # 잘림 표시 한 글자


def test_user_message_is_truncated_from_the_back():
    """사용자 발화는 앞을 남긴다 — 하려는 말이 보통 앞에 있다."""
    head = "제가 여쭤보고 싶은 것은"
    long_message = head + ("가" * (_HISTORY_MAX_CHARS_USER + 500))

    state = SessionState()
    state.append_history("user", long_message)

    stored = state.history[0]["content"]
    assert stored.startswith(head)
    assert len(stored) <= _HISTORY_MAX_CHARS_USER + 1


def test_history_is_capped_by_message_count():
    state = SessionState()
    for i in range(_HISTORY_MAX_MESSAGES * 2):
        state.append_history("user" if i % 2 == 0 else "assistant", f"메시지 {i}")

    assert len(state.history) == _HISTORY_MAX_MESSAGES
    # 오래된 것부터 버리므로 마지막 메시지는 살아 있어야 한다.
    assert state.history[-1]["content"] == f"메시지 {_HISTORY_MAX_MESSAGES * 2 - 1}"


def test_history_is_capped_by_total_chars():
    state = SessionState()
    chunk = "가" * 1000
    for _ in range(_HISTORY_MAX_MESSAGES):
        state.append_history("user", chunk)

    total = sum(len(m["content"]) for m in state.history)
    assert total <= _HISTORY_MAX_CHARS_TOTAL


def test_history_round_trips_through_json_context():
    """컬럼 추가 없이 per_agent_context 의 _shared 아래로 오간다."""
    state = SessionState()
    state.append_history("user", "어제 돌아가셨어요")
    state.append_history("assistant", "사망신고부터 하셔야 합니다.")

    restored = SessionState.from_json_context(state.to_json_context())

    assert restored.history == state.history


def test_corrupted_history_entries_are_dropped_not_fatal():
    """저장된 값 한 줄이 깨져도 대화 전체를 잃지 않는다."""
    raw = {
        SessionState.SHARED_KEY: {
            "history": [
                {"role": "user", "content": "정상"},
                {"role": "system", "content": "역할이 이상함"},
                {"role": "assistant", "content": 123},
                "문자열이 통째로 들어옴",
                {"role": "assistant", "content": "정상2"},
            ]
        }
    }

    restored = SessionState.from_json_context(raw)

    assert restored.history == [
        {"role": "user", "content": "정상"},
        {"role": "assistant", "content": "정상2"},
    ]


def test_empty_history_is_not_written_to_json():
    assert SessionState.SHARED_KEY not in SessionState().to_json_context()


# ------------------------------------------------------ HeirState.confirmed


def test_first_value_is_taken_and_marked_confirmed():
    state = HeirState().merge(SlotUpdate(death_date=date(2026, 9, 1)))

    assert state.death_date == date(2026, 9, 1)
    assert "death_date" in state.confirmed


def test_confirmed_value_is_not_overwritten_by_re_extraction():
    """자정을 넘겨 '어제'가 하루 뒤로 재계산돼도 확정값은 버틴다."""
    state = HeirState().merge(SlotUpdate(death_date=date(2026, 9, 1)))

    drifted = state.merge(SlotUpdate(death_date=date(2026, 9, 2)))

    assert drifted.death_date == date(2026, 9, 1)


def test_explicit_correction_overwrites_confirmed_value():
    state = HeirState().merge(SlotUpdate(death_date=date(2026, 9, 1)))

    corrected = state.merge(
        SlotUpdate(death_date=date(2026, 8, 30), corrections=["death_date"])
    )

    assert corrected.death_date == date(2026, 8, 30)
    assert "death_date" in corrected.confirmed


def test_correction_of_one_slot_does_not_unlock_another():
    state = HeirState().merge(SlotUpdate(death_date=date(2026, 9, 1), has_debt="yes"))

    result = state.merge(
        SlotUpdate(death_date=date(2026, 9, 2), has_debt="no", corrections=["has_debt"])
    )

    assert result.death_date == date(2026, 9, 1)  # 정정 대상이 아니므로 그대로
    assert result.has_debt == "no"  # 정정 대상이므로 갱신


def test_unknown_correction_names_are_dropped():
    update = SlotUpdate(corrections=["death_date", "존재하지_않는_슬롯", "turns"])

    assert update.corrections == ["death_date"]


def test_none_and_unknown_never_erase_existing_values():
    state = HeirState().merge(
        SlotUpdate(death_date=date(2026, 9, 1), has_debt="yes", will_exists="yes")
    )

    untouched = state.merge(SlotUpdate(has_debt="unknown", agreement="none"))

    assert untouched.death_date == date(2026, 9, 1)
    assert untouched.has_debt == "yes"
    assert untouched.will_exists == "yes"


def test_completed_steps_still_accumulate_without_confirmation_gate():
    from agents.heir_navigator.procedure import StepId

    state = HeirState().merge(SlotUpdate(completed_steps=[StepId.DEATH_REPORT]))
    state = state.merge(SlotUpdate(completed_steps=[StepId.ONE_STOP]))

    assert state.completed == {StepId.DEATH_REPORT, StepId.ONE_STOP}


def test_confirmed_values_renders_dates_as_iso_strings():
    state = HeirState().merge(SlotUpdate(death_date=date(2026, 9, 1), has_debt="no"))

    assert state.confirmed_values() == {"death_date": "2026-09-01", "has_debt": "no"}


def test_confirmed_survives_json_round_trip():
    state = HeirState().merge(SlotUpdate(death_date=date(2026, 9, 1)))

    restored = HeirState.model_validate(state.model_dump(mode="json"))

    assert restored.confirmed == {"death_date"}
    assert restored.merge(SlotUpdate(death_date=date(2026, 9, 2))).death_date == date(
        2026, 9, 1
    )


# ------------------------------------------------------- normalize_messages


def test_leading_assistant_messages_are_dropped():
    """이력을 앞에서 자르면 assistant 로 시작할 수 있는데 API 가 거부한다."""
    normalized = normalize_messages(
        [
            {"role": "assistant", "content": "앞이 잘려 남은 답변"},
            {"role": "user", "content": "어제"},
        ]
    )

    assert normalized == [{"role": "user", "content": "어제"}]


def test_consecutive_same_role_messages_are_merged():
    normalized = normalize_messages(
        [
            {"role": "user", "content": "첫째"},
            {"role": "user", "content": "둘째"},
        ]
    )

    assert normalized == [{"role": "user", "content": "첫째\n둘째"}]


def test_all_assistant_history_normalizes_to_empty():
    assert normalize_messages([{"role": "assistant", "content": "답변뿐"}]) == []


# ------------------------------------------------ 라우터 왕복 (에이전트까지)


def _recording_agent(seen: list[list[dict[str, str]]]):
    """받은 history 를 기록만 하는 가짜 에이전트."""

    def _run(payload: AgentInput) -> AgentOutput:
        seen.append(list(payload.history))
        return AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR, reply="확인했습니다.", data={}
        )

    return _run


def test_history_accumulates_across_turns_and_reaches_the_agent(monkeypatch):
    seen: list[list[dict[str, str]]] = []
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.setitem(
        router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, _recording_agent(seen)
    )

    router.route(AgentInput(session_id="hist-1", user_message="부모님이 돌아가셨어요"))
    router.route(AgentInput(session_id="hist-1", user_message="어제"))

    # 1턴: 이번 발화 하나만. 2턴: 앞 턴 왕복 + 이번 발화.
    assert seen[0] == [{"role": "user", "content": "부모님이 돌아가셨어요"}]
    assert seen[1] == [
        {"role": "user", "content": "부모님이 돌아가셨어요"},
        {"role": "assistant", "content": "확인했습니다."},
        {"role": "user", "content": "어제"},
    ]


def test_history_is_scoped_to_its_own_session(monkeypatch):
    seen: list[list[dict[str, str]]] = []
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.setitem(
        router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, _recording_agent(seen)
    )

    router.route(AgentInput(session_id="hist-a", user_message="첫 세션 발화"))
    router.route(AgentInput(session_id="hist-b", user_message="다른 세션 발화"))

    assert seen[1] == [{"role": "user", "content": "다른 세션 발화"}]

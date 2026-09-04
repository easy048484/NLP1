"""
LLM-first 라우팅 테스트 (담당: 정민)

llm.claude.extract 를 가짜로 바꿔 실제 API 를 타지 않고, planner.classify 가
LLM 에 무엇을 넘기고 결과를 어떻게 해석하는지 검증합니다.

ORCHESTRATOR_USE_LLM=on 이면 llm_enabled() 가 키 없이도 True 라 LLM 경로를 탑니다.
conftest 가 ANTHROPIC_API_KEY 를 지우지만 여기서는 extract 자체를 가짜로 바꾸므로
네트워크는 절대 안 탑니다.

키워드 규칙 경로(LLM 없을 때)는 test_orchestrator_planner.py 가 그대로 검증합니다.
"""

from __future__ import annotations

import pytest

from llm import claude
from orchestrator import planner, registry, router
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName, AgentOutput

HEIR_Q = "고인 명의 예금 계좌가 있나요?"
HEIR_A = "네, 은행 계좌 하나 있어요"


@pytest.fixture(autouse=True)
def _llm_on(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "on")
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())


class _FakeExtract:
    """claude.extract 대역. answers 를 호출 순서대로 돌려주고 인자를 기록한다."""

    def __init__(self, *answers, raise_exc: BaseException | None = None):
        self.answers = list(answers)
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.answers.pop(0)

    @property
    def last(self) -> dict:
        return self.calls[-1]

    def enum(self, call: int = -1) -> list[str]:
        tool = self.calls[call]["tool"]
        return tool["input_schema"]["properties"]["agents"]["items"]["enum"]


def _install(monkeypatch, *answers, raise_exc=None) -> _FakeExtract:
    fake = _FakeExtract(*answers, raise_exc=raise_exc)
    monkeypatch.setattr(claude, "extract", fake)
    return fake


def _classify(message, **kw):
    kw.setdefault("pending_handoff", None)
    kw.setdefault("last_agent", None)
    kw.setdefault("default_agent", AgentName.HEIR_NAVIGATOR)
    return planner.classify(message, **kw)


def _non_stub_names() -> set[str]:
    return {n.value for n, s in registry.all_specs().items() if not s.is_stub}


# ------------------------------------------------------- 하이재킹 / 관성


def test_answer_to_previous_question_continues_last_agent(monkeypatch):
    """heir_navigator 가 던진 질문에 답하는 발화가 asset_organizer 키워드
    ("은행", "계좌")에 걸려도, LLM 이 __continue__ 를 고르면 대화가 이어진다.

    LLM-first 이전에는 키워드 후보 1개 → Standard 확정 호출이라 여기서
    asset_organizer 가 대화를 가로챘다(하이재킹)."""
    # 전제: 키워드만 보면 asset_organizer 가 단독 후보다.
    assert registry.match_keywords(HEIR_A) == [AgentName.ASSET_ORGANIZER]

    fake = _install(
        monkeypatch, {"agents": ["__continue__"], "reason": "직전 질문 답변"}
    )
    plan = _classify(
        HEIR_A,
        last_agent=AgentName.HEIR_NAVIGATOR,
        history=[
            {"role": "assistant", "content": HEIR_Q},
            {"role": "user", "content": HEIR_A},
        ],
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.HEIR_NAVIGATOR]]
    assert plan.llm_used is True

    # LLM 이 판단에 필요한 재료를 실제로 받았는지.
    user_text = fake.last["user_text"]
    assert HEIR_Q in user_text
    assert "직전 에이전트: heir_navigator" in user_text
    assert "키워드 힌트: asset_organizer" in user_text
    assert "__continue__" in fake.enum()
    assert "__continue__" in fake.last["system"]


def test_llm_sees_every_non_stub_agent_regardless_of_keywords(monkeypatch):
    """키워드가 하나도 안 걸리는 발화도 LLM 이 전체 에이전트를 놓고 고른다.

    이전에는 후보 0개 → LLM 호출 없이 last_agent 에 붙잡혔다(관성)."""
    message = "큰애한테 다 주고 싶은데 괜찮을까요"
    assert registry.match_keywords(message) == []

    fake = _install(monkeypatch, {"agents": ["heir_share_analyzer"]})
    plan = _classify(message, last_agent=AgentName.ASSET_ORGANIZER)
    assert plan.layers == [[AgentName.HEIR_SHARE_ANALYZER]]
    assert plan.llm_used is True

    enum = fake.enum()
    assert set(enum) == _non_stub_names() | {"__continue__"}
    assert AgentName.RETIREMENT_PLANNER.value not in enum  # is_stub 는 후보에서 제외
    assert "키워드 힌트" not in fake.last["user_text"]


def test_no_continue_option_on_fresh_conversation(monkeypatch):
    fake = _install(monkeypatch, {"agents": ["heir_navigator"]})
    plan = _classify("아버지가 어제 돌아가셨어요")
    assert plan.layers == [[AgentName.HEIR_NAVIGATOR]]
    assert "__continue__" not in fake.enum()
    assert "직전 에이전트: 없음" in fake.last["user_text"]


def test_continue_from_llm_is_ignored_without_last_agent(monkeypatch):
    """enum 에 없는데도 LLM 이 __continue__ 를 내면(방어) 무시하고 규칙으로 폴백."""
    _install(monkeypatch, {"agents": ["__continue__"]})
    plan = _classify("상속세 얼마예요")
    assert plan.llm_used is False
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]  # 규칙: 키워드 1개


# ------------------------------------------------------------- 핸드오프


def test_pending_handoff_is_a_hint_not_a_preempt(monkeypatch):
    """핸드오프가 걸려 있어도 사용자가 다른 주제를 꺼내면 LLM 이 그쪽을 고를 수
    있다. (규칙 경로에서는 여전히 Fast 선점 — test_orchestrator_planner.py)"""
    fake = _install(monkeypatch, {"agents": ["tax_calculator"]})
    plan = _classify(
        "그건 됐고 상속세가 얼마나 나올지 궁금해요",
        pending_handoff=AgentName.DECEDENT_ESTATE,
        last_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.path == "standard"
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]
    assert "핸드오프 예정: decedent_estate" in fake.last["user_text"]


def test_llm_can_follow_pending_handoff(monkeypatch):
    _install(monkeypatch, {"agents": ["decedent_estate"]})
    plan = _classify(
        "네, 봐주세요",
        pending_handoff=AgentName.DECEDENT_ESTATE,
        last_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


# ------------------------------------------------------------ 복수 선택


def test_multiple_picks_build_full_plan(monkeypatch):
    _install(monkeypatch, {"agents": ["tax_calculator", "decedent_estate"]})
    plan = _classify("유언장 효력도 보고 상속세도 계산해줘")
    assert plan.path == "full"
    assert plan.llm_used is True
    # will_status: decedent_estate → tax_calculator 순서로 층이 나뉜다.
    assert plan.layers == [[AgentName.DECEDENT_ESTATE], [AgentName.TAX_CALCULATOR]]


def test_continue_plus_new_topic_runs_both(monkeypatch):
    _install(monkeypatch, {"agents": ["__continue__", "tax_calculator"]})
    plan = _classify(
        "네 있어요. 그런데 상속세는 얼마나 나와요?",
        last_agent=AgentName.HEIR_NAVIGATOR,
        history=[{"role": "assistant", "content": HEIR_Q}],
    )
    assert plan.path == "full"
    assert set(plan.agents) == {AgentName.HEIR_NAVIGATOR, AgentName.TAX_CALCULATOR}


# ------------------------------------------------------------ 결과 방어


def test_unknown_and_stub_names_are_dropped(monkeypatch):
    _install(
        monkeypatch,
        {
            "agents": [
                "retirement_planner",
                "nonsense",
                "tax_calculator",
                "tax_calculator",
            ]
        },
    )
    plan = _classify("아무거나")
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


def test_only_invalid_names_falls_back_to_rules(monkeypatch):
    _install(monkeypatch, {"agents": ["retirement_planner"]})
    plan = _classify("상속세 얼마예요")
    assert plan.llm_used is False
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


# ------------------------------------------------------------ 폴백/정책


def test_llm_failure_falls_back_to_rules(monkeypatch):
    fake = _install(monkeypatch, raise_exc=RuntimeError("network down"))
    plan = _classify(
        "상속세 얼마예요",
        pending_handoff=AgentName.DECEDENT_ESTATE,
        last_agent=AgentName.HEIR_NAVIGATOR,
    )
    assert fake.calls  # 시도는 했다
    assert plan.llm_used is False
    assert plan.path == "fast"  # 규칙 경로에서는 핸드오프가 선점
    assert plan.layers == [[AgentName.DECEDENT_ESTATE]]


def test_llm_failure_raises_in_required_mode(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "required")
    _install(monkeypatch, raise_exc=RuntimeError("network down"))
    with pytest.raises(RuntimeError):
        _classify("상속세 얼마예요")


def test_llm_off_never_calls_extract(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "off")
    fake = _install(monkeypatch, {"agents": ["heir_share_analyzer"]})
    plan = _classify("상속세 얼마예요")
    assert fake.calls == []
    assert plan.layers == [[AgentName.TAX_CALCULATOR]]


def test_router_model_env_is_passed_through(monkeypatch):
    monkeypatch.setenv("CLAUDE_ROUTER_MODEL", "claude-test-router")
    fake = _install(monkeypatch, {"agents": ["heir_navigator"]})
    _classify("안녕하세요")
    assert fake.last["model"] == "claude-test-router"

    monkeypatch.delenv("CLAUDE_ROUTER_MODEL")
    _classify("안녕하세요")
    assert fake.last["model"] is None  # → llm.claude 기본(CLAUDE_MODEL)


def test_system_prompt_has_no_per_turn_state(monkeypatch):
    """대화 상태는 user 쪽에만 — system 프롬프트가 턴마다 같아야 캐시가 된다."""
    fake = _install(
        monkeypatch, {"agents": ["heir_navigator"]}, {"agents": ["__continue__"]}
    )
    _classify("아버지가 돌아가셨어요", last_agent=AgentName.HEIR_NAVIGATOR)
    _classify(
        HEIR_A,
        last_agent=AgentName.HEIR_NAVIGATOR,
        pending_handoff=AgentName.TAX_CALCULATOR,
        history=[{"role": "assistant", "content": HEIR_Q}],
    )
    assert fake.calls[0]["system"] == fake.calls[1]["system"]
    assert HEIR_Q not in fake.calls[1]["system"]


# ------------------------------------------------------ 라우터 end-to-end


def test_router_passes_previous_reply_to_classifier(monkeypatch):
    """route() 두 턴: 1턴 답변(질문 포함)이 2턴 라우팅 LLM 의 입력에 들어간다."""

    def heir(payload: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR,
            reply=HEIR_Q,
            data={AgentName.HEIR_NAVIGATOR.value: {"step": 1}},
        )

    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, heir)
    fake = _install(
        monkeypatch, {"agents": ["heir_navigator"]}, {"agents": ["__continue__"]}
    )

    first = router.route(
        AgentInput(session_id="e2e", user_message="아버지가 돌아가셨어요")
    )
    assert first.agent == AgentName.HEIR_NAVIGATOR

    second = router.route(AgentInput(session_id="e2e", user_message=HEIR_A))
    assert second.agent == AgentName.HEIR_NAVIGATOR
    assert second.path == "standard"

    turn2 = fake.calls[1]["user_text"]
    assert HEIR_Q in turn2
    assert "직전 에이전트: heir_navigator" in turn2
    assert turn2.rstrip().endswith(HEIR_A)

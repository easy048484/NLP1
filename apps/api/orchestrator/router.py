"""
오케스트레이터 (라우팅·상태관리·전환, 담당: 정민)

라우터 → 플래너 재설계(docs/라우팅방식변경.md). 기존 route(AgentInput) 시그니처는
그대로 두되 반환형이 AgentOutput 의 상위 호환인 ChatResponse 로 바뀌었습니다.

파이프라인 (LangGraph StateGraph):
  load_session → classify → build_context → execute_plan → compose → persist_session

- load_session: session_id 로 이전 턴까지의 상태(SessionState)를 불러옵니다.
- classify (planner.classify): 이번 턴에 실행할 에이전트와 경로 등급을 정합니다.
  LLM-first — LLM 이 전체 에이전트를 후보로 놓고, 직전 에이전트 · 직전 질문 ·
  핸드오프 예정 · 키워드 힌트를 보고 고릅니다 (planner.py 독스트링 참고).
    Standard  LLM 이 1개 고름 / LLM 없을 때 키워드 후보 1개 (없으면 직전 → 기본)
    Full      LLM 이 2개 이상 고름 / LLM 없을 때 키워드 후보 2개 이상 → DAG
    Fast      LLM 없을 때만: 직전 턴 핸드오프 대상 1개 (LLM 이 있으면 힌트로 강등)
  이름 → 에이전트 대응은 orchestrator/registry.py 가 agents/*/spec.py 를 자동으로
  읽어 만듭니다. 여기에는 에이전트 이름이 하드코딩돼 있지 않습니다.
- build_context: family_graph(요청값 > family_graph_id 조회)와 financial_profile
  (세션값 + 요청값 병합)을 준비합니다. family_graph 우선순위와 폴백 규칙은 이전과
  동일합니다 (schemas/agent_io.py AgentInput.family_graph_id 설명 참고).
- execute_plan (planner.execute_plan): 층 단위 병렬, 층 사이 순차 + context 주입.
- compose (compose.compose): 에이전트 1개면 원문 그대로, 여러 개면 LLM 합성 →
  verify_numbers 코드 검증 → 실패 시 원문 이어붙이기 + verification.ok=False.
- persist_session: 실행된 모든 에이전트의 네임스페이스 상태, 핸드오프, 공유
  financial_profile 을 저장합니다. 핸드오프는 output.handoffs(우선순위 최대) 가
  먼저고, 비어 있으면 레거시 next_action="handoff:x" 를 파싱합니다.

에이전트 간 정보 교환 형태(네임스페이스 규약, 핸드오프 문자열 형식)는 handoff.py 에
그대로 있습니다. LEGACY_FLAT_CONTEXT_AGENTS 도 그대로 둡니다 (이번 변경 범위 밖).

알려진 한계:
- "대화 주제를 완전히 바꾸고 싶을 때" 명시적 리셋은 여전히 없습니다.
- 세션 저장소 기본값은 인메모리입니다 (session_store.py).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from family_graph import get_heirs_dict
from schemas import (
    AgentInput,
    AgentName,
    AgentOutput,
    ChatResponse,
    FinancialProfile,
    VerificationResult,
    WillStatus,
)

from . import registry
from .compose import compose
from .handoff import extract_state_to_persist, parse_handoff
from .planner import ExecutionResult, Plan, classify, execute_plan
from .session_store import SessionState, SessionStore, default_store

logger = logging.getLogger(__name__)

#: 핸드오프도, 이어갈 이전 에이전트도 없을 때(=새 대화) 받을 기본 에이전트.
_DEFAULT_AGENT = AgentName.HEIR_NAVIGATOR


class _RunnerTable(dict):
    """AgentName → run 함수. 없는 키는 레지스트리의 entrypoint 로 채웁니다.

    테스트가 `monkeypatch.setitem(router._AGENT_RUNNERS, name, fake)` 로 특정
    에이전트만 바꿔치기하는 기존 관례를 그대로 지원하기 위한 dict 입니다.
    """

    def __missing__(self, name: AgentName) -> Callable[[AgentInput], AgentOutput]:
        return registry.get(name).entrypoint


_AGENT_RUNNERS: dict[AgentName, Callable[[AgentInput], AgentOutput]] = _RunnerTable()


def configure_session_store(store: SessionStore) -> None:
    """세션 저장소 구현체를 교체합니다. main.py가 앱 시작 시 한 번 호출합니다."""
    global default_store
    default_store = store


def current_session_store() -> SessionStore:
    """지금 쓰이고 있는 세션 저장소.

    default_store 는 configure_session_store 로 갈아끼워지는 모듈 전역이라,
    바깥에서 `from ... import default_store` 로 가져가면 교체 이전 값을 붙들게
    됩니다. 만료 정리 배치처럼 앱 밖에서 저장소를 만져야 하는 쪽은 이 함수를
    쓰세요.
    """
    return default_store


class GraphState(TypedDict, total=False):
    payload: AgentInput
    #: 요청자의 사용자 id. 비로그인이면 None.
    user_id: Optional[str]
    session: SessionState
    plan: Plan
    family_graph: Optional[dict]
    financial_profile: FinancialProfile
    will_status: Optional[WillStatus]
    execution: ExecutionResult
    output: ChatResponse


# ------------------------------------------------------------------- 노드


def node_load_session(state: GraphState) -> GraphState:
    payload = state["payload"]
    user_id = state.get("user_id")
    session = default_store.load(payload.session_id, user_id=user_id)

    # 비로그인으로 시작한 대화를 로그인한 채로 이어가면 그 자리에서 계정에
    # 붙입니다(claim). 다음 저장에서 보관 기간이 2시간 → 30일로 늘고,
    # 가족정보·재산정보·대화 이력이 다음 방문까지 남습니다. 반대로 로그아웃
    # 상태로 이어가도 소유자를 지우지는 않습니다 — 한 번 사용자 것이 된
    # 데이터를 토큰 없는 요청이 익명화해 버리면 안 되기 때문입니다.
    if session.user_id is None and user_id is not None:
        session.user_id = user_id
    # 이번 턴 발화를 먼저 이력에 넣습니다. 이렇게 해야 에이전트가 받는 history의
    # 마지막 원소가 항상 이번 user_message가 되고, 슬롯 추출기가 "직전 질문 →
    # 이번 답변"을 한 덩어리로 볼 수 있습니다.
    session.append_history("user", payload.user_message)
    return {"session": session}


def node_classify(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]
    plan = classify(
        payload.user_message,
        pending_handoff=session.pending_handoff,
        last_agent=session.last_agent,
        default_agent=_DEFAULT_AGENT,
        axis=payload.axis,
        # 직전 assistant 발화(=직전 질문)를 라우터가 보게 한다. load_session 이
        # 이번 user_message 를 이미 이력에 넣었으므로 마지막 assistant 는 직전 턴이다.
        history=session.history,
    )
    return {"plan": plan}


def node_build_context(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]

    family_graph_id = payload.family_graph_id or session.family_graph_id
    session.family_graph_id = family_graph_id
    if payload.family_graph is not None:
        family_graph = payload.family_graph
    else:
        family_graph = get_heirs_dict(family_graph_id)

    profile = session.financial_profile.merged_with(payload.financial_profile)

    base_will_status = session.will_status or WillStatus()
    will_status = base_will_status.merged_with(payload.will_status)

    return {
        "family_graph": family_graph,
        "financial_profile": profile,
        "will_status": will_status,
        "session": session,
    }


def node_execute_plan(state: GraphState) -> GraphState:
    session = state["session"]
    execution = execute_plan(
        state["plan"],
        payload=state["payload"],
        family_graph=state.get("family_graph"),
        financial_profile=state["financial_profile"],
        will_status=state.get("will_status"),
        stored_context_for=session.context_for,
        runners=_AGENT_RUNNERS,
        history=session.history,
    )
    return {"execution": execution}


def _resolve_handoff(output: AgentOutput) -> Optional[AgentName]:
    if output.handoffs:
        best = max(output.handoffs, key=lambda h: h.priority)
        return best.target if registry.get_optional(best.target) is not None else None
    return parse_handoff(output.next_action)


def node_compose(state: GraphState) -> GraphState:
    payload = state["payload"]
    plan = state["plan"]
    outputs = state["execution"].outputs

    reply, verification = compose(outputs, payload.user_message)
    primary = outputs[-1]
    if len(outputs) == 1:
        verification = VerificationResult(ok=True, mode="single")

    merged_data = {}
    for o in outputs:
        merged_data.update(o.data)

    response = ChatResponse(
        agent=primary.agent,
        reply=reply,
        next_action=primary.next_action,
        handoffs=[h for o in outputs for h in o.handoffs],
        financial_profile=state["execution"].financial_profile,
        will_status=state["execution"].will_status,
        data=merged_data,
        agents=[o.agent for o in outputs],
        contributions=outputs,
        path=plan.path,
        verification=verification,
    )
    return {"output": response}


def node_persist_session(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]
    outputs = state["execution"].outputs

    # 핸드오프: 실행된 에이전트 중 가장 나중 것이 낸 신호가 우선.
    handoff_target: Optional[AgentName] = None
    for output in outputs:
        session.per_agent_context[output.agent.value] = extract_state_to_persist(
            output.agent, output
        )
        candidate = _resolve_handoff(output)
        if candidate is not None:
            handoff_target = candidate

    primary = outputs[-1].agent
    session.remember(
        primary,
        context=session.per_agent_context.get(primary.value, {}),
        pending_handoff=handoff_target,
    )
    session.financial_profile = state["execution"].financial_profile
    session.will_status = state["execution"].will_status
    # 합성까지 끝난 최종 답변만 이력에 남깁니다 (에이전트별 원문이 아니라
    # 사용자가 실제로 본 문장). 다음 턴 추출기가 "무엇을 물어봤는지"를 정확히
    # 같은 문장으로 보게 하려면 이쪽이 맞습니다.
    session.append_history("assistant", state["output"].reply)
    default_store.save(payload.session_id, session)
    return {"session": session}


# ------------------------------------------------------------------- 그래프


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("load_session", node_load_session)
    graph.add_node("classify", node_classify)
    graph.add_node("build_context", node_build_context)
    graph.add_node("execute_plan", node_execute_plan)
    graph.add_node("compose", node_compose)
    graph.add_node("persist_session", node_persist_session)

    graph.add_edge(START, "load_session")
    graph.add_edge("load_session", "classify")
    graph.add_edge("classify", "build_context")
    graph.add_edge("build_context", "execute_plan")
    graph.add_edge("execute_plan", "compose")
    graph.add_edge("compose", "persist_session")
    graph.add_edge("persist_session", END)

    return graph.compile()


_COMPILED = None


def _compiled():
    """컴파일된 그래프 싱글턴. 요청마다 다시 컴파일하지 않습니다."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_graph()
    return _COMPILED


def route(payload: AgentInput, *, user_id: Optional[str] = None) -> ChatResponse:
    """한 턴을 처리합니다.

    user_id 는 요청을 보낸 사람입니다(비로그인이면 None). 남의 세션을 이어받지
    못하게 막고, 비로그인으로 시작한 세션을 계정에 붙이는 데 씁니다.
    """
    result = _compiled().invoke({"payload": payload, "user_id": user_id})
    return result["output"]

"""
오케스트레이터 (라우팅·상태관리·전환, 담당: 지원)

LangGraph StateGraph로 재작성한 버전입니다 (2단계 뼈대였던 키워드 한 번
매칭 함수를 대체). 기존 route(AgentInput) -> AgentOutput 시그니처는 그대로
유지해 main.py 등 호출부를 바꾸지 않아도 됩니다.

파이프라인: load_session → resolve_target → build_context → call_agent → persist_session

- load_session: session_id로 이전 턴까지의 상태(SessionState)를 불러옵니다.
- resolve_target: 이번 턴을 받을 에이전트를 정합니다. 우선순위는
  (1) 직전 턴이 지정한 핸드오프 대상 (2) 같은 에이전트와 대화를 이어가는 중이면
  그 에이전트 (3) 키워드 매칭 (4) 기본 에이전트(heir_navigator) 입니다.
  (1)이 없을 때 (2)를 키워드보다 먼저 보는 이유: decedent_estate/heir_navigator의
  "네/아니오로 답해주세요" 같은 후속 질문에는 키워드가 안 들어있는 경우가
  대부분이라, 키워드를 먼저 보면 답변이 엉뚱한 에이전트(기본값)로 새버립니다.
- build_context / persist_session: 각 에이전트가 정보를 주고받는 형태(네임스페이스
  규약, 핸드오프 신호 형식)는 handoff.py에 정의돼 있습니다 — 새 에이전트를
  붙이거나 기존 에이전트를 고칠 때는 그 문서를 먼저 보세요.

알려진 한계 (다음 반복에서 다룰 것):
- "대화 주제를 완전히 바꾸고 싶을 때" 되돌아갈 방법이 아직 없습니다. 핸드오프
  신호가 없는 한 마지막에 응답한 에이전트가 계속 우선권을 가집니다. 명시적인
  "새 상담 시작" 신호(리셋 버튼/문구)는 이번 반복 범위 밖입니다.
- 세션은 프로세스 메모리에만 있습니다 (session_store.py 참고) — family_graph
  DB가 준비되면 그쪽으로 옮깁니다.
"""

from __future__ import annotations

import logging
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import decedent_estate, heir_navigator, tax_calculator
from schemas import AgentInput, AgentName, AgentOutput

from .handoff import build_agent_context, extract_state_to_persist, parse_handoff
from .session_store import SessionState, default_store

logger = logging.getLogger(__name__)

#: 핸드오프도, 이어갈 이전 에이전트도 없을 때(=새 대화) 받을 기본 에이전트.
_DEFAULT_AGENT = AgentName.HEIR_NAVIGATOR

#: 새 대화를 시작할 때만 쓰이는 키워드 라우팅. 기존 router.py의 키워드 세트를
#: 그대로 유지합니다 — 세트 자체를 조정하고 싶으면 지원님에게 요청해주세요
#: (README "병렬 개발 시 충돌 지점" 원칙과 동일).
_KEYWORD_ROUTES: dict[str, AgentName] = {
    "유언": AgentName.DECEDENT_ESTATE,
    "자산정리": AgentName.DECEDENT_ESTATE,
    "상속세": AgentName.TAX_CALCULATOR,
    "세금": AgentName.TAX_CALCULATOR,
}

_AGENT_RUNNERS: dict[AgentName, Callable[[AgentInput], AgentOutput]] = {
    AgentName.HEIR_NAVIGATOR: heir_navigator.run,
    AgentName.DECEDENT_ESTATE: decedent_estate.run,
    AgentName.TAX_CALCULATOR: tax_calculator.run,
}


class GraphState(TypedDict, total=False):
    payload: AgentInput
    session: SessionState
    target: AgentName
    agent_input: AgentInput
    output: AgentOutput


def _keyword_route(user_message: str) -> AgentName:
    for keyword, agent in _KEYWORD_ROUTES.items():
        if keyword in user_message:
            return agent
    return _DEFAULT_AGENT


# ------------------------------------------------------------------- 노드


def node_load_session(state: GraphState) -> GraphState:
    payload = state["payload"]
    return {"session": default_store.load(payload.session_id)}


def node_resolve_target(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]

    if session.pending_handoff is not None:
        target = session.pending_handoff
    elif session.last_agent is not None:
        target = session.last_agent
    else:
        target = _keyword_route(payload.user_message)

    return {"target": target}


def node_build_context(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]
    target = state["target"]

    stored = session.context_for(target)
    context = build_agent_context(target, stored, payload.context or {})

    agent_input = AgentInput(
        session_id=payload.session_id,
        user_message=payload.user_message,
        family_graph=payload.family_graph,
        context=context,
    )
    return {"agent_input": agent_input}


def node_call_agent(state: GraphState) -> GraphState:
    target = state["target"]
    runner = _AGENT_RUNNERS[target]
    output = runner(state["agent_input"])
    return {"output": output}


def node_persist_session(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]
    target = state["target"]
    output = state["output"]

    handoff_target = parse_handoff(output.next_action)
    session.remember(
        target,
        context=extract_state_to_persist(target, output),
        pending_handoff=handoff_target,
    )
    default_store.save(payload.session_id, session)
    return {"session": session}


# ------------------------------------------------------------------- 그래프


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("load_session", node_load_session)
    graph.add_node("resolve_target", node_resolve_target)
    graph.add_node("build_context", node_build_context)
    graph.add_node("call_agent", node_call_agent)
    graph.add_node("persist_session", node_persist_session)

    graph.add_edge(START, "load_session")
    graph.add_edge("load_session", "resolve_target")
    graph.add_edge("resolve_target", "build_context")
    graph.add_edge("build_context", "call_agent")
    graph.add_edge("call_agent", "persist_session")
    graph.add_edge("persist_session", END)

    return graph.compile()


_COMPILED = None


def _compiled():
    """컴파일된 그래프 싱글턴. 요청마다 다시 컴파일하지 않습니다."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_graph()
    return _COMPILED


def route(payload: AgentInput) -> AgentOutput:
    result = _compiled().invoke({"payload": payload})
    return result["output"]

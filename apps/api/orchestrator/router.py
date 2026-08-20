"""
오케스트레이터 (라우팅·상태관리·전환, 담당: 지원)

LangGraph StateGraph로 재작성한 버전입니다 (2단계 뼈대였던 키워드 한 번
매칭 함수를 대체). 기존 route(AgentInput) -> AgentOutput 시그니처는 그대로
유지해 main.py 등 호출부를 바꾸지 않아도 됩니다.

파이프라인: load_session → resolve_target → build_context → call_agent → persist_session

- load_session: session_id로 이전 턴까지의 상태(SessionState)를 불러옵니다.
- resolve_target: 이번 턴을 받을 에이전트를 정합니다. 우선순위는
  (1) 직전 턴이 지정한 핸드오프 대상 (2) 이번 메시지에 키워드가 있으면 그
  키워드가 가리키는 에이전트 (3) 같은 에이전트와 대화를 이어가는 중이면 그
  에이전트 (4) 기본 에이전트(heir_navigator) 입니다.
  (2)를 (3)보다 먼저 보는 이유: 대화 중간에 사용자가 새 주제 키워드("상속세
  얼마나 나와요?" 등)를 꺼내면 직전 에이전트가 아니라 그 주제를 다루는
  에이전트로 넘어가야 합니다. 키워드가 없는 "네/아니오" 같은 짧은 후속
  답변은 (2)에서 그냥 통과되어 (3)에서 직전 에이전트로 자연히 이어집니다 —
  즉 이 순서를 바꿔도 후속 질문 처리는 그대로 유지되면서, 새 키워드가 있을
  때만 더 정확히 라우팅됩니다.
- build_context / persist_session: 각 에이전트가 정보를 주고받는 형태(네임스페이스
  규약, 핸드오프 신호 형식)는 handoff.py에 정의돼 있습니다 — 새 에이전트를
  붙이거나 기존 에이전트를 고칠 때는 그 문서를 먼저 보세요.
  build_context의 family_graph 우선순위는 (1) 이번 요청에 family_graph가
  직접 담겨 있으면 그 값 (테스트/레거시 클라이언트가 명시적으로 override하는
  경우 — schemas/agent_io.py의 AgentInput.family_graph_id 필드 설명과 동일한
  우선순위입니다) (2) 없으면 family_graph_id(요청에 있으면 그 값, 없으면
  세션에 저장된 값)로 family_graph.get_heirs_dict()를 호출한 결과입니다. DB
  조회가 안 되거나(DATABASE_URL 없음 등) 결과가 없으면 family_graph는
  비웁니다 — family_graph_id 하나 잘못 보냈다고 요청 전체가 실패하지
  않습니다.

알려진 한계 (다음 반복에서 다룰 것):
- "대화 주제를 완전히 바꾸고 싶을 때" 되돌아갈 방법이 아직 없습니다. 핸드오프
  신호가 없는 한 마지막에 응답한 에이전트가 계속 우선권을 가집니다. 명시적인
  "새 상담 시작" 신호(리셋 버튼/문구)는 이번 반복 범위 밖입니다.
- 세션 저장소는 기본값이 인메모리입니다. DATABASE_URL이 설정된 환경에서는
  main.py가 시작 시 configure_session_store(PostgresSessionStore())를 불러
  Postgres 기반으로 교체합니다 (session_store.py 참고).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents import decedent_estate, heir_navigator, tax_calculator
from family_graph import get_heirs_dict
from schemas import AgentInput, AgentName, AgentOutput

from .handoff import build_agent_context, extract_state_to_persist, parse_handoff
from .session_store import SessionState, SessionStore, default_store

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


def configure_session_store(store: SessionStore) -> None:
    """세션 저장소 구현체를 교체합니다. main.py가 앱 시작 시 한 번 호출합니다.

    DATABASE_URL이 설정돼 있으면 PostgresSessionStore로, 아니면(로컬/CI
    등) 기본값인 InMemorySessionStore를 그대로 둡니다. 아래 노드 함수들은
    전부 module-level인 `default_store` 이름을 그때그때 조회하므로, 여기서
    재대입하면 이후의 모든 요청이 새 구현체를 씁니다.
    """
    global default_store
    default_store = store


class GraphState(TypedDict, total=False):
    payload: AgentInput
    session: SessionState
    target: AgentName
    agent_input: AgentInput
    output: AgentOutput


def _keyword_route(user_message: str) -> Optional[AgentName]:
    """메시지에 라우팅 키워드가 있으면 그 에이전트를, 없으면 None을 돌려줍니다."""
    for keyword, agent in _KEYWORD_ROUTES.items():
        if keyword in user_message:
            return agent
    return None


# ------------------------------------------------------------------- 노드


def node_load_session(state: GraphState) -> GraphState:
    payload = state["payload"]
    return {"session": default_store.load(payload.session_id)}


def node_resolve_target(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]

    keyword_target = _keyword_route(payload.user_message)

    if session.pending_handoff is not None:
        target = session.pending_handoff
    elif keyword_target is not None:
        target = keyword_target
    elif session.last_agent is not None:
        target = session.last_agent
    else:
        target = _DEFAULT_AGENT

    return {"target": target}


def node_build_context(state: GraphState) -> GraphState:
    session = state["session"]
    payload = state["payload"]
    target = state["target"]

    # family_graph_id: 이번 요청이 새로 지정했으면 그 값이 우선, 아니면
    # 세션에 이미 연결돼 있던 값을 이어받습니다. 여기서 session에 바로
    # 반영해둬야 node_persist_session이 그대로 저장합니다.
    family_graph_id = payload.family_graph_id or session.family_graph_id
    session.family_graph_id = family_graph_id

    # 이번 요청이 family_graph를 직접 채워 보냈으면 그 값이 최우선입니다
    # (스키마 설명대로 — agent_io.py의 AgentInput.family_graph_id docstring
    # 참고). family_graph_id만으로는 세션이 기억하고 있던 예전 그래프를
    # 계속 가리킬 수 있으므로, 이번 턴에 한해 명시적으로 override하고 싶은
    # 테스트/레거시 클라이언트가 이 값으로 그렇게 할 수 있어야 합니다.
    if payload.family_graph is not None:
        family_graph = payload.family_graph
    else:
        family_graph = get_heirs_dict(family_graph_id)

    stored = session.context_for(target)
    context = build_agent_context(target, stored, payload.context or {})

    agent_input = AgentInput(
        session_id=payload.session_id,
        user_message=payload.user_message,
        family_graph=family_graph,
        context=context,
    )
    return {"agent_input": agent_input, "session": session}


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

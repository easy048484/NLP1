"""
세션 상태 저장소 (담당: 지원)

오케스트레이터가 여러 턴에 걸쳐 "지금 어느 에이전트와 대화 중인지"와
"각 에이전트별로 이어가야 하는 context"를 들고 있기 위한 최소 저장소입니다.

Phase 1에서는 프로세스 메모리(dict)에만 저장했습니다. Phase 2(family_graph
DB 연결)에서 SessionStore 인터페이스(load/save)는 그대로 유지한 채
PostgresSessionStore 구현체를 추가했습니다 — 오케스트레이터의 나머지
코드(router.py)는 이 모듈이 인메모리인지 DB인지 알지 못합니다. 실제로 어느
구현체를 쓸지는 main.py가 DATABASE_URL 유무로 결정해서
`router.configure_session_store()`로 갈아끼웁니다 (기본값은 계속
InMemorySessionStore — DB가 없는 환경에서도 기존 동작이 그대로 유지되도록).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Optional

from db.base import mask_sensitive_id, session_scope
from family_graph.models import FamilyGraph
from schemas import AgentName

from .models import ChatSession

logger = logging.getLogger(__name__)

#: 세션을 이 시간(초) 동안 아무 요청도 없으면 만료된 것으로 보고 다음 조회 때
#: 새로 시작합니다. 인메모리 단계에서 "방치된 세션이 무한정 쌓이는 것"만 막는
#: 용도라 값은 임의 기준이며, DB로 옮길 때 보관 정책에 맞춰 재조정합니다.
_SESSION_TTL_SECONDS = 60 * 60 * 2  # 2시간


@dataclass
class SessionState:
    """세션 하나가 들고 있는 상태.

    per_agent_context: 에이전트 이름(AgentName.value) -> 그 에이전트가 다음 턴에
        이어받아야 하는 context dict. 규약을 따르는 에이전트는 항상 이 값이
        직전 턴 AgentOutput.data[에이전트이름]과 동일합니다 (handoff.py 참고).
    pending_handoff: 직전 턴에서 어떤 에이전트가 "다음은 이 에이전트로 넘겨라"라고
        지정했으면 그 AgentName. 이번 턴 라우팅에 최우선으로 반영되고, 한 번
        쓰이면 다음 remember() 호출에서 자연히 갱신(또는 소거)됩니다.
    last_agent: 직전 턴에 실제로 응답한 에이전트. pending_handoff가 없을 때
        "같은 에이전트와 대화를 이어가는 중" 판단에 씁니다.
    family_graph_id: 이 세션이 연결된 family_graph의 식별자. 세션보다
        오래 사는 데이터라 세션이 만료돼도 이 값 자체는 DB의 family_graphs
        테이블에 그대로 남아있습니다 — 여기 저장해두는 건 "이 세션이 어느
        family_graph를 보고 있었는지"만 기억하기 위해서입니다.
    """

    per_agent_context: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_handoff: Optional[AgentName] = None
    last_agent: Optional[AgentName] = None
    family_graph_id: Optional[str] = None
    updated_at: float = field(default_factory=time.time)

    def context_for(self, agent: AgentName) -> dict[str, Any]:
        return dict(self.per_agent_context.get(agent.value, {}))

    def remember(
        self,
        agent: AgentName,
        *,
        context: dict[str, Any],
        pending_handoff: Optional[AgentName],
    ) -> None:
        self.per_agent_context[agent.value] = context
        self.pending_handoff = pending_handoff
        self.last_agent = agent
        self.updated_at = time.time()


class SessionStore:
    """세션 상태 저장소 인터페이스. 지금은 인메모리 구현 하나뿐입니다."""

    def load(self, session_id: str) -> SessionState:
        raise NotImplementedError

    def save(self, session_id: str, state: SessionState) -> None:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = Lock()

    def load(self, session_id: str) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None or self._is_expired(state):
                return SessionState()
            return state

    def save(self, session_id: str, state: SessionState) -> None:
        with self._lock:
            self._sessions[session_id] = state

    @staticmethod
    def _is_expired(state: SessionState) -> bool:
        return (time.time() - state.updated_at) > _SESSION_TTL_SECONDS


class PostgresSessionStore(SessionStore):
    """sessions 테이블 기반 구현. 여러 워커/인스턴스로 확장해도 세션을 공유합니다.

    main.py가 DATABASE_URL이 설정돼 있을 때 이 구현체를 만들어
    router.configure_session_store()로 등록합니다. 인터페이스는
    InMemorySessionStore와 동일해서, 오케스트레이터 나머지 코드는 이 클래스의
    존재 자체를 몰라도 됩니다.
    """

    def load(self, session_id: str) -> SessionState:
        with session_scope() as db:
            row = db.get(ChatSession, session_id)
            if row is None or row.expires_at < datetime.now(timezone.utc):
                return SessionState()
            return SessionState(
                per_agent_context=dict(row.per_agent_context or {}),
                pending_handoff=(
                    AgentName(row.pending_handoff) if row.pending_handoff else None
                ),
                last_agent=(AgentName(row.last_agent) if row.last_agent else None),
                family_graph_id=row.family_graph_id,
                updated_at=row.updated_at.timestamp(),
            )

    def save(self, session_id: str, state: SessionState) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=_SESSION_TTL_SECONDS)
        with session_scope() as db:
            row = db.get(ChatSession, session_id)
            if row is None:
                row = ChatSession(session_id=session_id)
                db.add(row)

            family_graph_id = state.family_graph_id
            if (
                family_graph_id is not None
                and db.get(FamilyGraph, family_graph_id) is None
            ):
                # 존재하지 않는(또는 삭제된) family_graph_id — sessions의 FK
                # 제약을 그대로 두면 이 한 줄 때문에 요청 전체가 500으로
                # 죽습니다. family_graph_id 하나 잘못 들어왔다고 세션 저장이
                # 실패하면 안 되므로 조용히 비워둡니다 (repository.get_heirs_dict가
                # 알 수 없는 id에 조용히 None을 돌려주는 것과 같은 원칙).
                logger.warning(
                    "family_graph_id=%s가 family_graphs에 없어 세션에서 비웁니다.",
                    mask_sensitive_id(family_graph_id),
                )
                family_graph_id = None

            row.family_graph_id = family_graph_id
            row.last_agent = state.last_agent.value if state.last_agent else None
            row.pending_handoff = (
                state.pending_handoff.value if state.pending_handoff else None
            )
            row.per_agent_context = dict(state.per_agent_context)
            row.expires_at = expires_at


#: 오케스트레이터 프로세스 전역에서 공유하는 싱글턴 — 기본값은 인메모리입니다.
#: DATABASE_URL이 설정된 환경에서는 main.py가 시작 시
#: router.configure_session_store(PostgresSessionStore())를 호출해 교체합니다.
#: DATABASE_URL이 없는 환경(지금 CI가 그렇습니다)에서는 이 기본값이 그대로
#: 쓰이므로 기존 동작이 깨지지 않습니다.
default_store = InMemorySessionStore()

"""
세션 상태 저장소 (담당: 지원)

오케스트레이터가 여러 턴에 걸쳐 "지금 어느 에이전트와 대화 중인지"와
"각 에이전트별로 이어가야 하는 context"를 들고 있기 위한 최소 저장소입니다.

지금은 프로세스 메모리(dict)에만 저장합니다 — family_graph DB(3단계)가
준비되면 이 인터페이스(SessionStore.load/save)를 그대로 유지한 채 구현체만
Postgres 기반으로 교체할 수 있도록, 오케스트레이터의 나머지 코드는 이
모듈이 인메모리인지 DB인지 알지 못하게 분리해뒀습니다.

세션은 서버 재시작 시 사라집니다(인메모리이므로). 로컬 개발/데모 단계에서는
문제 없지만, 실제 배포에서 세션 유지가 중요해지면 3단계에서 DB 백엔드로
바꿔야 합니다. (개발_배포_파이프라인_계획.md의 개인정보 보관 정책과 맞춰
sessions 테이블의 expires_at을 그대로 이 TTL 개념으로 옮기면 됩니다.)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

from schemas import AgentName

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
    """

    per_agent_context: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_handoff: Optional[AgentName] = None
    last_agent: Optional[AgentName] = None
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


#: 오케스트레이터 프로세스 전역에서 공유하는 싱글턴. FastAPI가 단일 워커로
#: 뜬다는 전제(로컬/데모 단계)에서만 유효합니다 — 멀티 워커/멀티 인스턴스로
#: 확장하면 곧바로 DB 기반 SessionStore로 교체해야 합니다(3단계, family_graph
#: DB와 같은 시점에 처리하는 걸 권장합니다).
default_store = InMemorySessionStore()

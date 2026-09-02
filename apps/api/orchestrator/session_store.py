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

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from db.base import mask_sensitive_id, session_scope
from family_graph.models import FamilyGraph
from schemas import AgentName, FinancialProfile, WillStatus

from .models import ChatSession

logger = logging.getLogger(__name__)

#: 세션 보관 기간. 로그인 여부로 갈립니다 (docs/개발_배포_파이프라인_계획.md
#: 10절 "개인정보 보관 기간·삭제 정책").
#:
#: 비로그인은 "대화창을 떠나면 남지 않는다"가 목표입니다. 다만 브라우저를 그냥
#: 닫으면 서버가 알 방법이 없어서 즉시 삭제는 보장할 수 없고, 이 TTL이 실질
#: 상한 역할을 합니다. 만료된 행은 purge_expired_sessions()가 실제로 지웁니다
#: (예전에는 조회할 때 무시만 하고 행은 영구히 남았습니다).
#:
#: 로그인은 반대로 "다음 방문에 이어서 쓴다"가 목표입니다. 상속 절차는 몇 주~몇
#: 달 이어지므로 30일을 둡니다.
_ANONYMOUS_TTL_SECONDS = 60 * 60 * 2  # 2시간
_AUTHENTICATED_TTL_SECONDS = 60 * 60 * 24 * 30  # 30일


def session_ttl_seconds(user_id: Optional[str]) -> int:
    """이 세션을 얼마나 보관할지. 소유자 유무 하나로 정합니다."""
    return _AUTHENTICATED_TTL_SECONDS if user_id else _ANONYMOUS_TTL_SECONDS


#: 세션에 보관하는 대화 이력 상한. 이력은 추출 LLM에 매 턴 통째로 실려 나가고
#: sessions.per_agent_context JSON 안에 함께 저장되므로, 상한이 없으면 대화가
#: 길어질수록 DB row와 토큰 비용이 선형으로 늘어납니다. 세 겹으로 막습니다.
#:   - 메시지 개수 (user/assistant 각각 1개로 셈)
#:   - 메시지 하나의 길이 (role 별로 다름 — 아래 참고)
#:   - 이력 전체 길이 (오래된 것부터 버림)
_HISTORY_MAX_MESSAGES = 24
_HISTORY_MAX_CHARS_TOTAL = 12000

#: 사용자 발화 상한. 긴 붙여넣기 한 번이 예산을 다 먹지 않도록 앞에서 자릅니다
#: (사용자가 하려는 말은 보통 앞에 있습니다).
_HISTORY_MAX_CHARS_USER = 2000

#: 에이전트 답변 상한. 절차 안내는 2000자를 예사로 넘는데, 이력을 읽는 쪽은
#: 지금 슬롯 추출기 하나뿐이고 거기서 필요한 건 "직전에 무엇을 물었는가"입니다.
#: 그 질문은 항상 답변 **끝**에 붙으므로, 앞에서 자르면 정작 필요한 문장이
#: 날아갑니다. 그래서 assistant 만 뒤에서부터 남깁니다.
_HISTORY_MAX_CHARS_ASSISTANT = 800

#: 잘라냈다는 표시. 모델이 "앞이 잘린 글"임을 알 수 있게 붙입니다.
_TRUNCATION_MARK = "…"

#: 이력에 들어갈 수 있는 role.
_HISTORY_ROLES = ("user", "assistant")


def _trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """상한을 넘으면 오래된 메시지부터 버립니다.

    자르는 방향이 "앞에서부터"인 이유: 슬롯 추출에서 중요한 건 최근 문맥이고,
    확정된 값은 이미 에이전트 상태(HeirState 등)에 남아 있어서 오래된 원문이
    사라져도 잃는 게 없습니다.
    """
    trimmed = history[-_HISTORY_MAX_MESSAGES:]
    while (
        trimmed and sum(len(m["content"]) for m in trimmed) > _HISTORY_MAX_CHARS_TOTAL
    ):
        trimmed.pop(0)
    return trimmed


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
    #: 세션 공유 재무 상태 (schemas.FinancialProfile). DB에는 per_agent_context 의
    #: 예약 키 "_shared" 아래에 함께 저장합니다 — 컬럼/마이그레이션 추가 없이
    #: 기존 sessions 테이블을 그대로 씁니다. 에이전트 이름과 충돌하지 않도록
    #: 밑줄로 시작합니다.
    financial_profile: FinancialProfile = field(default_factory=FinancialProfile)
    #: 세션 공유 유언장 판정 요약 (schemas.WillStatus). financial_profile 과
    #: 똑같이 "_shared" 아래에 저장합니다. decedent_estate 가 점검했을 때만
    #: 값이 차고(checked=True), tax_calculator·heir_share_analyzer 가 읽습니다.
    will_status: Optional[WillStatus] = None
    pending_handoff: Optional[AgentName] = None
    last_agent: Optional[AgentName] = None
    #: 이 세션을 소유한 사용자 id. None이면 비로그인 세션입니다.
    #: 보관 기간(session_ttl_seconds)과 접근 권한(can_be_accessed_by)이
    #: 이 값 하나로 갈립니다.
    user_id: Optional[str] = None
    family_graph_id: Optional[str] = None
    #: 이 세션의 대화 원문. [{"role": "user"|"assistant", "content": str}, ...]
    #: 시간순이고, 상한(_HISTORY_MAX_*)을 넘으면 오래된 것부터 버립니다.
    #:
    #: 왜 필요한가: 슬롯 추출기가 이전에는 "이번 턴 발화 한 줄"만 받았습니다.
    #: 그래서 시스템이 "돌아가신 날짜가 언제인가요?"라고 묻고 사용자가 "어제"라고
    #: 답하면, 추출기 입장에서는 그 "어제"가 무엇의 날짜인지 알 근거가 없어
    #: null을 돌려주고 같은 질문을 반복했습니다. 이력을 함께 넘겨야 풀립니다.
    #:
    #: financial_profile / will_status 와 같은 이유로 컬럼을 새로 만들지 않고
    #: per_agent_context JSON 의 "_shared" 아래에 함께 저장합니다.
    history: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def context_for(self, agent: AgentName) -> dict[str, Any]:
        return dict(self.per_agent_context.get(agent.value, {}))

    def can_be_accessed_by(self, user_id: Optional[str]) -> bool:
        """요청자가 이 세션을 이어받을 수 있는지.

        family_graph의 user_can_access와 같은 규칙입니다.
        - 소유자가 없는(비로그인) 세션: session_id를 아는 사람이면 누구나.
          session_id 자체가 접근 권한처럼 쓰이는 값(capability token)입니다.
        - 소유자가 있는 세션: 그 사용자 본인만. 남의 세션 id를 찍어 넣어도
          "없는 세션"과 똑같이 새 대화가 시작될 뿐, 내용이 새지 않습니다.
        """
        if self.user_id is None:
            return True
        return self.user_id == user_id

    def append_history(self, role: str, content: str) -> None:
        """대화 한 줄을 이력에 덧붙입니다. 빈 내용은 넣지 않습니다.

        자르는 방향이 role 마다 다릅니다 (_HISTORY_MAX_CHARS_* 주석 참고) —
        사용자 발화는 앞을, 에이전트 답변은 뒤를 남깁니다.
        """
        if role not in _HISTORY_ROLES:
            raise ValueError(f"알 수 없는 role: {role!r}")
        text = (content or "").strip()
        if not text:
            return
        if role == "assistant":
            if len(text) > _HISTORY_MAX_CHARS_ASSISTANT:
                text = _TRUNCATION_MARK + text[-_HISTORY_MAX_CHARS_ASSISTANT:]
        elif len(text) > _HISTORY_MAX_CHARS_USER:
            text = text[:_HISTORY_MAX_CHARS_USER] + _TRUNCATION_MARK
        self.history = _trim_history([*self.history, {"role": role, "content": text}])

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

    # ---- DB 직렬화 (per_agent_context JSON 하나에 공유 상태까지 같이 담는다)
    SHARED_KEY = "_shared"

    def to_json_context(self) -> dict[str, Any]:
        data = {k: v for k, v in self.per_agent_context.items() if k != self.SHARED_KEY}
        shared: dict[str, Any] = {}

        profile = self.financial_profile.model_dump(exclude_none=True)
        if profile.get("extra") == {}:
            profile.pop("extra")
        if profile:
            shared["financial_profile"] = profile

        if self.will_status is not None and self.will_status.checked:
            will_status = self.will_status.model_dump(exclude_none=True)
            if will_status:
                shared["will_status"] = will_status

        if self.history:
            shared["history"] = self.history

        if shared:
            data[self.SHARED_KEY] = shared
        return data

    @classmethod
    def from_json_context(cls, raw: dict[str, Any], **kwargs: Any) -> "SessionState":
        raw = dict(raw or {})
        shared = raw.pop(cls.SHARED_KEY, None) or {}
        profile_raw = shared.get("financial_profile") or {}
        try:
            profile = FinancialProfile.model_validate(profile_raw)
        except Exception:  # noqa: BLE001 — 깨진 값 하나가 세션 로드를 막지 않게
            logger.warning("세션의 financial_profile 이 손상돼 비웁니다.")
            profile = FinancialProfile()

        will_status: Optional[WillStatus] = None
        will_status_raw = shared.get("will_status")
        if will_status_raw:
            try:
                will_status = WillStatus.model_validate(will_status_raw)
            except Exception:  # noqa: BLE001
                logger.warning("세션의 will_status 가 손상돼 비웁니다.")

        history: list[dict[str, str]] = []
        for item in shared.get("history") or []:
            # 저장된 값이 깨져 있어도 대화 전체를 날리지 않고 그 줄만 버립니다.
            if (
                isinstance(item, dict)
                and item.get("role") in _HISTORY_ROLES
                and isinstance(item.get("content"), str)
            ):
                history.append({"role": item["role"], "content": item["content"]})

        return cls(
            per_agent_context=raw,
            financial_profile=profile,
            will_status=will_status,
            history=_trim_history(history),
            **kwargs,
        )


class SessionStore:
    """세션 상태 저장소 인터페이스.

    load 의 user_id 는 "이 요청을 보낸 사람"입니다. 남의 세션을 이어받지
    못하게 막고(can_be_accessed_by), 비로그인으로 시작한 세션을 로그인 후
    계정에 붙이는(claim) 판단에 씁니다.

    소유권 검사는 load 와 save 양쪽에 있어야 합니다. load 만 막으면, 남의
    session_id 를 찍어 넣은 요청이 읽기는 실패해서 빈 상태로 시작하더라도
    저장 단계에서 그 빈 상태로 원래 주인의 행을 덮어써 버립니다.
    """

    def load(self, session_id: str, user_id: Optional[str] = None) -> SessionState:
        raise NotImplementedError

    def save(self, session_id: str, state: SessionState) -> None:
        raise NotImplementedError

    def purge_expired(self) -> int:
        """만료된 세션을 실제로 지우고 지운 개수를 돌려줍니다."""
        return 0


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = Lock()

    def load(self, session_id: str, user_id: Optional[str] = None) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None or self._is_expired(state):
                return SessionState(user_id=user_id)
            if not state.can_be_accessed_by(user_id):
                # 남의 세션이면 "없는 것"과 똑같이 취급합니다 (내용 유출 방지).
                logger.warning("소유자가 다른 세션 접근 시도 — 새 세션으로 시작합니다.")
                return SessionState(user_id=user_id)
            return state

    def save(self, session_id: str, state: SessionState) -> None:
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None and not existing.can_be_accessed_by(state.user_id):
                logger.warning(
                    "소유자가 다른 세션에는 저장하지 않습니다(session=%s).",
                    mask_sensitive_id(session_id),
                )
                return
            self._sessions[session_id] = state

    def purge_expired(self) -> int:
        with self._lock:
            expired = [
                sid for sid, st in self._sessions.items() if self._is_expired(st)
            ]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)

    @staticmethod
    def _is_expired(state: SessionState) -> bool:
        ttl = session_ttl_seconds(state.user_id)
        return (time.time() - state.updated_at) > ttl


class PostgresSessionStore(SessionStore):
    """sessions 테이블 기반 구현. 여러 워커/인스턴스로 확장해도 세션을 공유합니다.

    main.py가 DATABASE_URL이 설정돼 있을 때 이 구현체를 만들어
    router.configure_session_store()로 등록합니다. 인터페이스는
    InMemorySessionStore와 동일해서, 오케스트레이터 나머지 코드는 이 클래스의
    존재 자체를 몰라도 됩니다.
    """

    def load(self, session_id: str, user_id: Optional[str] = None) -> SessionState:
        with session_scope() as db:
            row = db.get(ChatSession, session_id)
            if row is None or row.expires_at < datetime.now(timezone.utc):
                return SessionState(user_id=user_id)

            state = SessionState.from_json_context(
                row.per_agent_context or {},
                pending_handoff=(
                    AgentName(row.pending_handoff) if row.pending_handoff else None
                ),
                last_agent=(AgentName(row.last_agent) if row.last_agent else None),
                user_id=row.user_id,
                family_graph_id=row.family_graph_id,
                updated_at=row.updated_at.timestamp(),
            )
            if not state.can_be_accessed_by(user_id):
                # 남의 세션이면 "없는 것"과 똑같이 취급합니다 (내용 유출 방지).
                logger.warning(
                    "소유자가 다른 세션 접근 시도(session=%s) — 새 세션으로 시작합니다.",
                    mask_sensitive_id(session_id),
                )
                return SessionState(user_id=user_id)
            return state

    def save(self, session_id: str, state: SessionState) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=session_ttl_seconds(state.user_id))
        # 같은 session_id로 두 요청이 동시에 "없는 세션"을 보면 둘 다 INSERT를
        # 시도해 PK 충돌이 납니다. flush에서 IntegrityError가 나면 한 번 더
        # 시도해 이미 커밋된 row를 갱신합니다.
        last_error: Optional[IntegrityError] = None
        for _ in range(2):
            try:
                with session_scope() as db:
                    row = db.get(ChatSession, session_id)
                    if row is None:
                        row = ChatSession(session_id=session_id)
                        db.add(row)
                        db.flush()
                    elif row.user_id is not None and row.user_id != state.user_id:
                        # 남의 세션 id 를 찍어 넣은 요청. load 가 이미 빈 상태를
                        # 돌려줬으므로, 여기서 막지 않으면 그 빈 상태가 원래
                        # 주인의 대화를 통째로 덮어씁니다.
                        logger.warning(
                            "소유자가 다른 세션에는 저장하지 않습니다(session=%s).",
                            mask_sensitive_id(session_id),
                        )
                        return

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

                    row.user_id = state.user_id
                    row.family_graph_id = family_graph_id
                    row.last_agent = (
                        state.last_agent.value if state.last_agent else None
                    )
                    row.pending_handoff = (
                        state.pending_handoff.value if state.pending_handoff else None
                    )
                    row.per_agent_context = state.to_json_context()
                    row.expires_at = expires_at
                return
            except IntegrityError as exc:
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    def purge_expired(self) -> int:
        """만료된 세션 행을 실제로 삭제합니다.

        예전에는 load()가 만료된 행을 무시만 하고 행 자체는 영구히 남았습니다.
        비로그인 대화의 원문·사망일·재산정보가 그대로 쌓인다는 뜻이라, 만료를
        "안 보이게 하는 것"과 "지우는 것"을 분리하지 않고 실제로 지웁니다.
        """
        with session_scope() as db:
            result = db.execute(
                delete(ChatSession).where(
                    ChatSession.expires_at < datetime.now(timezone.utc)
                )
            )
            return int(result.rowcount or 0)


#: 오케스트레이터 프로세스 전역에서 공유하는 싱글턴 — 기본값은 인메모리입니다.
#: DATABASE_URL이 설정된 환경에서는 main.py가 시작 시
#: router.configure_session_store(PostgresSessionStore())를 호출해 교체합니다.
#: DATABASE_URL이 없는 환경(지금 CI가 그렇습니다)에서는 이 기본값이 그대로
#: 쓰이므로 기존 동작이 깨지지 않습니다.
default_store = InMemorySessionStore()

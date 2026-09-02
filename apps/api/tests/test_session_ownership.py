"""세션 소유권과 보관 기간 테스트.

비로그인은 "대화창을 떠나면 남지 않는다", 로그인은 "다음 방문에 이어서 쓴다"가
목표입니다. 둘을 가르는 건 sessions.user_id 하나입니다.

- 비로그인(user_id IS NULL): 2시간 뒤 만료, 정리 배치가 실제로 행을 삭제.
- 로그인(user_id 있음): 30일 보관. 가족정보·재산정보·대화 이력이 그대로 남음.

소유권 검사는 load 와 save 양쪽에 있어야 합니다. load 만 막으면 남의
session_id 를 찍어 넣은 요청이 읽기에는 실패하고도, 저장 단계에서 그 빈 상태로
원래 주인의 대화를 덮어써 버립니다. 그 회귀를 여기서 잡습니다.

DB가 필요한 테스트는 with_db(conftest.py)를 쓰고, DB가 없으면 skip합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from auth.repository import create_user
from db.base import session_scope
from orchestrator import router
from orchestrator.models import ChatSession
from orchestrator.session_store import (
    _ANONYMOUS_TTL_SECONDS,
    _AUTHENTICATED_TTL_SECONDS,
    InMemorySessionStore,
    PostgresSessionStore,
    SessionState,
    session_ttl_seconds,
)
from schemas import AgentInput, AgentName, AgentOutput

ALICE = "alice-user-id"
BOB = "bob-user-id"


# ------------------------------------------------------------------ 보관 기간


def test_ttl_splits_on_ownership():
    assert session_ttl_seconds(None) == _ANONYMOUS_TTL_SECONDS
    assert session_ttl_seconds(ALICE) == _AUTHENTICATED_TTL_SECONDS
    assert _ANONYMOUS_TTL_SECONDS < _AUTHENTICATED_TTL_SECONDS


# ------------------------------------------------------------------ 접근 권한


def test_anonymous_session_is_reachable_by_anyone_who_knows_the_id():
    """소유자 없는 세션은 session_id 자체가 접근 권한(capability token)입니다."""
    anonymous = SessionState()

    assert anonymous.can_be_accessed_by(None)
    assert anonymous.can_be_accessed_by(ALICE)


def test_owned_session_is_reachable_only_by_its_owner():
    owned = SessionState(user_id=ALICE)

    assert owned.can_be_accessed_by(ALICE)
    assert not owned.can_be_accessed_by(BOB)
    assert not owned.can_be_accessed_by(None)


# -------------------------------------------------- InMemorySessionStore


def test_other_user_gets_a_fresh_state_instead_of_someone_elses_data():
    store = InMemorySessionStore()
    alice = SessionState(user_id=ALICE)
    alice.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 3}, pending_handoff=None)
    store.save("s", alice)

    intruder = store.load("s", user_id=BOB)

    assert intruder.user_id == BOB
    assert intruder.context_for(AgentName.HEIR_NAVIGATOR) == {}


def test_other_users_save_does_not_clobber_the_owners_session():
    store = InMemorySessionStore()
    alice = SessionState(user_id=ALICE)
    alice.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 3}, pending_handoff=None)
    store.save("s", alice)

    store.save("s", SessionState(user_id=BOB))

    assert store.load("s", user_id=ALICE).context_for(AgentName.HEIR_NAVIGATOR) == {
        "turns": 3
    }


def test_anonymous_request_cannot_clobber_an_owned_session():
    store = InMemorySessionStore()
    alice = SessionState(user_id=ALICE)
    alice.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 3}, pending_handoff=None)
    store.save("s", alice)

    store.save("s", SessionState())  # 로그아웃 상태의 같은 session_id

    assert store.load("s", user_id=ALICE).user_id == ALICE


def test_purge_removes_expired_sessions_only():
    store = InMemorySessionStore()

    fresh = SessionState()
    store.save("fresh", fresh)

    stale = SessionState()
    stale.updated_at -= _ANONYMOUS_TTL_SECONDS + 60
    store.save("stale", stale)

    # 로그인 세션은 같은 시간이 지나도 아직 만료가 아닙니다 (30일).
    stale_but_owned = SessionState(user_id=ALICE)
    stale_but_owned.updated_at -= _ANONYMOUS_TTL_SECONDS + 60
    store.save("owned", stale_but_owned)

    removed = store.purge_expired()

    assert removed == 1
    assert store.load("fresh") is fresh
    assert store.load("owned", user_id=ALICE) is stale_but_owned


# ------------------------------------------------------------ 라우터 왕복


def _fake_agent():
    def _run(payload: AgentInput) -> AgentOutput:
        return AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR, reply="확인했습니다.", data={}
        )

    return _run


def test_logging_in_mid_conversation_claims_the_anonymous_session(monkeypatch):
    """비로그인으로 시작한 대화를 로그인한 채 이어가면 그 자리에서 계정에 붙는다."""
    store = InMemorySessionStore()
    monkeypatch.setattr(router, "default_store", store)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, _fake_agent())

    router.route(AgentInput(session_id="c", user_message="도와주세요"))
    assert store.load("c").user_id is None

    router.route(AgentInput(session_id="c", user_message="이어서요"), user_id=ALICE)

    assert store.load("c", user_id=ALICE).user_id == ALICE


def test_logging_out_does_not_strip_the_owner(monkeypatch):
    """한 번 사용자 것이 된 세션을 토큰 없는 요청이 익명화해 버리면 안 된다."""
    store = InMemorySessionStore()
    monkeypatch.setattr(router, "default_store", store)
    monkeypatch.setitem(router._AGENT_RUNNERS, AgentName.HEIR_NAVIGATOR, _fake_agent())

    router.route(AgentInput(session_id="c", user_message="도와주세요"), user_id=ALICE)
    router.route(AgentInput(session_id="c", user_message="로그아웃 후"))

    assert store.load("c", user_id=ALICE).user_id == ALICE


# ------------------------------------------------- PostgresSessionStore (DB)


def test_postgres_ttl_reflects_ownership(with_db):
    store = PostgresSessionStore()
    store.save("anon", SessionState())
    store.save("owned", SessionState(user_id=None))

    with session_scope() as db:
        anon_expires = db.get(ChatSession, "anon").expires_at

    limit = datetime.now(timezone.utc) + timedelta(seconds=_ANONYMOUS_TTL_SECONDS + 60)
    assert anon_expires < limit


def _make_user(email: str) -> str:
    """FK(sessions.user_id -> users.id) 때문에 실제 사용자 행이 필요합니다."""
    with session_scope() as db:
        return create_user(db, email=email, password_hash="x", name="테스트").id


def test_postgres_other_users_save_does_not_clobber(with_db):
    """load 만 막고 save 를 안 막으면 남의 빈 상태가 원래 대화를 덮어쓴다."""
    store = PostgresSessionStore()
    alice_id = _make_user("alice@test.local")
    bob_id = _make_user("bob@test.local")

    alice = SessionState(user_id=alice_id)
    alice.remember(AgentName.HEIR_NAVIGATOR, context={"turns": 3}, pending_handoff=None)
    store.save("s", alice)

    intruder = store.load("s", user_id=bob_id)
    assert intruder.context_for(AgentName.HEIR_NAVIGATOR) == {}
    store.save("s", intruder)

    survived = store.load("s", user_id=alice_id)
    assert survived.user_id == alice_id
    assert survived.context_for(AgentName.HEIR_NAVIGATOR) == {"turns": 3}


def test_postgres_purge_deletes_expired_rows(with_db):
    """만료를 '조회할 때 무시'로만 두면 행이 영구히 남는다 — 실제로 지운다."""
    store = PostgresSessionStore()
    store.save("alive", SessionState())
    store.save("dead", SessionState())

    with session_scope() as db:
        db.get(ChatSession, "dead").expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )

    removed = store.purge_expired()

    assert removed == 1
    with session_scope() as db:
        assert db.get(ChatSession, "dead") is None
        assert db.get(ChatSession, "alive") is not None

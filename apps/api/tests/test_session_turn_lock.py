"""세션 단위 요청 직렬화(turn_lock) 회귀 테스트 (2026-09-07).

배경: InMemorySessionStore.load()는 저장된 SessionState 객체를 복사 없이
그대로 돌려준다. 같은 session_id로 진짜 동시 요청이 두 번 들어오면(예: 같은
브라우저 세션을 두 탭으로 열고 거의 동시에 메시지를 보낸 경우), 두 요청이
하나의 mutable SessionState를 공유한 채 각자 load→classify→...→persist
파이프라인을 진행한다 — 기존에는 개별 load()/save() 호출만 락으로 보호돼서,
그 사이(파이프라인 실행 구간)에는 보호가 전혀 없었다. 실측(2026-09-07,
23회 threaded 재현)으로 나중에 끝난 요청이 먼저 끝난 요청의 변경 이전 상태를
그대로 응답하는 경우가 12/23회 나왔다(최종 저장값은 매번 정상이었지만 응답
자체가 stale했다).

router.route()가 default_store.turn_lock(session_id)로 파이프라인 전체를
감싸도록 고쳐서, 같은 session_id에 대한 요청은 완전히 직렬화되고(먼저 온
요청의 persist까지 끝나야 다음 요청이 load를 시작), 서로 다른 session_id는
여전히 동시에 처리된다(전역 락이 아니다) — 이 두 가지를 아래에서 검증한다.
"""

from __future__ import annotations

import threading
import time

import pytest

from orchestrator import router
from orchestrator.session_store import InMemorySessionStore, SessionState
from schemas import AgentInput, AgentName, AgentOutput


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())


def _make_recording_agent(agent_name: AgentName, order: list[tuple]):
    """호출될 때마다 (start/end, session_id, thread id)를 순서대로 남기는 가짜 에이전트.

    중간에 짧게 sleep해서(GIL이 풀리는 지점) 실제로 두 스레드가 겹칠 수 있는
    창을 만든다 — turn_lock이 없으면 서로 다른 스레드의 start/end가 뒤섞여
    기록된다.
    """

    def _run(payload: AgentInput) -> AgentOutput:
        tid = threading.get_ident()
        order.append(("start", payload.session_id, tid))
        time.sleep(0.05)
        order.append(("end", payload.session_id, tid))
        return AgentOutput(agent=agent_name, reply="ok", next_action=None, data={})

    return _run


def test_route_serializes_concurrent_requests_for_same_session(monkeypatch):
    order: list[tuple] = []
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.HEIR_NAVIGATOR,
        _make_recording_agent(AgentName.HEIR_NAVIGATOR, order),
    )

    def _call():
        router.route(AgentInput(session_id="shared-session", user_message="도와주세요"))

    threads = [threading.Thread(target=_call) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(order) == 8
    # 직렬화됐다면 각 start 바로 다음 이벤트는 반드시 같은 스레드의 end다 —
    # 다른 스레드의 start/end가 그 사이에 끼어들 수 없다.
    for i in range(0, len(order), 2):
        start_evt, end_evt = order[i], order[i + 1]
        assert start_evt[0] == "start" and end_evt[0] == "end"
        assert start_evt[2] == end_evt[2]


def test_route_does_not_serialize_across_different_sessions(monkeypatch):
    order: list[tuple] = []
    monkeypatch.setitem(
        router._AGENT_RUNNERS,
        AgentName.HEIR_NAVIGATOR,
        _make_recording_agent(AgentName.HEIR_NAVIGATOR, order),
    )

    def _call(session_id: str):
        router.route(AgentInput(session_id=session_id, user_message="도와주세요"))

    t1 = threading.Thread(target=_call, args=("session-a",))
    t2 = threading.Thread(target=_call, args=("session-b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 서로 다른 session_id는 직렬화 대상이 아니므로, 두 스레드의 start가 모두
    # 첫 end보다 먼저 기록될 수 있어야 한다(겹침).
    first_end_index = next(i for i, e in enumerate(order) if e[0] == "end")
    assert first_end_index >= 2


def test_turn_lock_returns_same_lock_instance_for_same_session_id():
    store = InMemorySessionStore()
    lock = store.turn_lock("s1")
    lock.acquire()
    try:
        assert store.turn_lock("s1").acquire(blocking=False) is False
    finally:
        lock.release()


def test_turn_lock_is_independent_across_session_ids():
    store = InMemorySessionStore()
    lock_a = store.turn_lock("s1")
    lock_a.acquire()
    try:
        assert store.turn_lock("s2").acquire(blocking=False) is True
        store.turn_lock("s2").release()
    finally:
        lock_a.release()


def test_purge_expired_prunes_stale_turn_locks():
    store = InMemorySessionStore()
    session = SessionState()
    session.updated_at -= 60 * 60 * 24 * 31  # 만료 TTL을 넘김
    store.save("stale", session)

    lock_before = store.turn_lock("stale")
    store.purge_expired()
    lock_after = store.turn_lock("stale")

    assert lock_before is not lock_after

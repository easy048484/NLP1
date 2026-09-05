from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    # conftest 가 매 테스트 전에 ANTHROPIC_API_KEY 를 비우므로 기본은 unconfigured.
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "llm": "unconfigured"}


def test_health_llm_on(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert client.get("/health").json()["llm"] == "on"


def test_health_llm_off(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "off")
    assert client.get("/health").json()["llm"] == "off"


def test_chat_default_route() -> None:
    resp = client.post(
        "/chat",
        json={
            "session_id": "test-default-route",
            "user_message": "아빠가 돌아가셨어요",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"] == "heir_navigator"


def test_chat_routes_to_decedent_estate() -> None:
    resp = client.post(
        "/chat",
        json={
            "session_id": "test-decedent-estate",
            "user_message": "유언장을 써두고 싶어요",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["agent"] == "decedent_estate"


def test_chat_routes_to_tax_calculator() -> None:
    # 별도 session_id를 쓴다 — 위 test_chat_routes_to_decedent_estate와 같은
    # session_id를 공유하면, decedent_estate가 자료를 요청하며 낸
    # next_action=await_user_confirmation이 pending_reply_agent로 저장돼(연속
    # 대화 이탈 방지 기능, router.py 참고) 이 턴의 키워드("상속세")보다
    # 우선하게 되어 tax_calculator가 아니라 decedent_estate로 라우팅된다 —
    # 세 테스트는 서로 무관한 새 대화를 검증하려는 의도이므로 session_id를
    # 분리하는 것이 맞는 수정이다.
    resp = client.post(
        "/chat",
        json={
            "session_id": "test-tax-calculator",
            "user_message": "상속세가 얼마나 나올까요",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["agent"] == "tax_calculator"

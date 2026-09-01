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
        json={"session_id": "test", "user_message": "아빠가 돌아가셨어요"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"] == "heir_navigator"


def test_chat_routes_to_decedent_estate() -> None:
    resp = client.post(
        "/chat",
        json={"session_id": "test", "user_message": "유언장을 써두고 싶어요"},
    )
    assert resp.status_code == 200
    assert resp.json()["agent"] == "decedent_estate"


def test_chat_routes_to_tax_calculator() -> None:
    resp = client.post(
        "/chat",
        json={"session_id": "test", "user_message": "상속세가 얼마나 나올까요"},
    )
    assert resp.status_code == 200
    assert resp.json()["agent"] == "tax_calculator"

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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

"""
review 모드 document intake gate (agent.py._document_intake_output).

버그: "아버지가 돌아가시고 집 정리하다가 손으로 직접 쓴 유언장을 발견했어요.
이게 법적으로 효력이 있는 건지 확인하고 싶어요." 같은 상담 요청 문장은
handwritten 방식 추론(#92)까지는 정상 동작하지만, 실제 유언장 사진/본문이
없는데도 곧바로 check_requirements() 가 이 요청 문장을 유언장 본문처럼
검사해 날짜/주소/성명이 없다며 RED 판정을 매기고 있었다.

수정: review 모드에서 사진도, 실제 유언장 본문/초안으로 볼 만한 텍스트도
없으면(_looks_like_draft — prepare 모드가 쓰던 것과 동일 heuristic 재사용)
요건 판정 자체를 돌리지 않고 자료(사진 또는 본문)를 요청한다.
"""

from typing import Any

from agents import decedent_estate
from agents.decedent_estate.agent import NEXT_ACTION_AWAIT_USER
from schemas import AgentInput

_REQUEST_ONLY_MESSAGE = (
    "아버지가 돌아가시고 집 정리하다가 손으로 직접 쓴 유언장을 발견했어요. "
    "이게 법적으로 효력이 있는 건지 확인하고 싶어요."
)

_WILL_TEXT_COMPLETE = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 전 재산을 배우자에게 상속한다."
)

_FAKE_IMAGE = "ZmFrZS1pbWFnZS1kYXRh"  # "fake-image-data"의 base64, 실제 이미지 아님


def test_document_intake_gate_blocks_requirement_check_without_document() -> None:
    """실제 유언장 자료 없이 상담 요청 문장만 왔을 때: will_type은 handwritten으로
    확정되고(#92), 방식 재질문도 없지만, 요건 판정은 아예 돌지 않고 자료를
    요청해야 한다."""
    payload = AgentInput(session_id="s1", user_message=_REQUEST_ONLY_MESSAGE)

    output = decedent_estate.run(payload)

    assert output.data["will_type"] == "handwritten"
    assert "어떤 형태의 유언인가요?" not in output.reply

    # 판정 결과를 아직 만들지 않았다 — 날짜/주소/성명에 RED가 매겨지면 안 된다.
    assert "requirements" not in output.data
    namespaced = output.data["decedent_estate"]
    assert namespaced.get("requirements", {}) == {}

    # 사용자에게 사진 업로드 또는 본문 입력을 요청한다.
    assert (
        "유언장 사진을 올려주시거나, 적힌 내용을 그대로 입력해 주세요" in output.reply
    )
    assert output.next_action == NEXT_ACTION_AWAIT_USER


def test_actual_will_text_still_runs_existing_requirement_check() -> None:
    """실제 유언장 본문이 오면(날짜·주소·처분 의사 포함) 기존 판정 파이프라인이
    그대로 돈다 — intake gate 회귀 없음."""
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"will_type": "handwritten"},
    )

    output = decedent_estate.run(payload)

    assert output.data["will_type"] == "handwritten"
    assert "requirements" in output.data
    requirements = output.data["requirements"]
    assert requirements["date"]["grade"] == "GREEN"
    assert requirements["address"]["grade"] == "GREEN"


def test_image_upload_is_not_blocked_by_intake_gate(monkeypatch) -> None:
    """사진이 함께 들어오면(payload.image_base64) 요청 문장만 있어도 intake gate에
    막히지 않고 기존 사진 판독 파이프라인이 실행돼야 한다."""
    fields: dict[str, dict[str, Any]] = {
        "name": {"value": "홍길동", "confidence": "high"},
        "address": {
            "value": "서울특별시 강남구 테헤란로 123, 45동 678호",
            "confidence": "high",
        },
        "date": {"value": "2026년 5월 3일", "confidence": "high"},
        "seal": {"value": "seal_or_fingerprint", "confidence": "high"},
    }
    monkeypatch.setattr(
        decedent_estate.agent, "extract_will_photo_fields", lambda *a, **kw: fields
    )

    output = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_REQUEST_ONLY_MESSAGE,
            context={"will_type": "handwritten"},
            image_base64=_FAKE_IMAGE,
            image_media_type="image/jpeg",
        )
    )

    assert "유언장 사진을 올려주시거나" not in output.reply
    requirements = output.data["decedent_estate"]["requirements"]
    assert requirements["name"]["grade"] == "GREEN"
    assert requirements["date"]["grade"] == "GREEN"


def test_document_provided_on_next_turn_proceeds_normally() -> None:
    """1턴: 자료 없이 상담 요청만 → intake gate. 2턴: 실제 본문을 보내면 이어서
    기존 판정이 정상 실행돼야 한다."""
    turn1 = decedent_estate.run(
        AgentInput(session_id="s1", user_message=_REQUEST_ONLY_MESSAGE)
    )
    assert "requirements" not in turn1.data
    assert turn1.next_action == NEXT_ACTION_AWAIT_USER

    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_WILL_TEXT_COMPLETE,
            context=turn1.data["decedent_estate"],
        )
    )
    assert turn2.data["will_type"] == "handwritten"
    assert "requirements" in turn2.data
    assert turn2.data["requirements"]["date"]["grade"] == "GREEN"

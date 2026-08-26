"""
유언장 사진 판독 1단계 통합 테스트 (agent.py._resolve_photo_intake).

LLM 호출은 agents.decedent_estate.agent.extract_will_photo_fields 를 직접
monkeypatch 해서 가짜로 바꾼다 — image_reader.py 내부까지 내려가지 않으므로
실제 네트워크 호출도, conftest.py 의 격리 fixture(#34)도 전혀 관여하지 않는다.

핵심 확인 사항:
1. 판독 결과가 기존 요건 판정에 정상 투입되는지 (재구성 텍스트 → check_requirements)
2. 확신도 3단(high/low/none) 각각의 분기
3. 자서 요건은 LLM 판정이 아니라 항상 확인 질문으로 가는지 (설계 방침 F)
4. 이미지가 세션·응답 어디에도 남지 않는지
5. 기존 텍스트 입력 경로 회귀 (이미지 없이도 그대로 동작)
"""

from typing import Any

from agents import decedent_estate
from schemas import AgentInput

_FAKE_IMAGE = "ZmFrZS1pbWFnZS1kYXRh"  # "fake-image-data"의 base64, 실제 이미지 아님


def _all_high() -> dict[str, dict[str, Any]]:
    return {
        "name": {"value": "홍길동", "confidence": "high"},
        "address": {
            "value": "서울특별시 강남구 테헤란로 123, 45동 678호",
            "confidence": "high",
        },
        "date": {"value": "2026년 5월 3일", "confidence": "high"},
        "seal": {"value": "seal_or_fingerprint", "confidence": "high"},
    }


def _upload(monkeypatch, fields, *, user_message: str = "", **context):
    monkeypatch.setattr(
        decedent_estate.agent, "extract_will_photo_fields", lambda *a, **kw: fields
    )
    return decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=user_message,
            context=context,
            image_base64=_FAKE_IMAGE,
            image_media_type="image/jpeg",
        )
    )


# ---------------------------------------------------------------------------
# [1]/[2] 확신도 3단 분기
# ---------------------------------------------------------------------------


def test_all_high_confidence_fills_immediately_without_questions(monkeypatch) -> None:
    """전부 명확히 읽혔으면 확인 질문 없이 곧바로 요건 판정까지 끝난다.

    단, 자서는 예외 — 방침 F에 따라 여전히 확인을 물어야 한다(아래 별도 테스트).
    """
    out = _upload(monkeypatch, _all_high(), will_type="handwritten")

    requirements = out.data["decedent_estate"]["requirements"]
    assert requirements["name"]["grade"] == "GREEN"
    assert requirements["address"]["grade"] == "GREEN"
    assert requirements["date"]["grade"] == "GREEN"
    assert requirements["seal"]["grade"] == "GREEN"
    assert requirements["seal"]["condition_id"] == "seal_or_fingerprint"

    photo_questions = [
        q
        for q in out.data["decedent_estate"]["pending_questions"]
        if q["field"].startswith("photo_confirm_answers.")
    ]
    assert photo_questions == []


def test_low_confidence_field_asks_confirmation_before_judging(monkeypatch) -> None:
    """애매한 필드가 있으면 요건 판정을 미루고 먼저 확인 질문을 낸다."""
    fields = _all_high()
    fields["date"] = {"value": "2026년 5월 3일", "confidence": "low"}

    out = _upload(monkeypatch, fields, will_type="handwritten")

    assert out.next_action == "await_user_confirmation"
    assert out.data["decedent_estate"]["requirements"] == {}

    questions = out.data["decedent_estate"]["pending_questions"]
    assert len(questions) == 1
    assert questions[0]["field"] == "photo_confirm_answers.date"
    assert "2026년 5월 3일" in questions[0]["question"]
    assert {"label": "예, 맞습니다", "value": "yes"} in questions[0]["options"]


def test_confirming_yes_completes_judgment_on_next_turn(monkeypatch) -> None:
    """확인 질문에 "예"로 답하면(사진 재전송 없이) 판정이 완료된다."""
    fields = _all_high()
    fields["date"] = {"value": "2026년 5월 3일", "confidence": "low"}
    turn1 = _upload(monkeypatch, fields, will_type="handwritten")

    stored = turn1.data["decedent_estate"]
    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="",
            context={
                "decedent_estate": {
                    **stored,
                    "photo_confirm_answers": {"date": "yes"},
                }
            },
        )
    )

    requirements = turn2.data["decedent_estate"]["requirements"]
    assert requirements["date"]["grade"] == "GREEN"
    assert requirements["date"]["extracted"]["entries"][0]["year"] == 2026
    # 확인이 끝났으니 draft/answers는 소비되어 비어 있어야 한다.
    assert turn2.data["decedent_estate"]["photo_draft"] == {}
    assert turn2.data["decedent_estate"]["photo_confirm_answers"] == {}


def test_confirming_no_drops_field_and_falls_back_to_typed_text(monkeypatch) -> None:
    """ "아니요"로 답하면 그 필드는 판독값을 버리고, 사용자가 그 턴에 직접
    입력한 텍스트를 기존 정규식이 그대로 다시 찾는다."""
    fields = _all_high()
    fields["date"] = {"value": "2026년 5월 3일", "confidence": "low"}
    turn1 = _upload(monkeypatch, fields, will_type="handwritten")

    stored = turn1.data["decedent_estate"]
    turn2 = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="2026년 7월 20일",  # 사용자가 직접 정정
            context={
                "decedent_estate": {
                    **stored,
                    "photo_confirm_answers": {"date": "no"},
                }
            },
        )
    )

    requirements = turn2.data["decedent_estate"]["requirements"]
    entry = requirements["date"]["extracted"]["entries"][0]
    assert (entry["year"], entry["month"], entry["day"]) == (2026, 7, 20)


def test_none_confidence_field_is_absent_without_a_photo_question(monkeypatch) -> None:
    """전혀 못 읽었으면(confidence="none") *사진 확인* 질문은 내지 않는다
    (물어봐야 소용없다 — 값 자체가 없다). 그 필드는 그냥 absent로 재구성 텍스트에서
    빠지고, 이후 기존 요건 판정 로직(예: 주소의 봉투 확인 followup)이 평소와
    동일하게 이어받는다 — 재구성 텍스트가 기존 파이프라인을 그대로 타고 있다는
    증거이기도 하다."""
    fields = _all_high()
    fields["address"] = {"value": None, "confidence": "none"}

    out = _upload(monkeypatch, fields, will_type="handwritten")

    photo_questions = [
        q
        for q in out.data["decedent_estate"]["pending_questions"]
        if q["field"].startswith("photo_confirm_answers.")
    ]
    assert photo_questions == []
    # absent가 된 주소는 기존 address.followup(봉투 확인)으로 자연히 이어진다.
    assert out.data["decedent_estate"]["requirements"]["address"]["grade"] == "PENDING"
    assert any(
        q["field"] == "address_envelope_answer"
        for q in out.data["decedent_estate"]["pending_questions"]
    )


# ---------------------------------------------------------------------------
# [3] 자서(전문 자서) — 절대 LLM 판정 아님, 항상 확인 질문 (설계 방침 F)
# ---------------------------------------------------------------------------


def test_handwriting_always_stays_a_direct_question_even_at_high_confidence(
    monkeypatch,
) -> None:
    """사진의 다른 3필드가 전부 명확히 읽혀도 자서 여부는 절대 자동 판정하지
    않는다 — 필적 감정 영역이라 LLM에게 물어보지도 않는다."""
    out = _upload(monkeypatch, _all_high(), will_type="handwritten")

    requirements = out.data["decedent_estate"]["requirements"]
    assert requirements["handwriting"]["grade"] == "PENDING"

    questions = out.data["decedent_estate"]["pending_questions"]
    assert any(q["field"] == "handwriting_answer" for q in questions)


def test_extraction_result_never_contains_a_handwriting_field(monkeypatch) -> None:
    """판독 모듈 자체가 자서 필드를 반환할 방법이 없다는 것도 확인한다."""
    from agents.decedent_estate.image_reader import PHOTO_FIELD_IDS

    assert "handwriting" not in PHOTO_FIELD_IDS


# ---------------------------------------------------------------------------
# [4] 🔴 이미지 미저장
# ---------------------------------------------------------------------------


def test_image_data_never_appears_in_response(monkeypatch) -> None:
    out = _upload(monkeypatch, _all_high(), will_type="handwritten")

    assert _FAKE_IMAGE not in out.model_dump_json()


def test_state_model_has_no_field_for_image_data() -> None:
    """C안과 동일한 원칙 — 이미지를 담을 필드 자체가 없어야 한다."""
    from agents.decedent_estate.state import DecedentState

    fields = set(DecedentState.model_fields)
    assert "image_base64" not in fields
    assert "image" not in fields
    assert "photo" not in fields  # photo_draft/photo_confirm_answers는 예외적으로 허용


def test_photo_draft_holds_only_short_extracted_values_not_raw_image(
    monkeypatch,
) -> None:
    """photo_draft에 저장되는 것은 4개 필드의 문자열/열거값뿐임을 직접 확인한다."""
    fields = _all_high()
    fields["date"] = {"value": "2026년 5월 3일", "confidence": "low"}  # 확인 대기 유도
    out = _upload(monkeypatch, fields, will_type="handwritten")

    draft = out.data["decedent_estate"]["photo_draft"]
    assert set(draft.keys()) == {"name", "address", "date", "seal"}
    assert _FAKE_IMAGE not in str(draft)


def test_extraction_failure_does_not_block_manual_typing(monkeypatch) -> None:
    """판독이 실패해도(None) 에이전트가 죽지 않고 안내만 한다."""
    out = _upload(monkeypatch, None, will_type="handwritten")

    assert "직접 입력" in out.reply
    assert out.data["decedent_estate"]["requirements"] == {}


# ---------------------------------------------------------------------------
# [5] 기존 텍스트 입력 경로 회귀 — 이미지 없이도 완전히 동일하게 동작
# ---------------------------------------------------------------------------


def test_no_image_leaves_existing_text_path_untouched(monkeypatch) -> None:
    """이미지가 아예 없으면 _resolve_photo_intake가 개입조차 하지 않는다."""

    def _fail_if_called(*a, **kw):
        raise AssertionError("이미지가 없으면 판독 함수를 호출하면 안 된다")

    monkeypatch.setattr(
        decedent_estate.agent, "extract_will_photo_fields", _fail_if_called
    )

    text = (
        "유언자: 김철수\n주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
        "2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
    )
    out = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=text,
            context={
                "will_type": "handwritten",
                "handwriting_answer": "yes",
                "seal_answer": "seal_or_fingerprint",
            },
        )
    )

    requirements = out.data["decedent_estate"]["requirements"]
    assert requirements["name"]["grade"] == "GREEN"
    assert out.data["decedent_estate"]["photo_draft"] == {}

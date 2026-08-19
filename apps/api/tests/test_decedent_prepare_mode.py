"""
피상속인(생전 준비) 모드 — intent 게이트 + prepare(작성 가이드) 파이프라인 테스트.

context.will_type 이 확정된 다음 단계로 context.intent("review"|"prepare")를
확인한다. 미지정 시 review로 조용히 기본 동작(하위 호환)하는지, 잘못된 값이면
will_type 게이트와 같은 패턴으로 재질문하는지, prepare 모드가 요건별 가이드
문구(📝)를 내는지, 초안이 있으면 기존 review 파이프라인 결과가 그대로 이어
붙는지를 확인한다. review 모드 자체가 안 깨지는지는 기존
test_decedent_agent.py / test_decedent_recording.py / test_decedent_will_type.py
가 계속 통과하는 것으로 확인한다(이 파일은 intent 특화 케이스만 다룬다).
"""

import json
from pathlib import Path

from agents import decedent_estate
from agents.decedent_estate.agent import (
    NEXT_ACTION_AWAIT_USER,
    NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
)
from agents.decedent_estate.recording_checker import FORMAL_RECORDING_REQUIREMENT_IDS
from schemas import AgentInput

_PRECEDENTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "decedent_estate"
    / "rules"
    / "precedents.json"
)

_HANDWRITTEN_GUIDE_IDS = ("date", "address", "name", "handwriting", "seal")

_WILL_TEXT_COMPLETE = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 전 재산을 배우자에게 상속한다."
)


def _citation(precedent_id: str) -> str:
    with _PRECEDENTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    p = next(x for x in data["precedents"] if x["id"] == precedent_id)
    if p["type"] == "commentary":
        return "(대한법률구조공단 해설)"
    if p["type"] == "statute":
        return f"({p['source']})"
    return f"({p['court']} {p['case_number']})"


def _run(text: str, **context):
    payload = AgentInput(session_id="s1", user_message=text, context=context)
    return decedent_estate.run(payload)


# ---------------------------------------------------------------------------
# intent 게이트
# ---------------------------------------------------------------------------


def test_missing_intent_defaults_to_review_and_matches_existing_pipeline() -> None:
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    # intent를 아예 안 보내는 옛 호출부와 동일하게 review 파이프라인이 그대로 돈다.
    assert "guide" not in output.data
    assert "requirements" in output.data
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply


def test_explicit_review_intent_matches_missing_intent() -> None:
    omitted = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )
    explicit = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="review",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    assert omitted.reply == explicit.reply
    assert omitted.data == explicit.data


def test_invalid_intent_reasks_with_warning() -> None:
    output = _run(_WILL_TEXT_COMPLETE, will_type="handwritten", intent="whatever")

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert "지금 필요하신 게 어떤 건가요?" in output.reply
    assert output.data["will_type"] == "handwritten"
    assert output.data["warnings"] == [
        {
            "field": "intent",
            "invalid_value": "whatever",
            "allowed": ["review", "prepare"],
        }
    ]
    [question] = output.data["pending_questions"]
    assert question["field"] == "intent"
    assert question["options"] == [
        {"value": "review", "label": "이미 작성한 유언장/대본을 점검하고 싶어요"},
        {"value": "prepare", "label": "아직 작성 전이고, 준비 방법이 궁금해요"},
    ]
    assert "requirements" not in output.data  # 재질문 단계라 판정 파이프라인은 안 돈다


def test_will_type_gate_still_runs_before_intent_gate() -> None:
    """will_type 이 아예 없으면 intent와 무관하게 방식부터 물어봐야 한다."""
    output = _run(_WILL_TEXT_COMPLETE, intent="prepare")

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_notarial_ignores_intent_entirely() -> None:
    """notarial/secret/oral은 review/prepare 구분이 없는 안내 전용 분기라 intent
    값과 무관하게 기존 안내 문구만 나와야 한다."""
    output = _run(_WILL_TEXT_COMPLETE, will_type="notarial", intent="prepare")

    assert output.reply == (
        "공증인이 작성한 유언은 형식 요건 검증이 필요하지 않습니다. "
        "가정법원 검인 절차도 필요하지 않습니다."
    )
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
    assert "guide" not in output.data


# ---------------------------------------------------------------------------
# prepare 모드 — handwritten, 초안 없음 (가이드만)
# ---------------------------------------------------------------------------


def test_prepare_handwritten_without_draft_returns_guide_only() -> None:
    output = _run("", will_type="handwritten", intent="prepare")

    assert output.next_action is None
    assert "requirements" not in output.data
    assert "review" not in output.data
    assert output.data["will_type"] == "handwritten"
    assert output.data["intent"] == "prepare"
    assert set(output.data["guide"].keys()) == set(_HANDWRITTEN_GUIDE_IDS)

    assert "**자필증서 유언 작성 가이드입니다.**" in output.reply
    assert "✅" not in output.reply and "❌" not in output.reply

    date_citation = _citation("date_missing_day_invalid")
    assert (
        f"📝 연월일: 연월일을 쓰실 때는 반드시 일(日)까지 적어주세요. "
        f'"2026년 5월"처럼 일이 빠지면 무효가 된 판례가 있습니다 {date_citation}.'
    ) in output.reply

    seal_citation = _citation("signature_only_insufficient")
    assert (
        f"📝 날인: 도장이나 지장을 반드시 찍어주세요. 서명(사인)만으로는 인정되지 않습니다 "
        f"{seal_citation}. 지장도 유효합니다."
    ) in output.reply

    assert "작성하신 초안(또는 대본)이 있다면 그대로 보내주세요" in output.reply


def test_prepare_guide_payload_structure_for_seal() -> None:
    output = _run("", will_type="handwritten", intent="prepare")

    seal_guide = output.data["guide"]["seal"]
    assert seal_guide == {
        "id": "seal",
        "name": "날인",
        "instruction": "도장이나 지장을 반드시 찍어주세요.",
        "mistake_sentence": "서명(사인)만으로는 인정되지 않습니다",
        "mistake_precedent_id": "signature_only_insufficient",
        "extra_note": "지장도 유효합니다.",
    }


def test_prepare_unknown_will_type_defaults_to_handwritten_guide_with_notice() -> None:
    output = _run("", will_type="unknown", intent="prepare")

    assert output.reply.startswith("가장 널리 쓰이는 자필증서 기준으로 점검하겠습니다")
    assert "**자필증서 유언 작성 가이드입니다.**" in output.reply
    assert output.data["will_type"] == "handwritten"


# ---------------------------------------------------------------------------
# prepare 모드 — recording, 초안 없음 (가이드만)
# ---------------------------------------------------------------------------


def test_prepare_recording_without_draft_returns_guide_only() -> None:
    output = _run("", will_type="recording", intent="prepare")

    assert output.next_action is None
    assert "requirements" not in output.data
    assert set(output.data["guide"].keys()) == set(FORMAL_RECORDING_REQUIREMENT_IDS)
    assert "**녹음 유언 작성 가이드입니다.**" in output.reply
    assert "✅" not in output.reply and "❌" not in output.reply

    date_citation = _citation("date_missing_day_invalid")
    assert (
        f"📝 연월일: 연월일을 구술할 때는 반드시 일(日)까지 말해주세요. "
        f'"2026년 5월"처럼 일이 빠지면 무효가 된 판례가 있습니다 {date_citation}.'
    ) in output.reply

    eligible_citation = _citation("witness_disqualification")
    assert (
        f"📝 증인 결격 여부: 증인은 미성년자, 피성년후견인·피한정후견인, 그리고 이 "
        f"유언으로 재산을 받는 사람과 그 배우자·직계혈족이 아니어야 합니다. "
        f"결격 사유가 있는 사람을 증인으로 세우면 요건을 갖추지 못합니다 "
        f"{eligible_citation}. 유언집행자라는 사정만으로는 증인 결격이 아니라고 "
        f"본 판례가 있습니다."
    ) in output.reply


# ---------------------------------------------------------------------------
# prepare 모드 + 초안 있음 → 가이드 + review 결과 둘 다
# ---------------------------------------------------------------------------


def test_prepare_handwritten_with_draft_also_includes_review_result() -> None:
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="prepare",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    assert "**자필증서 유언 작성 가이드입니다.**" in output.reply
    assert "작성하신 초안을 점검한 결과입니다." in output.reply
    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply
    assert "✅ 연월일: 기재 확인" in output.reply

    assert "review" in output.data
    assert output.data["review"]["requirements"]["date"]["grade"] == "GREEN"
    # 초안이 있어도 가이드 정보는 그대로 함께 반환된다.
    assert set(output.data["guide"].keys()) == set(_HANDWRITTEN_GUIDE_IDS)
    # next_action은 review 결과를 그대로 따른다.
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR


def test_prepare_handwritten_with_incomplete_draft_still_pending() -> None:
    """초안은 있지만 확인 답변이 없으면 review 파트는 여전히 PENDING이어야 한다."""
    output = _run(_WILL_TEXT_COMPLETE, will_type="handwritten", intent="prepare")

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert output.data["review"]["requirements"]["handwriting"]["grade"] == "PENDING"


def test_prepare_recording_with_draft_also_includes_review_result() -> None:
    transcript = "\n".join(
        [
            "유언자: 홍길동",
            "저의 전 재산을 배우자에게 상속한다.",
            "2026년 5월 3일",
            "증인: 김철수",
            "증인은 위 유언이 정확함을 확인합니다.",
        ]
    )
    output = _run(
        transcript,
        will_type="recording",
        intent="prepare",
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    assert "**녹음 유언 작성 가이드입니다.**" in output.reply
    assert "작성하신 대본을 점검한 결과입니다." in output.reply
    assert "✅ 연월일: 기재 확인" in output.reply
    assert "review" in output.data
    assert output.data["review"]["requirements"]["rec_content"]["grade"] == "GREEN"
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR


def test_prepare_has_draft_context_flag_overrides_heuristic() -> None:
    """has_draft=False를 명시하면 user_message에 내용이 있어도 가이드만 준다."""
    output = _run(
        _WILL_TEXT_COMPLETE, will_type="handwritten", intent="prepare", has_draft=False
    )

    assert "review" not in output.data
    assert "requirements" not in output.data
    assert output.next_action is None


# ---------------------------------------------------------------------------
# 마무리 문구(§3-3 상담 연결 · §3-4 하단 고지) 중복 방지
#
# 가이드 블록(format_guide)과 점검 블록(format_result)이 각각 같은 두 줄로 끝나서,
# 초안을 함께 낸 경우 한 화면에 두 번씩 반복되던 문제의 회귀 방지. 개수를 세지
# 않고 `in`으로만 검사하면 중복을 못 잡으므로 여기서는 count()로 확인한다.
# ---------------------------------------------------------------------------

_CONSULTATION_MARK = "대한법률구조공단 132"
_FOOTER_MARK = "법률 자문이 아닙니다"


def _assert_closing_appears_once(reply: str) -> None:
    assert reply.count(_CONSULTATION_MARK) == 1, "상담 연결 문구가 한 번만 나와야 한다"
    assert reply.count(_FOOTER_MARK) == 1, "하단 고지가 한 번만 나와야 한다"


def test_prepare_handwritten_with_draft_has_no_duplicated_closing() -> None:
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="prepare",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    _assert_closing_appears_once(output.reply)
    # 마무리 문구는 가이드가 아니라 점검 결과 뒤(맨 끝)에 남아야 한다.
    assert output.reply.index(_CONSULTATION_MARK) > output.reply.index(
        "작성하신 초안을 점검한 결과입니다."
    )


def test_prepare_recording_with_draft_has_no_duplicated_closing() -> None:
    transcript = "\n".join(
        [
            "유언자: 홍길동",
            "저의 전 재산을 배우자에게 상속한다.",
            "2026년 5월 3일",
            "증인: 김철수",
            "증인은 위 유언이 정확함을 확인합니다.",
        ]
    )
    output = _run(
        transcript,
        will_type="recording",
        intent="prepare",
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    _assert_closing_appears_once(output.reply)


def test_prepare_without_draft_still_keeps_closing_once() -> None:
    """초안이 없어 가이드만 보여줄 때는 마무리 문구가 그대로 (한 번) 있어야 한다 —
    스펙 §3-3/§3-4는 "모든 결과 화면"에 들어가야 하므로 중복 제거가 누락으로
    바뀌면 안 된다."""
    for will_type in ("handwritten", "recording"):
        output = _run("", will_type=will_type, intent="prepare")
        _assert_closing_appears_once(output.reply)


def test_review_mode_closing_unaffected() -> None:
    """기존 review 모드는 이번 수정과 무관하게 그대로 한 번씩만 나와야 한다."""
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    _assert_closing_appears_once(output.reply)

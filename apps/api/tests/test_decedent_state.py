"""
네임스페이스 규약(orchestrator/handoff.py 1번) 전환 테스트.

세 갈래를 확인한다:
1. state.py 단위 — load_state/dump_state, 스키마 불일치 방어, 평면 폴백 우선순위
2. agent.run() 레벨 — 네임스페이스 입력과 평면 입력이 같은 판정을 내는지
3. C안 저장 정책 — data["decedent_estate"] 에 유언장 원문이 절대 들어가지 않는지

3번이 이 PR의 핵심 안전장치다. 원문을 담을 필드 자체가 DecedentState 에 없지만,
누군가 나중에 필드를 늘리다 원문을 흘릴 수 있어 출력물 전체를 문자열로 훑어
확인한다.
"""

import json

import pytest

from agents import decedent_estate
from agents.decedent_estate.state import (
    STATE_KEY,
    DecedentState,
    dump_state,
    load_state,
)
from schemas import AgentInput

_WILL_TEXT = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 전 재산을 배우자에게 상속한다."
)

_TRANSCRIPT = "\n".join(
    [
        "유언자: 홍길동",
        "저의 전 재산을 배우자에게 상속한다.",
        "2026년 5월 3일",
        "증인: 김철수",
        "증인은 위 유언이 정확함을 확인합니다.",
    ]
)


# ---------------------------------------------------------------------------
# 1. state.py 단위
# ---------------------------------------------------------------------------


def test_load_state_from_namespace() -> None:
    state = load_state({STATE_KEY: {"will_type": "recording", "seal_answer": "absent"}})

    assert state.will_type == "recording"
    assert state.seal_answer == "absent"


def test_load_state_without_context_is_empty() -> None:
    for context in (None, {}, {"unrelated": 1}):
        state = load_state(context)
        assert state.will_type is None
        assert state.requirements == {}


def test_load_state_falls_back_to_flat_keys() -> None:
    """네임스페이스가 아예 없으면 평면 키를 읽는다 (옛 클라이언트)."""
    state = load_state({"will_type": "handwritten", "handwriting_answer": "yes"})

    assert state.will_type == "handwritten"
    assert state.handwriting_answer == "yes"


def test_flat_key_this_turn_wins_over_stored_namespace() -> None:
    """평면 키는 "이번 턴 입력", 네임스페이스는 "지난 턴 상태"라 평면이 우선한다.

    사용자가 답을 바꿔 다시 보냈는데 지난 턴 값이 이기면 안 된다
    (handoff.build_agent_context 의 "이번 턴에 명시적으로 답한 값이 우선" 원칙).
    """
    state = load_state(
        {
            STATE_KEY: {"will_type": "handwritten", "seal_answer": "signature_only"},
            "seal_answer": "seal_or_fingerprint",
        }
    )

    assert state.will_type == "handwritten"  # 평면에 없으면 네임스페이스 값 유지
    assert state.seal_answer == "seal_or_fingerprint"  # 이번 턴 답이 이김


def test_broken_namespace_state_starts_empty_instead_of_raising() -> None:
    """스키마가 안 맞아도 예외 대신 빈 상태 — 상태 하나로 대화가 죽지 않게."""
    for broken in ({"requirements": "요건이-dict가-아님"}, {"pending_questions": 5}):
        state = load_state({STATE_KEY: broken})
        assert state.will_type is None

    # 네임스페이스 자리에 dict가 아닌 값이 와도 마찬가지.
    assert load_state({STATE_KEY: "문자열"}).will_type is None


def test_broken_flat_value_keeps_namespace_state() -> None:
    state = load_state({STATE_KEY: {"will_type": "handwritten"}, "has_draft": "예"})

    assert state.will_type == "handwritten"


def test_empty_string_flat_value_does_not_override_namespace() -> None:
    """빈 문자열은 "미지정"이라 저장된 값을 덮어쓰면 안 된다.

    프론트가 아직 선택 안 한 필드를 `will_type=""` 로 실어 보내는 경우가 있는데,
    이게 override 로 인정되면 will_type 게이트가 다시 열려 사용자가 이미 답한
    질문을 또 받게 된다.
    """
    state = load_state(
        {
            STATE_KEY: {"will_type": "handwritten", "seal_answer": "signature_only"},
            "will_type": "",
            "seal_answer": "",
        }
    )

    assert state.will_type == "handwritten"
    assert state.seal_answer == "signature_only"


def test_false_has_draft_is_still_a_valid_override() -> None:
    """회귀: has_draft=False 는 bool 이라 빈 문자열 필터에 걸리지 않아야 한다.

    `False == ""` 는 False 이므로 그대로 유효한 override 로 남는다 — "초안이
    없다"는 명시적 답을 잃으면 prepare 모드가 잘못 동작한다.
    """
    state = load_state({STATE_KEY: {"has_draft": True}, "has_draft": False})

    assert state.has_draft is False


def test_dump_state_roundtrip() -> None:
    original = DecedentState(will_type="handwritten", handwriting_answer="yes")
    assert load_state({STATE_KEY: dump_state(original)}) == original


def test_state_model_has_no_field_for_raw_text() -> None:
    """C안 — 원문을 담을 필드 자체가 없어야 한다."""
    fields = set(DecedentState.model_fields)

    assert "user_message" not in fields
    assert "text" not in fields
    assert "will_text" not in fields


def test_state_model_has_no_field_for_raw_image() -> None:
    """사진 판독 1단계(방침 B) — 원본 이미지를 담을 필드 자체가 없어야 한다.

    photo_draft/photo_confirm_answers는 판독 결과의 짧은 문자열/열거값만
    담는 자리이지 이미지 데이터를 담는 자리가 아니다 — 별도 확인:
    test_decedent_photo_intake.py::test_photo_draft_holds_only_short_extracted_values_not_raw_image
    """
    fields = set(DecedentState.model_fields)

    assert "image" not in fields
    assert "image_base64" not in fields
    assert "photo" not in fields
    assert "photo_base64" not in fields


# ---------------------------------------------------------------------------
# 2. agent.run() — 네임스페이스 / 평면 둘 다
# ---------------------------------------------------------------------------


def _flat(text: str, **context):
    return decedent_estate.run(
        AgentInput(session_id="s1", user_message=text, context=context)
    )


def _namespaced(text: str, **context):
    return decedent_estate.run(
        AgentInput(session_id="s1", user_message=text, context={STATE_KEY: context})
    )


@pytest.mark.parametrize("run", [_flat, _namespaced], ids=["flat", "namespaced"])
def test_handwritten_judgment_identical_in_both_context_styles(run) -> None:
    output = run(
        _WILL_TEXT,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    grades = {rid: r["grade"] for rid, r in output.data["requirements"].items()}
    assert grades["date"] == "GREEN"
    assert grades["address"] == "GREEN"
    assert grades["seal"] == "GREEN"
    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply


@pytest.mark.parametrize("run", [_flat, _namespaced], ids=["flat", "namespaced"])
def test_recording_judgment_identical_in_both_context_styles(run) -> None:
    output = run(
        _TRANSCRIPT,
        will_type="recording",
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )

    grades = {rid: r["grade"] for rid, r in output.data["requirements"].items()}
    assert set(grades.values()) == {"GREEN"}


def test_both_context_styles_produce_same_reply_and_state() -> None:
    kwargs = dict(
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="signature_only",
    )
    flat = _flat(_WILL_TEXT, **kwargs)
    namespaced = _namespaced(_WILL_TEXT, **kwargs)

    assert flat.reply == namespaced.reply
    assert flat.data[STATE_KEY] == namespaced.data[STATE_KEY]


def test_output_always_carries_namespace_state() -> None:
    """어느 분기로 나가든 data[STATE_KEY]가 있어야 오케스트레이터가 세션에 저장한다."""
    cases = [
        _flat(_WILL_TEXT),  # will_type 미확인 → 방식 질문
        _flat(_WILL_TEXT, will_type="typed"),  # 잘못된 방식 → 재질문
        _flat(_WILL_TEXT, will_type="handwritten", intent="oops"),  # 잘못된 intent
        _flat(_WILL_TEXT, will_type="handwritten"),  # 판정 파이프라인
        _flat(_TRANSCRIPT, will_type="recording"),  # 녹음 파이프라인
        _flat("", will_type="handwritten", intent="prepare"),  # prepare 가이드
        _flat(_WILL_TEXT, will_type="notarial"),  # 안내 전용
        _flat(_WILL_TEXT, will_type="secret"),
        _flat(_WILL_TEXT, will_type="oral"),
    ]

    for output in cases:
        assert STATE_KEY in output.data, output.reply[:30]


def test_confirm_answers_survive_a_turn_through_the_namespace() -> None:
    """1턴에서 받은 답변이 상태에 남아, 2턴에 답변을 다시 안 보내도 유지된다."""
    first = _flat(_WILL_TEXT, will_type="handwritten", handwriting_answer="yes")
    assert first.data["requirements"]["seal"]["grade"] == "PENDING"

    # 2턴: 날인 답변만 새로 보내고, 나머지는 세션 상태(1턴 결과)를 그대로 넘긴다.
    second = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=_WILL_TEXT,
            context={
                STATE_KEY: first.data[STATE_KEY],
                "seal_answer": "seal_or_fingerprint",
            },
        )
    )

    reqs = second.data["requirements"]
    assert reqs["handwriting"]["grade"] == "GREEN"  # 1턴 답변이 살아 있음
    assert reqs["seal"]["grade"] == "GREEN"  # 2턴 답변이 반영됨


def test_flat_keys_still_emitted_for_old_clients() -> None:
    """전환기에는 응답에 평면 키도 함께 나가야 한다 (프론트 호환)."""
    output = _flat(_WILL_TEXT, will_type="handwritten")

    assert "will_type" in output.data
    assert "requirements" in output.data
    assert "pending_questions" in output.data


# ---------------------------------------------------------------------------
# 3. C안 — 원문은 세션에 저장하지 않는다
# ---------------------------------------------------------------------------

_SENSITIVE_SNIPPETS = (
    "나의 전 재산을 배우자에게 상속한다",
    "저의 전 재산을 배우자에게 상속한다",
    "증인은 위 유언이 정확함을 확인합니다",
)


def _assert_no_raw_text(output, source_text: str) -> None:
    blob = json.dumps(output.data[STATE_KEY], ensure_ascii=False)

    assert source_text not in blob, "유언장 전문이 세션 상태에 들어갔다"
    for snippet in _SENSITIVE_SNIPPETS:
        assert snippet not in blob, f"본문 문장이 세션 상태에 들어갔다: {snippet}"


def test_handwritten_state_excludes_will_text() -> None:
    output = _flat(
        _WILL_TEXT,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )
    _assert_no_raw_text(output, _WILL_TEXT)


def test_recording_state_excludes_transcript() -> None:
    output = _flat(
        _TRANSCRIPT,
        will_type="recording",
        rec_witness_present_answer="yes",
        rec_witness_eligible_answer="not_disqualified",
    )
    _assert_no_raw_text(output, _TRANSCRIPT)


def test_prepare_with_draft_state_excludes_will_text() -> None:
    output = _flat(_WILL_TEXT, will_type="handwritten", intent="prepare")
    _assert_no_raw_text(output, _WILL_TEXT)


def test_state_keeps_judgment_results_and_answers() -> None:
    """원문은 빼되, C안이 담기로 한 것들은 실제로 담겨야 한다."""
    output = _flat(
        _WILL_TEXT,
        will_type="handwritten",
        handwriting_answer="yes",
        seal_answer="signature_only",
    )
    state = output.data[STATE_KEY]

    assert state["will_type"] == "handwritten"
    assert state["intent"] == "review"
    assert state["handwriting_answer"] == "yes"
    assert state["seal_answer"] == "signature_only"
    assert state["requirements"]["seal"]["grade"] == "RED"
    assert state["requirements"]["seal"]["red_label"] == "도장·지장"
    assert state["requirements"]["date"]["condition_id"] == "all_present"
    # 추출값(판정 근거)은 판정 결과의 일부라 포함된다 — 전문(全文)만 제외한다.
    assert state["requirements"]["name"]["extracted"]["raw_text"] == "홍길동"
    assert isinstance(state["pending_questions"], list)

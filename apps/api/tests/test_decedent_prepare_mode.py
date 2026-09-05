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

import pytest

from agents import decedent_estate
from agents.decedent_estate.agent import (
    NEXT_ACTION_AWAIT_USER,
    NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
    _looks_like_draft,
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
    """평면 키 context (전환기 폴백 경로)."""
    payload = AgentInput(session_id="s1", user_message=text, context=context)
    return decedent_estate.run(payload)


def _run_namespaced(text: str, **context):
    """네임스페이스 규약 context — 같은 값을 context["decedent_estate"] 로 넣는다."""
    payload = AgentInput(
        session_id="s1", user_message=text, context={"decedent_estate": context}
    )
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
        f"{seal_citation}. 무인(지장)을 날인으로 인정한 판례가 있습니다."
    ) in output.reply

    assert (
        "초안을 작성하신 뒤 그 내용을 보내주시면 형식 요건을 점검해드릴게요."
        in output.reply
    )


def test_prepare_guide_payload_structure_for_seal() -> None:
    output = _run("", will_type="handwritten", intent="prepare")

    seal_guide = output.data["guide"]["seal"]
    assert seal_guide == {
        "id": "seal",
        "name": "날인",
        "instruction": "도장이나 지장을 반드시 찍어주세요.",
        "mistake_sentence": "서명(사인)만으로는 인정되지 않습니다",
        "mistake_precedent_id": "signature_only_insufficient",
        "extra_note": "무인(지장)을 날인으로 인정한 판례가 있습니다.",
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
        f"{eligible_citation}. 조문상 유언집행자는 증인 결격사유로 열거되어 "
        f"있지 않습니다."
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


def test_prepare_handwritten_with_draft_carries_requirement_body_and_precedents() -> (
    None
):
    """A안: review 파이프라인이 요건별로 채운 body/precedents가 prepare+초안
    흐름에서도 사라지지 않고 data["review"]와 네임스페이스 양쪽에 남아야
    한다. requirements[rid]는 DecedentState 필드라, review_output.data 를
    `k != STATE_KEY` 로 거를 때(중첩 저장을 피하려고) 함께 걸러지지 않고
    그대로 남는다 — #58 원안의 통짜 body/precedents(extra_namespaced,
    STATE_KEY 안에만 있어 따로 옮겨 담아야 했던 것)와 다른 지점이다."""
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="prepare",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    date_req = output.data["review"]["requirements"]["date"]
    assert isinstance(date_req["body"], str) and date_req["body"]
    assert date_req["precedents"] == []  # GREEN이라 인용 없음

    ns = output.data["decedent_estate"]
    assert ns["requirements"]["date"] == date_req


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


def test_namespaced_context_produces_same_prepare_guide_as_flat() -> None:
    """prepare 모드도 네임스페이스 규약으로 동일하게 동작해야 한다."""
    flat = _run("", will_type="handwritten", intent="prepare")
    namespaced = _run_namespaced("", will_type="handwritten", intent="prepare")

    assert flat.reply == namespaced.reply
    assert flat.data["decedent_estate"] == namespaced.data["decedent_estate"]


def test_namespaced_prepare_with_draft_runs_review_too() -> None:
    output = _run_namespaced(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="prepare",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    assert "**자필증서 유언 작성 가이드입니다.**" in output.reply
    assert "작성하신 초안을 점검한 결과입니다." in output.reply
    assert "review" in output.data


# ---------------------------------------------------------------------------
# 초안 판별 (_looks_like_draft)
#
# user_message가 비어 있지 않다는 것만으로 초안이라고 보면 "유언장을 준비하려고요"
# 같은 요청 문장까지 초안으로 오인해, 아직 쓰지도 않은 사용자에게 "❌ 날짜가
# 확인되지 않습니다"를 보여주게 된다. 재산 처분 의사 / 날짜 / 제목줄+내용 중
# 하나 이상이 있을 때만 초안으로 본다.
# ---------------------------------------------------------------------------

_NOT_DRAFT_MESSAGES = [
    "유언장을 준비하려고요",
    "유언장 쓰고 싶어요",
    "유언장 쓰려는데 어떻게 해요?",
    "유언장 어떻게 써요",
    "상속 준비를 하고 싶어요",
    "내년에 유언장 준비하려고 합니다",
    "유언장",  # 제목만 있고 내용이 없음
    "",
    "   ",
    # 회귀 테스트 — "준다/드립니다/남깁니다" 같은 범용 어미가 수신자·재산 표시
    # 없이 단독으로 쓰인 일상 응답은 초안으로 오인되면 안 된다 (실측 확인된 버그).
    "확인해 드립니다.",
    "설명 드립니다.",
    "이거 확인 후 남깁니다.",
    "곧 다시 연락 드리겠습니다.",
    # 회귀 테스트 — "주고"는 "-아/어 주다" 보조동사로도 흔히 쓰인다. 앞에 다른
    # 동사의 활용형이 오면(수신자 표시 "에게"/"한테"가 아니라) 처분 의사가
    # 아니다 — 문장 안에 재산 명사가 우연히 있어도(예: "아파트") 오탐이면
    # 안 된다(실측 확인된 버그).
    "유언장을 확인해 주고 싶어요",
    "아파트 관련해서 설명해 주고 싶어요",
]

_DRAFT_MESSAGES = [
    "나의 전 재산을 배우자에게 상속한다.",  # 재산 처분 의사
    "내 통장 돈은 모두 딸에게 준다",  # 처분 의사(구어체 어미)
    "제 모든 재산을 장남에게 물려주고자 합니다",  # 처분 의사(녹음 대본체)
    "2026년 5월 3일",  # 날짜 표기
    "유언장\n나는 아래와 같이 정한다",  # 제목 줄 + 내용
    # 회귀 테스트 — "에게/한테 주고"(연결형)도 처분 의사로 인정해야 한다.
    # 실제 재현: intake gate 이후 사용자가 보낸 진짜 유언장 본문이 "발견했다"는
    # 상담 문장의 연장으로 오인돼 checker가 실행되지 않던 버그.
    "내 소유 아파트는 장남 김민수에게 주고, 은행 예금은 두 아들이 반씩 나누어 가진다.",
    "아파트는 장남에게 주고 예금은 차남에게 준다",
    "재산을 두 자녀에게 나누어 준다",
]


@pytest.mark.parametrize("message", _NOT_DRAFT_MESSAGES)
def test_request_sentences_are_not_treated_as_draft(message: str) -> None:
    assert _looks_like_draft(message) is False


@pytest.mark.parametrize("message", _DRAFT_MESSAGES)
def test_will_like_text_is_treated_as_draft(message: str) -> None:
    assert _looks_like_draft(message) is True


def test_prepare_with_request_sentence_shows_guide_only() -> None:
    """버그 재현 케이스 — "유언장을 준비하려고요"에 점검 결과가 붙으면 안 된다."""
    output = _run("유언장을 준비하려고요", will_type="handwritten", intent="prepare")

    assert "review" not in output.data
    assert "requirements" not in output.data
    assert output.next_action is None
    # 아직 쓰지도 않은 사람에게 "확인되지 않습니다" ❌ 를 보여주면 안 된다.
    assert "❌" not in output.reply
    assert "확인되지 않습니다" not in output.reply
    # 가이드는 정상적으로 나오고, 초안 요청 안내로 끝난다.
    assert "**자필증서 유언 작성 가이드입니다.**" in output.reply
    assert output.reply.rstrip().endswith(
        "초안을 작성하신 뒤 그 내용을 보내주시면 형식 요건을 점검해드릴게요."
    )


def test_prepare_with_polite_reply_shows_guide_only() -> None:
    """버그 재현 케이스 — "확인해 드립니다." 같은 평범한 응답도 점검 결과가

    붙으면 안 된다. "드립니다"만으로 초안 처분 의사로 오인하던 문제.
    """
    output = _run("확인해 드립니다.", will_type="handwritten", intent="prepare")

    assert "review" not in output.data
    assert "requirements" not in output.data
    assert "❌" not in output.reply
    assert "확인되지 않습니다" not in output.reply


def test_prepare_with_real_draft_still_shows_both_guide_and_review() -> None:
    """실제 유언장 텍스트는 그대로 초안으로 인식돼 점검 결과까지 나와야 한다."""
    output = _run(
        _WILL_TEXT_COMPLETE,
        will_type="handwritten",
        intent="prepare",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )

    assert "**자필증서 유언 작성 가이드입니다.**" in output.reply
    assert "작성하신 초안을 점검한 결과입니다." in output.reply
    assert "review" in output.data


def test_prepare_recording_with_request_sentence_shows_guide_only() -> None:
    """녹음 prepare도 같은 판별을 쓴다."""
    output = _run(
        "녹음으로 유언 남기고 싶어요", will_type="recording", intent="prepare"
    )

    assert "review" not in output.data
    assert "❌" not in output.reply
    assert "**녹음 유언 작성 가이드입니다.**" in output.reply

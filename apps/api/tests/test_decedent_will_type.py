"""
유언 방식(민법 5방식) 분기 테스트.

context.will_type 값에 따라 agent.run() 이 어떻게 갈라지는지 확인한다:
미확인(질문 반환) / 잘못된 값(경고+재질문) / handwritten(요건 판정 파이프라인) /
unknown(자필증서 기본값 적용) / notarial(검증·검인 불요 안내, 자동 handoff 없음) /
secret·oral(요건 요약 + 자동 점검 미지원 안내).

recording(녹음, §1067)은 이제 handwritten과 마찬가지로 실제 요건 판정
파이프라인을 타므로 별도 파일 test_decedent_recording.py 에서 다룬다.
"""

import pytest

from agents import decedent_estate
from agents.decedent_estate.agent import NEXT_ACTION_AWAIT_USER
from agents.decedent_estate.will_types import get_will_type
from schemas import AgentInput

_WILL_TEXT_COMPLETE = (
    "유언장\n"
    "유언자: 홍길동\n"
    "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
    "2026년 5월 3일\n"
    "\n"
    "나의 전 재산을 배우자에게 상속한다."
)


def test_missing_will_type_asks_the_selection_question() -> None:
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE
    )  # context 없음

    output = decedent_estate.run(payload)

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert "어떤 형태의 유언인가요?" in output.reply
    assert (
        "자필증서는 혼자 무료로 작성할 수 있어 가장 널리 쓰이지만, "
        "형식 요건 미비로 무효가 되는 사례가 많아 점검이 필요합니다."
    ) in output.reply
    assert output.data["warnings"] == []
    assert (
        "requirements" not in output.data
    )  # 방식 확인 전이니 판정 파이프라인은 아직 안 돈다

    [question] = output.data["pending_questions"]
    assert question["field"] == "will_type"
    assert question["question"] == "어떤 형태의 유언인가요?"
    assert question["options"] == [
        {"value": "handwritten", "label": "직접 손으로 쓴 유언장"},
        {"value": "recording", "label": "녹음·영상"},
        {"value": "notarial", "label": "공증받은 유언"},
        {"value": "unknown", "label": "그 외·모르겠음"},
        {"value": "none", "label": "유언장이 없거나 찾지 못했습니다"},
    ]


def test_invalid_will_type_reasks_with_warning() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"will_type": "typed"},
    )

    output = decedent_estate.run(payload)

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert "어떤 형태의 유언인가요?" in output.reply
    assert output.data["warnings"] == [
        {
            "field": "will_type",
            "invalid_value": "typed",
            "allowed": [
                "handwritten",
                "recording",
                "notarial",
                "secret",
                "oral",
                # 아래 둘은 민법 5방식이 아니라 UI sentinel이다
                # ("모르겠음" / "유언장 없음").
                "unknown",
                "none",
            ],
        }
    ]


def test_handwritten_runs_existing_pipeline_unchanged() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={
            "will_type": "handwritten",
            "handwriting_answer": "yes",
            "seal_answer": "seal_or_fingerprint",
        },
    )

    output = decedent_estate.run(payload)

    assert output.data["will_type"] == "handwritten"
    assert "requirements" in output.data
    # 종결돼도 더 이상 자동 handoff 없음(2026-09-05).
    assert output.next_action is None
    assert "형식 요건상 문제가 발견되지 않았습니다" in output.reply


def test_unknown_defaults_to_handwritten_with_notice() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={
            "will_type": "unknown",
            "handwriting_answer": "yes",
            "seal_answer": "seal_or_fingerprint",
        },
    )

    output = decedent_estate.run(payload)

    assert output.reply.startswith("가장 널리 쓰이는 자필증서 기준으로 점검하겠습니다")
    assert (
        "형식 요건상 문제가 발견되지 않았습니다" in output.reply
    )  # 파이프라인이 그대로 이어짐
    assert output.data["will_type"] == "handwritten"
    assert "requirements" in output.data
    # 종결돼도 더 이상 자동 handoff 없음(2026-09-05).
    assert output.next_action is None


def test_handwritten_mentioned_in_message_is_not_reasked() -> None:
    """ "자필로 쓴 유언장이 있는데 효력이 있나요?"처럼 자필 방식이 문장에 명백히
    드러나 있으면, will_type이 context에 없어도 방식 선택 질문을 다시 하지 않고
    바로 handwritten으로 확정해야 한다.

    단, 이 문장 자체는 상담 요청일 뿐 실제 유언장 본문이 아니므로(날짜/주소/
    처분 의사 등 내용이 없음) document intake gate 에 걸려 요건 판정까지는
    들어가지 않는다 — 자세한 내용은
    test_document_intake_gate_blocks_requirement_check_without_document."""
    payload = AgentInput(
        session_id="s1",
        user_message="자필로 쓴 유언장이 있는데 효력이 있나요?",
        # context 없음 — will_type 미확인
    )

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "handwritten"
    assert "requirements" not in output.data  # 실제 본문이 없어 판정을 안 돈다
    assert output.next_action == NEXT_ACTION_AWAIT_USER


def test_handwritten_ui_phrase_directly_written_by_hand_is_not_reasked() -> None:
    """ "직접 손으로 쓴 유언장인데..." 같은 UI 표현도 동일하게 감지해야 한다.
    이 문장도 실제 본문이 아니므로 document intake gate 에 걸린다."""
    payload = AgentInput(
        session_id="s1",
        user_message="직접 손으로 쓴 유언장인데 이대로 괜찮은지 봐주세요.",
    )

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "handwritten"
    assert "requirements" not in output.data


def test_ambiguous_will_message_still_asks_the_selection_question() -> None:
    """방식이 명확하지 않은 일반 문장("유언장이 있는데 효력이 있나요?")은 여전히
    기존 will_type 선택 질문을 유지해야 한다 — 오탐 방지."""
    payload = AgentInput(
        session_id="s1",
        user_message="유언장이 있는데 효력이 있나요?",
    )

    output = decedent_estate.run(payload)

    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_generic_direct_writing_phrase_does_not_trigger_false_positive() -> None:
    """ "직접 작성"처럼 오탐 가능성이 있는 일반 표현만으로는 자필로 추정하면 안
    된다 — 여전히 will_type 선택 질문을 유지해야 한다."""
    payload = AgentInput(
        session_id="s1",
        user_message="유언장을 직접 작성한 유언장이 있는데 효력이 있을까요?",
    )

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_explicit_context_will_type_still_wins_over_message_inference() -> None:
    """context에 will_type이 이미 명시돼 있으면(예: notarial), 문장에 자필 표현이
    섞여 있어도 자연어 추론보다 명시값이 우선해야 한다."""
    payload = AgentInput(
        session_id="s1",
        user_message="자필로 쓴 유언장 같은데 공증도 따로 받았어요.",
        context={"will_type": "notarial"},
    )

    output = decedent_estate.run(payload)

    assert output.data["will_type"] == "notarial"
    assert (
        "requirements" not in output.data
    )  # notarial 은 판정 파이프라인 자체를 안 돈다


# ---------------------------------------------------------------------------
# recording(§1067) 자연어 will_type 추론 (2026-09-05)
#
# 실측 재현: "휴대폰을 정리하다가 재산 얘기를 남긴 음성메모를 발견했어요"처럼
# 이미 명백히 녹음임을 밝혔는데도 방식 선택 질문을 다시 했다.
# handwritten과 동일 원칙 — 최소·명백한 표현만 deterministic하게 매칭하고
# LLM은 쓰지 않는다. "메모"/"파일"/"영상"/"말"/"기록" 같은 단어 하나만으로는
# 추론하지 않는다.
# ---------------------------------------------------------------------------


def test_voice_memo_message_is_inferred_as_recording_without_reasking() -> None:
    """정확한 production 재현 — 첫 턴부터 recording으로 자동 확정되고, 방식
    선택 질문 없이 곧장 대본 요청(transcript intake)으로 넘어가야 한다."""
    payload = AgentInput(
        session_id="s1",
        user_message=(
            "어머니가 돌아가신 뒤 휴대폰을 정리하다가 재산 얘기를 남긴 음성메모를 "
            "발견했어요. 이런 것도 유언으로 효력이 있는지 확인할 수 있나요?"
        ),
    )

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "recording"
    assert "requirements" not in output.data  # 아직 대본이 없어 판정을 안 돈다
    assert output.next_action == NEXT_ACTION_AWAIT_USER
    assert output.reply.startswith("📼 녹음하신 내용을 그대로 적어주세요")


def test_recorded_will_phrase_is_inferred_as_recording() -> None:
    payload = AgentInput(session_id="s1", user_message="녹음으로 남긴 유언이 있어요")

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "recording"


def test_bare_memo_word_does_not_trigger_recording_inference() -> None:
    """ "메모"라는 단어 하나만으로는 recording을 추론하지 않는다 — 여전히 방식
    선택 질문을 유지해야 한다."""
    payload = AgentInput(session_id="s1", user_message="메모를 발견했어요")

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_bare_file_word_does_not_trigger_recording_inference() -> None:
    """ "파일"이라는 단어 하나만으로는 recording을 추론하지 않는다."""
    payload = AgentInput(session_id="s1", user_message="파일이 있어요")

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_explicit_handwritten_wins_over_voice_memo_phrase_in_message() -> None:
    """context에 will_type=handwritten이 이미 명시돼 있으면, 문장에 "음성메모"
    같은 recording 표현이 섞여 있어도 명시값이 우선해야 한다(우선순위 A)."""
    payload = AgentInput(
        session_id="s1",
        user_message="음성메모도 하나 있긴 한데, 이 손으로 쓴 유언장부터 봐주세요.",
        context={
            "will_type": "handwritten",
            "handwriting_answer": "yes",
            "seal_answer": "seal_or_fingerprint",
        },
    )

    output = decedent_estate.run(payload)

    assert output.data["will_type"] == "handwritten"


# ---------------------------------------------------------------------------
# notarial(공정증서, §1068) 자연어 will_type 추론 (2026-09-06)
#
# 실측 재현: "아버지가 돌아가시고 서류를 정리하다가 공증받은 유언장을
# 발견했어요"처럼 이미 명백히 공정증서임을 밝혔는데도 방식 선택 질문을
# 다시 했다. handwritten/recording과 동일 원칙 — 최소·명백한 표현만
# deterministic하게 매칭하고 LLM은 쓰지 않는다. "공증"/"서류"/"증서"/
# "공증사무소" 같은 단어 하나만으로는 추론하지 않는다.
# ---------------------------------------------------------------------------


def test_notarized_will_found_message_is_inferred_as_notarial_without_reasking() -> (
    None
):
    """테스트 A — 정확한 production 재현. 첫 턴부터 notarial로 자동 확정되고,
    방식 선택 질문 없이 곧장 공정증서 안내로 넘어가야 한다."""
    payload = AgentInput(
        session_id="s1",
        user_message=(
            "아버지가 돌아가시고 서류를 정리하다가 공증받은 유언장을 발견했어요. "
            "이 경우에도 따로 효력이나 형식 요건을 확인해야 하나요?"
        ),
    )

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "notarial"
    assert "requirements" not in output.data
    assert output.next_action is None
    assert "공증인이 작성한 유언은 형식 요건 검증이 필요하지 않습니다" in output.reply


def test_notarial_deed_phrase_is_inferred_as_notarial() -> None:
    """테스트 B."""
    payload = AgentInput(session_id="s1", user_message="공정증서 유언을 발견했습니다")

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "notarial"


def test_bare_notarized_document_phrase_does_not_trigger_notarial_inference() -> None:
    """테스트 C — "공증받은 서류"는 유언 방식 자체가 불명확해 추론하지
    않는다. 여전히 방식 선택 질문을 유지해야 한다."""
    payload = AgentInput(session_id="s1", user_message="공증받은 서류를 발견했어요")

    output = decedent_estate.run(payload)

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


@pytest.mark.parametrize(
    "message",
    [
        "공증사무소에서 서류를 찾았어요",
        "증서가 하나 있어요",
        "공증을 받았다고 들었어요",
    ],
)
def test_bare_notarial_related_words_do_not_trigger_inference(message: str) -> None:
    """ "공증"/"서류"/"증서"/"공증사무소" 같은 단어 하나만으로는 notarial을
    추론하지 않는다."""
    output = decedent_estate.run(AgentInput(session_id="s1", user_message=message))

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_explicit_handwritten_wins_over_notarized_will_phrase_in_message() -> None:
    """테스트 D — context에 will_type=handwritten이 이미 명시돼 있으면,
    문장에 "공증받은 유언장" 같은 notarial 표현이 섞여 있어도 명시값이
    우선해야 한다(우선순위 A)."""
    payload = AgentInput(
        session_id="s1",
        user_message="공증받은 유언장도 하나 있긴 한데, 이 손으로 쓴 유언장부터 봐주세요.",
        context={
            "will_type": "handwritten",
            "handwriting_answer": "yes",
            "seal_answer": "seal_or_fingerprint",
        },
    )

    output = decedent_estate.run(payload)

    assert output.data["will_type"] == "handwritten"


# ---------------------------------------------------------------------------
# rules 기반 generic will_type 자연어 추론 (2026-09-06)
#
# _infer_will_type_from_message()가 방식별 marker 상수를 하드코딩하는 대신
# rules/will_types.json 의 will_types[].inference_markers 를 generic하게
# 순회한다(will_types.infer_will_type_from_message). 핵심 invariant: 사용자가
# 민법상 유언 방식을 명백하게 특정했다면, 그 방식이 full-support(handwritten/
# recording)인지 guidance-only(notarial/secret/oral)인지와 무관하게 방식
# 선택 질문을 다시 하지 않는다.
# ---------------------------------------------------------------------------

_FIVE_WAY_INFERENCE_CASES = [
    ("handwritten", "아버지가 자필증서 유언을 남겼어요"),
    ("recording", "어머니가 녹음 유언을 남겼어요"),
    ("notarial", "공증받은 유언장을 발견했어요"),
    ("secret", "비밀증서 유언이라고 적혀 있습니다"),
    ("oral", "구수증서 유언이라고 들었습니다"),
]


@pytest.mark.parametrize("expected_will_type,message", _FIVE_WAY_INFERENCE_CASES)
def test_all_five_statutory_will_types_are_inferred_without_reasking(
    expected_will_type: str, message: str
) -> None:
    """민법 5방식 전체 table-driven regression — 명백한 자연어 표현이면
    support 여부와 무관하게 방식 선택 질문 없이 곧장 해당 will_type으로
    확정되고, 각자의 기존 pipeline/guidance로 들어가야 한다."""
    output = decedent_estate.run(AgentInput(session_id="s1", user_message=message))

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == expected_will_type
    if expected_will_type in ("notarial", "secret", "oral"):
        # guidance-only 방식은 요건 판정 파이프라인 자체를 안 돈다.
        assert "requirements" not in output.data
    get_will_type_info = get_will_type(expected_will_type)
    assert get_will_type_info is not None


@pytest.mark.parametrize(
    "message",
    [
        "자필증서인지 공정증서인지 모르겠습니다",
        "봉인된 유언장을 발견했습니다",
        "고인이 말로 유언을 남겼습니다",
        "공증받은 서류입니다",
    ],
)
def test_ambiguous_or_underspecified_messages_do_not_infer_will_type(
    message: str,
) -> None:
    """모호한 표현(둘 이상의 방식에 동시에 걸리거나, 어느 marker에도 명백히
    걸리지 않는 표현)은 추론하지 않고 기존 방식 선택 질문으로 돌아간다.
    "자필증서인지 공정증서인지 모르겠습니다"는 handwritten/notarial marker에
    동시에 걸리는 충돌 케이스 — 임의로 하나를 고르지 않아야 한다."""
    output = decedent_estate.run(AgentInput(session_id="s1", user_message=message))

    assert "어떤 형태의 유언인가요?" in output.reply
    assert "requirements" not in output.data


def test_secret_exact_production_scenario_infers_secret_without_reasking() -> None:
    """정확한 production 재현 — "봉인된 유언장"(모호) + "비밀증서 유언이라고
    적혀 있어요"(명백한 방식 특정)가 함께 있는 문장에서, 명백한 방식 명칭이
    있으므로 secret으로 확정되고 방식 재질문 없이 기존 비밀증서 guidance-only
    안내(자동 점검 미지원)로 들어가야 한다. handwritten으로 잘못 폴백하면 안
    된다."""
    output = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=(
                "아버지가 돌아가시고 서류를 정리하다가 봉인된 유언장을 발견했는데, "
                "겉에 비밀증서 유언이라고 적혀 있어요. 이것도 효력이 있는지 "
                "확인할 수 있나요?"
            ),
        )
    )

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "secret"
    assert "requirements" not in output.data
    assert "민법 제1069조" in output.reply
    assert (
        "이 방식은 증인 2인 이상이 필요합니다. 현재 자동 점검을 지원하지 않으니 "
        "법률 전문가 확인을 권합니다."
    ) in output.reply


def test_oral_natural_language_mention_infers_oral_without_reasking() -> None:
    """oral 최소 API smoke — "구수증서 유언이라고 적혀 있습니다"만으로도 방식
    재질문 없이 곧장 구수증서 guidance-only 안내로 들어가야 한다."""
    output = decedent_estate.run(
        AgentInput(session_id="s1", user_message="구수증서 유언이라고 적혀 있습니다")
    )

    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data["will_type"] == "oral"
    assert "requirements" not in output.data
    assert "민법 제1070조" in output.reply


# ---------------------------------------------------------------------------
# will_type 자연어 변경(type switch, 2026-09-07)
#
# 실측 재현: handwritten이 이미 저장된 뒤 "아아 녹음으로 하려고"처럼 명백히
# 다른 방식을 선택해도, 자연어 추론이 state.will_type이 None일 때만 실행돼
# 계속 handwritten 가이드가 반복됐다. "단순 언급/비교"(예: "녹음 유언은
# 자필이랑 뭐가 달라?")와 "명백한 변경 의도"(예: "녹음으로 하려고")를
# 구분해야 하므로, 방식명 뒤에 선택/변경 어미가 곧장 붙은 경우만 switch로
# 인정한다(rules/will_types.json 의 type_switch.intent_suffix_pattern +
# will_types[].switch_markers).
# ---------------------------------------------------------------------------


def _stored(will_type: str, **extra: str) -> dict:
    """already-stored 상태를 만들기 위한 1턴짜리 namespaced 상태 dict."""
    output = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="",
            context={"will_type": will_type, **extra},
        )
    )
    return output.data["decedent_estate"]


def _run_with_stored(stored: dict, message: str):
    return decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message=message,
            context={"decedent_estate": stored},
        )
    )


_TYPE_SWITCH_CASES = [
    ("handwritten", "아아 녹음으로 하려고", "recording"),
    ("recording", "자필로 바꿀게", "handwritten"),
    ("handwritten", "공정증서로 하려고", "notarial"),
    ("notarial", "비밀증서 유언으로 바꿀게", "secret"),
    ("secret", "구수증서로 하겠습니다", "oral"),
]


@pytest.mark.parametrize("stored_type,message,expected_type", _TYPE_SWITCH_CASES)
def test_explicit_type_change_switches_stored_will_type(
    stored_type: str, message: str, expected_type: str
) -> None:
    """민법 5방식 table-driven switch regression — 명백한 변경 문장이면
    저장된 will_type과 무관하게 새 will_type으로 전환돼야 한다."""
    stored = _stored(stored_type)
    output = _run_with_stored(stored, message)

    assert output.data["decedent_estate"]["will_type"] == expected_type


def test_type_switch_resets_previous_type_progress_state() -> None:
    """방식이 실제로 바뀌면 이전 방식 전용 진행 상태(요건 판정·확인 답변)가
    새 방식에 오염되지 않도록 초기화돼야 한다."""
    stored = _stored(
        "handwritten",
        handwriting_answer="yes",
        seal_answer="seal_or_fingerprint",
    )
    # handwritten review가 실제로 진행돼 requirements/pending_questions가
    # 채워진 상태를 재현한다.
    progressed = _run_with_stored(stored, _WILL_TEXT_COMPLETE).data["decedent_estate"]
    assert progressed["requirements"]

    switched = _run_with_stored(progressed, "아아 녹음으로 하려고").data[
        "decedent_estate"
    ]

    assert switched["will_type"] == "recording"
    assert switched["requirements"] == {}
    assert switched["pending_questions"] == []
    assert switched["handwriting_answer"] is None
    assert switched["seal_answer"] is None
    assert switched["address_envelope_answer"] is None
    assert switched["rec_witness_present_answer"] is None
    assert switched["rec_witness_eligible_answer"] is None


@pytest.mark.parametrize(
    "message",
    [
        "녹음 유언은 자필이랑 뭐가 달라?",
        "공정증서 유언도 있나요?",
        "다른 방식도 궁금해요",
        "다른 방식으로 할까 고민 중이야",
    ],
)
def test_mention_or_ambiguous_change_does_not_switch_stored_will_type(
    message: str,
) -> None:
    """단순 언급/비교 질문이나 모호한 변경 의도는 저장된 will_type을 바꾸지
    않는다 — "~로 하려고/할게/바꿀게" 같은 선택·변경 어미가 방식명 바로 뒤에
    붙어야만 switch로 인정한다."""
    stored = _stored("handwritten")
    output = _run_with_stored(stored, message)

    assert output.data["decedent_estate"]["will_type"] == "handwritten"


def test_explicit_context_will_type_wins_over_switch_phrase_in_message() -> None:
    """이번 턴 explicit context.will_type이 있으면, 문장에 다른 방식으로의
    명백한 변경 표현이 섞여 있어도 명시값이 우선해야 한다(우선순위 A > B)."""
    stored = _stored("recording")
    output = decedent_estate.run(
        AgentInput(
            session_id="s1",
            user_message="자필로 바꿀게",
            context={
                "will_type": "notarial",
                "decedent_estate": stored,
            },
        )
    )

    assert output.data["decedent_estate"]["will_type"] == "notarial"


def test_notarial_gives_guidance_without_auto_handoff() -> None:
    """notarial 안내 완료 후 자동 handoff가 없어야 한다(2026-09-06) —
    handwritten/recording의 #126/#127과 동일 원칙. 안내 자체(형식 요건
    검증·검인 불요)는 그대로 유지된다."""
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"will_type": "notarial"},
    )

    output = decedent_estate.run(payload)

    assert output.reply == (
        "공증인이 작성한 유언은 형식 요건 검증이 필요하지 않습니다. "
        "가정법원 검인 절차도 필요하지 않습니다."
    )
    assert output.next_action is None
    assert output.data["will_type"] == "notarial"
    assert "handoff_reason" not in output.data
    assert "requirements" not in output.data  # 형식 요건 판정 자체를 안 돈다


def test_secret_gives_requirements_summary_and_unsupported_notice() -> None:
    payload = AgentInput(
        session_id="s1",
        user_message=_WILL_TEXT_COMPLETE,
        context={"will_type": "secret"},
    )

    output = decedent_estate.run(payload)

    assert "민법 제1069조" in output.reply
    assert "증인 2인 이상이 필요" in output.reply
    assert (
        "이 방식은 증인 2인 이상이 필요합니다. 현재 자동 점검을 지원하지 않으니 법률 전문가 확인을 권합니다."
        in output.reply
    )
    assert output.next_action is None
    assert output.data["will_type"] == "secret"


def test_oral_gives_requirements_summary_and_unsupported_notice() -> None:
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context={"will_type": "oral"}
    )

    output = decedent_estate.run(payload)

    assert "민법 제1070조" in output.reply
    assert "증인 2인 이상이 필요" in output.reply
    assert (
        "이 방식은 증인 2인 이상이 필요합니다. 현재 자동 점검을 지원하지 않으니 법률 전문가 확인을 권합니다."
        in output.reply
    )
    assert output.next_action is None
    assert output.data["will_type"] == "oral"


def test_oral_guidance_includes_nodding_only_precedent() -> None:
    """구수증서 안내에 '질문에 고개만 끄덕인 경우 구수 불인정' 판례 문구가 포함된다."""
    payload = AgentInput(
        session_id="s1", user_message=_WILL_TEXT_COMPLETE, context={"will_type": "oral"}
    )

    output = decedent_estate.run(payload)

    assert (
        "미리 작성된 서면을 확인하며 고개를 끄덕이거나 간단한 답변만 한 경우는 "
        "'유언취지의 구수'로 인정되지 않은 사례가 있습니다"
    ) in output.reply
    assert "2005다57899" in output.reply
    for assertive in ("무효입니다", "유효합니다", "인정되지 않습니다"):
        assert assertive not in output.reply


def test_all_guidance_only_types_have_no_requirements_payload() -> None:
    for will_type in ("notarial", "secret", "oral"):
        payload = AgentInput(
            session_id="s1",
            user_message=_WILL_TEXT_COMPLETE,
            context={"will_type": will_type},
        )
        output = decedent_estate.run(payload)
        assert "requirements" not in output.data, will_type


def test_requirements_summary_matches_verified_statute_text() -> None:
    """rules/will_types.json 의 requirements_summary가 국가법령정보센터 확인 조문
    원문과 글자 단위로 일치하는지, source(조문 출처) 필드가 채워져 있는지 확인한다."""
    expected = {
        "handwritten": (
            "민법 제1066조 제1항",
            "유언자가 그 전문과 연월일, 주소, 성명을 자서하고 날인하여야 한다",
        ),
        "recording": (
            "민법 제1067조",
            "유언자가 유언의 취지, 그 성명과 연월일을 구술하고, 이에 참여한 증인이 "
            "유언의 정확함과 그 성명을 구술하여야 한다",
        ),
        "notarial": (
            "민법 제1068조",
            "유언자가 증인 2인이 참여한 공증인의 면전에서 유언의 취지를 구수하고, "
            "공증인이 이를 필기낭독하여 유언자와 증인이 그 정확함을 승인한 후 각자 "
            "서명 또는 기명날인하여야 한다",
        ),
        "secret": (
            "민법 제1069조 제1항",
            "유언자가 필자의 성명을 기입한 증서를 엄봉날인하고 이를 2인 이상의 증인의 "
            "면전에 제출하여 자기의 유언서임을 표시한 후 그 봉서 표면에 제출 연월일을 "
            "기재하고 유언자와 증인이 각자 서명 또는 기명날인하여야 한다",
        ),
        "oral": (
            "민법 제1070조 제1항",
            "질병 기타 급박한 사유로 인하여 다른 4가지 방식에 의할 수 없는 경우에, "
            "유언자가 2인 이상의 증인의 참여로 그 1인에게 유언의 취지를 구수하고, 그 "
            "구수를 받은 자가 이를 필기낭독하여 유언자와 증인이 그 정확함을 승인한 후 "
            "각자 서명 또는 기명날인하여야 한다",
        ),
    }

    for will_type_id, (source, summary) in expected.items():
        info = get_will_type(will_type_id)
        assert info["source"] == source, will_type_id
        assert info["requirements_summary"] == summary, will_type_id

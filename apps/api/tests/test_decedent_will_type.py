"""
유언 방식(민법 5방식) 분기 테스트.

context.will_type 값에 따라 agent.run() 이 어떻게 갈라지는지 확인한다:
미확인(질문 반환) / 잘못된 값(경고+재질문) / handwritten(요건 판정 파이프라인) /
unknown(자필증서 기본값 적용) / notarial(검증·검인 불요 안내+핸드오프) /
secret·oral(요건 요약 + 자동 점검 미지원 안내).

recording(녹음, §1067)은 이제 handwritten과 마찬가지로 실제 요건 판정
파이프라인을 타므로 별도 파일 test_decedent_recording.py 에서 다룬다.
"""

from agents import decedent_estate
from agents.decedent_estate.agent import (
    NEXT_ACTION_AWAIT_USER,
    NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR,
)
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


def test_notarial_gives_guidance_and_handoff_without_verification() -> None:
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
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
    assert output.data["will_type"] == "notarial"
    assert "handoff_reason" in output.data
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

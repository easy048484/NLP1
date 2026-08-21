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
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR
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
    assert output.next_action == NEXT_ACTION_HANDOFF_HEIR_NAVIGATOR


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

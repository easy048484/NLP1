"""
유언장 없음 케이스(will_type="none") 테스트.

"유언장이 없다/못 찾았다"는 요건 판정 대상이 아예 없으므로, 판정 파이프라인을
돌지 않고 법정상속 안내 + 공정증서 고지만 한다. heir_navigator로의 직접
next_action 핸드오프는 없다(2026-08-25 제거) — 웹 UI가 로그인 후 채팅창에서
라우터가 적합한 에이전트를 선택하는 구조로 확정되면서, #20에서 넣었던
handoff:heir_navigator는 받는 쪽이 없어 막다른 길이었다. 사용자가 채팅으로
돌아가 다시 말하면 라우터가 알아서 보낸다.

범위가 의도적으로 좁다는 점을 테스트로 고정한다:
- 유언장 탐색 안내(어디에 뒀는지 찾는 법)는 하지 않는다 — 공정증서 고지만 예외
- 상속인 범위·지분·유류분은 답하지 않는다 (heir_navigator 영역)
- 무단정 원칙(CLAUDE.md 절대 원칙 2)을 그대로 지킨다
"""

from agents import decedent_estate
from agents.decedent_estate.will_types import no_will_guidance, selection_question
from schemas import AgentInput, AgentName


def _run(user_message: str = "유언장이 없어요", **context):
    return decedent_estate.run(
        AgentInput(session_id="s1", user_message=user_message, context=context)
    )


def _no_will_output():
    return _run(will_type="none")


# ---------------------------------------------------------------------------
# 진입 경로
# ---------------------------------------------------------------------------


def test_none_is_offered_as_a_will_type_option() -> None:
    """방식 질문에 "없음" 선택지가 있어야 사용자가 이 경로로 들어올 수 있다.

    이게 없으면 "그 외·모르겠음"을 고를 수밖에 없는데, 그쪽은 자필증서를
    기본값으로 삼아 존재하지도 않는 유언장을 점검하려 든다.
    """
    options = selection_question()["options"]
    values = [o["value"] for o in options]

    assert "none" in values
    label = next(o["label"] for o in options if o["value"] == "none")
    assert "없" in label  # "유언장이 없거나 찾지 못했습니다"


def test_none_is_accepted_and_does_not_reask_will_type() -> None:
    """ "none"이 화이트리스트에 있어야 방식을 다시 묻지 않는다."""
    output = _no_will_output()

    assert output.agent == AgentName.DECEDENT_ESTATE
    assert "어떤 형태의 유언인가요?" not in output.reply
    assert output.data.get("warnings") == []


def test_no_will_skips_requirement_judgment_entirely() -> None:
    """판정 대상이 없으므로 요건 판정 결과가 아예 없어야 한다."""
    output = _no_will_output()

    assert "requirements" not in output.data
    assert "pending_questions" not in output.data
    assert "✅" not in output.reply
    assert "❌" not in output.reply


def test_intent_does_not_affect_no_will_path() -> None:
    """review/prepare 구분은 "유언장이 있다"를 전제하므로 이 경로엔 의미가 없다."""
    review = _run(will_type="none", intent="review")
    prepare = _run(will_type="none", intent="prepare")

    assert review.reply == prepare.reply == _no_will_output().reply
    assert "guide" not in prepare.data


# ---------------------------------------------------------------------------
# [2] 공정증서 고지 — 1회, 탐색 안내 아님
# ---------------------------------------------------------------------------


def test_notarial_notice_appears_exactly_once() -> None:
    output = _no_will_output()
    notice = no_will_guidance()["notarial_notice"]

    assert output.reply.count(notice) == 1


def test_notarial_notice_is_not_a_search_instruction() -> None:
    """ "확인 안 된 경로가 있다"는 고지지, "어디를 뒤져보라"는 탐색 조언이 아니다."""
    reply = _no_will_output().reply

    for search_advice in (
        "찾아보세요",
        "뒤져",
        "서랍",
        "금고를 열",
        "유품",
        "보관 장소",
    ):
        assert search_advice not in reply, search_advice


def test_notarial_notice_does_not_name_unverified_institution() -> None:
    """검증하지 못한 기관명·URL을 쓰지 않는다.

    공정증서 원본이 공증사무소에 보관된다는 사실만 확인됐고, 유언 존재 여부를
    조회하는 통합 검색 제도(기관명·절차)는 확인하지 못해 의도적으로 낮춰 썼다.
    """
    reply = _no_will_output().reply

    assert "공증사무소" in reply  # 확인된 사실만 말한다
    for unverified in ("대한공증인협회", "유언검색", "http://", "https://", ".or.kr"):
        assert unverified not in reply, unverified


# ---------------------------------------------------------------------------
# [3] 법정상속 안내 — 무단정, 상속인 범위·지분은 침범하지 않음
# ---------------------------------------------------------------------------


def test_legal_succession_guidance_is_not_assertive() -> None:
    """CLAUDE.md 절대 원칙 2 — "유언장이 없으니 법정상속입니다" 식 단정 금지."""
    reply = _no_will_output().reply

    assert "확인된 유언장이 없는 경우 일반적으로" in reply
    for assertive in (
        "법정상속입니다",
        "법정상속이 됩니다",
        "유언장이 없으므로",
        "무효입니다",
        "유효합니다",
    ):
        assert assertive not in reply, assertive


def test_does_not_answer_heir_scope_or_shares() -> None:
    """상속인 범위·지분·유류분은 heir_navigator 영역이라 여기서 답하지 않는다.

    두 에이전트가 서로 다른 답을 하면 사용자가 어느 쪽을 믿어야 할지 알 수 없다.
    """
    reply = _no_will_output().reply

    for heir_navigator_territory in (
        "1순위",
        "2순위",
        "직계비속",
        "직계존속",
        "1.5배",
        "유류분",
        "3분의",
        "2분의",
        "상속분은",
    ):
        assert heir_navigator_territory not in reply, heir_navigator_territory


def test_closing_lines_present_once() -> None:
    """안내 전용 화면도 다른 결과 화면과 동일하게 §3-3·§3-4로 끝난다."""
    reply = _no_will_output().reply

    assert reply.count("대한법률구조공단 132") == 1
    assert reply.count("법률 자문이 아닙니다") == 1


# ---------------------------------------------------------------------------
# [4] heir_navigator로의 직접 핸드오프 없음 (2026-08-25 제거 — 라우터가 담당)
# ---------------------------------------------------------------------------


def test_does_not_hand_off_to_heir_navigator() -> None:
    """웹 UI가 라우터 방식으로 확정돼, #20에서 넣었던 handoff:heir_navigator를
    제거했다 — 받는 쪽이 없어 막다른 길이었다. next_action은 다른 안내 전용
    분기(secret/oral)와 마찬가지로 None이다."""
    output = _no_will_output()

    assert output.next_action is None
    assert "handoff_reason" not in output.data


def test_guides_user_back_to_chat_for_legal_succession() -> None:
    """직접 핸드오프 대신, 채팅으로 돌아가 다시 물어보라고 안내한다."""
    reply = _no_will_output().reply

    assert no_will_guidance()["chat_return_notice"] in reply
    assert "처음 화면에서 다시 문의해 주세요" in reply


def test_no_will_state_is_persisted_to_session_namespace() -> None:
    """회귀: will_type="none" 이 다른 안내 전용 분기(notarial/secret/oral)와
    동일하게 세션 네임스페이스(data["decedent_estate"])에 저장돼야 한다.

    _run_no_will_pipeline이 _namespaced()를 거치지 않고 평면 dict만 반환하던
    시절에는 output.data에 "decedent_estate" 키 자체가 없어서,
    handoff.extract_state_to_persist가 빈 dict를 돌려줬다 — 즉 "유언장 없음"
    답변이 세션에 전혀 남지 않았다. 나중에 다시 decedent_estate로 라우팅되면
    (예: heir_navigator 대화 중 사용자가 "유언장"을 다시 언급) will_type을
    처음부터 다시 물어보는 회귀가 있었다.
    """
    from orchestrator.handoff import extract_state_to_persist

    output = _no_will_output()

    assert "decedent_estate" in output.data
    assert output.data["decedent_estate"]["will_type"] == "none"

    persisted = extract_state_to_persist(AgentName.DECEDENT_ESTATE, output)
    assert persisted.get("will_type") == "none"


# ---------------------------------------------------------------------------
# 회귀 — 기존 경로 무영향
# ---------------------------------------------------------------------------


def test_existing_will_types_unaffected() -> None:
    """ "none" 추가가 기존 방식 분기를 건드리지 않아야 한다."""
    will = (
        "유언장\n유언자: 홍길동\n"
        "주소: 서울특별시 강남구 테헤란로 123, 45동 678호\n"
        "2026년 5월 3일\n\n나의 전 재산을 배우자에게 상속한다."
    )

    handwritten = _run(will, will_type="handwritten")
    assert "requirements" in handwritten.data

    notarial = _run(will, will_type="notarial")
    assert "공증인이 작성한 유언은 형식 요건 검증이 필요하지 않습니다" in notarial.reply

    unknown = _run(will, will_type="unknown")
    assert unknown.data["will_type"] == "handwritten"  # 자필증서 기본값 유지


def test_unknown_will_type_still_reasks() -> None:
    """화이트리스트 확장이 "아무 값이나 통과"로 새지 않았는지."""
    output = _run(will_type="아무거나")

    assert "어떤 형태의 유언인가요?" in output.reply
    assert output.data["warnings"][0]["field"] == "will_type"
    assert "none" in output.data["warnings"][0]["allowed"]

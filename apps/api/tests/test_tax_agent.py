from agents.tax_calculator.agent import STATE_KEY, _parse_money, run
from schemas import AgentInput, AgentName, AgentOutput


def test_tax_agent_asks_first_missing_slot() -> None:
    output = run(
        AgentInput(
            session_id="tax-test",
            user_message="상속세를 계산하고 싶어요.",
        )
    )

    assert output.agent == AgentName.TAX_CALCULATOR
    assert "[mock]" not in output.reply
    assert output.data[STATE_KEY]["status"] == "collecting"
    assert output.data[STATE_KEY]["asked_slot"] == "decedent_is_resident"


def test_tax_agent_keeps_state_between_turns() -> None:
    first_output = run(
        AgentInput(
            session_id="tax-test",
            user_message="상속세를 계산하고 싶어요.",
        )
    )

    second_output = run(
        AgentInput(
            session_id="tax-test",
            user_message="네, 국내 거주자였어요.",
            context={
                STATE_KEY: first_output.data[STATE_KEY],
            },
        )
    )

    state = second_output.data[STATE_KEY]

    assert state["values"]["decedent_is_resident"] is True
    assert state["asked_slot"] == "spouse_exists"


def test_tax_agent_uses_family_graph_and_calculates() -> None:
    context = {
        STATE_KEY: {
            "status": "collecting",
            "values": {
                "decedent_is_resident": True,
                "original_inherited_property": 1_000_000_000,
                "deemed_inherited_property": 0,
                "debts": 0,
                "financial_assets": 0,
                "financial_debts": 0,
                "prior_gifts_to_heirs": 0,
                "prior_gifts_to_non_heirs": 0,
                "filing_within_deadline": True,
            },
            "confirmed_fields": [],
            "asked_slot": None,
            "missing_fields": [],
            "last_result": None,
        }
    }

    family_graph = {
        "heirs": [
            {
                "name": "자녀 1",
                "relation": "child",
                "alive": True,
                "minor": False,
            }
        ]
    }

    output = run(
        AgentInput(
            session_id="tax-test",
            user_message="계산해주세요.",
            family_graph=family_graph,
            context=context,
        )
    )

    state = output.data[STATE_KEY]

    assert output.agent == AgentName.TAX_CALCULATOR
    assert state["status"] == "calculated"
    assert state["values"]["spouse_exists"] is False
    assert state["values"]["children_count"] == 1
    assert state["last_result"]["estimated_tax_due"] == 86_330_000
    assert "최종 예상 상속세" in output.reply
    assert "세금을 매기는 기준 금액" in output.reply
    assert "상속세 과세가액" not in output.reply
    assert "상속세 과세표준" not in output.reply
    assert "산출세액" not in output.reply
    assert "신고세액공제" not in output.reply


# ---------------------------------------------------------------------------
# family_graph 기반 spouse_is_sole_heir 판별 — 민법 제1003조상 형제자매는
# 배우자의 단독상속 여부에 영향을 주면 안 되고, 부모(2순위)는 영향을 줘야 한다.
# ---------------------------------------------------------------------------


def _run_with_family_graph(session_id: str, heirs: list[dict]) -> AgentOutput:
    context = {
        STATE_KEY: {
            "status": "collecting",
            "values": {
                "decedent_is_resident": True,
                "original_inherited_property": 1_000_000_000,
                "deemed_inherited_property": 0,
                "debts": 0,
                "financial_assets": 0,
                "financial_debts": 0,
                "prior_gifts_to_heirs": 0,
                "prior_gifts_to_non_heirs": 0,
                "spouse_actual_inheritance": 600_000_000,
                "filing_within_deadline": True,
            },
            "confirmed_fields": [],
            "asked_slot": None,
            "missing_fields": [],
            "last_result": None,
        }
    }
    return run(
        AgentInput(
            session_id=session_id,
            user_message="계산해주세요.",
            family_graph={"heirs": heirs},
            context=context,
        )
    )


def test_family_graph_sibling_does_not_block_spouse_sole_heir() -> None:
    """자녀·부모 없이 배우자와 형제자매만 있으면 배우자가 단독상속인이다."""
    output = _run_with_family_graph(
        "tax-fg-sibling",
        [
            {"name": "배우자", "relation": "spouse", "alive": True},
            {"name": "형", "relation": "sibling", "alive": True},
        ],
    )

    state = output.data[STATE_KEY]
    assert state["values"]["spouse_is_sole_heir"] is True
    assert state["status"] == "calculated"


def test_family_graph_parent_blocks_spouse_sole_heir() -> None:
    """자녀는 없지만 부모(2순위)가 생존해 있으면 배우자는 단독상속인이 아니다
    — 아직 지원하지 않는 조합이므로 계산 대신 안내 메시지를 반환해야 한다."""
    output = _run_with_family_graph(
        "tax-fg-parent",
        [
            {"name": "배우자", "relation": "spouse", "alive": True},
            {"name": "모", "relation": "parent", "alive": True},
        ],
    )

    state = output.data[STATE_KEY]
    assert state["values"]["spouse_is_sole_heir"] is False
    assert state["status"] == "unsupported"


def test_family_graph_grandchild_is_not_reported_as_parent_case() -> None:
    """배우자와 손주가 있는 경우를 부모님 공동상속으로 안내하면 안 된다."""

    output = _run_with_family_graph(
        "tax-fg-grandchild",
        [
            {"name": "배우자", "relation": "spouse", "alive": True},
            {"name": "자녀", "relation": "child", "alive": False},
            {"name": "손주", "relation": "grandchild", "alive": True},
        ],
    )

    state = output.data[STATE_KEY]

    assert state["status"] == "unsupported"
    assert "자녀분이 먼저 돌아가시고 손주가 대신 상속받는 경우" in output.reply
    assert "부모님" not in output.reply


# ---------------------------------------------------------------------------
# _parse_money — "0원"을 부분 문자열로 검사하면 500000000원처럼 끝나는
# 정상적인 금액까지 전부 0으로 잘못 인식되던 버그의 회귀 테스트.
# ---------------------------------------------------------------------------


def test_parse_money_handles_round_amounts_ending_in_zero() -> None:
    assert _parse_money("500000000원") == 500_000_000
    assert _parse_money("100000000원") == 100_000_000
    assert _parse_money("1000000000원") == 1_000_000_000
    assert _parse_money("500,000,000원") == 500_000_000


def test_parse_money_handles_compound_korean_units() -> None:
    assert _parse_money("9천5백만원") == 95_000_000
    assert _parse_money("1억9천5백만원") == 195_000_000
    assert _parse_money("2억 3천만원") == 230_000_000


def test_parse_money_still_treats_zero_and_none_as_zero() -> None:
    assert _parse_money("0원") == 0
    assert _parse_money("0") == 0
    assert _parse_money("없어요") == 0
    assert _parse_money("없음") == 0


def test_tax_agent_accepts_round_amount_ending_in_zero() -> None:
    """회귀 재현 — 대화형으로 '500000000원'을 답하면 0으로 잘못 저장되면 안 된다."""
    first_output = run(
        AgentInput(session_id="tax-zero-bug", user_message="상속세를 계산하고 싶어요.")
    )
    context = {STATE_KEY: first_output.data[STATE_KEY]}

    for answer in ("네, 국내 거주자였어요.", "아니요, 배우자는 없어요."):
        output = run(
            AgentInput(session_id="tax-zero-bug", user_message=answer, context=context)
        )
        context = {STATE_KEY: output.data[STATE_KEY]}

    output = run(
        AgentInput(
            session_id="tax-zero-bug",
            user_message="0명",
            context=context,
        )
    )
    context = {STATE_KEY: output.data[STATE_KEY]}

    output = run(
        AgentInput(
            session_id="tax-zero-bug",
            user_message="500000000원",
            context=context,
        )
    )

    assert (
        output.data[STATE_KEY]["values"]["original_inherited_property"] == 500_000_000
    )


# ---------------------------------------------------------------------------
# 자녀 없는 배우자 상속 — spouse_is_sole_heir를 묻지 않아 배우자 실제 상속액이
# 5억원 이상이면 계산이 예외로 실패하던 버그의 회귀 테스트.
# ---------------------------------------------------------------------------


def _answer_all(session_id: str, answers: list[str]) -> AgentOutput:
    context: dict = {}
    output = None
    for answer in answers:
        output = run(
            AgentInput(session_id=session_id, user_message=answer, context=context)
        )
        context = {STATE_KEY: output.data[STATE_KEY]}
    return output


def test_childless_couple_asks_whether_spouse_is_sole_heir() -> None:
    output = _answer_all(
        "tax-childless",
        [
            "상속세를 계산하고 싶어요.",
            "네, 국내 거주자였어요.",
            "네, 배우자가 있어요.",
            "자녀는 없어요.",
        ],
    )

    assert output.data[STATE_KEY]["asked_slot"] == "spouse_is_sole_heir"


def test_childless_couple_sole_heir_calculates_successfully() -> None:
    """회귀 재현 — 자녀 없는 부부, 배우자 실제 상속액 5억 이상이면 이전에는

    calculate_spouse_legal_share가 ValueError를 던져 계산이 실패했다.
    """
    output = _answer_all(
        "tax-childless-sole",
        [
            "상속세를 계산하고 싶어요.",
            "네, 국내 거주자였어요.",
            "네, 배우자가 있어요.",
            "자녀는 없어요.",
            "네, 배우자가 단독으로 상속받아요.",
            "10억원",
            "0원",  # 사망보험금 없음
            "0원",  # 신탁재산 없음
            "0원",  # 퇴직급여 없음
            "0원",
            "0원",
            "0원",
            "0원",
            "0원",
            "6억원",
            "네, 신고할 예정이에요.",
        ],
    )

    assert output.data[STATE_KEY]["status"] == "calculated"
    assert output.data[STATE_KEY]["values"]["spouse_is_sole_heir"] is True
    assert "최종 예상 상속세" in output.reply


def test_childless_couple_co_heir_with_parents_is_reported_as_unsupported() -> None:
    output = _answer_all(
        "tax-childless-parents",
        [
            "상속세를 계산하고 싶어요.",
            "네, 국내 거주자였어요.",
            "네, 배우자가 있어요.",
            "자녀는 없어요.",
            "아니요, 부모님과 함께 상속받아요.",
        ],
    )

    assert output.data[STATE_KEY]["status"] == "unsupported"
    assert "부모님" in output.reply
    # 이전 버그처럼 "정보가 서로 안 맞는다"는 오해를 주는 문구가 아니어야 한다.
    assert "서로 맞지 않는" not in output.reply


def test_validation_error_uses_friendly_reply_and_keeps_raw_error_for_dev() -> None:
    output = run(
        AgentInput(
            session_id="tax-friendly-error",
            user_message="계산해주세요.",
            context={
                "tax_input": {
                    "decedent_is_resident": True,
                    "spouse_exists": False,
                    "children_count": 0,
                    "original_inherited_property": 100_000_000,
                    "deemed_inherited_property": 0,
                    "debts": 0,
                    "financial_assets": 200_000_000,
                    "financial_debts": 0,
                    "prior_gifts_to_heirs": 0,
                    "prior_gifts_to_non_heirs": 0,
                    "filing_within_deadline": True,
                }
            },
        )
    )

    state = output.data[STATE_KEY]
    raw_error = "금융재산가액은 총상속재산가액보다 클 수 없습니다."

    assert state["status"] == "needs_review"
    assert raw_error in state["last_error"]
    assert raw_error not in output.reply
    assert "금융재산으로 입력한 금액이 전체 상속재산보다 커요" in output.reply

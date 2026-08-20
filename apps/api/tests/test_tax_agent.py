from agents.tax_calculator.agent import STATE_KEY, run
from schemas import AgentInput, AgentName


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
    assert "예상 납부세액" in output.reply

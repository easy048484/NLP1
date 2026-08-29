"""상속분·유류분 1차 위험 점검 에이전트 테스트."""

from __future__ import annotations

from datetime import date

import pytest

from agents.heir_share_analyzer.agent import run
from agents.heir_share_analyzer.calculator import (
    UnsupportedFamilyCase,
    calculate_heir_share,
)
from agents.heir_share_analyzer.models import (
    AnalysisStage,
    AnalysisStatus,
    ComplexityFlag,
    HeirShareInput,
)
from schemas import AgentInput, AgentName


SPOUSE_AND_TWO_CHILDREN = {
    "heirs": [
        {"name": "배우자", "relation": "spouse", "alive": True, "minor": False},
        {"name": "자녀1", "relation": "child", "alive": True, "minor": False},
        {"name": "자녀2", "relation": "child", "alive": True, "minor": False},
    ]
}


def test_spouse_and_two_children_detects_simple_gap() -> None:
    data = HeirShareInput(
        stage=AnalysisStage.PRE_DEATH,
        estate_value=700_000_000,
        debts=0,
        planned_acquisitions={
            "배우자": 500_000_000,
            "자녀1": 200_000_000,
            "자녀2": 0,
        },
    )

    result = calculate_heir_share(data, SPOUSE_AND_TWO_CHILDREN)

    assert result.status == AnalysisStatus.POSSIBLE_GAP
    by_name = {heir.name: heir for heir in result.heirs}
    assert by_name["배우자"].statutory_share_fraction == "3/7"
    assert by_name["배우자"].basic_forced_share_estimate == 150_000_000
    assert by_name["자녀1"].statutory_share_fraction == "2/7"
    assert by_name["자녀2"].basic_forced_share_estimate == 100_000_000
    assert by_name["자녀2"].simple_gap == 100_000_000
    assert result.expert_handoff.possible_gap_heirs == ["자녀2"]
    assert result.expert_handoff.per_heir_calculation[2].simple_gap == 100_000_000
    assert any(
        "실제 청구 가능 여부" in point for point in result.expert_handoff.review_points
    )


def test_spouse_is_sole_heir_when_only_siblings_are_also_registered() -> None:
    family_graph = {
        "heirs": [
            {"name": "배우자", "relation": "spouse", "alive": True},
            {"name": "형제", "relation": "sibling", "alive": True},
        ]
    }
    result = calculate_heir_share(
        HeirShareInput(estate_value=500_000_000), family_graph
    )

    assert len(result.heirs) == 1
    assert result.heirs[0].name == "배우자"
    assert result.heirs[0].statutory_share_fraction == "1/1"
    assert result.heirs[0].basic_forced_share_estimate == 250_000_000


def test_siblings_have_no_forced_share_under_current_rule() -> None:
    family_graph = {
        "heirs": [
            {"name": "형제1", "relation": "sibling", "alive": True},
            {"name": "형제2", "relation": "sibling", "alive": True},
        ]
    }
    result = calculate_heir_share(
        HeirShareInput(estate_value=400_000_000), family_graph
    )

    assert [heir.statutory_share_fraction for heir in result.heirs] == ["1/2", "1/2"]
    assert [heir.basic_forced_share_estimate for heir in result.heirs] == [0, 0]


def test_grandchild_case_is_not_guessed() -> None:
    family_graph = {
        "heirs": [
            {"name": "손자녀", "relation": "grandchild", "alive": True},
        ]
    }

    with pytest.raises(UnsupportedFamilyCase, match="대습상속"):
        calculate_heir_share(HeirShareInput(estate_value=300_000_000), family_graph)


def test_complexity_flag_forces_expert_review() -> None:
    data = HeirShareInput(
        estate_value=700_000_000,
        planned_acquisitions={"배우자": 300_000_000},
        complexity_flags=[ComplexityFlag.PRIOR_GIFT],
    )

    result = calculate_heir_share(data, SPOUSE_AND_TWO_CHILDREN)

    assert result.status == AnalysisStatus.EXPERT_REVIEW_REQUIRED
    assert any("과거 증여" in point for point in result.expert_handoff.review_points)


def test_old_opening_date_requires_expert_review() -> None:
    data = HeirShareInput(
        stage=AnalysisStage.POST_DEATH,
        estate_value=700_000_000,
        inheritance_opening_date=date(2025, 12, 1),
    )

    result = calculate_heir_share(data, SPOUSE_AND_TWO_CHILDREN)

    assert result.status == AnalysisStatus.EXPERT_REVIEW_REQUIRED
    assert any("시행일 이전" in point for point in result.expert_handoff.review_points)


def test_agent_uses_structured_context_and_returns_namespaced_summary() -> None:
    payload = AgentInput(
        session_id="share-structured",
        user_message="계산해주세요",
        family_graph=SPOUSE_AND_TWO_CHILDREN,
        context={
            "share_input": {
                "stage": "pre_death",
                "estate_value": 700_000_000,
                "debts": 0,
                "planned_acquisitions": {
                    "배우자": 500_000_000,
                    "자녀1": 200_000_000,
                    "자녀2": 0,
                },
                "complexity_flags": [],
            }
        },
    )

    output = run(payload)

    assert output.agent == AgentName.HEIR_SHARE_ANALYZER
    assert "부족 가능성" in output.reply
    state = output.data["heir_share_analyzer"]
    assert state["status"] == "possible_gap"
    assert state["expert_handoff"]["possible_gap_heirs"] == ["자녀2"]


def test_agent_collects_values_over_multiple_turns() -> None:
    context: dict = {}
    answers = ["생전", "7억원", "0원", "배우자=5억원, 자녀1=2억원, 자녀2=0원", "아니요"]

    output = run(
        AgentInput(
            session_id="share-chat",
            user_message="유류분을 확인하고 싶어요",
            family_graph=SPOUSE_AND_TWO_CHILDREN,
            context=context,
        )
    )
    assert "생전에" in output.reply

    for answer in answers:
        context = output.data
        output = run(
            AgentInput(
                session_id="share-chat",
                user_message=answer,
                family_graph=SPOUSE_AND_TWO_CHILDREN,
                context=context,
            )
        )

    assert output.data["heir_share_analyzer"]["status"] == "possible_gap"
    assert "100,000,000원" in output.reply


def test_post_death_chat_asks_for_opening_date() -> None:
    first = run(
        AgentInput(
            session_id="share-post-death",
            user_message="유류분을 확인하고 싶어요",
            family_graph=SPOUSE_AND_TWO_CHILDREN,
        )
    )
    second = run(
        AgentInput(
            session_id="share-post-death",
            user_message="사망 후",
            family_graph=SPOUSE_AND_TWO_CHILDREN,
            context=first.data,
        )
    )

    assert "사망일" in second.reply
    assert second.data["heir_share_analyzer"]["asked_slot"] == (
        "inheritance_opening_date"
    )


def test_agent_does_not_calculate_without_family_graph() -> None:
    output = run(
        AgentInput(session_id="share-no-family", user_message="유류분 계산해주세요")
    )

    assert output.agent == AgentName.HEIR_SHARE_ANALYZER
    assert "가족관계" in output.reply
    assert output.data["heir_share_analyzer"]["status"] == "collecting_family"

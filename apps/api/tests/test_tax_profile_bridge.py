"""공유 DB/LLM을 쓰지 않는 재무정보 연동 회귀 테스트."""

from copy import deepcopy
import socket

import pytest

from agents.tax_calculator.agent import (
    STATE_KEY,
    _apply_financial_profile,
    _empty_state,
    _parse_money,
    run,
)
from agents.tax_calculator.profile_bridge import profile_candidates, tax_snapshot
from schemas import AgentInput, FinancialProfile


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("연동 단위 테스트에서 네트워크 연결 금지")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def profile(assets=None, liabilities=None, insurance=None):
    details = {}
    for key, value in (
        ("assets", assets),
        ("liabilities", liabilities),
        ("insurance", insurance),
    ):
        if value is not None:
            details[key] = value
    return FinancialProfile(
        financial_assets=0, other_assets=999_000_000, extra={"asset_organizer": details}
    )


def complete_values():
    return dict(
        decedent_is_resident=True,
        spouse_exists=False,
        children_count=1,
        original_inherited_property=1_000_000_000,
        deemed_inherited_property=0,
        debts=0,
        financial_assets=0,
        financial_debts=0,
        prior_gifts_to_heirs=0,
        prior_gifts_to_non_heirs=0,
        filing_within_deadline=True,
    )


def turn(message="상속세 계산", state=None, shared=None, explicit=None):
    context = {}
    if state is not None:
        context[STATE_KEY] = state
    if explicit is not None:
        context["tax_input"] = explicit
    return run(
        AgentInput(
            session_id="offline-tax-profile",
            user_message=message,
            financial_profile=shared,
            context=context,
        )
    )


def test_itemized_assets_override_placeholder_zero_without_double_counting():
    shared = profile(
        assets=[
            {"type": "부동산", "value": 600},
            {"type": "예금", "value": 200},
            {"type": "주식", "value": 100},
            {"type": "펀드", "value": 100},
        ]
    )
    before = shared.model_dump()
    candidates, warnings = profile_candidates(tax_snapshot(shared))
    assert candidates["original_inherited_property"] == 1000
    assert candidates["financial_assets"] == 400
    assert any("최대주주" in warning for warning in warnings)
    assert shared.model_dump() == before


def test_other_asset_is_not_removed_from_estate_or_silently_excluded_from_deduction():
    candidates, warnings = profile_candidates(
        tax_snapshot(
            profile(
                assets=[
                    {"type": "예금", "value": 200},
                    {"type": "기타", "value": 300},
                ]
            )
        )
    )
    assert candidates["original_inherited_property"] == 500
    assert "financial_assets" not in candidates
    assert any("미확인" in warning for warning in warnings)


@pytest.mark.parametrize("bad", [None, -1, True, "100", 1.5])
def test_invalid_asset_amount_never_becomes_partial_total(bad):
    candidates, _ = profile_candidates(
        tax_snapshot(
            profile(
                assets=[
                    {"type": "예금", "value": 200},
                    {"type": "기타", "value": bad},
                ]
            )
        )
    )
    assert "original_inherited_property" not in candidates
    assert "financial_assets" not in candidates


def test_zero_marked_as_unknown_is_not_known():
    candidates, _ = profile_candidates(
        tax_snapshot(
            profile(
                assets=[
                    {"type": "예금", "value": 0, "note": "금액 미언급"},
                ]
            )
        )
    )
    assert "original_inherited_property" not in candidates


def test_partial_flat_profile_and_financial_zero_are_not_tax_inputs():
    candidates, _ = profile_candidates(
        tax_snapshot(FinancialProfile(financial_assets=0))
    )
    assert candidates == {}


def test_complete_flat_profile_only_suggests_total():
    candidates, _ = profile_candidates(
        tax_snapshot(
            FinancialProfile(
                real_estate_value=600,
                financial_assets=300,
                other_assets=100,
                total_debts=20,
            )
        )
    )
    assert candidates == {"original_inherited_property": 1000, "debts": 20}


@pytest.mark.parametrize("name", ["대출", "카드론", "전세자금대출", "은행대출"])
def test_loan_name_does_not_classify_creditor(name):
    candidates, warnings = profile_candidates(
        tax_snapshot(
            profile(
                liabilities=[
                    {"type": name, "remaining_balance": 50},
                ]
            )
        )
    )
    assert candidates["debts"] == 50
    assert "financial_debts" not in candidates
    assert any("채권자" in warning for warning in warnings)


def test_creditor_classification_suggests_only_financial_institution_debt():
    candidates, _ = profile_candidates(
        tax_snapshot(
            profile(
                liabilities=[
                    {
                        "remaining_balance": 70,
                        "creditor_category": "financial_institution",
                    },
                    {"remaining_balance": 30, "creditor_category": "non_financial"},
                ]
            )
        )
    )
    assert candidates["debts"] == 100
    assert candidates["financial_debts"] == 70


def test_insurance_tag_is_not_deemed_property():
    candidates, warnings = profile_candidates(
        tax_snapshot(
            profile(
                insurance=[
                    {"type": "종신보험", "value": 100_000_000},
                ]
            )
        )
    )
    assert "deemed_inherited_property" not in candidates
    assert any("가입금액" in warning for warning in warnings)


def test_shared_data_is_saved_but_not_confirmed():
    state = _empty_state()
    _apply_financial_profile(
        AgentInput(
            session_id="test", user_message="test", financial_profile=profile(assets=[])
        ),
        state,
    )
    assert state["profile_snapshot"] is not None
    assert state["values"] == {}
    assert state["confirmed_fields"] == []


def test_scope_confirmation_precedes_suggestions():
    shared = profile(assets=[{"type": "예금", "value": 500_000_000}])
    first = turn(shared=shared)
    assert first.data[STATE_KEY]["asked_slot"] == "profile_scope_confirmed"
    assert "사망일" in first.reply
    second = turn("네", first.data[STATE_KEY], shared)
    assert second.data[STATE_KEY]["profile_scope_confirmed"] is True
    assert second.data[STATE_KEY]["asked_slot"] == "decedent_is_resident"


def test_flat_shared_fields_are_candidates_not_confirmed_inputs():
    shared = FinancialProfile(
        real_estate_value=600_000_000,
        financial_assets=200_000_000,
        other_assets=100_000_000,
        total_debts=80_000_000,
        financial_debts=50_000_000,
    )
    first = turn(shared=shared)
    state = first.data[STATE_KEY]
    assert state["values"] == {}
    assert state["confirmed_fields"] == []
    assert state["profile_candidates"] == {
        "original_inherited_property": 900_000_000,
        "debts": 80_000_000,
    }
    # 자료 범위에 대한 동의는 개별 금액까지 확정한 것이 아니다.
    second = turn("네", state, shared)
    assert second.data[STATE_KEY]["values"] == {}
    assert second.data[STATE_KEY]["confirmed_fields"] == []


@pytest.mark.parametrize(
    "shared",
    [
        FinancialProfile(real_estate_value=800_000_000),
        FinancialProfile(financial_assets=0),
    ],
)
def test_incomplete_flat_profile_does_not_confirm_partial_total(shared):
    first = turn(
        shared=shared,
        explicit={
            "decedent_is_resident": True,
            "spouse_exists": False,
            "children_count": 1,
        },
    )
    second = turn("네", first.data[STATE_KEY], shared)
    state = second.data[STATE_KEY]
    assert state["asked_slot"] == "original_inherited_property"
    assert "original_inherited_property" not in state["profile_candidates"]
    assert "original_inherited_property" not in state["values"]
    assert "financial_assets" not in state["values"]


def test_rejected_scope_does_not_use_retirement_assets():
    shared = profile(assets=[{"type": "예금", "value": 500_000_000}])
    first = turn(shared=shared)
    second = turn("아니요", first.data[STATE_KEY], shared)
    assert "original_inherited_property" not in second.data[STATE_KEY]["values"]
    assert second.data[STATE_KEY]["profile_scope_confirmed"] is False


def test_rejected_profile_does_not_reappear_on_following_turn():
    shared = profile(assets=[{"type": "예금", "value": 500_000_000}])
    first = turn(
        shared=shared,
        explicit={
            "decedent_is_resident": True,
            "spouse_exists": False,
            "children_count": 1,
        },
    )
    rejected = turn("아니요", first.data[STATE_KEY], shared)
    pending = turn("모름", rejected.data[STATE_KEY], shared)
    state = pending.data[STATE_KEY]
    assert state["profile_scope_confirmed"] is False
    assert state["asked_slot"] == "original_inherited_property"
    assert "original_inherited_property" not in state["values"]
    assert "financial_assets" not in state["values"]
    assert state["last_result"] is None


def test_confirmed_candidate_is_saved_with_source():
    shared = profile(assets=[{"type": "예금", "value": 500_000_000}])
    first = turn(
        shared=shared,
        explicit={
            "decedent_is_resident": True,
            "spouse_exists": False,
            "children_count": 1,
        },
    )
    second = turn("네", first.data[STATE_KEY], shared)
    assert "500,000,000원" in second.reply
    third = turn("네", second.data[STATE_KEY], shared)
    assert third.data[STATE_KEY]["values"]["original_inherited_property"] == 500_000_000
    assert (
        third.data[STATE_KEY]["profile_sources"]["original_inherited_property"]
        == "profile_confirmed"
    )


def test_structured_input_overrides_pending_chat_and_shared_candidate():
    state = _empty_state()
    state["asked_slot"] = "financial_assets"
    state["values"] = complete_values()
    state["values"].pop("financial_assets")
    output = turn("0원", state, explicit={"financial_assets": 200_000_000})
    assert output.data[STATE_KEY]["values"]["financial_assets"] == 200_000_000
    assert output.data[STATE_KEY]["status"] == "calculated"


def test_changed_snapshot_invalidates_results_and_preserves_direct_input():
    shared = profile(assets=[{"type": "예금", "value": 500_000_000}])
    first = turn(shared=shared, explicit=complete_values())
    second = turn("네", first.data[STATE_KEY], shared)
    assert second.data[STATE_KEY]["last_result"] is not None
    changed = profile(assets=[{"type": "예금", "value": 600_000_000}])
    third = turn("네", second.data[STATE_KEY], changed)
    state = third.data[STATE_KEY]
    assert state["last_result"] is None
    assert state["values"]["original_inherited_property"] == 1_000_000_000
    assert "original_inherited_property" in state["profile_reconfirm"]
    assert state["asked_slot"] == "profile_scope_confirmed"
    assert "변경" in third.reply


def test_profile_values_are_invalidated_after_snapshot_change():
    state = _empty_state()
    state["profile_snapshot"] = tax_snapshot(profile(assets=[]))
    state["values"]["original_inherited_property"] = 0
    state["profile_sources"]["original_inherited_property"] = "profile_confirmed"
    state["confirmed_fields"].append("original_inherited_property")
    output = turn(state=state, shared=profile(assets=[{"type": "예금", "value": 500}]))
    assert "original_inherited_property" not in output.data[STATE_KEY]["values"]
    assert state["values"]["original_inherited_property"] == 0  # 입력 상태도 불변


def test_retirement_only_change_does_not_reset_tax_confirmation():
    shared = FinancialProfile(real_estate_value=0, financial_assets=0, other_assets=0)
    state = turn(shared=shared).data[STATE_KEY]
    state["profile_scope_confirmed"] = True
    updated = shared.model_copy(update={"retirement_age": 65})
    output = turn(state=state, shared=updated)
    assert output.data[STATE_KEY]["profile_scope_confirmed"] is True


@pytest.mark.parametrize(
    "answer",
    ["모름", "잘 모르겠어요", "알 수 없어요", "정보 없어요", "아직 확인 못했어요"],
)
def test_unknown_is_not_zero(answer):
    assert _parse_money(answer) is None
    state = _empty_state()
    state["asked_slot"] = "insurance_proceeds"
    state["last_result"] = {"estimated_tax_due": 0}
    output = turn(answer, state)
    assert output.data[STATE_KEY]["deemed_items"] == {}
    assert output.data[STATE_KEY]["last_result"] is None
    assert "보류" in output.reply


def test_all_three_deemed_items_are_asked_then_zero_can_be_confirmed():
    values = complete_values()
    values.pop("deemed_inherited_property")
    output = turn(explicit=values)
    for slot in ("insurance_proceeds", "trust_property", "retirement_benefits"):
        assert output.data[STATE_KEY]["asked_slot"] == slot
        output = turn("0원", output.data[STATE_KEY])
    assert output.data[STATE_KEY]["status"] == "calculated"
    assert output.data[STATE_KEY]["values"]["deemed_inherited_property"] == 0


def test_positive_deemed_items_require_tax_and_overlap_confirmation():
    values = complete_values()
    values.pop("deemed_inherited_property")
    output = turn(explicit=values)
    for answer in ("1억원", "0원", "0원"):
        output = turn(answer, output.data[STATE_KEY])
    assert output.data[STATE_KEY]["asked_slot"] == "deemed_amounts_confirmed"
    assert "deemed_inherited_property" not in output.data[STATE_KEY]["values"]
    held = turn("아니요", output.data[STATE_KEY])
    assert held.data[STATE_KEY]["status"] == "needs_review"
    assert held.data[STATE_KEY]["last_result"] is None
    confirmed = turn("네", held.data[STATE_KEY])
    assert (
        confirmed.data[STATE_KEY]["values"]["deemed_inherited_property"] == 100_000_000
    )
    assert confirmed.data[STATE_KEY]["status"] == "calculated"


def test_none_explicit_value_is_missing_and_not_confirmed():
    output = turn(explicit={**complete_values(), "financial_assets": None})
    assert output.data[STATE_KEY]["asked_slot"] == "financial_assets"
    assert "financial_assets" not in output.data[STATE_KEY]["confirmed_fields"]


def test_zero_tax_disclaimer_is_present_in_text_and_structured_result():
    output = turn(
        explicit={**complete_values(), "original_inherited_property": 100_000_000}
    )
    assert output.data[STATE_KEY]["last_result"]["estimated_tax_due"] == 0
    assert "납세·신고 의무가 없다는 확정 판단이 아닙니다" in output.reply
    assert any(
        "확정 판단" in text
        for text in output.data[STATE_KEY]["last_result"]["warnings"]
    )


def test_legacy_context_without_profile_still_calculates():
    before = {**_empty_state(), "values": complete_values()}
    original = deepcopy(before)
    output = turn(state=before)
    assert output.data[STATE_KEY]["status"] == "calculated"
    assert before == original


def test_reenter_deemed_amounts_after_review_hold():
    values = complete_values()
    values.pop("deemed_inherited_property")
    output = turn(explicit=values)
    for answer in ("1억원", "0원", "0원", "아니요", "다시 입력"):
        output = turn(answer, output.data[STATE_KEY])
    assert output.data[STATE_KEY]["asked_slot"] == "insurance_proceeds"
    assert output.data[STATE_KEY]["deemed_items"] == {}
    assert output.data[STATE_KEY]["last_result"] is None


def test_new_deemed_amount_invalidates_profile_financial_deduction_input():
    state = _empty_state()
    state["values"] = complete_values()
    state["profile_sources"]["financial_assets"] = "profile_confirmed"
    output = turn(state=state, explicit={"deemed_inherited_property": 100_000_000})
    assert output.data[STATE_KEY]["asked_slot"] == "financial_assets"
    assert "financial_assets" not in output.data[STATE_KEY]["values"]


def test_changed_profile_rechecks_previous_absence_of_deemed_property():
    state = _empty_state()
    assets = [{"type": "부동산", "value": 1_000_000_000}]
    state["profile_snapshot"] = tax_snapshot(profile(assets=assets))
    state["values"] = complete_values()
    state["deemed_items"] = {
        "insurance_proceeds": 0,
        "trust_property": 0,
        "retirement_benefits": 0,
    }
    state["profile_sources"]["deemed_inherited_property"] = "itemized_confirmed"
    changed = profile(
        assets=assets, insurance=[{"type": "종신보험", "value": 100_000_000}]
    )
    output = turn(state=state, shared=changed)
    assert "deemed_inherited_property" not in output.data[STATE_KEY]["values"]
    confirmed = turn("네", output.data[STATE_KEY], changed)
    assert confirmed.data[STATE_KEY]["asked_slot"] == "insurance_proceeds"


@pytest.mark.parametrize("bad_type", [None, [], {}])
def test_malformed_type_is_unclassified_not_an_exception(bad_type):
    candidates, _ = profile_candidates(
        tax_snapshot(
            profile(
                assets=[
                    {"type": bad_type, "value": 100},
                ],
                liabilities=[{"creditor_category": bad_type, "remaining_balance": 50}],
            )
        )
    )
    assert candidates["original_inherited_property"] == 100
    assert candidates["debts"] == 50
    assert "financial_assets" not in candidates
    assert "financial_debts" not in candidates


def test_end_to_end_profile_confirmation_and_calculation():
    shared = profile(assets=[{"type": "예금", "value": 1_000_000_000}], liabilities=[])
    values = complete_values()
    for field in (
        "original_inherited_property",
        "debts",
        "financial_assets",
        "financial_debts",
    ):
        values.pop(field)
    output = turn(shared=shared, explicit=values)
    for slot in (
        "profile_scope_confirmed",
        "original_inherited_property",
        "debts",
        "financial_assets",
        "financial_debts",
    ):
        assert output.data[STATE_KEY]["asked_slot"] == slot
        output = turn("네", output.data[STATE_KEY], shared)
    assert output.data[STATE_KEY]["status"] == "calculated"
    assert output.data[STATE_KEY]["values"]["financial_assets"] == 1_000_000_000
    assert (
        output.data[STATE_KEY]["last_result"]["total_inherited_property"]
        == 1_000_000_000
    )


def test_changed_profile_conflict_can_keep_existing_direct_amount():
    shared = profile(assets=[{"type": "예금", "value": 1_000_000_000}])
    output = turn(shared=shared, explicit=complete_values())
    output = turn("네", output.data[STATE_KEY], shared)
    changed = profile(assets=[{"type": "예금", "value": 600_000_000}])
    output = turn("네", output.data[STATE_KEY], changed)
    output = turn("네", output.data[STATE_KEY], changed)
    assert output.data[STATE_KEY]["asked_slot"] == "original_inherited_property"
    output = turn("10억원", output.data[STATE_KEY], changed)
    assert (
        output.data[STATE_KEY]["values"]["original_inherited_property"] == 1_000_000_000
    )
    assert (
        "original_inherited_property" not in output.data[STATE_KEY]["profile_reconfirm"]
    )


def test_real_orchestrator_preserves_tax_profile_state_in_memory(monkeypatch):
    from orchestrator import router
    from orchestrator.session_store import InMemorySessionStore

    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.setenv("ORCHESTRATOR_USE_LLM", "off")
    shared = profile(assets=[{"type": "예금", "value": 500_000_000}])
    first = router.route(
        AgentInput(
            session_id="memory-profile-test",
            user_message="상속세 계산",
            financial_profile=shared,
        )
    )
    assert first.data[STATE_KEY]["asked_slot"] == "profile_scope_confirmed"
    second = router.route(
        AgentInput(session_id="memory-profile-test", user_message="네")
    )
    assert second.data[STATE_KEY]["profile_scope_confirmed"] is True
    assert (
        second.data[STATE_KEY]["profile_candidates"]["original_inherited_property"]
        == 500_000_000
    )
    assert second.data[STATE_KEY]["asked_slot"] == "decedent_is_resident"


def test_explicit_none_clears_conflict_without_crashing():
    state = _empty_state()
    state["values"] = complete_values()
    state["profile_reconfirm"] = ["financial_assets"]
    output = turn(state=state, explicit={"financial_assets": None})
    assert output.data[STATE_KEY]["asked_slot"] == "financial_assets"
    assert output.data[STATE_KEY]["last_result"] is None

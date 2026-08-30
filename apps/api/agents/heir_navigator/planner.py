"""절차 엔진 — 상태를 넣으면 "지금 어디이고 다음에 뭘 해야 하는지"가 나옵니다.

여기가 이 에이전트의 사실 원천입니다. LLM 호출 없음, 네트워크 없음, 순수 계산.
compose 단계는 이 객체에 들어 있는 내용만 말로 풀어야 하고, 여기 없는 날짜나
서류를 언급하면 안 됩니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas import FinancialProfile

from .consent import ConsentChecklist, build_checklist
from .procedure import (
    DISCLAIMER,
    DISPLAY_ORDER,
    STEP_BY_ID,
    DeadlineItem,
    StepId,
    blocked_by,
    compute_deadlines,
    guide_for,
    unlocked,
)
from .state import HeirState


class TimelineEntry(BaseModel):
    step: StepId
    title: str
    summary: str
    #: done | ready | blocked
    status: str
    blocked_by: list[str] = Field(default_factory=list)


class NextAction(BaseModel):
    step: StepId
    title: str
    summary: str
    documents: list[str] = Field(default_factory=list)
    agencies: list[str] = Field(default_factory=list)
    links: list[dict[str, str]] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    deadline: Optional[DeadlineItem] = None
    #: 이 단계의 서류·기관 정보가 아직 팀 검증 전이면 True
    needs_verification: bool = False


class Branch(BaseModel):
    """채무가 있을 때 제시하는 선택지. 추천 없이 결과만."""

    title: str
    effect: str
    caution: str = ""


class Solvency(BaseModel):
    """공유 상속재산(estate)에서 계산한 '빚 vs 재산' 대조. 추천 없이 사실만.

    asset_organizer 가 파악한 고인의 재산·부채가 세션에 들어와 있을 때만
    채워집니다. debt_exceeds_assets 가 True 면 한정승인/상속포기 선택지를
    자동으로 함께 보여줍니다(사용자가 "빚 있어요"라고 말하지 않았더라도).
    """

    assets: int
    debts: int
    debt_exceeds_assets: bool
    note: str


class ProcedurePlan(BaseModel):
    death_date: Optional[date] = None
    known_date: Optional[date] = None
    known_date_estimated: bool = False
    timeline: list[TimelineEntry] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    deadlines: list[DeadlineItem] = Field(default_factory=list)
    urgent: list[DeadlineItem] = Field(default_factory=list)
    overdue: list[DeadlineItem] = Field(default_factory=list)
    consent: Optional[ConsentChecklist] = None
    branches: list[Branch] = Field(default_factory=list)
    #: 공유 상속재산에서 계산한 빚 vs 재산 대조 (asset_organizer 가 파악했을 때만)
    solvency: Optional[Solvency] = None
    #: 다른 에이전트로 넘길 지점 (오케스트레이터가 읽는 힌트)
    handoff: Optional[str] = None
    handoff_reason: Optional[str] = None
    #: 이게 없으면 안내 자체를 만들 수 없는 슬롯 (사실상 사망일뿐)
    blocking_slot: Optional[str] = None
    #: 안내 뒤에 한 개만 덧붙여 물을 슬롯
    follow_up: Optional[str] = None
    missing_slots: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


#: 이 안에 들어오면 "임박"으로 표시. 3개월 기한을 놓치는 사고가 가장 잦아서
#: 넉넉하게 잡았습니다.
URGENT_DAYS = 30

_DEBT_BRANCHES = (
    Branch(
        title="단순승인",
        effect="재산과 빚을 모두 그대로 물려받습니다. 아무 신고도 하지 않고 3개월이 지나면 자동으로 이렇게 됩니다.",
        caution="빚이 재산보다 많으면 상속인이 본인 재산으로 갚아야 합니다.",
    ),
    Branch(
        title="한정승인",
        effect="물려받은 재산 범위 안에서만 빚을 갚습니다. 재산을 넘는 빚은 갚지 않아도 됩니다.",
        caution="가정법원에 상속재산목록을 붙여 신고해야 하고, 이후 채권자에게 알리고 청산하는 절차가 따라옵니다.",
    ),
    Branch(
        title="상속포기",
        effect="재산도 빚도 받지 않습니다.",
        caution="포기하면 상속권이 다음 순위(자녀 → 손자녀 → 부모 → 형제자매 등)로 넘어가, 가족 중 다른 사람이 빚을 떠안게 될 수 있습니다.",
    ),
)


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _solvency(estate: FinancialProfile | None) -> Optional[Solvency]:
    """세션 공유 상속재산에서 '빚 > 재산' 여부를 계산한다. 값이 하나도
    없으면 None (판단하지 않음 — 없는 정보를 0으로 채우지 않는다)."""
    if estate is None:
        return None
    asset_fields = (
        estate.real_estate_value,
        estate.financial_assets,
        estate.other_assets,
    )
    if all(v is None for v in asset_fields) and estate.total_debts is None:
        return None

    assets = sum(v for v in asset_fields if v is not None)
    debts = estate.total_debts or 0
    exceeds = debts > assets
    if exceeds:
        note = (
            f"확인된 고인의 빚({_won(debts)})이 재산({_won(assets)})보다 많습니다. "
            "빚을 떠안지 않으려면 상속개시를 안 날부터 3개월 안에 한정승인이나 "
            "상속포기를 신고해야 합니다. 아래 선택지를 함께 확인하세요."
        )
    else:
        note = (
            f"확인된 고인의 재산({_won(assets)})이 빚({_won(debts)})보다 많습니다. "
            "아무 신고를 하지 않아도(단순승인) 상속인이 본인 재산으로 빚을 갚아야 "
            "하는 상황은 아닙니다. 다만 아직 확인 안 된 빚이 있을 수 있습니다."
        )
    return Solvency(assets=assets, debts=debts, debt_exceeds_assets=exceeds, note=note)


def _timeline(state: HeirState) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for step_id in DISPLAY_ORDER:
        step = STEP_BY_ID[step_id]
        if step_id in state.completed:
            status, blockers = "done", []
        else:
            blockers = [item.title for item in blocked_by(step, state.completed)]
            status = "blocked" if blockers else "ready"
        entries.append(
            TimelineEntry(
                step=step_id,
                title=step.title,
                summary=step.summary,
                status=status,
                blocked_by=blockers,
            )
        )
    return entries


def _next_actions(state: HeirState, deadlines: list[DeadlineItem]) -> list[NextAction]:
    by_step = {item.step: item for item in deadlines}
    actions: list[NextAction] = []
    for step in unlocked(state.completed):
        guide = guide_for(step.id)
        actions.append(
            NextAction(
                step=step.id,
                title=step.title,
                summary=step.summary,
                documents=list(guide.documents) if guide else [],
                agencies=list(guide.agencies) if guide else [],
                links=[
                    {"label": label, "url": url}
                    for label, url in (guide.links if guide else ())
                ],
                tips=list(guide.tips) if guide else [],
                deadline=by_step.get(step.id),
                needs_verification=not guide.verified if guide else True,
            )
        )
    # 기한이 있는 것부터, 그중에서도 임박한 것부터 보여줍니다.
    actions.sort(
        key=lambda action: (
            action.deadline is None,
            action.deadline.days_left if action.deadline else 0,
        )
    )
    return actions


def _handoff(state: HeirState) -> tuple[Optional[str], Optional[str]]:
    """다른 에이전트로 넘길 지점 판정 (연동 지점 5번)."""
    if StepId.ASSET_SEARCH in state.completed:
        return (
            "tax_calculator",
            "재산 조회 결과가 확인되어, 상속세 계산은 승원 에이전트가 이어받을 수 있습니다.",
        )
    if state.will_exists == "yes":
        return (
            "decedent_estate",
            "유언장이 있는 것으로 확인되어, 유언장 조사는 정호 에이전트가 이어받을 수 있습니다.",
        )
    if state.death_date is None and state.turns > 0:
        # 아직 상속이 개시되지 않았고 미리 준비하려는 경우의 역전환은
        # graph.py에서 발화 신호를 보고 별도로 처리합니다.
        return None, None
    return None, None


def build_plan(
    state: HeirState,
    *,
    family_graph: dict[str, Any] | None = None,
    today: date | None = None,
    estate: FinancialProfile | None = None,
) -> ProcedurePlan:
    today = today or date.today()
    deadlines = compute_deadlines(
        death_date=state.death_date,
        known_date=state.known_date,
        completed=state.completed,
        today=today,
    )
    pending = [item for item in deadlines if not item.completed]
    handoff, reason = _handoff(state)

    solvency = _solvency(estate)
    # 사용자가 "빚 있어요"라고 말했거나, 공유 상속재산에서 빚 > 재산이 확인되면
    # 선택지를 보여준다.
    debt_signal = state.has_debt == "yes" or (
        solvency is not None and solvency.debt_exceeds_assets
    )
    show_branches = debt_signal and StepId.ACCEPT_DECIDE not in state.completed
    missing = state.missing_required()
    blocking = state.blocking_slot()
    follow_up = next((slot for slot in missing if slot != blocking), None)

    return ProcedurePlan(
        death_date=state.death_date,
        known_date=state.effective_known_date,
        known_date_estimated=state.known_date is None and state.death_date is not None,
        timeline=_timeline(state),
        next_actions=_next_actions(state, deadlines),
        deadlines=deadlines,
        urgent=[item for item in pending if 0 <= item.days_left <= URGENT_DAYS],
        overdue=[item for item in pending if item.days_left < 0],
        consent=build_checklist(family_graph),
        branches=list(_DEBT_BRANCHES) if show_branches else [],
        solvency=solvency,
        handoff=handoff,
        handoff_reason=reason,
        blocking_slot=blocking,
        follow_up=follow_up,
        missing_slots=missing,
    )

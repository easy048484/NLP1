"""법정 기한 역산.

이 모듈은 순수 함수만 있습니다. LLM도, 네트워크도, 전역 상태도 없습니다.
이 에이전트가 내놓는 모든 날짜는 여기서만 나오고, 여기만 테스트가 있으면
나머지가 흔들려도 숫자는 틀리지 않습니다.

기간 계산은 민법 제157조(초일불산입)·제160조(역에 의한 계산)를 따릅니다.
- 초일은 산입하지 않으므로 '안 날 + N개월'의 응당일 전일이 만료일이 되는데,
  이는 결과적으로 '기준일 + N개월'과 같은 날짜가 됩니다.
- 최종 월에 해당 일이 없으면 그 달의 말일로 만료합니다(제160조 제3항).
- 말일이 토요일·공휴일이면 다음 날로 만료합니다(제161조). 공휴일 달력은
  들고 있지 않으므로 계산에 반영하지 않고 안내문에 주의사항으로 붙입니다.
"""

from __future__ import annotations

import calendar
from datetime import date

from pydantic import BaseModel

from .steps import STEPS, DeadlineBase, Step, StepId

DISCLAIMER = (
    "안내 기준입니다. 사망일·상속개시를 안 날 확인, 재외국민·실종선고 등 "
    "특수한 사정에 따라 실제 기한은 달라질 수 있으니 확정 전 담당 기관이나 "
    "전문가에게 확인하세요."
)

WEEKEND_NOTE = "기한 마지막 날이 토요일·공휴일이면 그다음 날까지입니다(민법 제161조)."


def add_months(base: date, months: int) -> date:
    """월 단위 가산. 해당 일이 없는 달이면 그 달의 말일로 내립니다."""
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def month_end(base: date) -> date:
    """그 날짜가 속한 달의 말일."""
    return date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])


class DeadlineItem(BaseModel):
    step: StepId
    step_title: str
    label: str
    due_date: date
    days_left: int
    base_label: str
    base_date: date
    law: str
    note: str = ""
    completed: bool = False
    #: 기준점을 정확히 알 수 없어 사망일로 갈음했는지 (예: '안 날'을 안 물어본 경우)
    base_estimated: bool = False
    verified: bool = True
    disclaimer: str = DISCLAIMER
    weekend_note: str = WEEKEND_NOTE

    @property
    def overdue(self) -> bool:
        return self.days_left < 0


_BASE_LABELS = {
    DeadlineBase.DEATH: "사망일",
    DeadlineBase.KNOWN: "상속개시를 안 날",
    DeadlineBase.DEATH_MONTH_END: "사망일이 속한 달의 말일",
}


def _resolve_base(
    kind: DeadlineBase, death_date: date | None, known_date: date | None
) -> tuple[date, bool] | None:
    """기준일과 '추정 여부'를 돌려줍니다. 계산 불가면 None."""
    if kind is DeadlineBase.DEATH:
        return (death_date, False) if death_date else None
    if kind is DeadlineBase.DEATH_MONTH_END:
        return (month_end(death_date), False) if death_date else None
    if kind is DeadlineBase.KNOWN:
        if known_date:
            return known_date, False
        # 안 날을 아직 안 물어봤으면 사망일로 갈음하되 추정 표시를 남깁니다.
        return (death_date, True) if death_date else None
    return None


def deadline_for(
    step: Step,
    *,
    death_date: date | None,
    known_date: date | None,
    today: date,
    completed: set[StepId] | None = None,
) -> DeadlineItem | None:
    if step.deadline is None:
        return None
    resolved = _resolve_base(step.deadline.base, death_date, known_date)
    if resolved is None:
        return None
    base_date, estimated = resolved
    due = add_months(base_date, step.deadline.months)
    return DeadlineItem(
        step=step.id,
        step_title=step.title,
        label=step.deadline.label,
        due_date=due,
        days_left=(due - today).days,
        base_label=_BASE_LABELS[step.deadline.base],
        base_date=base_date,
        law=step.deadline.law,
        note=step.deadline.note,
        completed=bool(completed and step.id in completed),
        base_estimated=estimated,
        verified=step.deadline.verified,
    )


def compute_deadlines(
    *,
    death_date: date | None,
    known_date: date | None = None,
    completed: set[StepId] | None = None,
    today: date | None = None,
) -> list[DeadlineItem]:
    """사망일 기준으로 모든 법정 기한을 역산해 임박한 순으로 돌려줍니다.

    사망일을 모르면 빈 리스트입니다. 이 에이전트가 사망일부터 묻는 이유입니다.
    """
    if death_date is None:
        return []
    today = today or date.today()
    items = [
        item
        for step in STEPS
        if (
            item := deadline_for(
                step,
                death_date=death_date,
                known_date=known_date,
                today=today,
                completed=completed,
            )
        )
        is not None
    ]
    return sorted(items, key=lambda item: (item.completed, item.due_date))

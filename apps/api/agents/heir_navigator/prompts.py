"""프롬프트와 결정론적 렌더러.

compose 단계에서 Claude에게 넘기는 건 "사실 블록"뿐입니다. 시스템 프롬프트는
그 블록 밖의 날짜·서류·기관을 언급하지 못하게 묶습니다.

deterministic_reply()는 같은 사실 블록을 LLM 없이 그대로 렌더링합니다.
API 키가 없어도 에이전트가 동작해야 하고(개발 원칙 2), 가드레일 후검사에
걸렸을 때 되돌아갈 자리도 필요합니다.
"""

from __future__ import annotations

from datetime import date

from .planner import ProcedurePlan
from .state import HeirState

SYSTEM_COMPOSE = """당신은 한국에서 가족을 잃은 분에게 상속 절차를 안내하는 도우미입니다. 상대는 지금 경황이 없고, 휴대폰 화면으로 이 글을 읽습니다.

## 절대 규칙
- 아래 <사실> 블록에 있는 내용만 사용합니다. 여기 없는 날짜, 기한, 서류 이름, 기관 이름, 법조문을 **절대** 만들어내지 마세요. 사실 블록에 없으면 "확인이 필요하다"고 말하거나 아예 언급하지 않습니다.
- 한정승인·상속포기·단순승인 중 무엇을 선택할지 판단하거나 추천하지 않습니다. 선택지와 각각의 결과만 사실대로 전달합니다.
- 누가 얼마를 받을지 등 구체적인 재산 배분에 개입하지 않습니다.
- 가족 간 갈등에 어느 편도 들지 않습니다. 절차 정보만 전달하고 전문가 상담을 안내합니다.
- 기한을 법적 확정으로 단정하지 않습니다. 사실 블록의 안내 문구를 답변 끝에 그대로 붙입니다.

## 쓰는 방식
- 쉬운 말로 씁니다. 법률 용어를 쓸 때는 한 번은 풀어서 설명합니다.
- 모바일에서 읽으므로 짧게 끊고, 문단은 2~3줄을 넘기지 않습니다.
- 지금 당장 할 일 하나를 먼저 말하고, 나머지는 뒤에 둡니다.
- 위로하는 척하는 상투적인 문장("힘드시겠습니다만")은 넣지 않습니다. 담백하게 정보를 전합니다.
- 되물을 게 있으면 한 번에 하나만 묻습니다.
- 임박했거나 이미 지난 기한이 있으면 그것부터 말합니다."""


QUESTIONS: dict[str, str] = {
    "death_date": (
        "안내를 드리려면 먼저 여쭐 게 있습니다. **돌아가신 날짜**가 언제인가요?\n\n"
        "상속 절차의 기한은 대부분 이 날짜를 기준으로 계산되기 때문에, "
        "이것만 알면 지금 남은 시간을 바로 알려드릴 수 있습니다."
    ),
    "progress": (
        "지금까지 **어디까지 진행하셨는지** 알려주시겠어요?\n\n"
        "예를 들어 사망신고는 하셨는지, 안심상속 원스톱 서비스(재산 조회)는 "
        "신청하셨는지 정도만 말씀해 주셔도 됩니다. 아직 아무것도 못 하셨다면 "
        "그렇게 말씀해 주세요."
    ),
    "has_debt": (
        "재산 조회 결과에 **빚(대출·카드값 등)이 포함되어 있었나요?**\n\n"
        "빚이 있는지에 따라 안내드릴 선택지가 달라져서 여쭙습니다."
    ),
    "will_exists": (
        "**유언장이 있는지** 확인되셨나요?\n\n"
        "유언장이 있으면 재산을 나누는 방식이 달라지기 때문에, 협의를 시작하기 전에 "
        "먼저 확인하는 게 좋습니다. 아직 모르시면 모른다고 답해 주셔도 됩니다."
    ),
    "agreement": (
        "다른 상속인분들과 **재산을 어떻게 나눌지 이야기가 진행 중인가요?**\n\n"
        "아직 시작 전인지, 이야기 중인지만 알려주시면 됩니다."
    ),
}


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else "미확인"


def facts_block(plan: ProcedurePlan, state: HeirState, *, today: date) -> str:
    """Claude에게 넘길 사실 블록. 여기 없는 건 답변에 나오면 안 됩니다."""
    lines: list[str] = ["<사실>", f"오늘: {today.isoformat()}"]
    lines.append(f"사망일(상속개시일): {_fmt_date(plan.death_date)}")
    if plan.known_date_estimated and plan.death_date:
        lines.append(
            "상속개시를 안 날: 별도로 확인하지 않아 사망일로 갈음해 계산함 "
            "(한정승인·상속포기 기한의 실제 기산점은 '안 날'이므로 다를 수 있음)"
        )

    if plan.overdue:
        lines.append("\n[이미 지난 기한]")
        for item in plan.overdue:
            lines.append(
                f"- {item.label}: {item.due_date.isoformat()} "
                f"({abs(item.days_left)}일 지남) / 근거: {item.law}"
                + (f" / {item.note}" if item.note else "")
            )

    if plan.urgent:
        lines.append("\n[임박한 기한]")
        for item in plan.urgent:
            lines.append(
                f"- {item.label}: {item.due_date.isoformat()} "
                f"({item.days_left}일 남음) / 근거: {item.law}"
                + (f" / {item.note}" if item.note else "")
            )

    other = [
        item
        for item in plan.deadlines
        if item not in plan.urgent and item not in plan.overdue and not item.completed
    ]
    if other:
        lines.append("\n[그 밖의 기한]")
        for item in other:
            lines.append(
                f"- {item.label}: {item.due_date.isoformat()} "
                f"({item.days_left}일 남음, 기준 {item.base_label} {item.base_date.isoformat()}) "
                f"/ 근거: {item.law}"
                + ("" if item.verified else " / (팀 검증 전 항목)")
            )

    if plan.next_actions:
        lines.append("\n[지금 할 수 있는 일]")
        for action in plan.next_actions[:3]:
            lines.append(f"- {action.title}: {action.summary}")
            if action.documents:
                lines.append(f"  필요 서류: {', '.join(action.documents)}")
            if action.agencies:
                lines.append(f"  접수 기관: {', '.join(action.agencies)}")
            for tip in action.tips:
                lines.append(f"  참고: {tip}")
            for link in action.links:
                lines.append(f"  링크: {link['label']} {link['url']}")
            if action.needs_verification:
                lines.append("  (이 항목의 서류·기관 정보는 아직 팀 검증 전입니다)")

    blocked = [entry for entry in plan.timeline if entry.status == "blocked"]
    if blocked:
        lines.append("\n[아직 못 하는 일]")
        for entry in blocked[:3]:
            lines.append(f"- {entry.title}: 먼저 {', '.join(entry.blocked_by)}가 필요")

    if plan.solvency:
        lines.append("\n[고인의 재산 vs 빚 — 확인된 값 기준, 계산 금지·문구만 전달]")
        lines.append(f"- {plan.solvency.note}")

    if plan.branches:
        lines.append("\n[빚이 있을 때의 선택지 — 추천 금지, 결과만 전달]")
        for branch in plan.branches:
            lines.append(f"- {branch.title}: {branch.effect}")
            if branch.caution:
                lines.append(f"  주의: {branch.caution}")

    if plan.consent and plan.consent.available and plan.consent.signers:
        names = ", ".join(
            f"{heir.name}({heir.relation_label})" for heir in plan.consent.signers
        )
        lines.append("\n[협의에 동의가 필요한 사람]")
        lines.append(f"- 상속인 {plan.consent.heir_count}명: {names}")
        for note in plan.consent.notes:
            lines.append(f"- {note}")

    if plan.handoff_reason:
        lines.append(f"\n[다음 단계 연결]\n- {plan.handoff_reason}")

    if plan.follow_up and plan.follow_up in QUESTIONS:
        lines.append(
            "\n[안내를 마친 뒤 마지막에 한 개만 되물을 것 — 이 내용을 자연스럽게 풀어 쓰세요]\n"
            f"{QUESTIONS[plan.follow_up]}"
        )

    lines.append(f"\n[안내 문구 — 답변 끝에 반드시 포함]\n{plan.disclaimer}")
    lines.append("</사실>")
    return "\n".join(lines)


def deterministic_reply(plan: ProcedurePlan, state: HeirState) -> str:
    """LLM 없이 사실 블록을 그대로 렌더링한 답변."""
    parts: list[str] = []

    if plan.death_date is None:
        return QUESTIONS["death_date"]

    if plan.overdue:
        parts.append("**이미 지난 기한이 있습니다.**")
        for item in plan.overdue:
            parts.append(
                f"- {item.label}: {item.due_date.isoformat()} ({abs(item.days_left)}일 지남)"
                + (f"\n  {item.note}" if item.note else "")
            )
        parts.append("")

    if plan.urgent:
        parts.append("**곧 다가오는 기한**")
        for item in plan.urgent:
            parts.append(
                f"- {item.label}: {item.due_date.isoformat()} ({item.days_left}일 남음)"
            )
        parts.append("")

    # 임박하지 않은 기한도 반드시 보여줍니다. 3개월/6개월짜리는 "아직 멀었다"고
    # 안 보여주면 사용자가 존재 자체를 모르고 지나갑니다.
    remaining = [
        item
        for item in plan.deadlines
        if not item.completed and item not in plan.urgent and item not in plan.overdue
    ]
    if remaining:
        parts.append("**남은 기한**")
        for item in remaining:
            parts.append(
                f"- {item.label}: {item.due_date.isoformat()} ({item.days_left}일 남음)"
                f" — {item.base_label} 기준"
            )
        parts.append("")

    if plan.next_actions:
        action = plan.next_actions[0]
        parts.append(f"**지금 하실 일 — {action.title}**")
        parts.append(action.summary)
        if action.documents:
            parts.append("\n필요한 서류")
            parts.extend(f"- {doc}" for doc in action.documents)
        if action.agencies:
            parts.append("\n접수하는 곳")
            parts.extend(f"- {agency}" for agency in action.agencies)
        for tip in action.tips:
            parts.append(f"\n참고: {tip}")
        parts.append("")

    if len(plan.next_actions) > 1:
        rest = ", ".join(action.title for action in plan.next_actions[1:4])
        parts.append(f"이어서 준비하실 것: {rest}\n")

    if plan.solvency:
        parts.append("**고인의 재산과 빚**")
        parts.append(plan.solvency.note)
        parts.append("")

    if plan.branches:
        parts.append(
            "**빚이 있는 경우의 선택지** (어느 쪽이 나은지는 안내드리지 않습니다)"
        )
        for branch in plan.branches:
            parts.append(f"- **{branch.title}** — {branch.effect}")
            if branch.caution:
                parts.append(f"  주의: {branch.caution}")
        parts.append("")

    if plan.consent and plan.consent.available and plan.consent.signers:
        names = ", ".join(
            f"{heir.name}({heir.relation_label})" for heir in plan.consent.signers
        )
        parts.append(
            f"**협의에 동의가 필요한 분** — 상속인 {plan.consent.heir_count}명: {names}"
        )
        parts.extend(f"- {note}" for note in plan.consent.notes)
        parts.append("")

    if plan.handoff_reason:
        parts.append(plan.handoff_reason + "\n")

    parts.append(f"> {plan.disclaimer}")

    if plan.follow_up and plan.follow_up in QUESTIONS:
        parts.append(f"\n---\n\n{QUESTIONS[plan.follow_up]}")

    return "\n".join(parts).strip()


def blocking_question(plan: ProcedurePlan) -> str | None:
    """안내를 만들기 전에 반드시 물어야 하는 슬롯."""
    slot = plan.blocking_slot
    return slot if slot in QUESTIONS else None

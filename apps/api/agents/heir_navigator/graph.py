"""LangGraph 서브그래프.

    load → guard ─(위반)→ boundary ─────────────┐
             │                                  │
          extract → resolve ─(슬롯 부족)→ ask ──┤
                        │                       │
                        └────(충분)──→ compose ─┴→ finalize → END

guard가 resolve보다 **앞**에 있는 게 핵심입니다. "한정승인이랑 포기 중에 뭐가
나아요?" 같은 질문은 절차 계산을 돌릴 필요 없이 고정 응답으로 빠져야 합니다.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from llm.claude import LLMUnavailable, complete

from . import guardrails, prompts, slots
from .ics import build_calendar
from .planner import ProcedurePlan, build_plan
from .state import HeirState

logger = logging.getLogger(__name__)

#: 오케스트레이터(지원님)가 라우팅 키워드로 쓸 수 있게 노출합니다.
#: router.py를 직접 고치지 않기 위한 창구입니다.
TRIGGER_KEYWORDS: tuple[str, ...] = (
    "사망",
    "돌아가",
    "장례",
    "상속 시작",
    "상속이 시작",
    "상속인",
    "사망신고",
    "한정승인",
    "상속포기",
    "안심상속",
)

#: 아직 상속이 개시되지 않았고 미리 준비하고 싶다는 신호 → 정호 에이전트로 역전환
_PRE_PLANNING = re.compile(
    r"(아직|안)\s*(돌아가|사망|시작)"
    r"|살아\s*계|생전에|미리\s*(준비|정리|알아)|나중을\s*대비|유언장을?\s*(쓰|작성|남기)"
)


class GraphState(TypedDict, total=False):
    user_message: str
    family_graph: Optional[dict[str, Any]]
    #: 세션 공유 상속재산 (schemas.FinancialProfile). 빚 vs 재산 판정에 씁니다.
    estate: Any
    session_id: str
    today: date
    use_llm: bool

    heir: HeirState
    guard_hit: Optional[guardrails.GuardrailHit]
    plan: Optional[ProcedurePlan]
    asked_slot: Optional[str]

    reply: str
    next_action: Optional[str]
    data: dict[str, Any]


# ------------------------------------------------------------------- 노드


def node_load(state: GraphState) -> GraphState:
    heir = state["heir"]
    return {"heir": heir.model_copy(update={"turns": heir.turns + 1})}


def node_guard(state: GraphState) -> GraphState:
    return {"guard_hit": guardrails.check_input(state.get("user_message", ""))}


def node_boundary(state: GraphState) -> GraphState:
    hit = state["guard_hit"]
    assert hit is not None
    logger.info("경계 감지: %s", hit.boundary.value)
    return {
        "reply": hit.reply,
        "next_action": hit.next_action,
        "data": {"boundary": hit.boundary.value},
    }


def node_extract(state: GraphState) -> GraphState:
    update = slots.extract_slots(
        state.get("user_message", ""),
        today=state["today"],
        use_llm=state.get("use_llm", True),
    )
    return {"heir": state["heir"].merge(update)}


def node_resolve(state: GraphState) -> GraphState:
    plan = build_plan(
        state["heir"],
        family_graph=state.get("family_graph"),
        today=state["today"],
        estate=state.get("estate"),
    )
    return {"plan": plan}


def node_ask(state: GraphState) -> GraphState:
    """안내를 만들 수 없을 때만 오는 노드. 사실상 사망일을 묻는 자리입니다."""
    plan = state["plan"]
    assert plan is not None
    slot = prompts.blocking_question(plan)
    assert slot is not None
    heir = state["heir"]
    # 같은 질문을 두 번 하지 않도록 표시해둡니다.
    asked = set(heir.asked) | {slot}
    return {
        "heir": heir.model_copy(update={"asked": asked}),
        "asked_slot": slot,
        "reply": prompts.QUESTIONS[slot],
    }


def node_compose(state: GraphState) -> GraphState:
    plan = state["plan"]
    heir = state["heir"]
    assert plan is not None
    fallback = prompts.deterministic_reply(plan, heir)

    # 안내 뒤에 되물을 슬롯은 여기서 "물어봤음"으로 표시합니다.
    updates: dict[str, Any] = {}
    if plan.follow_up:
        updates["heir"] = heir.model_copy(
            update={"asked": set(heir.asked) | {plan.follow_up}}
        )
        updates["asked_slot"] = plan.follow_up

    if not state.get("use_llm", True):
        return {**updates, "reply": fallback}

    facts = prompts.facts_block(plan, heir, today=state["today"])
    user_turn = (
        f"{facts}\n\n"
        f"사용자의 마지막 말: {state.get('user_message', '')}\n\n"
        "위 사실 블록만 사용해서, 사용자가 지금 무엇을 해야 하는지 안내해 주세요."
    )
    try:
        reply = complete(
            system=prompts.SYSTEM_COMPOSE,
            messages=[{"role": "user", "content": user_turn}],
        )
    except LLMUnavailable as exc:
        logger.debug("compose LLM 사용 불가, 결정론적 렌더러 사용: %s", exc)
        return {**updates, "reply": fallback}
    except Exception:  # pragma: no cover - 네트워크/SDK 예외
        logger.exception("compose 실패, 결정론적 렌더러 사용")
        return {**updates, "reply": fallback}

    if not reply:
        return {**updates, "reply": fallback}

    # 출력 후검사: 모델이 어쨌든 추천을 해버렸으면 고정 템플릿으로 교체합니다.
    breach = guardrails.check_output(reply)
    if breach is not None:
        logger.warning("compose 출력이 경계를 넘어 폴백으로 교체: %s", breach.value)
        return {
            **updates,
            "reply": guardrails.fallback_reply(breach),
            "data": {"boundary": breach.value},
        }

    if plan.disclaimer not in reply:
        reply = f"{reply}\n\n> {plan.disclaimer}"
    return {**updates, "reply": reply}


def node_finalize(state: GraphState) -> GraphState:
    plan = state.get("plan")
    heir = state["heir"]
    data: dict[str, Any] = dict(state.get("data") or {})
    next_action = state.get("next_action")

    if plan is not None:
        data["plan"] = plan.model_dump(mode="json")
        if plan.deadlines:
            data["calendar_ics"] = build_calendar(
                plan.deadlines,
                session_id=state.get("session_id", "session"),
                now=state["today"],
            )
        if plan.handoff and next_action is None:
            next_action = f"handoff:{plan.handoff}"

    if state.get("asked_slot"):
        data["asked_slot"] = state["asked_slot"]

    # 안내를 마친 뒤 되물을 슬롯은 답변 본문이 아니라 별도 질문 블록으로 내보낸다.
    # (사망일처럼 안내 자체를 막는 blocking 질문은 그대로 reply 로 둔다.)
    if plan is not None and plan.follow_up and prompts.blocking_question(plan) is None:
        follow_up_q = prompts.follow_up_prompt(plan.follow_up)
        if follow_up_q is not None:
            data["pending_questions"] = [follow_up_q]

    if _PRE_PLANNING.search(state.get("user_message", "")) and heir.death_date is None:
        # 상속이 아직 개시되지 않은 경우의 역전환 (연동 지점 5번)
        next_action = "handoff:decedent_estate"
        data["handoff_reason"] = (
            "아직 상속이 개시되지 않아 미리 준비하시려는 상황으로 보입니다. "
            "생전 자산 정리·유언장 준비는 정호 에이전트가 이어받을 수 있습니다."
        )

    return {"data": data, "next_action": next_action}


# ------------------------------------------------------------------- 분기


def _after_guard(state: GraphState) -> str:
    return "boundary" if state.get("guard_hit") else "extract"


def _after_resolve(state: GraphState) -> str:
    plan = state.get("plan")
    if plan is not None and prompts.blocking_question(plan) is not None:
        return "ask"
    return "compose"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("load", node_load)
    graph.add_node("guard", node_guard)
    graph.add_node("boundary", node_boundary)
    graph.add_node("extract", node_extract)
    graph.add_node("resolve", node_resolve)
    graph.add_node("ask", node_ask)
    graph.add_node("compose", node_compose)
    graph.add_node("finalize", node_finalize)

    graph.add_edge(START, "load")
    graph.add_edge("load", "guard")
    graph.add_conditional_edges(
        "guard", _after_guard, {"boundary": "boundary", "extract": "extract"}
    )
    graph.add_edge("boundary", "finalize")
    graph.add_edge("extract", "resolve")
    graph.add_conditional_edges(
        "resolve", _after_resolve, {"ask": "ask", "compose": "compose"}
    )
    graph.add_edge("ask", "finalize")
    graph.add_edge("compose", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


_COMPILED = None


def compiled():
    """컴파일된 그래프 싱글턴. 요청마다 다시 컴파일하지 않습니다."""
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_graph()
    return _COMPILED

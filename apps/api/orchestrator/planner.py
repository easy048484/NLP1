"""
분류(classify) · 계획(build_plan) · 실행(execute_plan) — 축 2, 축 3 (담당: 정민)

classify
--------
LLM-first (2026-09-05 개편). registry.all_specs()의 모든 등록 에이전트(is_stub
제외) 중 실제로 필요한 것을 LLM이 매 턴 직접 고릅니다 — 예전처럼 "키워드
후보가 2개 이상일 때만" LLM을 부르지 않습니다. name/description/
example_utterances가 키워드 매칭의 보조가 아니라 라우팅의 주된 판단 근거가
되게 하려는 목적입니다(키워드만으로는 "아버지가 손으로 남긴 문서가 있는데
효력이 있는지 모르겠어요"처럼 등록된 키워드를 전혀 안 쓴 발화를 못 잡음).

  등급           조건                                    처리
  Fast Path      직전 턴 핸드오프 대상이 있음             build_plan 생략, 그 에이전트 1개(LLM 미호출)
  Standard Path  직전 턴 응답 대기(pending_reply_agent)   그 에이전트 1개(LLM 미호출)
  Standard/Full  그 외 전부                               LLM이 전체 eligible 후보 중 선택
                                                          → 1개면 Standard, 2개 이상이면
                                                          DAG → 병렬/순차 → compose

pending_handoff/pending_reply_agent는 여전히 결정론적 최우선이라 LLM을 아예
부르지 않습니다(#110/#111, #118/#119, #126/#127 continuation 계약 유지) —
이미 자료를 요청했거나 명시적으로 다음 에이전트를 지정해둔 상태에서 LLM의
판단이 그걸 뒤집으면 안 되기 때문입니다.

LLM 을 못 쓰는 환경(ANTHROPIC_API_KEY 없음, 호출 실패, 응답 파싱 실패)에서만
기존 키워드 기반 결정론적 폴백을 씁니다 — 개발 원칙 2 "항상 실행 가능".
키워드 정보(registry.match_keywords)는 삭제하지 않고 이 폴백 전용으로
남깁니다: 키워드 후보 1개 → 그 에이전트, 후보 0개 → 직전 에이전트→axis
기본→전체 기본, 후보 2개 이상 → 전부 실행(예전 "LLM 실패 시 후보 전부"와
동일).

build_plan
----------
AgentSpec.requires / produces 로 층(layer)을 만듭니다. 같은 층은 병렬, 다음 층은
앞 층의 결과를 context 에 주입받은 뒤 실행됩니다. 뽑히지 않은 에이전트가 만드는
필드는 무시합니다(soft 의존성) — 그래서 tax_calculator 가 혼자 뽑히면 첫 층에서
바로 돕니다.

execute_plan
------------
에이전트 run() 은 전부 동기 함수이므로(결정 4) 층 하나를 ThreadPoolExecutor 로
동시에 돌립니다. 에이전트 하나가 예외를 던지면 그 에이전트만 오류 응답으로
대체하고 나머지는 계속 진행합니다.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from schemas import (
    AgentInput,
    AgentName,
    AgentOutput,
    FinancialProfile,
    WillStatus,
)

from . import registry
from .llm_policy import llm_enabled, llm_required
from .handoff import build_agent_context

logger = logging.getLogger(__name__)

PATH_FAST = "fast"
PATH_STANDARD = "standard"
PATH_FULL = "full"

#: 앞 층 결과를 다음 층 에이전트에 넘길 때 쓰는 context 키. 값은
#: {에이전트이름: {"reply": str, "data": dict}} 입니다. 네임스페이스 상태
#: (context[에이전트이름])와 별도로, 원문 답변까지 참고하고 싶은 에이전트용.
UPSTREAM_KEY = "_upstream"


@dataclass
class Plan:
    path: str
    layers: list[list[AgentName]] = field(default_factory=list)
    #: LLM 분류가 실제로 쓰였는지 (디버그/테스트용)
    llm_used: bool = False

    @property
    def agents(self) -> list[AgentName]:
        return [name for layer in self.layers for name in layer]


# ------------------------------------------------------------------ classify


# _llm_enabled 는 llm_policy 로 이동 (compose.py 와 중복 제거)


_CLASSIFY_TOOL_NAME = "select_agents"


def _eligible_agents() -> list[AgentName]:
    """LLM 라우팅 후보 전체 — is_stub 은 하드 제외한다.

    retirement_planner 처럼 "데모 범위 제외" 결정으로 껍데기 취급되는
    에이전트는 예전에도 keywords=[] 로 후보에 아예 안 들어왔다(실측 확인,
    agents/retirement_planner/spec.py 참고). LLM-first 로 바꾸면서 후보를
    "키워드 매칭 결과"가 아니라 "등록된 전체 에이전트"로 넓히더라도, 이
    제품 의도(준비 중 에이전트는 일반 라우팅에서 선택되지 않음)는 그대로
    지켜야 하므로 is_stub 인 에이전트는 후보 자체에서 뺀다.
    """
    return [name for name, spec in registry.all_specs().items() if not spec.is_stub]


def _classify_prompt(
    candidates: list[AgentName], *, last_agent: Optional[AgentName] = None
) -> str:
    specs = registry.all_specs()
    lines = [
        "당신은 가족 자산·상속 상담 서비스의 라우터입니다. 사용자 메시지를 읽고 아래 "
        "후보 에이전트 중 이번 답변에 실제로 필요한 것만 고르세요. 여러 주제를 한 번에 "
        "물었으면 여러 개를 고르고, 하나만 물었으면 하나만 고르세요. 후보 밖의 이름은 "
        "절대 쓰지 마세요.",
    ]
    if last_agent is not None and last_agent in candidates:
        lines.append(
            f'참고: 직전 턴에 답변한 에이전트는 "{last_agent.value}"입니다. 사용자의 '
            '메시지가 새 주제를 지목하지 않는 순수 후속 질문(예: "그럼 ~된 건가요?", '
            '"그거 맞아요?")이면 보통 같은 에이전트가 이어서 답하는 것이 자연스럽습니다. '
            "다만 실제로 다른 주제(예: 상속 절차, 자산 정리 등)를 물었다면 그 주제에 "
            "맞는 에이전트를 고르세요."
        )
    lines += ["", "후보:"]
    for name in candidates:
        spec = specs[name]
        stub = (
            " (준비 중 — 사용자가 명시적으로 그 주제를 물었을 때만)"
            if spec.is_stub
            else ""
        )
        lines.append(f"- {name.value} [{spec.axis.value}]: {spec.description}{stub}")
        for utterance in spec.example_utterances[:3]:
            lines.append(f'    예) "{utterance}"')
    return "\n".join(lines)


def _llm_select(
    user_message: str,
    candidates: list[AgentName],
    *,
    last_agent: Optional[AgentName] = None,
) -> Optional[list[AgentName]]:
    """후보 중 필요한 에이전트를 LLM 이 고릅니다. 실패하면 None (호출부가 폴백)."""
    if not llm_enabled():
        return None
    try:
        from llm import claude

        tool = {
            "name": _CLASSIFY_TOOL_NAME,
            "description": "이번 답변에 필요한 에이전트 이름 목록을 고른다",
            "input_schema": {
                "type": "object",
                "properties": {
                    "agents": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [c.value for c in candidates],
                        },
                        "minItems": 1,
                    }
                },
                "required": ["agents"],
            },
        }
        result = claude.extract(
            system=_classify_prompt(candidates, last_agent=last_agent),
            user_text=user_message,
            tool=tool,
            max_tokens=1024,
            effort="low",
        )
    except Exception:  # noqa: BLE001 — LLMUnavailable 포함, 어떤 실패든 폴백
        if llm_required():
            raise
        logger.warning("라우팅 LLM 분류 실패 — 키워드 기반 폴백", exc_info=True)
        return None

    picked: list[AgentName] = []
    for raw in result.get("agents", []):
        try:
            name = AgentName(raw)
        except ValueError:
            continue
        if name in candidates and name not in picked:
            picked.append(name)
    return picked or None


#: 상담 축(온보딩 "상담 구분") → 키워드 후보가 없을 때 고를 기본 에이전트.
#: 대상이 등록 안 됐거나 껍데기(is_stub)면 default_agent 로 되돌린다.
_AXIS_DEFAULT_AGENT: dict[str, AgentName] = {
    "post_death": AgentName.HEIR_NAVIGATOR,
    "pre_need": AgentName.ASSET_ORGANIZER,
}


def _axis_default_agent(axis: Optional[str], default_agent: AgentName) -> AgentName:
    if axis is None:
        return default_agent
    target = _AXIS_DEFAULT_AGENT.get(axis)
    if target is None:
        return default_agent
    spec = registry.get_optional(target)
    if spec is None or spec.is_stub:
        return default_agent
    return target


def classify(
    user_message: str,
    *,
    pending_handoff: Optional[AgentName],
    pending_reply_agent: Optional[AgentName] = None,
    last_agent: Optional[AgentName],
    default_agent: AgentName,
    axis: Optional[str] = None,
) -> Plan:
    """이번 턴에 실행할 에이전트와 경로 등급을 정합니다 (계획의 층 구성은 build_plan).

    LLM-first: pending_handoff/pending_reply_agent 두 결정론적 경우가 아니면
    등록된 전체 에이전트(is_stub 제외) 중 LLM이 직접 고른다. axis(생전 준비 /
    사후 절차)는 하드 필터가 아니라 LLM 없이 폴백할 때만(키워드 후보가 하나도
    없을 때) 개입한다 — 직전 에이전트가 있으면 그 대화를 이어가고, 없으면
    axis에 맞는 기본 에이전트(사후→heir_navigator, 생전→asset_organizer)로
    시작한다.

    pending_reply_agent: 직전 턴 응답이 "사용자 답변을 기다리는 중"이었던
    에이전트(router._WAITING_NEXT_ACTIONS 참고 — 특정 에이전트 이름을
    하드코딩하지 않고 next_action 값 계약만 본다). LLM 판단보다 우선한다 —
    이미 자료를 요청해놓고 다음 턴에 그 답을 LLM이 다른 에이전트로 흘려보내면
    안 되기 때문. pending_handoff보다는 낮은 우선순위.
    """
    # (1) 직전 턴 핸드오프가 최우선 — 기존 라우터와 동일. Fast Path. LLM 미호출.
    if (
        pending_handoff is not None
        and registry.get_optional(pending_handoff) is not None
    ):
        return Plan(path=PATH_FAST, layers=[[pending_handoff]])

    # (2) 직전 턴에 답변을 기다리던 에이전트가 있으면 LLM 판단보다 우선한다.
    #     LLM 미호출.
    if (
        pending_reply_agent is not None
        and registry.get_optional(pending_reply_agent) is not None
    ):
        return Plan(path=PATH_STANDARD, layers=[[pending_reply_agent]])

    # (3) 그 외 전부 — LLM이 전체 eligible 후보를 보고 고른다(키워드 개수와
    #     무관). 키워드 매칭은 LLM 불가/실패 시 폴백 전용으로만 쓴다(아래).
    candidates = registry.match_keywords(user_message)
    eligible = _eligible_agents()
    selected = _llm_select(user_message, eligible, last_agent=last_agent)
    llm_used = selected is not None

    if selected is None:
        # ---- LLM 불가/실패 — 기존 키워드 기반 결정론적 폴백 그대로 ----
        if len(candidates) == 1:
            return Plan(path=PATH_STANDARD, layers=[[candidates[0]]])
        if not candidates:
            if last_agent is not None and registry.get_optional(last_agent) is not None:
                target = last_agent
            else:
                target = _axis_default_agent(axis, default_agent)
            if registry.get_optional(target) is None:
                target = default_agent
            return Plan(path=PATH_STANDARD, layers=[[target]])
        # 후보 2개 이상, LLM 못 씀 — 예전처럼 후보 전부 실행.
        selected = candidates

    if len(selected) == 1:
        # 하나로 좁혀졌으면 굳이 합성할 것이 없다 — Standard 로 내린다.
        return Plan(path=PATH_STANDARD, layers=[[selected[0]]], llm_used=llm_used)
    plan = build_plan(selected)
    plan.llm_used = llm_used
    return plan


# ---------------------------------------------------------------- build_plan


def build_plan(selected: list[AgentName]) -> Plan:
    """requires/produces 로 층을 나눕니다. 순환이면 남은 것을 한 층에 몰아넣습니다."""
    specs = registry.all_specs()
    producers: dict[str, set[AgentName]] = {}
    for name in selected:
        for produced in specs[name].produces:
            producers.setdefault(produced, set()).add(name)

    deps: dict[AgentName, set[AgentName]] = {}
    for name in selected:
        needed: set[AgentName] = set()
        for required in specs[name].requires:
            needed |= producers.get(required, set())
        needed.discard(name)
        deps[name] = needed

    layers: list[list[AgentName]] = []
    done: set[AgentName] = set()
    remaining = list(selected)
    while remaining:
        ready = [n for n in remaining if deps[n] <= done]
        if not ready:
            logger.warning(
                "에이전트 의존성에 순환이 있어 나머지를 한 층에 넣습니다: %s", remaining
            )
            ready = list(remaining)
        layers.append(ready)
        done |= set(ready)
        remaining = [n for n in remaining if n not in done]

    return Plan(path=PATH_FULL, layers=layers)


# -------------------------------------------------------------- execute_plan


@dataclass
class ExecutionResult:
    outputs: list[AgentOutput]  # 실행 순서(층 순, 층 안에서는 계획 순)
    inputs: dict[
        AgentName, AgentInput
    ]  # 각 에이전트가 실제로 받은 입력 (테스트/디버그)
    financial_profile: FinancialProfile
    will_status: Optional[WillStatus] = None


def _error_output(name: AgentName, exc: BaseException) -> AgentOutput:
    logger.exception("에이전트 %s 실행 실패", name.value, exc_info=exc)
    return AgentOutput(
        agent=name,
        reply="이 부분의 안내를 만드는 중에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
        next_action=None,
        data={"error": "agent_failed"},
    )


def execute_plan(
    plan: Plan,
    *,
    payload: AgentInput,
    family_graph: Optional[dict[str, Any]],
    financial_profile: FinancialProfile,
    stored_context_for: Callable[[AgentName], dict[str, Any]],
    runners: dict[AgentName, Callable[[AgentInput], AgentOutput]],
    will_status: Optional[WillStatus] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> ExecutionResult:
    """층 단위로 병렬 실행하고, 앞 층 결과를 다음 층 context 에 주입합니다.

    will_status 는 decedent_estate 가 같은 턴 앞 층에서 새로 판정하면 그 값이
    다음 층으로 전파됩니다(financial_profile 과 같은 방식).
    """
    outputs: list[AgentOutput] = []
    inputs: dict[AgentName, AgentInput] = {}
    upstream: dict[str, dict[str, Any]] = {}
    profile = financial_profile
    will = will_status

    for layer in plan.layers:
        layer_inputs: list[tuple[AgentName, AgentInput]] = []
        for name in layer:
            turn_context = dict(payload.context or {})
            # 앞 층 에이전트들의 네임스페이스 상태와 원문을 함께 넘긴다.
            for up_name, up in upstream.items():
                turn_context.setdefault(up_name, up["data"].get(up_name, {}))
            if upstream:
                turn_context[UPSTREAM_KEY] = {
                    k: {"reply": v["reply"], "data": v["data"]}
                    for k, v in upstream.items()
                }
            context = build_agent_context(name, stored_context_for(name), turn_context)
            agent_input = AgentInput(
                session_id=payload.session_id,
                user_message=payload.user_message,
                axis=payload.axis,
                family_graph=family_graph,
                family_graph_id=payload.family_graph_id,
                financial_profile=profile,
                will_status=will,
                history=list(history or []),
                context=context,
                # 이미지는 세션에 저장되지 않는다 — extract_state_to_persist가
                # output.data[agent.value]만 영속화하고, payload(이번 요청)는
                # 애초에 저장 경로에 들어가지 않는다. 그대로 통과만 시킨다
                # (라우터→플래너 재설계 이전에 orchestrator/router.py의
                # node_build_context에 있던 예외 그대로, 위치만 옮겨왔다 —
                # CLAUDE.md의 "router.py 절대 수정 금지" 원칙의 명시적 예외).
                image_base64=payload.image_base64,
                image_media_type=payload.image_media_type,
            )
            inputs[name] = agent_input
            layer_inputs.append((name, agent_input))

        def _run_one(item: tuple[AgentName, AgentInput]) -> AgentOutput:
            name, agent_input = item
            try:
                return runners[name](agent_input)
            except Exception as exc:  # noqa: BLE001
                return _error_output(name, exc)

        if len(layer_inputs) == 1:
            layer_outputs = [_run_one(layer_inputs[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(layer_inputs)) as pool:
                layer_outputs = list(pool.map(_run_one, layer_inputs))

        for output in layer_outputs:
            outputs.append(output)
            upstream[output.agent.value] = {"reply": output.reply, "data": output.data}
            if output.financial_profile is not None:
                profile = profile.merged_with(output.financial_profile)
            if output.will_status is not None and output.will_status.checked:
                will = (will or WillStatus()).merged_with(output.will_status)

    return ExecutionResult(
        outputs=outputs,
        inputs=inputs,
        financial_profile=profile,
        will_status=will,
    )

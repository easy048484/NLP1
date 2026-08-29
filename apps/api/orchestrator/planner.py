"""
분류(classify) · 계획(build_plan) · 실행(execute_plan) — 축 2, 축 3 (담당: 정민)

classify
--------
키워드 우선, 애매할 때만 LLM.

  등급           조건                                    처리
  Fast Path      직전 턴 핸드오프 대상이 있음             build_plan 생략, 그 에이전트 1개
  Standard Path  키워드 후보 0~1개                        후보 1개(없으면 직전 에이전트→기본)
  Full Pipeline  키워드 후보 2개 이상                     LLM 이 후보 중 실제 필요한 것만 고름
                                                          → DAG → 병렬/순차 → compose

LLM 을 못 쓰는 환경(ANTHROPIC_API_KEY 없음, 호출 실패, 거절)에서는 키워드 후보
전부를 그대로 계획에 넣습니다 — 개발 원칙 2 "항상 실행 가능".

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
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from schemas import AgentInput, AgentName, AgentOutput, FinancialProfile

from . import registry
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


def _llm_enabled() -> bool:
    flag = os.getenv("ORCHESTRATOR_USE_LLM", "auto").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


_CLASSIFY_TOOL_NAME = "select_agents"


def _classify_prompt(candidates: list[AgentName]) -> str:
    specs = registry.all_specs()
    lines = [
        "당신은 가족 자산·상속 상담 서비스의 라우터입니다. 사용자 메시지를 읽고 아래 "
        "후보 에이전트 중 이번 답변에 실제로 필요한 것만 고르세요. 여러 주제를 한 번에 "
        "물었으면 여러 개를 고르고, 하나만 물었으면 하나만 고르세요. 후보 밖의 이름은 "
        "절대 쓰지 마세요.",
        "",
        "후보:",
    ]
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
    user_message: str, candidates: list[AgentName]
) -> Optional[list[AgentName]]:
    """후보 중 필요한 에이전트를 LLM 이 고릅니다. 실패하면 None (호출부가 폴백)."""
    if not _llm_enabled():
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
            system=_classify_prompt(candidates),
            user_text=user_message,
            tool=tool,
            max_tokens=1024,
            effort="low",
        )
    except Exception:  # noqa: BLE001 — LLMUnavailable 포함, 어떤 실패든 폴백
        logger.warning("라우팅 LLM 분류 실패 — 키워드 후보 전부로 폴백", exc_info=True)
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


def classify(
    user_message: str,
    *,
    pending_handoff: Optional[AgentName],
    last_agent: Optional[AgentName],
    default_agent: AgentName,
) -> Plan:
    """이번 턴에 실행할 에이전트와 경로 등급을 정합니다 (계획의 층 구성은 build_plan)."""
    # (1) 직전 턴 핸드오프가 최우선 — 기존 라우터와 동일. Fast Path.
    if (
        pending_handoff is not None
        and registry.get_optional(pending_handoff) is not None
    ):
        return Plan(path=PATH_FAST, layers=[[pending_handoff]])

    candidates = registry.match_keywords(user_message)

    # (2) 키워드 후보 1개 → Standard. (3) 없으면 직전 에이전트 → (4) 기본.
    if len(candidates) == 1:
        return Plan(path=PATH_STANDARD, layers=[[candidates[0]]])
    if not candidates:
        target = last_agent if last_agent is not None else default_agent
        if registry.get_optional(target) is None:
            target = default_agent
        return Plan(path=PATH_STANDARD, layers=[[target]])

    # (5) 후보 2개 이상 → Full Pipeline. LLM 이 고르고, 못 고르면 전부.
    selected = _llm_select(user_message, candidates)
    llm_used = selected is not None
    if selected is None:
        selected = candidates
    if len(selected) == 1:
        # LLM 이 하나로 좁혔으면 굳이 합성할 것이 없다 — Standard 로 내린다.
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
) -> ExecutionResult:
    """층 단위로 병렬 실행하고, 앞 층 결과를 다음 층 context 에 주입합니다."""
    outputs: list[AgentOutput] = []
    inputs: dict[AgentName, AgentInput] = {}
    upstream: dict[str, dict[str, Any]] = {}
    profile = financial_profile

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
                family_graph=family_graph,
                family_graph_id=payload.family_graph_id,
                financial_profile=profile,
                context=context,
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

    return ExecutionResult(outputs=outputs, inputs=inputs, financial_profile=profile)

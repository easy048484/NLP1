"""
분류(classify) · 계획(build_plan) · 실행(execute_plan) — 축 2, 축 3 (담당: 정민)

classify
--------
LLM-first. 키워드는 게이트가 아니라 힌트입니다.

  LLM 사용 가능   전체 에이전트(is_stub 제외)를 후보로 LLM 이 고른다. 프롬프트에
                  직전 에이전트 · 직전 어시스턴트 발화(=직전 질문) · 핸드오프 예정 ·
                  키워드 힌트를 함께 넘기고, 직전 에이전트가 있으면 "__continue__"
                  (이어가기) 선택지를 준다. 1개 → Standard, 2개 이상 → build_plan(Full).
  LLM 사용 불가   _rule_classify — 이전 키워드 규칙 그대로:
                  Fast(핸드오프) → Standard(키워드 1개 / 없으면 직전→axis→기본) →
                  Full(키워드 2개 이상 전부).

왜 바꿨나: 키워드가 후보를 제한하던 구조에서는 (a) 키워드가 하나도 안 걸리면
LLM 이 호출조차 안 돼 직전 에이전트에 붙잡히고, (b) 진행 중인 질문에 답하는
발화("네, 은행 계좌 하나 있어요")가 다른 에이전트 키워드에 걸려 대화를 가로챘다.
LLM 이 후보 전체와 대화 상태를 보면 둘 다 구조적으로 사라진다.

LLM 을 못 쓰는 환경(ANTHROPIC_API_KEY 없음, 호출 실패, 거절)에서는 키워드 규칙으로
내려간다 — 개발 원칙 2 "항상 실행 가능".

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
from .llm_policy import llm_enabled, llm_required, router_model
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


#: LLM 라우터가 "직전 에이전트와의 대화를 이어간다"를 고를 때 쓰는 예약 이름.
#: AgentName 이 아니므로 registry 에 없고, _llm_route 가 last_agent 로 치환합니다.
CONTINUE = "__continue__"

_ROUTE_TOOL_NAME = "route_message"

#: 직전 어시스턴트 발화를 프롬프트에 넣을 때 남기는 최대 글자 수. 뒤쪽을 남깁니다
#: — 사용자에게 던진 질문은 보통 답변 끝에 있습니다.
_LAST_ASSISTANT_MAX_CHARS = 500

_AXIS_LABEL = {"pre_need": "생전 준비", "post_death": "사후 처리"}


def _catalog_lines(names: list[AgentName]) -> list[str]:
    """에이전트 카탈로그 — spec.py 의 axis / description / example_utterances 그대로."""
    specs = registry.all_specs()
    lines: list[str] = []
    for name in names:
        spec = specs[name]
        axis = _AXIS_LABEL.get(spec.axis.value, spec.axis.value)
        lines.append(f"- {name.value} [{axis}]: {spec.description}")
        for utterance in spec.example_utterances[:3]:
            lines.append(f'    예) "{utterance}"')
    return lines


def _route_system_prompt(candidates: list[AgentName], offer_continue: bool) -> str:
    """라우팅 LLM 시스템 프롬프트.

    대화 상태(직전 에이전트, 직전 질문 등)는 여기 넣지 않고 user 쪽으로 보냅니다
    — 요청마다 바뀌는 값을 빼야 이 프롬프트가 고정 접두사로 남아 캐시가 됩니다.
    """
    lines = [
        "당신은 가족 자산·상속 상담 서비스의 라우터입니다. 사용자의 이번 메시지에 "
        "어느 에이전트가 답해야 하는지 고르세요.",
        "",
        "에이전트:",
        *_catalog_lines(candidates),
        "",
        "판단 규칙:",
    ]
    if offer_continue:
        lines += [
            f'1. 사용자가 직전 어시스턴트의 질문에 답하고 있으면 "{CONTINUE}" 를 '
            "고르세요. 답변 안에 다른 에이전트의 주제 단어(계좌, 재산, 세금 등)가 "
            '섞여 있어도 마찬가지입니다 — "예금 계좌가 있나요?" 에 "네, 은행 계좌 하나 '
            '있어요" 라고 답한 것은 새 주제가 아니라 진행 중인 대화입니다. 진행 중인 '
            "대화를 끊지 않는 것이 최우선입니다.",
            "2. 사용자가 새 주제를 꺼냈으면 그 주제를 맡는 에이전트를 고르세요. 직전 "
            "에이전트와 같은 에이전트여도 이름을 그대로 고르면 됩니다.",
        ]
    else:
        lines += [
            "1. 사용자 메시지의 주제를 맡는 에이전트를 고르세요.",
            "2. 이어갈 직전 대화가 없는 새 대화입니다.",
        ]
    lines += [
        "3. 한 메시지에 서로 다른 주제가 여럿이면 여러 개를 고르고, 하나만 물었으면 "
        "하나만 고르세요.",
        '4. [핸드오프 예정] 이 있으면: 사용자가 그 흐름을 따라가는 답변("네 봐주세요", '
        '"알려주세요")이면 그 에이전트를 고르고, 다른 주제를 꺼냈으면 무시하세요.',
        "5. [키워드 힌트] 는 단순 문자열 매칭 결과라 오탐이 잦습니다. 참고만 하고 "
        "메시지의 뜻을 우선하세요.",
        "6. 목록에 없는 이름은 절대 쓰지 마세요.",
    ]
    return "\n".join(lines)


def _route_user_text(
    user_message: str,
    *,
    last_agent: Optional[AgentName],
    last_assistant_message: Optional[str],
    pending_handoff: Optional[AgentName],
    axis: Optional[str],
    keyword_hits: list[AgentName],
) -> str:
    """요청마다 바뀌는 대화 상태 + 사용자 메시지."""
    specs = registry.all_specs()
    lines = ["[대화 상태]"]
    lines.append(f"- 상담 구분: {_AXIS_LABEL.get(axis or '', '미지정')}")
    if last_agent is not None and last_agent in specs:
        lines.append(
            f"- 직전 에이전트: {last_agent.value} ({specs[last_agent].description})"
        )
    else:
        lines.append("- 직전 에이전트: 없음 (새 대화)")
    if last_assistant_message:
        tail = last_assistant_message[-_LAST_ASSISTANT_MAX_CHARS:]
        lines.append(f"- 직전 어시스턴트 발화: <<<{tail}>>>")
    else:
        lines.append("- 직전 어시스턴트 발화: 없음")
    if pending_handoff is not None and pending_handoff in specs:
        lines.append(f"- 핸드오프 예정: {pending_handoff.value}")
    if keyword_hits:
        lines.append(f"- 키워드 힌트: {', '.join(n.value for n in keyword_hits)}")
    lines += ["", "[사용자 메시지]", user_message]
    return "\n".join(lines)


def _last_assistant_message(
    history: Optional[list[dict[str, str]]],
) -> Optional[str]:
    """이력에서 마지막 assistant 발화 = 직전 턴에 사용자가 본 문장(질문 포함)."""
    for item in reversed(history or []):
        if item.get("role") == "assistant" and item.get("content"):
            return item["content"]
    return None


def _llm_route(
    user_message: str,
    *,
    last_agent: Optional[AgentName],
    pending_handoff: Optional[AgentName],
    last_assistant_message: Optional[str],
    axis: Optional[str],
    keyword_hits: list[AgentName],
) -> Optional[list[AgentName]]:
    """LLM 이 전체 에이전트 중 이번 턴에 필요한 것을 고릅니다. 못 쓰면 None.

    후보는 키워드와 무관하게 등록된 에이전트 전부(is_stub 제외)입니다. 직전
    에이전트가 있으면 CONTINUE 선택지를 함께 줘서 "이어가기 vs 전환"을 LLM 이
    직접 결정하게 합니다. 실패하면 None 을 돌려주고 호출부가 규칙 경로로
    폴백합니다 (required 모드면 예외를 그대로 올림).
    """
    if not llm_enabled():
        return None
    specs = registry.all_specs()
    candidates = [name for name, spec in specs.items() if not spec.is_stub]
    if not candidates:
        return None
    offer_continue = last_agent is not None and last_agent in candidates
    enum = [c.value for c in candidates] + ([CONTINUE] if offer_continue else [])
    tool = {
        "name": _ROUTE_TOOL_NAME,
        "description": "이번 사용자 메시지에 답할 에이전트를 고른다",
        "input_schema": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string", "enum": enum},
                    "minItems": 1,
                    "description": (
                        "답변을 맡을 에이전트 이름. 직전 질문에 답하는 중이면 "
                        f"{CONTINUE}"
                    ),
                },
                "reason": {"type": "string", "description": "한 문장 근거"},
            },
            "required": ["agents"],
        },
    }
    try:
        from llm import claude

        result = claude.extract(
            system=_route_system_prompt(candidates, offer_continue),
            user_text=_route_user_text(
                user_message,
                last_agent=last_agent,
                last_assistant_message=last_assistant_message,
                pending_handoff=pending_handoff,
                axis=axis,
                keyword_hits=keyword_hits,
            ),
            tool=tool,
            max_tokens=1024,
            effort="low",
            model=router_model(),
        )
    except Exception:  # noqa: BLE001 — LLMUnavailable 포함, 어떤 실패든 폴백
        if llm_required():
            raise
        logger.warning("라우팅 LLM 분류 실패 — 규칙 경로로 폴백", exc_info=True)
        return None

    picked: list[AgentName] = []
    for raw in result.get("agents", []):
        if raw == CONTINUE:
            name = last_agent if offer_continue else None
        else:
            try:
                name = AgentName(raw)
            except ValueError:
                name = None
        if name is None or name not in candidates or name in picked:
            continue
        picked.append(name)
    logger.debug(
        "라우팅 LLM: %r → %s (%s)",
        user_message[:60],
        [n.value for n in picked],
        result.get("reason", ""),
    )
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


def _rule_classify(
    candidates: list[AgentName],
    *,
    pending_handoff: Optional[AgentName],
    last_agent: Optional[AgentName],
    default_agent: AgentName,
    axis: Optional[str],
) -> Plan:
    """LLM 을 못 쓸 때의 규칙 경로 — LLM-first 이전의 키워드 라우팅 그대로.

    candidates 는 registry.match_keywords() 결과입니다.
    """
    # (1) 직전 턴 핸드오프가 최우선. Fast Path.
    if (
        pending_handoff is not None
        and registry.get_optional(pending_handoff) is not None
    ):
        return Plan(path=PATH_FAST, layers=[[pending_handoff]])

    # (2) 키워드 후보 1개 → Standard. (3) 없으면 직전 에이전트 → (4) axis 기본 → (5) 기본.
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

    # (6) 후보 2개 이상 → 전부 실행 (LLM 이 없으니 고를 수 없다).
    return build_plan(candidates)


def classify(
    user_message: str,
    *,
    pending_handoff: Optional[AgentName],
    last_agent: Optional[AgentName],
    default_agent: AgentName,
    axis: Optional[str] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> Plan:
    """이번 턴에 실행할 에이전트와 경로 등급을 정합니다 (계획의 층 구성은 build_plan).

    LLM 을 쓸 수 있으면 LLM 이 전체 에이전트를 놓고 고릅니다. 키워드 매칭 결과는
    프롬프트에 힌트로만 들어가고 후보를 제한하지 않습니다. pending_handoff 도
    강제 라우팅이 아니라 힌트입니다 — 사용자가 흐름을 따라가면 그 에이전트로,
    다른 주제를 꺼내면 새 주제를 따릅니다.

    LLM 을 못 쓰면(키 없음, 호출 실패, off) _rule_classify 의 키워드 규칙으로
    내려갑니다 — 개발 원칙 2 "항상 실행 가능".

    history 는 세션 이력(role/content dict 목록)입니다. 마지막 assistant 발화를
    "직전 질문"으로 LLM 에 넘겨, 사용자가 그 질문에 답하는 중인지("네, 은행 계좌
    하나 있어요") 새 주제를 꺼낸 건지 구분하게 합니다.
    """
    keyword_hits = registry.match_keywords(user_message)

    selected = _llm_route(
        user_message,
        last_agent=last_agent,
        pending_handoff=pending_handoff,
        last_assistant_message=_last_assistant_message(history),
        axis=axis,
        keyword_hits=keyword_hits,
    )
    if selected is not None:
        if len(selected) == 1:
            return Plan(path=PATH_STANDARD, layers=[[selected[0]]], llm_used=True)
        plan = build_plan(selected)
        plan.llm_used = True
        return plan

    return _rule_classify(
        keyword_hits,
        pending_handoff=pending_handoff,
        last_agent=last_agent,
        default_agent=default_agent,
        axis=axis,
    )


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

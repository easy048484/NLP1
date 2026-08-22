"""
에이전트 간 정보 교환 규약 (담당: 지원)

세 에이전트가 오케스트레이터와 주고받는 context/data의 "형태"를 여기 한 곳에
정의합니다. 새 에이전트를 만들거나 기존 에이전트를 고칠 때는 이 규약만
따르면, 오케스트레이터 쪽 코드를 전혀 몰라도 세션 상태에 자동으로 편입됩니다.

규약
----
1. 상태 네임스페이스: 에이전트는 자기 상태를 항상
   ``AgentInput.context[에이전트이름]`` 에서 읽고, ``AgentOutput.data[에이전트이름]``
   에 써서 돌려줍니다. 여기서 "에이전트이름"은 ``AgentName.value`` (예:
   ``"heir_navigator"``) 입니다. heir_navigator가 이미 이 규약을 따르고
   있습니다 — state.py의 ``STATE_KEY`` 패턴을 그대로 규약화한 것입니다.
2. 핸드오프 신호: 다른 에이전트로 넘겨야 하면 ``AgentOutput.next_action``에
   ``"handoff:<에이전트이름>"`` 형태의 문자열을 담습니다. 오케스트레이터는 이
   값을 보고 다음 턴을 어느 에이전트로 보낼지 결정합니다. 형식이 안 맞거나
   알 수 없는 에이전트 이름이면 조용히 무시하고 기존 라우팅(같은 에이전트
   유지 → 키워드 매칭 → 기본 에이전트)으로 폴백합니다 — 잘못된 next_action
   문자열 하나가 오케스트레이터를 죽이지 않습니다.

LEGACY_FLAT_CONTEXT_AGENTS (현재 비어 있음)
--------------------------------------------
한때 decedent_estate가 네임스페이스 규약 대신 context 최상위에 평면 필드
(will_type, intent, handwriting_answer 등)를 직접 쓰고 있어서, 그 차이를
흡수하는 호환 어댑터를 두었습니다. decedent_estate가 규약으로 옮겨오면서
(agents/decedent_estate/state.py) 이 집합은 비었고, 이제 세 에이전트 모두
동일하게 세션 상태를 주고받습니다.

집합과 분기를 지우지 않고 남겨둔 이유: 앞으로 새 에이전트를 붙일 때 규약
적용 전까지 임시로 이름을 넣어 쓸 수 있는 자리이기 때문입니다. 비어 있으면
아래 두 함수의 분기는 그냥 타지 않습니다.

참고 — 평면 키를 보내는 옛 클라이언트 호환은 이제 오케스트레이터가 아니라
decedent_estate 쪽(state.load_state)이 담당합니다. 그쪽에서 네임스페이스를
기본으로 삼되 이번 턴 평면 키가 있으면 우선 적용합니다.
"""

from __future__ import annotations

from typing import Any, Optional

from schemas import AgentName, AgentOutput

_HANDOFF_PREFIX = "handoff:"

#: 아직 네임스페이스 규약(1번)을 따르지 않는 에이전트 목록.
#: decedent_estate가 규약으로 옮겨오면서(agents/decedent_estate/state.py) 비었습니다.
#: 새 에이전트를 규약 적용 전에 임시로 붙일 일이 있으면 여기에 넣으세요.
LEGACY_FLAT_CONTEXT_AGENTS: set[AgentName] = set()


def parse_handoff(next_action: Optional[str]) -> Optional[AgentName]:
    """AgentOutput.next_action에서 핸드오프 대상 에이전트를 파싱합니다.

    "handoff:tax_calculator"처럼 알려진 에이전트 이름이면 그 AgentName을,
    그 외(None, 다른 형식의 next_action, 알 수 없는 이름)는 None을 돌려줍니다.
    """
    if not next_action or not next_action.startswith(_HANDOFF_PREFIX):
        return None
    target = next_action[len(_HANDOFF_PREFIX) :].strip()
    try:
        return AgentName(target)
    except ValueError:
        return None


def build_agent_context(
    agent: AgentName,
    stored_context: dict[str, Any],
    turn_context: dict[str, Any],
) -> dict[str, Any]:
    """agent.run()에 실제로 넘길 context를 만듭니다.

    stored_context: 세션에 저장된 이 에이전트의 "이전 턴 상태" (규약을 따르는
        에이전트라면 지난 턴 output.data[agent.value]와 동일한 평면 dict;
        LEGACY_FLAT_CONTEXT_AGENTS는 세션에 아무것도 저장하지 않으므로 항상 {}).
    turn_context: 이번 턴에 클라이언트가 보낸 context (요청 바디의 context
        그대로) — 사용자가 이번 턴에 명시적으로 답한 값이 우선합니다.
    """
    if agent in LEGACY_FLAT_CONTEXT_AGENTS:
        # 규약 미적용 에이전트: 클라이언트가 보낸 평면 context를 그대로 사용
        # (세션 상태는 관여하지 않습니다). 현재 이 집합은 비어 있습니다.
        return dict(turn_context)

    merged_turn = dict(turn_context)
    # 클라이언트가 이번 턴에 자기 네임스페이스로 명시적 override를 보냈으면
    # (드문 경우지만) 저장된 상태보다 우선한다.
    namespaced_override = merged_turn.pop(agent.value, {})
    agent_state = {**stored_context, **namespaced_override}
    merged_turn[agent.value] = agent_state
    return merged_turn


def extract_state_to_persist(agent: AgentName, output: AgentOutput) -> dict[str, Any]:
    """이번 턴 AgentOutput에서, 다음 턴을 위해 세션에 저장해둬야 할 context를 뽑습니다.

    규약을 따르는 에이전트는 output.data[에이전트이름]을 그대로 다음 턴 context로
    재사용합니다. LEGACY_FLAT_CONTEXT_AGENTS에 든 에이전트는 세션에 저장하지 않고
    매 턴 클라이언트가 보낸 context에 의존합니다 (현재 이 집합은 비어 있습니다).
    """
    if agent in LEGACY_FLAT_CONTEXT_AGENTS:
        return {}
    return dict(output.data.get(agent.value, {}))

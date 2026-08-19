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

decedent_estate 관련 임시 호환 처리
------------------------------------
decedent_estate는 아직 이 규약(1번, 네임스페이스)을 따르지 않고 context
최상위에 직접 필드(will_type, intent, handwriting_answer 등)를 저장·조회
합니다. 정호님이 decedent_estate를 규약에 맞게 옮기기 전까지, 오케스트레이터는
아래 호환 어댑터로 이 차이를 흡수합니다 — decedent_estate 자체 코드는 건드리지
않습니다. 이 어댑터가 하는 일은 단순합니다: LEGACY_FLAT_CONTEXT_AGENTS에
속한 에이전트는 세션에 상태를 저장하지 않고, 매 턴 클라이언트가 보낸
context를 그대로 흘려보냅니다 (지금 프론트/클라이언트가 이미 그렇게
동작한다고 가정하는 것과 동일 — 즉 이 어댑터를 넣기 전과 동작이 똑같습니다.
regression 없음).

decedent_estate가 규약에 맞게 옮겨지면, LEGACY_FLAT_CONTEXT_AGENTS에서
빼기만 하면 자동으로 다른 에이전트들과 동일하게 세션이 상태를 들고 있게
됩니다 — 오케스트레이터 코드를 더 고칠 필요가 없습니다.
"""

from __future__ import annotations

from typing import Any, Optional

from schemas import AgentName, AgentOutput

_HANDOFF_PREFIX = "handoff:"

#: 아직 네임스페이스 규약(1번)을 따르지 않는 에이전트 목록.
#: decedent_estate가 규약에 맞게 옮겨지면(개발 방향 계획 Phase 0 항목) 여기서
#: 빼면 됩니다.
LEGACY_FLAT_CONTEXT_AGENTS = {AgentName.DECEDENT_ESTATE}


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
        # decedent_estate: 클라이언트가 보낸 평면 context를 그대로 사용 (지금까지의
        # 동작과 동일 — 세션 상태는 관여하지 않습니다).
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
    재사용합니다. LEGACY_FLAT_CONTEXT_AGENTS는 지금 구조상 "다음 턴에 그대로
    되돌려줘야 하는 답변 필드"를 output.data가 다 담고 있지 않으므로(프론트가
    UI 상태로 들고 있다가 다시 보내주는 걸 전제로 설계됨), 여기서는 저장하지
    않고 매 턴 클라이언트가 보낸 context에 의존합니다 — 정호님이 네임스페이스
    규약으로 옮기면 이 분기를 없앨 수 있습니다.
    """
    if agent in LEGACY_FLAT_CONTEXT_AGENTS:
        return {}
    return dict(output.data.get(agent.value, {}))

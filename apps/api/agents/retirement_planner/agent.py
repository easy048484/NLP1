"""
은퇴자금 설계 에이전트 — 껍데기(stub)입니다.

라우터 → 플래너 재설계(docs/라우팅방식변경.md)에서 라우팅 후보로 먼저 등록해 둔
자리입니다. 담당 팀원은 이 파일의 run() 만 채우면 됩니다 — 오케스트레이터는
spec.py 의 선언만 보고 이 에이전트를 편입하므로 orchestrator/ 를 건드릴 필요가
없습니다. 구현 시 지켜야 할 규약은 orchestrator/handoff.py(네임스페이스 상태)와
orchestrator/registry.py(requires/produces) 참고.

공유 재무 상태(payload.financial_profile)는 이미 이 에이전트에 들어옵니다.
새로 알게 된 값은 AgentOutput.financial_profile 로 돌려주면 세션에 병합됩니다.
"""

from __future__ import annotations

from schemas import AgentInput, AgentName, AgentOutput

STATE_KEY = AgentName.RETIREMENT_PLANNER.value


def run(payload: AgentInput) -> AgentOutput:
    state = dict((payload.context or {}).get(STATE_KEY) or {})
    state["turns"] = int(state.get("turns", 0)) + 1
    return AgentOutput(
        agent=AgentName.RETIREMENT_PLANNER,
        reply=(
            "[은퇴자금 설계] 이 기능은 준비 중입니다. 곧 이곳에서 은퇴자금 설계 안내를 받으실 수 있어요."
        ),
        next_action=None,
        data={STATE_KEY: state, "stub": True},
    )

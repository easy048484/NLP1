"""
각 에이전트가 계약(run: AgentInput -> AgentOutput)을 지키는지 개별적으로 검증합니다.

오케스트레이터 라우팅과 무관하게, 담당자가 자기 폴더(agents/<name>/agent.py)의 로직을
mock에서 실제 구현으로 바꿀 때 이 테스트가 깨지면 병합 전에 바로 알 수 있어야 합니다.
새 에이전트 로직을 붙이는 팀원은 이 파일에 자기 케이스를 추가해주세요.
"""

import pytest

from agents import decedent_estate, heir_navigator, tax_calculator
from schemas import AgentInput, AgentName

_AGENTS = [
    (heir_navigator, AgentName.HEIR_NAVIGATOR),
    (decedent_estate, AgentName.DECEDENT_ESTATE),
    (tax_calculator, AgentName.TAX_CALCULATOR),
]


@pytest.mark.parametrize("module,expected_name", _AGENTS)
def test_agent_returns_contract_compliant_output(module, expected_name) -> None:
    payload = AgentInput(session_id="test", user_message="테스트 메시지")
    output = module.run(payload)

    assert output.agent == expected_name
    assert isinstance(output.reply, str) and output.reply != ""

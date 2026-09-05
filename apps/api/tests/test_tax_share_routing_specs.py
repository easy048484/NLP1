"""상속세·유류분 에이전트의 LLM 라우팅 명세 회귀 테스트."""

from orchestrator import planner, registry
from schemas import AgentAxis, AgentName


def test_tax_calculator_spec_covers_pre_need_and_post_death():
    spec = registry.get(AgentName.TAX_CALCULATOR)

    assert spec.axes == [AgentAxis.PRE_NEED, AgentAxis.POST_DEATH]
    assert "생전" in spec.description
    assert "사후" in spec.description
    assert "asset_organizer" in spec.description
    assert "heir_share_analyzer" in spec.description

    prompt = planner._classify_prompt([AgentName.TAX_CALCULATOR])
    assert "[pre_need, post_death]" in prompt
    assert "아버지가 돌아가셨고" in prompt
    assert "제가 살아 있을 때" in prompt
    assert "일괄공제와 배우자공제" in prompt


def test_heir_share_analyzer_spec_covers_pre_need_and_post_death():
    spec = registry.get(AgentName.HEIR_SHARE_ANALYZER)

    assert spec.axes == [AgentAxis.PRE_NEED, AgentAxis.POST_DEATH]
    assert "생전" in spec.description
    assert "사후" in spec.description
    assert "전문가 검토" in spec.description
    assert "tax_calculator" in spec.description

    prompt = planner._classify_prompt([AgentName.HEIR_SHARE_ANALYZER])
    assert "[pre_need, post_death]" in prompt
    assert "3년 전에 여동생에게 2억 원을 증여" in prompt
    assert "제가 살아 있을 때 유언장을 작성" in prompt
    assert "공동상속인이고 순상속재산" in prompt

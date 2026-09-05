"""
heir_navigator AgentSpec(spec.py) 명세 품질 테스트.

LLM-first 라우팅(orchestrator/planner._classify_prompt)은 description 과
example_utterances[:3] 만 보고 에이전트를 고르므로, 담당 범위·경계 문구가
프롬프트에 그대로 실리는지 검증한다 (test_asset_organizer_spec.py 와 같은 취지).
"""

from __future__ import annotations

from agents.heir_navigator.spec import SPEC
from orchestrator import planner
from schemas import AgentAxis, AgentName


def test_axes_is_post_death_only():
    assert SPEC.axes == [AgentAxis.POST_DEATH]


def test_description_covers_procedure_steps():
    """procedure/steps.py 의 절차 단계와 기한 계산이 담당 범위로 적혀 있어야 한다."""
    for term in (
        "사망신고",
        "안심상속",
        "유언장 존재 확인",
        "한정승인",
        "상속포기",
        "3개월",
        "상속재산분할협의",
        "상속등기",
        "취득세",
        "상속세 신고",
        "서류",
        "기관",
    ):
        assert term in SPEC.description, f"description에 '{term}'이 없음"


def test_description_states_boundaries():
    """guardrails.py 가 코드로 막는 '선택 추천 금지'와, 이웃 에이전트 4개의
    담당 영역이 명시돼야 LLM 이 경계를 지킨다."""
    description = SPEC.description
    assert "추천하지는 않" in description
    for agent in ("decedent_estate", "asset_organizer", "tax_calculator", "heir_share_analyzer"):
        assert agent in description, f"경계 문구에 '{agent}'가 없음"


def test_first_three_examples_cover_boundary_scenarios():
    """앞 3개 예시만 few-shot 으로 쓰인다 — 포괄 질문 / 빚+상속포기(asset_organizer
    경계) / 유언장 없음+절차(decedent_estate 경계)가 앞 3개에 있어야 한다."""
    head = SPEC.example_utterances[:3]
    assert any("뭐부터" in u for u in head)
    assert any("빚" in u and "상속포기" in u for u in head)
    assert any("유언장 없이" in u and "절차" in u for u in head)


def test_classify_prompt_carries_description_and_examples():
    prompt = planner._classify_prompt([AgentName.HEIR_NAVIGATOR])
    assert "- heir_navigator [post_death]:" in prompt
    assert "추천하지는 않" in prompt
    for utterance in SPEC.example_utterances[:3]:
        assert utterance in prompt
    for utterance in SPEC.example_utterances[3:]:
        assert utterance not in prompt

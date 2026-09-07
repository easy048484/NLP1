"""
decedent_estate AgentSpec(spec.py) 명세 품질 테스트.

LLM-first 라우팅(orchestrator/planner._classify_prompt)은 description 과
example_utterances[:3] 만 보고 에이전트를 고른다(test_asset_organizer_spec.py /
test_heir_navigator_spec.py 와 같은 취지). 실제 자연어 QA(2026-09-07)에서
"집을 다 뒤졌는데 유언장을 못 찾겠어요"류(유언장 부재/미발견)가 5회 연속
heir_navigator로 잘못 라우팅되는 걸 발견했다 — 원인은 example_utterances의
"유언장 없이 돌아가셨는데 절차가 어떻게 되나요?" 예시가 이미 있었지만 7번째
자리라 few-shot([:3])에 전혀 실리지 않았기 때문이다. 두 번째 자리를 그
계열로 옮긴 뒤 이 회귀가 조용히 되돌아가지 않도록 고정한다.
"""

from __future__ import annotations

from agents.decedent_estate.spec import SPEC
from orchestrator import planner
from schemas import AgentName


def test_first_three_examples_cover_no_will_case():
    """few-shot에 실제로 쓰이는 앞 3자리에 유언장 부재/미발견 표현이 있어야
    한다 — 뒤쪽(4번째 이후)에만 있으면 planner._classify_prompt()가 아예
    보지 못한다."""
    head = SPEC.example_utterances[:3]
    assert any("못 찾겠" in u or "없이 돌아가" in u for u in head), (
        "example_utterances[:3]에 유언장 부재/미발견 계열 예시가 없음 — "
        f"현재 앞 3개: {head}"
    )


def test_first_three_examples_still_cover_no_keyword_and_prepare_cases():
    """이번 수정으로 기존에 확보돼 있던 다른 두 커버리지(유언/유언장 키워드
    없이도 알아채는 경우, prepare 모드)가 밀려나지 않았는지 확인한다."""
    head = SPEC.example_utterances[:3]
    assert any("효력이 있는지" in u and "유언" not in u for u in head)
    assert any("형식 요건" in u for u in head)


def test_classify_prompt_surfaces_no_will_example():
    """_classify_prompt()가 실제로 만드는 LLM 프롬프트 문자열에 no-will 예시
    문구가 그대로 실리는지 확인한다(간접 테스트 — LLM 최종 선택 자체는
    outside scope)."""
    prompt = planner._classify_prompt([AgentName.DECEDENT_ESTATE])

    for utterance in SPEC.example_utterances[:3]:
        assert utterance in prompt

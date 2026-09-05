"""
asset_organizer AgentSpec(spec.py) 명세 품질 테스트.

팀 전체가 키워드 의존 라우팅에서 LLM 기반(name/description/example_utterances)
라우팅으로 전환 중이라, 이 파일은 asset_organizer의 description/
example_utterances가 LLM 라우터(orchestrator/planner._classify_prompt)에게
"무엇을 하는지"뿐 아니라 "무엇을 안 하는지"까지 명확히 전달하는지 확인한다.

orchestrator/planner/registry 코드 자체는 건드리지 않았다 — 여기서는
실제 _classify_prompt()가 만드는 프롬프트 문자열에 이 명세가 그대로
반영되는지만 검증한다. keywords는 하위호환용으로 그대로 유지했으므로
기존 라우팅 정밀도 회귀는 test_asset_organizer_routing_precision.py가
계속 담당한다.
"""

from __future__ import annotations

from agents.asset_organizer.spec import SPEC
from orchestrator import planner
from schemas import AgentName


def test_description_covers_in_scope_categories():
    """자산·부채 세부 유형(예금·주식·펀드·부동산·자동차·퇴직연금·보험·대출)과
    상태(존재·부재, 확인된 금액, 금액 미확인)와 안심상속 조회 결과, 그리고
    검토·수정·확정까지가 담당 범위임이 description 문자열에 그대로
    있어야 한다 — LLM이 이 문구만 보고 담당 여부를 판단한다."""
    description = SPEC.description
    for term in (
        "예금",
        "주식",
        "펀드",
        "부동산",
        "자동차",
        "퇴직연금",
        "보험",
        "대출",
        "존재",
        "부재",
        "확인된 금액",
        "금액 미확인",
        "안심상속",
        "검토",
        "수정",
        "확정",
    ):
        assert term in description, f"description에 '{term}'이 없음"


def test_description_excludes_out_of_scope_topics():
    """상속포기·한정승인·상속 절차 판단, 유언 효력, 상속분 계산, 상속세
    계산은 명시적으로 "담당하지 않는다"고 밝혀야 한다 — 이 경계 문구가
    없으면 LLM이 "재산이 얼마나 있어야 상속포기가 유리한가요?" 같은
    절차 상담에도 asset_organizer를 고를 위험이 있다."""
    description = SPEC.description
    assert "담당하지 않는다" in description
    for term in ("상속포기", "한정승인", "유언 효력", "상속분 계산", "상속세 계산"):
        assert term in description, f"담당 제외 문구에 '{term}'이 없음"


def test_first_three_examples_cover_pre_need_post_death_disclosure():
    """_classify_prompt()는 example_utterances[:3]만 few-shot으로 쓴다 —
    이 자리는 반드시 생전/사후/안심상속 세 대표 시나리오여야 한다."""
    assert SPEC.example_utterances[:3] == [
        "내 재산이랑 빚이 뭐가 있는지 한 번 정리해보고 싶어요.",
        "어머니가 돌아가셔서 재산이랑 빚을 정리해두려고 해요.",
        "안심상속 조회 결과 예금 8천만원, 아파트 5억, 증권은 계좌만 확인됐고 대출 2천만원이에요.",
    ]


def test_supplementary_examples_cover_absence_and_unknown_amount():
    """보조 예시는 "없어요"(부재)와 "아직 몰라요"(금액 미확인) 표현까지
    담당 범위임을 보여줘야 한다."""
    remaining = SPEC.example_utterances[3:]
    assert "예금 6500만원, 펀드 1200만원 있고 주식이랑 대출은 없어요." in remaining
    assert "증권 계좌가 있다는 건 확인됐는데 잔액은 아직 몰라요." in remaining


def test_keywords_left_untouched_for_backward_compatibility():
    """중앙 LLM 라우터 전환이 끝나기 전까지 기존 keywords는 하위호환용으로
    그대로 유지해야 한다 — 이번 작업은 description/example_utterances만
    다듬는 것이라 keywords 목록 자체(그리고 "빚"/"채무"/"정리" 관련 기존
    제거 결정)는 손대지 않았다."""
    assert "정리" not in SPEC.keywords
    assert "빚" not in SPEC.keywords
    assert "채무" not in SPEC.keywords
    assert "안심상속" in SPEC.keywords
    assert "자산" in SPEC.keywords


def test_classify_prompt_surfaces_new_description_and_first_three_examples():
    """orchestrator/planner._classify_prompt()가 실제로 만드는 LLM
    프롬프트 문자열에 새 description과 앞 3개 예시가 그대로 들어가는지
    확인한다 — orchestrator 코드는 건드리지 않았고, spec.py 쪽 변경이
    실제 라우팅 프롬프트에 반영되는지만 검증."""
    prompt = planner._classify_prompt(
        [AgentName.ASSET_ORGANIZER, AgentName.HEIR_NAVIGATOR]
    )

    assert SPEC.description in prompt
    for utterance in SPEC.example_utterances[:3]:
        assert utterance in prompt
    # [:3] 밖의 보조 예시는 few-shot에 실리지 않는다 — 그대로임을 확인.
    for utterance in SPEC.example_utterances[3:]:
        assert utterance not in prompt

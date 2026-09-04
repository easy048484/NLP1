"""
asset_organizer 라우팅 정밀도 튜닝 회귀 테스트.

배경: 실제 재산·부채 목록화가 필요한 사용자에게는 잘 켜지되, 상속포기
여부·절차 안내처럼 다른 목적의 상담에는 과도하게 끼어들지 않도록
spec.py의 keywords/description/example_utterances를 조정했다(orchestrator
코드 자체는 건드리지 않음).

실측 재현된 문제: keywords의 "정리"가 너무 일반적인 동사라 "상속 절차를
정리해 주세요"처럼 재산 목록화와 전혀 무관한 절차 상담 문장에도
asset_organizer를 후보로 잘못 끼워 넣었다(routing false positive) —
"정리"를 제거하고 "자산"/"재산" 등 구체적인 키워드만 남겼다.

사후 모드 명시적 진입을 위해 "안심상속" 키워드를 추가했다.

후속 실측 재현(2차): generic "빚"/"채무" 키워드도 같은 클래스의 문제였다
— "빚이 많을 것 같은데 상속포기해야 하나요?", "채무가 많아서 한정승인을
해야 하나요?"처럼 재산 목록화가 아니라 상속포기·한정승인 절차 판단을
묻는 문장에도 asset_organizer가 후보로 남았고, production에서 LLM도
걸러내지 못해 실제로 실행까지 됐다(불필요한 실행 확인됨). "빚"/"채무"를
제거하고 대신 재산·부채 확인·파악 의도가 문구 자체에 명확한 구체 표현
("빚부터 파악", "빚이 얼마" 등)만 남겼다 — 막연히 "빚이 많다"는 더 이상
후보가 아니고, "빚부터 파악하고 싶다"는 여전히 후보다.
"""

from __future__ import annotations

import pytest

from orchestrator import registry, router
from orchestrator.session_store import InMemorySessionStore
from schemas import AgentInput, AgentName


@pytest.fixture(autouse=True)
def _fresh_session_store(monkeypatch):
    monkeypatch.setattr(router, "default_store", InMemorySessionStore())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --------------------------------------------------- "정리" 제거 회귀 방지


@pytest.mark.parametrize(
    "message",
    [
        "상속 절차를 정리해 주세요",
        "정리해 주세요",
        "이 내용 좀 정리해줄래요",
    ],
)
def test_generic_jeongni_alone_no_longer_matches_asset_organizer(message):
    """실측 재현된 routing false positive: "정리"는 너무 일반적인 동사라
    재산 목록화와 무관한 문장에도 asset_organizer를 후보로 끼워 넣었다.
    "자산"/"재산" 등 구체적인 키워드가 없는 순수 "정리" 문구는 더 이상
    후보가 아니어야 한다."""
    assert AgentName.ASSET_ORGANIZER not in registry.match_keywords(message)


def test_procedure_only_message_routes_to_heir_navigator_alone():
    """ "상속 절차를 정리해 주세요"는 heir_navigator 단독 후보로 정리돼야
    한다 — asset_organizer가 끼어들면 안 된다(회귀 방지)."""
    output = router.route(
        AgentInput(session_id="prec-r1", user_message="상속 절차를 정리해 주세요")
    )
    assert output.agent == AgentName.HEIR_NAVIGATOR
    agents = [c.agent for c in output.contributions]
    assert AgentName.ASSET_ORGANIZER not in agents


def test_asset_jeongni_without_generic_word_still_matches():
    """ "자산"/"재산" 같은 구체적인 키워드가 있으면 "정리" 없이도(또는
    있어도) 여전히 정상적으로 후보가 된다 — "정리" 제거가 정상 진입
    문장까지 막으면 안 된다."""
    assert AgentName.ASSET_ORGANIZER in registry.match_keywords("자산 정리하고 싶어요")
    assert AgentName.ASSET_ORGANIZER in registry.match_keywords(
        "가진 재산과 부채가 뭐가 있는지 한 번 정리하고 싶어요"
    )


def test_asset_tile_prompt_routes_to_asset_organizer_alone():
    """FunctionRail의 생전 "자산 정리" 타일 프롬프트는 여전히
    asset_organizer 단독 후보다(회귀 방지)."""
    output = router.route(
        AgentInput(
            session_id="prec-r2",
            user_message="자산 정리하고 싶어요",
        )
    )
    assert output.agent == AgentName.ASSET_ORGANIZER
    assert [c.agent for c in output.contributions] == [AgentName.ASSET_ORGANIZER]


# ------------------------------------------------------------- "안심상속" 추가


def test_ansim_sangsok_word_alone_triggers_candidacy():
    """구체적인 기관·금액 없이 "안심상속"이라는 단어만으로도 사후 모드
    진입 후보가 돼야 한다."""
    assert AgentName.ASSET_ORGANIZER in registry.match_keywords(
        "안심상속 조회 결과를 정리하고 싶어요"
    )


def test_post_death_disclosure_message_routes_to_asset_organizer_alone():
    """실제 안심상속 조회결과 문장(기관·금액 포함)은 여전히 asset_organizer
    단독 후보로 정상 라우팅된다(회귀 방지)."""
    output = router.route(
        AgentInput(
            session_id="prec-r3",
            user_message="안심상속 조회 결과 예금은 8천만원이고 증권은 계좌만 확인됐어요",
            axis="post_death",
        )
    )
    assert output.agent == AgentName.ASSET_ORGANIZER
    assert [c.agent for c in output.contributions] == [AgentName.ASSET_ORGANIZER]


# --------------------------------------------- 다중 후보 시나리오 (키워드 단계)


def test_asset_plus_tax_message_keeps_both_as_candidates():
    """ "재산부터 정리하고 상속세도 계산하고 싶어요"는 asset_organizer와
    tax_calculator 둘 다 후보여야 한다(둘 다 실제로 필요한 의도) —
    LLM 없는 환경에서는 둘 다 실행(concat)된다."""
    output = router.route(
        AgentInput(
            session_id="prec-r4",
            user_message="아버지 재산부터 정리하고 상속세도 계산하고 싶어요",
            axis="post_death",
        )
    )
    agents = {c.agent for c in output.contributions}
    assert agents == {AgentName.ASSET_ORGANIZER, AgentName.TAX_CALCULATOR}


def test_renunciation_question_no_longer_matches_asset_organizer():
    """실측 재현된 후속 버그: 이전엔 generic "빚" 키워드 때문에
    "빚이 많을 것 같은데 상속포기해야 하나요?"에 asset_organizer가
    후보로 남아 production에서 LLM도 걸러내지 못하고 실제 실행까지
    됐다(재산 목록화가 아니라 상속포기 절차 판단을 묻는 문장인데도).
    "빚"을 의도가 명확한 구체 표현("빚부터 파악" 등)으로 좁힌 뒤로는
    이 문장이 asset_organizer 후보에서 완전히 빠지고 heir_navigator
    단독 후보가 돼야 한다."""
    hits = registry.match_keywords("빚이 많을 것 같은데 상속포기해야 하나요?")
    assert hits == [AgentName.HEIR_NAVIGATOR]


def test_limited_approval_question_no_longer_matches_asset_organizer():
    """같은 클래스의 버그가 "채무"에도 있었다 — "채무가 많아서 한정승인을
    해야 하나요?"도 이제 asset_organizer 후보에서 빠지고 heir_navigator
    단독이어야 한다."""
    hits = registry.match_keywords("채무가 많아서 한정승인을 해야 하나요?")
    assert hits == [AgentName.HEIR_NAVIGATOR]


@pytest.mark.parametrize(
    "message",
    [
        "돌아가신 아버지 빚부터 파악하고 싶어요",
        "고인에게 빚이 얼마나 있는지 정리하고 싶어요",
    ],
)
def test_debt_inventory_intent_phrases_still_match_asset_organizer(message):
    """ "빚"을 의도가 명확한 구체 표현으로 좁혔지만, 실제 재산·부채
    목록화 의도가 담긴 문장("빚부터 파악", "빚이 얼마나")까지 막으면
    안 된다 — asset_organizer가 여전히 후보여야 한다."""
    assert AgentName.ASSET_ORGANIZER in registry.match_keywords(message)


def test_renunciation_question_routes_to_heir_navigator_alone():
    """실제 route()로도 확인: 위 두 절차 판단 문장은 asset_organizer가
    전혀 실행되지 않고 heir_navigator 단독으로 처리돼야 한다."""
    for msg in (
        "빚이 많을 것 같은데 상속포기해야 하나요?",
        "채무가 많아서 한정승인을 해야 하나요?",
    ):
        output = router.route(
            AgentInput(
                session_id=f"prec-r5-{hash(msg)}",
                user_message=msg,
                axis="post_death",
            )
        )
        assert output.agent == AgentName.HEIR_NAVIGATOR
        assert [c.agent for c in output.contributions] == [AgentName.HEIR_NAVIGATOR]

"""상속인 절차 내비게이터 (담당: 정민)

구조: 결정론적 절차 엔진 + LLM 껍데기.

    사용자 발화 → [Claude: 슬롯 추출] → [순수 Python: 절차 엔진] → [Claude: 서술]
                                              ↑ 날짜·서류·기관은 전부 여기서만 나옴

기한과 서류 목록을 LLM이 생성하게 두면, 경계를 지키기 이전에 사실이 틀립니다.
그래서 LLM은 입구(슬롯 추출)와 출구(쉬운 말로 풀기)에만 씁니다.

상태는 AgentInput.context / AgentOutput.data의 "heir_navigator" 키로 왕복시킵니다.
세션 저장소가 생기면 state.load_state / dump_state만 갈아끼우면 됩니다.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

from schemas import AgentInput, AgentName, AgentOutput

from .graph import TRIGGER_KEYWORDS, compiled
from .state import STATE_KEY, dump_state, load_state

logger = logging.getLogger(__name__)

__all__ = ["run", "TRIGGER_KEYWORDS"]


def _use_llm() -> bool:
    """LLM을 쓸지. 키가 없으면 규칙 기반 + 결정론적 렌더러로 끝까지 동작합니다."""
    if os.getenv("HEIR_NAVIGATOR_DISABLE_LLM", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return False
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def _today(payload: AgentInput) -> date:
    """오늘 날짜. 테스트에서 context로 고정할 수 있게 열어둡니다."""
    raw = (payload.context or {}).get("today")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def run(payload: AgentInput) -> AgentOutput:
    state = load_state(payload.context)
    graph_input: dict[str, Any] = {
        "user_message": payload.user_message,
        "family_graph": payload.family_graph,
        "session_id": payload.session_id,
        "today": _today(payload),
        "use_llm": _use_llm(),
        "heir": state,
        "data": {},
    }

    try:
        result = compiled().invoke(graph_input)
    except Exception:
        logger.exception("heir_navigator 그래프 실행 실패")
        return AgentOutput(
            agent=AgentName.HEIR_NAVIGATOR,
            reply=(
                "안내를 만드는 중에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.\n\n"
                "급한 기한이 걱정되신다면, 한정승인·상속포기는 상속개시를 안 날부터 "
                "3개월, 상속세 신고는 사망일이 속한 달의 말일부터 6개월이 기준입니다."
            ),
            next_action=None,
            data={"error": "graph_failed"},
        )

    data = dict(result.get("data") or {})
    data[STATE_KEY] = dump_state(result["heir"])

    return AgentOutput(
        agent=AgentName.HEIR_NAVIGATOR,
        reply=result.get("reply") or "무엇을 도와드릴까요?",
        next_action=result.get("next_action"),
        data=data,
    )

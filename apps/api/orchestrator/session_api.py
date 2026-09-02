"""세션 이어보기 HTTP 엔드포인트 (담당: 정민).

⚠️ 같은 패키지의 router.py 와 헷갈리지 마세요. router.py 는 한 턴을 처리하는
LangGraph 파이프라인이고, 이 파일은 FastAPI 라우터입니다.

왜 필요한가
-----------
로그아웃하면 클라이언트가 session_id 를 버립니다(scopedStorage.clearAllScopedKeys).
서버에는 그 세션이 30일 동안 그대로 남아 있는데 아무도 그걸 가리키지 않으니,
다시 로그인해도 대화가 처음부터 시작됐습니다 — 가족관계는
GET /family-graph/mine 으로 되찾아지는데 대화 맥락(사망일, 확정된 슬롯, 이력)만
유실되는 비대칭이 있었습니다.

이 엔드포인트가 그 비대칭을 없앱니다. family_graph 의 /family-graph/mine 과
정확히 같은 역할입니다.

로그인한 사용자만 쓸 수 있습니다 — 비로그인 세션은 애초에 "떠나면 남지 않는"
것이 원칙이라 되찾을 대상이 아닙니다.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import User, get_current_user

from .router import current_session_store

router = APIRouter(prefix="/sessions", tags=["sessions"])

_NOT_FOUND = HTTPException(status_code=404, detail="이어볼 대화가 없습니다.")


class ConversationTurn(BaseModel):
    role: str = Field(description='"user" 또는 "assistant"')
    content: str


class LatestSessionOut(BaseModel):
    """재로그인 직후 대화를 이어붙이는 데 필요한 최소 정보."""

    session_id: str = Field(
        description=(
            "이 값을 그대로 다음 /chat 요청의 session_id 로 쓰면 서버에 남아 있던 "
            "슬롯·재산정보·대화 이력을 그대로 이어씁니다."
        )
    )
    family_graph_id: Optional[str] = Field(
        default=None, description="이 세션이 보고 있던 가족관계 그래프."
    )
    history: list[ConversationTurn] = Field(
        default_factory=list,
        description=(
            "지난 대화 원문(시간순). 화면에 이전 대화를 다시 그려주는 용도입니다. "
            "에이전트 카드·계획표 같은 구조화된 응답은 저장하지 않으므로 텍스트만 "
            "돌아옵니다 — 다시 실행한 결과가 아니라 지나간 기록입니다."
        ),
    )


@router.get("/mine", response_model=LatestSessionOut)
def read_my_latest_session(
    user: User = Depends(get_current_user),
) -> LatestSessionOut:
    """내 가장 최근 대화 세션. 없으면 404."""
    found = current_session_store().latest_for_user(user.id)
    if found is None:
        raise _NOT_FOUND

    session_id, state = found
    return LatestSessionOut(
        session_id=session_id,
        family_graph_id=state.family_graph_id,
        history=[ConversationTurn(**turn) for turn in state.history],
    )

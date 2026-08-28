"""family_graph API의 요청/응답 스키마 (pydantic). AgentInput/AgentOutput과는
별개입니다 — 이건 프론트가 가족 구성원을 등록/조회할 때 쓰는 REST 계약입니다."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import RelationType


class FamilyMemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    relation: RelationType
    is_alive: bool = True
    is_minor: bool = False


class FamilyMemberPatch(BaseModel):
    """구성원 부분 수정 요청. 보낸 필드만 갱신합니다(예: 이름만 고치거나
    is_minor만 바꾸는 경우 나머지 필드를 다시 안 보내도 됨).

    최소 1개 필드는 있어야 합니다 — 전부 비어 있으면 아무 것도 바뀌지
    않는 요청이라 프론트 실수를 조기에 알아차리게 400으로 거절합니다
    (router.py 참고).
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    relation: Optional[RelationType] = None
    is_alive: Optional[bool] = None
    is_minor: Optional[bool] = None


class FamilyMemberOut(BaseModel):
    id: int
    name: str
    relation: RelationType
    is_alive: bool
    is_minor: bool

    model_config = {"from_attributes": True}


class FamilyGraphOut(BaseModel):
    id: str
    created_at: datetime
    members: list[FamilyMemberOut]

    model_config = {"from_attributes": True}

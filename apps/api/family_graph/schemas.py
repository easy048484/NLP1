"""family_graph API의 요청/응답 스키마 (pydantic). AgentInput/AgentOutput과는
별개입니다 — 이건 프론트가 가족 구성원을 등록/조회할 때 쓰는 REST 계약입니다."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .models import RelationType


class FamilyMemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    relation: RelationType
    is_alive: bool = True
    is_minor: bool = False


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

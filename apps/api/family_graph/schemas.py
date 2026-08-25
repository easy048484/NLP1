"""family_graph API의 요청/응답 스키마 (pydantic). AgentInput/AgentOutput과는
별개입니다 — 이건 프론트가 가족 트리를 저장/조회할 때 쓰는 REST 계약입니다.

트리는 통째로 저장합니다(부분 수정 없음). 프론트의 온보딩/수정 화면이 항상
완성된 트리를 들고 있으므로, 저장은 "이 트리로 교체"라는 단일 연산이면
충분하고, 검증(피상속인 정확히 1명 등)도 트리 전체를 놓고 한 번에 할 수
있습니다.

persons의 `key`는 클라이언트가 붙이는 임시 식별자입니다 — 아직 DB id가 없는
새 노드들 사이의 엣지를 표현하기 위한 것으로, 저장 시 서버 id로 치환되고
저장되지는 않습니다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from .models import RelationEdgeType


class PersonIn(BaseModel):
    #: 이 요청 안에서만 유효한 임시 식별자 (relations가 참조)
    key: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    is_decedent: bool = False
    is_alive: bool = True
    is_minor: bool = False
    death_date: Optional[date] = None
    birth_date: Optional[date] = None


class RelationIn(BaseModel):
    type: RelationEdgeType
    #: PARENT_OF면 from이 부모, SPOUSE_OF면 방향 무의미
    from_key: str
    to_key: str


class FamilyTreeIn(BaseModel):
    persons: list[PersonIn] = Field(min_length=1)
    relations: list[RelationIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_tree(self) -> "FamilyTreeIn":
        keys = [p.key for p in self.persons]
        if len(keys) != len(set(keys)):
            raise ValueError("persons의 key가 중복됩니다.")

        decedents = [p for p in self.persons if p.is_decedent]
        if len(decedents) != 1:
            raise ValueError("is_decedent=true인 사람이 정확히 1명이어야 합니다.")

        key_set = set(keys)
        decedent_key = decedents[0].key
        decedent_spouses = 0
        for rel in self.relations:
            if rel.from_key not in key_set or rel.to_key not in key_set:
                raise ValueError(
                    f"relations가 존재하지 않는 key를 참조합니다: "
                    f"{rel.from_key} -> {rel.to_key}"
                )
            if rel.from_key == rel.to_key:
                raise ValueError("자기 자신과의 관계는 만들 수 없습니다.")
            if rel.type is RelationEdgeType.SPOUSE_OF and decedent_key in (
                rel.from_key,
                rel.to_key,
            ):
                decedent_spouses += 1
        if decedent_spouses > 1:
            # 법률혼 배우자는 1명입니다. 재혼 이력 등 복수 혼인 관계 표현은
            # 판정 엔진과 함께 다음 단계에서 다룹니다.
            raise ValueError("피상속인의 배우자 관계는 최대 1개여야 합니다.")
        return self


class PersonOut(BaseModel):
    id: int
    name: str
    is_decedent: bool
    is_alive: bool
    is_minor: bool
    death_date: Optional[date] = None
    birth_date: Optional[date] = None

    model_config = {"from_attributes": True}


class RelationOut(BaseModel):
    id: int
    type: RelationEdgeType
    from_person_id: int
    to_person_id: int

    model_config = {"from_attributes": True}


class FamilyTreeOut(BaseModel):
    id: str
    created_at: datetime
    persons: list[PersonOut]
    relations: list[RelationOut]

    model_config = {"from_attributes": True}

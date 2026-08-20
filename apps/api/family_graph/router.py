"""family_graph REST API (담당: 지원). 프론트가 가족 구성원을 등록/조회할 때 씁니다.

이 라우터가 다루는 건 "가족관계 데이터 자체"의 CRUD뿐입니다. 오케스트레이터가
family_graph_id로 이 데이터를 읽어 AgentInput.family_graph를 채우는 부분은
repository.get_heirs_dict()가 담당하고, 이 라우터와는 별개 경로입니다.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.base import DatabaseNotConfigured, get_engine, session_scope

from . import repository
from .schemas import FamilyGraphOut, FamilyMemberIn, FamilyMemberOut

router = APIRouter(prefix="/family-graph", tags=["family-graph"])


def get_db() -> Iterator[Session]:
    try:
        get_engine()
    except DatabaseNotConfigured as exc:
        raise HTTPException(
            status_code=503, detail="DATABASE_URL이 설정돼 있지 않습니다."
        ) from exc
    with session_scope() as db:
        yield db


@router.post("", response_model=FamilyGraphOut, status_code=201)
def create_family_graph(db: Session = Depends(get_db)) -> repository.FamilyGraph:
    return repository.create_family_graph(db)


@router.get("/{family_graph_id}", response_model=FamilyGraphOut)
def read_family_graph(
    family_graph_id: str, db: Session = Depends(get_db)
) -> repository.FamilyGraph:
    graph = db.get(repository.FamilyGraph, family_graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="family_graph를 찾을 수 없습니다.")
    return graph


@router.post(
    "/{family_graph_id}/members", response_model=FamilyMemberOut, status_code=201
)
def add_family_member(
    family_graph_id: str, payload: FamilyMemberIn, db: Session = Depends(get_db)
) -> repository.FamilyMember:
    graph = db.get(repository.FamilyGraph, family_graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="family_graph를 찾을 수 없습니다.")
    return repository.add_member(
        db,
        family_graph_id,
        name=payload.name,
        relation=payload.relation,
        is_alive=payload.is_alive,
        is_minor=payload.is_minor,
    )

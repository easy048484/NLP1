"""family_graph REST API (담당: 지원). 프론트가 가족 구성원을 등록/조회할 때 씁니다.

이 라우터가 다루는 건 "가족관계 데이터 자체"의 CRUD뿐입니다. 오케스트레이터가
family_graph_id로 이 데이터를 읽어 AgentInput.family_graph를 채우는 부분은
repository.get_heirs_dict()가 담당하고, 이 라우터와는 별개 경로입니다.

보안 모델
--------
가족관계는 민감한 개인정보라 계정에 묶습니다.

- **로그인한 사용자**가 `POST /family-graph` 로 만든 그래프는 `user_id` 가
  채워지고, **그 사용자만** 조회·수정할 수 있습니다(다른 사람이 id를 알아도
  404). `GET /family-graph/mine` 으로 자기 그래프를 되찾습니다.
- **비로그인(익명)** 으로 만든 그래프는 `user_id` 가 NULL이고, 예전처럼
  id(추측 불가능한 32자리 hex)를 아는 사람이면 접근할 수 있는
  capability-token 모델입니다. 로그인 후 `POST /family-graph/{id}/claim` 으로
  자기 계정에 연결하면 그 순간부터 본인 전용이 됩니다.

id를 로그에 남길 때는 여전히 `db.base.mask_sensitive_id` 로 가리고, HTTPS로만
서비스합니다(URL 경로에 id 노출).
"""

from __future__ import annotations

from typing import Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user, get_current_user_optional
from auth.models import User
from db.base import DatabaseNotConfigured, get_engine, session_scope

from . import repository
from .schemas import FamilyGraphOut, FamilyMemberIn, FamilyMemberOut, FamilyMemberPatch

router = APIRouter(prefix="/family-graph", tags=["family-graph"])

_NOT_FOUND = HTTPException(status_code=404, detail="family_graph를 찾을 수 없습니다.")
_MEMBER_NOT_FOUND = HTTPException(status_code=404, detail="구성원을 찾을 수 없습니다.")


def get_db() -> Iterator[Session]:
    try:
        get_engine()
    except DatabaseNotConfigured as exc:
        raise HTTPException(
            status_code=503, detail="DATABASE_URL이 설정돼 있지 않습니다."
        ) from exc
    with session_scope() as db:
        yield db


def _load_accessible_graph(
    db: Session, family_graph_id: str, user: Optional[User]
) -> repository.FamilyGraph:
    """그래프를 불러오되, 요청자가 접근할 수 없으면 404로 취급합니다.

    "다른 사람 소유"와 "없음"을 구분하지 않는 이유: 구분하면 "이 id는 존재하되
    남의 것"이라는 정보가 새어 나갑니다.
    """
    graph = db.get(repository.FamilyGraph, family_graph_id)
    user_id = user.id if user is not None else None
    if graph is None or not repository.user_can_access(graph, user_id):
        raise _NOT_FOUND
    return graph


@router.post("", response_model=FamilyGraphOut, status_code=201)
def create_family_graph(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
) -> repository.FamilyGraph:
    return repository.create_family_graph(db, user_id=user.id if user else None)


@router.get("/mine", response_model=FamilyGraphOut)
def read_my_family_graph(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> repository.FamilyGraph:
    graph = repository.get_latest_for_user(db, user.id)
    if graph is None:
        raise _NOT_FOUND
    repository.touch_family_graph(db, graph.id)
    return graph


@router.get("/{family_graph_id}", response_model=FamilyGraphOut)
def read_family_graph(
    family_graph_id: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
) -> repository.FamilyGraph:
    graph = _load_accessible_graph(db, family_graph_id, user)
    repository.touch_family_graph(db, family_graph_id)
    return graph


@router.post("/{family_graph_id}/claim", response_model=FamilyGraphOut)
def claim_family_graph(
    family_graph_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> repository.FamilyGraph:
    """익명으로 만든 그래프를 로그인한 내 계정에 연결합니다."""
    graph = repository.claim_family_graph(db, family_graph_id, user.id)
    if graph is None:
        raise _NOT_FOUND
    return graph


@router.post(
    "/{family_graph_id}/members", response_model=FamilyMemberOut, status_code=201
)
def add_family_member(
    family_graph_id: str,
    payload: FamilyMemberIn,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
) -> repository.FamilyMember:
    _load_accessible_graph(db, family_graph_id, user)
    return repository.add_member(
        db,
        family_graph_id,
        name=payload.name,
        relation=payload.relation,
        is_alive=payload.is_alive,
        is_minor=payload.is_minor,
    )


@router.patch("/{family_graph_id}/members/{member_id}", response_model=FamilyMemberOut)
def update_family_member(
    family_graph_id: str,
    member_id: int,
    payload: FamilyMemberPatch,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
) -> repository.FamilyMember:
    _load_accessible_graph(db, family_graph_id, user)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=400, detail="수정할 필드를 하나 이상 보내주세요."
        )

    member = repository.update_member(db, family_graph_id, member_id, **updates)
    if member is None:
        raise _MEMBER_NOT_FOUND
    return member


@router.delete(
    "/{family_graph_id}/members/{member_id}", status_code=204, response_model=None
)
def delete_family_member(
    family_graph_id: str,
    member_id: int,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
) -> None:
    _load_accessible_graph(db, family_graph_id, user)
    if not repository.delete_member(db, family_graph_id, member_id):
        raise _MEMBER_NOT_FOUND

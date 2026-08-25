"""family_graph REST API (담당: 지원 · 개편: 정민). 프론트 온보딩이 가족 트리를
저장/조회할 때 씁니다.

이 라우터가 다루는 건 "가족 트리 데이터 자체"의 저장/조회뿐입니다.
오케스트레이터가 family_graph_id로 이 데이터를 읽어 AgentInput.family_graph를
채우는 부분은 repository.get_heirs_dict()가 담당하고, 이 라우터와는 별개
경로입니다.

트리는 통째로 저장/교체합니다(schemas.py 참고) — 구성원 단위 부분 수정
엔드포인트는 두지 않습니다.

보안 모델(현재 MVP 범위, 알려진 한계): 이 라우터는 로그인/세션 소유권
검증이 없습니다. family_graph_id(32자리 uuid4 hex, 추측 불가능한 값)를 아는
사람은 누구나 그 가족관계를 조회·수정할 수 있습니다 — 즉 이 id 자체가
비밀키(capability token)처럼 동작합니다. 이 설계를 유지하는 동안 지켜야
하는 것:
  1. family_graph_id를 로그에 그대로 남기지 않는다 (db.base.mask_sensitive_id
     사용 — repository.py/session_store.py 참고).
  2. HTTPS로만 서비스한다 (URL 경로에 id가 그대로 노출되므로 평문 HTTP에서는
     네트워크 경로 상에서 그대로 유출됩니다).
  3. 배포 환경의 웹서버/프록시 접근 로그에도 요청 경로가 그대로 남는다는 점을
     인지한다 (uvicorn access log 등) — 프로덕션에서는 그 로그의 보관 기간을
     짧게 하거나 접근을 제한하는 걸 권장합니다.
사용자 계정·로그인 자체가 아직 없는 MVP 단계라 실제 소유권 검증(로그인
사용자 ↔ family_graph 연결)은 다음 반복으로 미룹니다.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.base import DatabaseNotConfigured, get_engine, session_scope

from . import repository
from .schemas import FamilyTreeIn, FamilyTreeOut

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


def _tree_out(db: Session, family_graph_id: str) -> FamilyTreeOut:
    graph = db.get(repository.FamilyGraph, family_graph_id)
    assert graph is not None
    persons, relations = repository.load_tree(db, family_graph_id)
    return FamilyTreeOut(
        id=graph.id,
        created_at=graph.created_at,
        persons=persons,
        relations=relations,
    )


@router.post("", response_model=FamilyTreeOut, status_code=201)
def create_family_graph(
    payload: FamilyTreeIn, db: Session = Depends(get_db)
) -> FamilyTreeOut:
    """가족 트리를 새로 저장합니다. 온보딩 '저장하고 시작하기'가 호출합니다."""
    graph = repository.create_family_graph(db)
    repository.replace_tree(db, graph.id, payload)
    return _tree_out(db, graph.id)


@router.get("/{family_graph_id}", response_model=FamilyTreeOut)
def read_family_graph(
    family_graph_id: str, db: Session = Depends(get_db)
) -> FamilyTreeOut:
    """수정 화면 프리필용 트리 조회."""
    graph = db.get(repository.FamilyGraph, family_graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="family_graph를 찾을 수 없습니다.")
    repository.touch_family_graph(db, family_graph_id)
    return _tree_out(db, family_graph_id)


@router.put("/{family_graph_id}", response_model=FamilyTreeOut)
def replace_family_graph(
    family_graph_id: str, payload: FamilyTreeIn, db: Session = Depends(get_db)
) -> FamilyTreeOut:
    """트리를 통째로 교체합니다. 수정 화면 '저장'이 호출합니다.

    id를 유지한 채 내용만 바꾸므로, 세션(sessions.family_graph_id)이나
    프론트 localStorage가 들고 있는 id는 그대로 유효합니다.
    """
    graph = db.get(repository.FamilyGraph, family_graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="family_graph를 찾을 수 없습니다.")
    repository.replace_tree(db, family_graph_id, payload)
    return _tree_out(db, family_graph_id)

"""
family_graph·orchestrator가 공유하는 SQLAlchemy 인프라 (담당: 지원).

Phase 2(family_graph DB 연결)에서 새로 생겼습니다. 두 모듈의 models.py가
이 Base 하나를 공유해서, Alembic이 자동 생성할 때 테이블을 전부 찾을 수
있게 합니다.

엔진은 지연 생성합니다 — DATABASE_URL이 없는 환경(지금 CI가 그렇습니다)에서도
이 모듈이나 이 모듈을 쓰는 family_graph/orchestrator를 import하는 것 자체는
항상 안전해야 하기 때문입니다. 실제로 DB에 접근하는 시점에만
DatabaseNotConfigured를 던집니다.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """family_graph/orchestrator 공용 선언적 베이스."""


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL이 설정돼 있지 않아 DB 기능을 쓸 수 없을 때 던집니다."""


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _database_url() -> Optional[str]:
    return os.getenv("DATABASE_URL")


def get_engine() -> Engine:
    """엔진을 지연 생성해서 돌려줍니다. DATABASE_URL이 없으면 예외를 던집니다."""
    global _engine, _SessionLocal
    if _engine is None:
        url = _database_url()
        if not url:
            raise DatabaseNotConfigured("DATABASE_URL이 설정돼 있지 않습니다.")
        _engine = create_engine(url, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    """테스트에서 DATABASE_URL을 바꿔가며 검증할 때 캐시된 엔진을 초기화합니다."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def mask_sensitive_id(value: Optional[str]) -> str:
    """로그에 민감한 식별자(family_graph_id 등)를 남길 때 쓰는 헬퍼.

    family_graph_id는 그 자체가 접근 권한처럼 쓰이는 값입니다 (아는 사람은
    누구나 그 가족관계 데이터를 조회할 수 있음 — family_graph/router.py
    docstring 참고). 로그에 전체 값을 그대로 남기면 로그 접근 권한이 있는
    사람이 그 값만으로 실제 데이터에 접근할 수 있게 되므로, 앞 8자만 남기고
    나머지는 가립니다. 문제 추적(어떤 요청인지 구분)에는 충분하면서, 그
    자체로 원래 id를 복원할 수는 없습니다.
    """
    if not value:
        return "(none)"
    return f"{value[:8]}…" if len(value) > 8 else f"{value}…"


@contextmanager
def session_scope() -> Iterator[Session]:
    """트랜잭션 하나짜리 세션 컨텍스트. 성공하면 commit, 예외면 rollback."""
    get_engine()  # _SessionLocal 초기화 보장 (DB 미설정이면 여기서 예외 발생)
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

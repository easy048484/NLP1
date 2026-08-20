"""DB 관련 테스트 공통 fixture (담당: 지원).

`with_db` fixture를 쓰는 테스트는 실제 Postgres(DATABASE_URL)가 연결 가능할
때만 돌아갑니다. 지금 CI(ci.yml)에는 아직 Postgres 서비스가 없어서, 이
fixture를 쓰는 테스트는 CI에서 자동으로 skip됩니다 — 실패가 아니라 skip이라
CI는 계속 초록입니다. CI에서도 이 테스트들을 실제로 돌리려면 backend job에
postgres 서비스 컨테이너를 추가하는 작업이 별도로 필요합니다 (PR 설명 참고).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import family_graph.models  # noqa: F401 — Base.metadata에 테이블 등록
import orchestrator.models  # noqa: F401
from db.base import Base, DatabaseNotConfigured, get_engine


@pytest.fixture()
def with_db():
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)
    except DatabaseNotConfigured:
        pytest.skip("DATABASE_URL이 없어 DB 테스트를 건너뜁니다.")
    except OperationalError as exc:
        pytest.skip(f"DB에 연결할 수 없어 건너뜁니다: {exc}")

    yield

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE sessions, family_members, family_graphs "
                "RESTART IDENTITY CASCADE"
            )
        )

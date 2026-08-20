"""DB 관련 테스트 공통 fixture (담당: 지원).

`with_db` fixture를 쓰는 테스트는 실제 Postgres(DATABASE_URL)가 연결 가능할
때만 돌아갑니다. DATABASE_URL이 없거나 연결이 안 되면 skip합니다(실패가
아니라 skip이라 CI는 계속 초록입니다).

중요: 이 fixture는 테이블을 스스로 만들지 않습니다(예전엔
`Base.metadata.create_all()`로 직접 만들었지만, 그러면 Alembic 마이그레이션
파일이 실제로는 잘못돼 있어도 테스트가 그걸 우회해서 통과할 수 있었습니다).
대신 DATABASE_URL이 가리키는 DB에 `alembic upgrade head`가 이미 적용돼
있다고 가정합니다 — 스키마가 안 맞으면(테이블이 없으면) 아래 테스트들이
"relation ... does not exist" 같은 에러로 바로, 시끄럽게 실패합니다. 이게
의도된 동작입니다: 마이그레이션이 실제 테스트 대상이 되게 하기 위해서입니다.

로컬에서 이 테스트들을 돌리려면 먼저 한 번:
    cd apps/api && alembic upgrade head
CI(ci.yml)는 backend job에 Postgres 서비스를 띄워 pytest 실행 전에
`alembic upgrade head`를 실행하고, upgrade→downgrade→upgrade 사이클도 한 번
검증합니다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from db.base import DatabaseNotConfigured, get_engine


@pytest.fixture()
def with_db():
    try:
        engine = get_engine()
        with engine.connect():
            pass
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

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

# ---------------------------------------------------------------------------
# decedent_estate LLM 폴백을 실제 네트워크로부터 격리 (담당: 정호, 2026-08-25).
#
# 실전 검증에서 21개 테스트가 mock 없이 실제 Anthropic API를 호출하고
# 있었음이 드러났다. "conftest.py가 dotenv를 안 읽으니 안전할 것"이라는
# 전제가 실제로는 깨져 있었다 — main.py 최상단이 import 시점에 곧바로
# load_dotenv(repo_root/".env")를 실행하는데(모듈 레벨 부작용), 이 스위트의
# test_health.py가 `from main import app`을 하기 때문에 pytest가 테스트를
# "수집"만 해도(실행 전에!) main.py가 import되면서 그 부작용으로
# ANTHROPIC_API_KEY가 os.environ 전체에 새어 들어간다. 그 뒤로 실행되는
# 모든 테스트에서 llm_client._client()가 진짜 키를 읽어 실제 API를 호출했다
# (기존 requirement_checker/result_formatter 테스트들이 "정규식 absent →
# LLM 폴백 트리거" 텍스트를 흔히 쓰기 때문에 21개나 걸렸다).
#
# 방어 지점을 llm_client._client()가 아니라 환경변수 자체로 잡은 이유:
# test_decedent_llm_client.py의 파싱 회귀 테스트 9개(#33)는 각 테스트
# 안에서 monkeypatch.setattr(llm_client.anthropic, "Anthropic", 가짜)로
# _client()가 정상적으로 동작하는 것 자체를 검증한다 — _client()를 통째로
# 무력화하면 이 테스트들이 깨진다. 대신 매 테스트 시작 전에
# ANTHROPIC_API_KEY만 지워두면, 그 테스트가 스스로 monkeypatch.setenv로
# 다시 채우지 않는 한 _client()는 항상 정상적인 "키 없음 → None" 경로를
# 타므로 네트워크를 절대 안 탄다. 같은 monkeypatch fixture 인스턴스를 테스트
# 함수가 이어받아 쓰므로 두 setenv/delenv는 자연스럽게 합성된다.
#
# 예외: @pytest.mark.live 로 표시된 테스트는 이 fixture를 건너뛴다 — 실제
# API를 검증하고 싶을 때 opt-in 하는 경로다. 기본 실행(`pytest -q`)에서는
# pytest_collection_modifyitems가 live 테스트 자체를 deselect하므로,
# `--live` 를 명시적으로 줬을 때만 이 예외가 의미를 가진다.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_llm_calls(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if request.node.get_closest_marker("live") is not None:
        return
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="@pytest.mark.live 테스트(실제 Anthropic API 호출)도 함께 실행한다.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """--live 없이는 live 마커 테스트를 아예 deselect한다(skip이 아니라 —
    실행 목록/카운트에서 완전히 빠진다, `--runslow` 류 관례와 동일)."""
    if config.getoption("--live"):
        return
    keep, deselected = [], []
    for item in items:
        (deselected if "live" in item.keywords else keep).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = keep


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

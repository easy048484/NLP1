import os
import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# apps/api를 sys.path에 넣어야 db/family_graph/orchestrator를 import할 수
# 있습니다. pytest.ini의 `pythonpath = .`와 같은 이유로, alembic은 CLI로
# 실행되므로 여기서 직접 넣어줍니다.
_api_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_api_dir))

# uvicorn(main.py)과 같이 저장소 루트 .env를 읽습니다. alembic CLI는
# dotenv를 자동으로 로드하지 않아서, 이게 없으면 alembic.ini의
# placeholder(driver://...)로 붙어 dialects:driver 오류가 납니다.
_env_path = _api_dir.parents[1] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# Base.metadata에 모든 테이블이 올라오도록, models 모듈들을 import합니다
# (import 자체가 부작용으로 Base.metadata에 테이블을 등록시킵니다).
from db.base import Base  # noqa: E402
import auth.models  # noqa: E402,F401
import family_graph.models  # noqa: E402,F401
import orchestrator.models  # noqa: E402,F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# alembic.ini의 sqlalchemy.url 대신 환경변수 DATABASE_URL을 우선 씁니다 —
# 시크릿을 alembic.ini에 커밋하지 않기 위해서입니다 (.env.example과 동일한
# 원칙). ConfigParser가 %를 보간 문법으로 해석하므로 비밀번호의 %는
# %% 로 이스케이프합니다.
_database_url = os.getenv("DATABASE_URL", "").strip()
if not _database_url:
    raise RuntimeError(
        "DATABASE_URL이 없습니다. 저장소 루트 .env에 Postgres URL을 넣으세요."
    )
config.set_main_option("sqlalchemy.url", _database_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

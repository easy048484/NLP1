"""sessions.user_id owner

Revision ID: c7e9f1a4b820
Revises: b1c2d3e4f5a6
Create Date: 2026-09-02 00:00:00.000000

세션에 소유자를 붙입니다. 이 컬럼 하나로 두 동작이 갈립니다.

- user_id IS NULL (비로그인) — 대화가 끝나면 남지 않아야 하는 데이터입니다.
  짧은 TTL(2시간)을 걸고 만료분은 정리 배치가 실제로 지웁니다.
- user_id 있음 (로그인) — 다음 방문에 이어서 쓸 데이터입니다. 30일 보관하며
  (docs/개발_배포_파이프라인_계획.md 10절 "해당 대화 세션 종료 후 30일"),
  가족정보·재산정보·대화 이력이 그대로 살아 있습니다.

기존 세션은 user_id가 NULL(익명)로 남고 지금과 똑같이 동작합니다.
family_graphs.user_id(b1c2d3e4f5a6)와 같은 형태·같은 FK 정책입니다.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e9f1a4b820"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = "fk_sessions_user_id_users"


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("user_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_sessions_user_id"),
        "sessions",
        ["user_id"],
        unique=False,
    )
    op.create_foreign_key(
        _FK_NAME,
        "sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # 정리 배치가 "만료된 것만" 골라 지우는 질의를 매번 돌리므로 인덱스를 둡니다.
    op.create_index(
        op.f("ix_sessions_expires_at"),
        "sessions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_constraint(_FK_NAME, "sessions", type_="foreignkey")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_column("sessions", "user_id")

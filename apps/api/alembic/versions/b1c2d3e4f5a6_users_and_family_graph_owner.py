"""users table and family_graphs.user_id owner

Revision ID: b1c2d3e4f5a6
Revises: 47a1b29de8db
Create Date: 2026-08-28 00:00:00.000000

회원가입/로그인 도입 — users 테이블을 만들고, family_graphs에 소유자(user_id)를
붙입니다. 기존 그래프는 user_id가 NULL(익명)로 남고, 그대로 동작합니다.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "47a1b29de8db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = "fk_family_graphs_user_id_users"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.add_column(
        "family_graphs",
        sa.Column("user_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_family_graphs_user_id"),
        "family_graphs",
        ["user_id"],
        unique=False,
    )
    op.create_foreign_key(
        _FK_NAME,
        "family_graphs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "family_graphs", type_="foreignkey")
    op.drop_index(op.f("ix_family_graphs_user_id"), table_name="family_graphs")
    op.drop_column("family_graphs", "user_id")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

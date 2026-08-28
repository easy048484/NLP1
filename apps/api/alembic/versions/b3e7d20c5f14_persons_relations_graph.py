"""family_members를 persons + relations(노드-엣지)로 교체

가족그래프 개편(docs/가족그래프_개편_설계안.md). 관계 명칭을 저장하는 대신
parent_of / spouse_of 엣지에서 파생한다. 피상속인도 명시적 노드가 된다.

⚠️ 파괴적 마이그레이션: family_members 테이블과 그 데이터를 삭제한다.
적용 시점 기준 운영 데이터는 팀 테스트 행뿐이라 데이터 이행은 하지 않는다.
적용 후에는 옛 코드(family_members를 읽는 main 이전 버전)가 동작하지 않으므로,
머지와 동시에 팀 전체 git pull + alembic upgrade head가 필요하다.

Revision ID: b3e7d20c5f14
Revises: 47a1b29de8db
Create Date: 2026-08-25

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3e7d20c5f14"
down_revision: Union[str, None] = "47a1b29de8db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_graph_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_decedent", sa.Boolean(), nullable=False),
        sa.Column("is_alive", sa.Boolean(), nullable=False),
        sa.Column("is_minor", sa.Boolean(), nullable=False),
        sa.Column("death_date", sa.Date(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_graph_id"], ["family_graphs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_persons_family_graph_id"), "persons", ["family_graph_id"], unique=False
    )

    op.create_table(
        "relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_graph_id", sa.String(length=32), nullable=False),
        sa.Column("from_person_id", sa.Integer(), nullable=False),
        sa.Column("to_person_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("parent_of", "spouse_of", name="relation_edge_type"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_graph_id"], ["family_graphs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["from_person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_relations_family_graph_id"),
        "relations",
        ["family_graph_id"],
        unique=False,
    )

    op.drop_index(
        op.f("ix_family_members_family_graph_id"), table_name="family_members"
    )
    op.drop_table("family_members")
    # 테이블을 드롭해도 Postgres의 ENUM 타입(relation_type)은 남아 있으므로
    # 직접 지운다 (downgrade에서 family_members를 되살릴 때 다시 만든다).
    sa.Enum(name="relation_type").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_graph_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "relation",
            sa.Enum(
                "spouse",
                "child",
                "parent",
                "grandchild",
                "sibling",
                "grandparent",
                name="relation_type",
            ),
            nullable=False,
        ),
        sa.Column("is_alive", sa.Boolean(), nullable=False),
        sa.Column("is_minor", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["family_graph_id"], ["family_graphs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_family_members_family_graph_id"),
        "family_members",
        ["family_graph_id"],
        unique=False,
    )

    op.drop_index(op.f("ix_relations_family_graph_id"), table_name="relations")
    op.drop_table("relations")
    op.drop_index(op.f("ix_persons_family_graph_id"), table_name="persons")
    op.drop_table("persons")
    sa.Enum(name="relation_edge_type").drop(op.get_bind(), checkfirst=True)

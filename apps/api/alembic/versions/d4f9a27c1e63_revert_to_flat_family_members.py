"""persons/relations(노드-엣지, PR #30) 되돌리고 family_members로 복귀

배경: main에 PR #30(persons/relations 노드-엣지 스키마, revision b3e7d20c5f14)이
머지·배포되어 운영 DB가 이미 이 리비전까지 마이그레이션된 상태였습니다. 그런데
PR #38에서 그 스키마 자체를 폐기하고 develop의 기존 flat family_members
설계를 유지하기로 정리하면서(가족그래프 개편안 폐기), 코드베이스의 마이그레이션
체인에는 b3e7d20c5f14 이후가 없어 운영 배포 시
"Can't locate revision identified by 'b3e7d20c5f14'"로 실패했습니다.

이 리비전은 b3e7d20c5f14의 downgrade()를 그대로 가져와, 이미 그 리비전까지
가 있는 운영 DB를 다시 family_members 스키마로 되돌리고 이어서
b1c2d3e4f5a6(users/family_graphs.user_id)로 진행할 수 있게 합니다.
b3e7d20c5f14를 겪지 않은 새 DB(로컬/테스트)도 47a1b29de8db → b3e7d20c5f14 →
(이 리비전) → b1c2d3e4f5a6 순서로 동일하게 최종 스키마에 도달합니다.

확인: 운영 DB의 persons 테이블은 2026-08-26에 만든 테스트용 더미 4행
(피상속인/배우자/첫째/둘째, family_graph_id=fb4552a7506d42acb6f2853d2bde4416)
뿐이며, 이는 애초에 b3e7d20c5f14 자체가 "적용 시점 운영 데이터는 팀 테스트
행뿐"이라고 명시한 데이터입니다 - 실사용자 데이터 유실 없음을 확인했습니다.

Revision ID: d4f9a27c1e63
Revises: b3e7d20c5f14
Create Date: 2026-08-28

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d4f9a27c1e63"
down_revision: Union[str, None] = "b3e7d20c5f14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 이 리비전 안에서 relation_type을 한 번 더 만든다 - alembic이 한 번의
    # upgrade 실행 안에서 MetaData를 공유하기 때문에, op.create_table의
    # before_create 이벤트(checkfirst=False로 호출됨)에만 맡기면 "이미
    # 존재/존재하지 않음" 어느 쪽으로도 어긋날 수 있다. 그래서 여기서
    # checkfirst=True로 명시적으로 만들고, 컬럼 쪽은 postgresql.ENUM(
    # create_type=False)로 지정해 before_create가 중복 생성을 시도하지
    # 않게 한다 (generic sa.Enum은 dialect 어댑팅 과정에서 create_type이
    # 그대로 전달되지 않아 이 목적에 안 맞는다).
    relation_type_enum = postgresql.ENUM(
        "spouse",
        "child",
        "parent",
        "grandchild",
        "sibling",
        "grandparent",
        name="relation_type",
    )
    relation_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_graph_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "relation",
            postgresql.ENUM(
                "spouse",
                "child",
                "parent",
                "grandchild",
                "sibling",
                "grandparent",
                name="relation_type",
                create_type=False,
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


def downgrade() -> None:
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

    relation_edge_type_enum = postgresql.ENUM(
        "parent_of", "spouse_of", name="relation_edge_type"
    )
    relation_edge_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("family_graph_id", sa.String(length=32), nullable=False),
        sa.Column("from_person_id", sa.Integer(), nullable=False),
        sa.Column("to_person_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(
                "parent_of", "spouse_of", name="relation_edge_type", create_type=False
            ),
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
    sa.Enum(name="relation_type").drop(op.get_bind(), checkfirst=True)

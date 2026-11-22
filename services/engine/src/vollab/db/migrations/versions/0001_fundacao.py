"""Fundação: usuário fixo, configuração versionada e fila de jobs (Etapa 1).

ADR-13 (usuário fixo), PRD §5.3 (config_versions imutável), ADR-08 (fila em tabela).

Revision ID: 0001
Revises:
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXED_USER_ID = "00000000-0000-0000-0000-000000000001"

job_status = postgresql.ENUM("queued", "running", "succeeded", "failed", name="job_status", create_type=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    insert_user = sa.text("INSERT INTO users (id, display_name) VALUES (CAST(:id AS uuid), 'Usuário local')")
    op.execute(insert_user.bindparams(id=FIXED_USER_ID))

    op.create_table(
        "config_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_config_versions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_versions")),
    )
    op.create_index(op.f("ix_config_versions_user_id"), "config_versions", ["user_id"])
    # Imutabilidade garantida pelo banco: UPDATE e DELETE são proibidos (PRD §5.3).
    op.execute(
        """
        CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'A tabela % é imutável: crie um registro novo em vez de alterar (%).',
                TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER config_versions_immutable
        BEFORE UPDATE OR DELETE ON config_versions
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
        """
    )

    job_status.create(op.get_bind())
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", job_status, server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_queued",
        "jobs",
        ["run_after", "id"],
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_queued", table_name="jobs", postgresql_where=sa.text("status = 'queued'"))
    op.drop_table("jobs")
    job_status.drop(op.get_bind())
    op.execute("DROP TRIGGER config_versions_immutable ON config_versions")
    op.drop_index(op.f("ix_config_versions_user_id"), table_name="config_versions")
    op.drop_table("config_versions")
    op.execute("DROP FUNCTION forbid_mutation()")
    op.drop_table("users")

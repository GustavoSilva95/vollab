"""Operações, retrato da decisão e papéis do Postgres (Etapa 6).

PRD 1.9 §5.4, §5.8 e §6.5: `positions`, `position_entries` (tipo `entry` nesta etapa) e
`manual_inputs`, imutáveis por trigger como `config_versions` (RF-DIA-01, RN-EDG-06, CS-01).

Backlog M-2 (b) da revisão de segurança da Etapa 1: papel da aplicação (`vollab_app`) separado do
dono das migrations — sem DDL, sem TRUNCATE e sem UPDATE/DELETE nas tabelas imutáveis nem em
`alembic_version`. A API e o worker fazem `SET ROLE vollab_app` em cada conexão. A única DDL do app (a
partição mensal de `trades`, PRD-QA-02) passa por `create_trades_partition`, `SECURITY DEFINER`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "vollab_app"
IMMUTABLE_TABLES = ("config_versions", "positions", "position_entries", "manual_inputs")
NEW_IMMUTABLE = ("positions", "position_entries", "manual_inputs")


def _immutable() -> None:
    # Mesma função da 0001 (forbid_mutation): UPDATE, DELETE e TRUNCATE barrados pelo banco.
    for table in NEW_IMMUTABLE:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"
        )


def _app_role() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END $$;
        """  # noqa: S608 (constante do módulo, sem entrada externa)
    )
    # O dono das migrations precisa ser membro para o SET ROLE (superusuário já pode).
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT pg_has_role(current_user, '{APP_ROLE}', 'MEMBER') THEN
                EXECUTE format('GRANT %I TO %I', '{APP_ROLE}', current_user);
            END IF;
        END $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON {', '.join(IMMUTABLE_TABLES)} FROM {APP_ROLE}")
    # Tabelas criadas depois (partições e migrations futuras) recebem os mesmos direitos; uma tabela
    # imutável nova precisa do REVOKE explícito na sua migration.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}")
    op.execute(
        """
        CREATE FUNCTION create_trades_partition(day date) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE
            start date := date_trunc('month', day)::date;
            stop date := (date_trunc('month', day) + interval '1 month')::date;
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF trades FOR VALUES FROM (%L) TO (%L)',
                'trades_y' || to_char(start, 'YYYY') || 'm' || to_char(start, 'MM'), start, stop
            );
        END $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION create_trades_partition(date) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION create_trades_partition(date) TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("structure", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("edge_state", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decision_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("direction IN ('sell', 'buy')", name=op.f("ck_positions_direction")),
        sa.CheckConstraint(
            "edge_state IN ('edge', 'inconclusive', 'no_edge')", name=op.f("ck_positions_edge_state")
        ),
        sa.CheckConstraint(
            "structure IN ('short_straddle', 'short_strangle', 'covered_call', 'long_straddle', 'long_strangle')",
            name=op.f("ck_positions_structure"),
        ),
        sa.CheckConstraint("lots > 0", name=op.f("ck_positions_lots")),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_positions_config_version_id_config_versions"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_positions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_positions")),
    )
    op.create_index("ix_positions_user_created", "positions", ["user_id", "created_at"], unique=False)
    op.create_table(
        "manual_inputs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('spot', 'option_price', 'margin')", name=op.f("ck_manual_inputs_kind")),
        sa.CheckConstraint("value > 0", name=op.f("ck_manual_inputs_positive")),
        sa.ForeignKeyConstraint(
            ["position_id"], ["positions.id"], name=op.f("fk_manual_inputs_position_id_positions")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_manual_inputs_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manual_inputs")),
    )
    op.create_index("ix_manual_inputs_position", "manual_inputs", ["position_id"], unique=False)
    op.create_table(
        "position_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("series_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("fees_brl", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("brokerage_brl", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_entry_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('entry', 'hedge', 'strike_adjustment', 'exercise', 'assignment', 'exit', 'roll')",
            name=op.f("ck_position_entries_kind"),
        ),
        sa.CheckConstraint(
            "price >= 0 AND fees_brl >= 0 AND brokerage_brl >= 0",
            name=op.f("ck_position_entries_non_negative"),
        ),
        sa.CheckConstraint("quantity <> 0", name=op.f("ck_position_entries_quantity")),
        sa.ForeignKeyConstraint(
            ["linked_entry_id"],
            ["position_entries.id"],
            name=op.f("fk_position_entries_linked_entry_id_position_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["position_id"], ["positions.id"], name=op.f("fk_position_entries_position_id_positions")
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["option_series.id"], name=op.f("fk_position_entries_series_id_option_series")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_position_entries_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_position_entries")),
    )
    op.create_index("ix_position_entries_position", "position_entries", ["position_id"], unique=False)
    _immutable()
    _app_role()


def downgrade() -> None:
    op.execute("DROP FUNCTION create_trades_partition(date)")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {APP_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    # O papel é do cluster (pode servir a outro banco, ex.: o de testes): não é apagado.
    for table in NEW_IMMUTABLE[::-1]:
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.drop_index("ix_position_entries_position", table_name="position_entries")
    op.drop_table("position_entries")
    op.drop_index("ix_manual_inputs_position", table_name="manual_inputs")
    op.drop_table("manual_inputs")
    op.drop_index("ix_positions_user_created", table_name="positions")
    op.drop_table("positions")

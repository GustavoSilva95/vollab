"""Gestão da operação: alertas e estado das regras por posição (Etapa 8).

PRD 1.11 §5.10 e §6.5 (BRD 1.8 RN-GES-01..07, RS-07):
- `alerts`: ciclo de vida ativo → visto → resolvido; no máximo um alerta não resolvido por chave
  (regra, posição, escopo). O papel da aplicação tem INSERT e UPDATE, sem DELETE nem TRUNCATE. O
  trigger `alerts_guard` impede mudar as colunas do disparo e torna o alerta resolvido imutável, exceto
  `persisting` de verdadeiro para falso (a condição que segurava a reabertura sumiu).
- `position_management`: última avaliação das regras por posição (dado derivado, refeito pelo job).
- Revisão de segurança da Etapa 8 (I-1): `alerts_insert_guard` só aceita alerta novo como ativo, sem
  resolução e com a data do disparo do banco; FKs compostas ligam o alerta à posição e às versões de
  configuração **do mesmo usuário** (unique `(id, user_id)` em `positions` e `config_versions`).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "vollab_app"
KINDS = "('hedge', 'exit', 'roll', 'limit', 'dividend')"
RULES = (
    "('hedge_band', 'hedge_time', 'exit_edge', 'exit_dte', 'exit_profit', 'exit_stop', 'roll_suggested', "
    "'limit_stress', 'limit_vega', 'limit_underlying', 'limit_expiry', 'dividend_upcoming', "
    "'strike_adjustment_pending')"
)

GUARD = """
CREATE FUNCTION alerts_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'alerts: % não permitido (alertas não são apagados)', TG_OP;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.user_id IS DISTINCT FROM OLD.user_id
        OR NEW.kind IS DISTINCT FROM OLD.kind
        OR NEW.rule IS DISTINCT FROM OLD.rule
        OR NEW.position_id IS DISTINCT FROM OLD.position_id
        OR NEW.scope_key IS DISTINCT FROM OLD.scope_key
        OR NEW.triggered_at IS DISTINCT FROM OLD.triggered_at
        OR NEW.triggered_as_of IS DISTINCT FROM OLD.triggered_as_of
        OR NEW.config_version_id IS DISTINCT FROM OLD.config_version_id
        OR NEW.engine_version IS DISTINCT FROM OLD.engine_version THEN
        RAISE EXCEPTION 'alerts: colunas do disparo são imutáveis';
    END IF;
    IF OLD.state = 'resolved' THEN
        IF (to_jsonb(NEW) - 'persisting') IS DISTINCT FROM (to_jsonb(OLD) - 'persisting')
            OR (NEW.persisting AND NOT OLD.persisting) THEN
            RAISE EXCEPTION 'alerts: alerta resolvido é imutável';
        END IF;
    END IF;
    RETURN NEW;
END;
$$
"""


INSERT_GUARD = """
CREATE FUNCTION alerts_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state <> 'active' OR NEW.resolved_at IS NOT NULL OR NEW.resolved_by IS NOT NULL
        OR NEW.resolution_note IS NOT NULL OR NEW.persisting THEN
        RAISE EXCEPTION 'alerts: alerta novo nasce ativo, sem resolução';
    END IF;
    NEW.triggered_at := now();
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_positions_id_user_id"), "positions", ["id", "user_id"])
    op.create_unique_constraint(op.f("uq_config_versions_id_user_id"), "config_versions", ["id", "user_id"])
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=True),
        sa.Column("scope_key", sa.Text(), server_default="", nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "triggered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("triggered_as_of", sa.Date(), nullable=False),
        sa.Column("last_as_of", sa.Date(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluated_config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("persisting", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(f"kind IN {KINDS}", name=op.f("ck_alerts_kind")),
        sa.CheckConstraint(f"rule IN {RULES}", name=op.f("ck_alerts_rule")),
        sa.CheckConstraint("state IN ('active', 'seen', 'resolved')", name=op.f("ck_alerts_state")),
        sa.CheckConstraint(
            "resolved_by IS NULL OR resolved_by IN ('auto', 'user')", name=op.f("ck_alerts_resolved_by")
        ),
        sa.CheckConstraint(
            "(state = 'resolved') = (resolved_at IS NOT NULL AND resolved_by IS NOT NULL)",
            name=op.f("ck_alerts_resolution"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_alerts_user_id_users")),
        sa.ForeignKeyConstraint(
            ["position_id", "user_id"],
            ["positions.id", "positions.user_id"],
            name=op.f("fk_alerts_position_user"),
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id", "user_id"],
            ["config_versions.id", "config_versions.user_id"],
            name=op.f("fk_alerts_config_version_user"),
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_config_version_id", "user_id"],
            ["config_versions.id", "config_versions.user_id"],
            name=op.f("fk_alerts_evaluated_config_version_user"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(
        "ux_alerts_open_key",
        "alerts",
        ["user_id", "rule", sa.text("coalesce(position_id, 0)"), "scope_key"],
        unique=True,
        postgresql_where=sa.text("state <> 'resolved'"),
    )
    op.create_index("ix_alerts_user_state", "alerts", ["user_id", "state"])
    op.create_index("ix_alerts_position", "alerts", ["position_id"])
    op.execute(GUARD)
    op.execute(
        "CREATE TRIGGER alerts_guard BEFORE UPDATE OR DELETE ON alerts "
        "FOR EACH ROW EXECUTE FUNCTION alerts_guard()"
    )
    op.execute(
        "CREATE TRIGGER alerts_no_truncate BEFORE TRUNCATE ON alerts "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()"
    )
    op.execute(INSERT_GUARD)
    op.execute(
        "CREATE TRIGGER alerts_insert_guard BEFORE INSERT ON alerts "
        "FOR EACH ROW EXECUTE FUNCTION alerts_insert_guard()"
    )
    op.execute(f"REVOKE DELETE, TRUNCATE ON alerts FROM {APP_ROLE}")

    op.create_table(
        "position_management",
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("edge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("roll", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["position_id"], ["positions.id"], name=op.f("fk_position_management_position_id_positions")
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_position_management_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("position_id", name=op.f("pk_position_management")),
    )


def downgrade() -> None:
    op.drop_table("position_management")
    op.execute("DROP TRIGGER alerts_no_truncate ON alerts")
    op.execute("DROP TRIGGER alerts_insert_guard ON alerts")
    op.execute("DROP TRIGGER alerts_guard ON alerts")
    op.execute("DROP FUNCTION alerts_insert_guard()")
    op.execute("DROP FUNCTION alerts_guard()")
    op.drop_table("alerts")
    op.drop_constraint(op.f("uq_config_versions_id_user_id"), "config_versions", type_="unique")
    op.drop_constraint(op.f("uq_positions_id_user_id"), "positions", type_="unique")

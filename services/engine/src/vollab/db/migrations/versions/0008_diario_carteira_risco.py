"""Diário, marcação D-1, atribuição, carteira e crise (Etapa 7).

PRD 1.10 §5.9 e §6.5 (BRD 1.7 RF-DIA-02..04, RF-RSK-01..04, RS-06, QA-12):
- `position_entries` ganha o tipo `void` (estorno, com motivo e ligado ao lançamento anulado) e as
  colunas `strike_after`, `void_reason`, `note`, `config_version_id` e `engine_version`. Continua
  imutável (trigger da 0007); só DDL de migration altera a estrutura.
- `positions.rolled_from_position_id`: a rolagem liga a posição nova à de origem (RN-GES-04).
- `daily_marks` e `pnl_attribution`: dados **derivados** (refeitos pelo job `marks_recompute`).
- `crisis_measurements`: choques medidos nos episódios de crise, por usuário e ativo (o episódio e a
  janela vêm da configuração de cada usuário).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "('entry', 'hedge', 'strike_adjustment', 'exercise', 'assignment', 'exit', 'roll')"
NEW_KINDS = "('entry', 'hedge', 'strike_adjustment', 'exercise', 'assignment', 'exit', 'roll', 'void')"
MONEY = sa.Numeric(precision=18, scale=6)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_position_entries_kind"), "position_entries", type_="check")
    op.create_check_constraint(op.f("ck_position_entries_kind"), "position_entries", f"kind IN {NEW_KINDS}")
    op.add_column("position_entries", sa.Column("strike_after", MONEY, nullable=True))
    op.add_column("position_entries", sa.Column("void_reason", sa.Text(), nullable=True))
    op.add_column("position_entries", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("position_entries", sa.Column("config_version_id", sa.BigInteger(), nullable=True))
    op.add_column("position_entries", sa.Column("engine_version", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_position_entries_config_version_id_config_versions"),
        "position_entries",
        "config_versions",
        ["config_version_id"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_position_entries_void_linked"),
        "position_entries",
        "kind <> 'void' OR (linked_entry_id IS NOT NULL AND void_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_position_entries_strike_after"),
        "position_entries",
        "kind <> 'strike_adjustment' OR strike_after > 0",
    )
    op.create_index(
        "ux_position_entries_void_once",
        "position_entries",
        ["linked_entry_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'void'"),
    )

    op.add_column("positions", sa.Column("rolled_from_position_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_positions_rolled_from_position_id_positions"),
        "positions",
        "positions",
        ["rolled_from_position_id"],
        ["id"],
    )

    op.create_table(
        "daily_marks",
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("spot", MONEY, nullable=False),
        sa.Column("stock_qty", sa.BigInteger(), nullable=False),
        sa.Column("options_value", MONEY, nullable=False),
        sa.Column("stock_value", MONEY, nullable=False),
        sa.Column("delta_shares", sa.Double(), nullable=False),
        sa.Column("gamma", sa.Double(), nullable=False),
        sa.Column("vega_per_point_brl", sa.Double(), nullable=False),
        sa.Column("theta_per_bd_brl", sa.Double(), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("legs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["position_id"], ["positions.id"], name=op.f("fk_daily_marks_position_id_positions")
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_daily_marks_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("position_id", "trade_date", name=op.f("pk_daily_marks")),
    )
    op.create_table(
        "pnl_attribution",
        sa.Column("position_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("delta_brl", MONEY, nullable=False),
        sa.Column("gamma_brl", MONEY, nullable=False),
        sa.Column("theta_brl", MONEY, nullable=False),
        sa.Column("vega_brl", MONEY, nullable=False),
        sa.Column("market_brl", MONEY, nullable=False),
        sa.Column("residual_brl", MONEY, nullable=False),
        sa.Column("execution_brl", MONEY, nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("error_flag", sa.Boolean(), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["position_id"], ["positions.id"], name=op.f("fk_pnl_attribution_position_id_positions")
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_pnl_attribution_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("position_id", "trade_date", name=op.f("pk_pnl_attribution")),
    )
    op.create_table(
        "crisis_measurements",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("episode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("price_shock", sa.Double(), nullable=True),
        sa.Column("worst_day", sa.Date(), nullable=True),
        sa.Column("worst_day_return", sa.Double(), nullable=True),
        sa.Column("vol_shock", sa.Double(), nullable=True),
        sa.Column("vol_method", sa.Text(), nullable=True),
        sa.Column("vol_before", sa.Double(), nullable=True),
        sa.Column("vol_after", sa.Double(), nullable=True),
        sa.Column("dividends_checked", sa.Boolean(), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'unavailable')", name=op.f("ck_crisis_measurements_status")),
        sa.CheckConstraint(
            "vol_method IS NULL OR vol_method IN ('atm_iv', 'rv20')",
            name=op.f("ck_crisis_measurements_vol_method"),
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_crisis_measurements_config_version_id_config_versions"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_crisis_measurements_user_id_users")),
        sa.PrimaryKeyConstraint("user_id", "ticker", "episode", name=op.f("pk_crisis_measurements")),
    )


def downgrade() -> None:
    op.drop_table("crisis_measurements")
    op.drop_table("pnl_attribution")
    op.drop_table("daily_marks")
    op.drop_constraint(
        op.f("fk_positions_rolled_from_position_id_positions"), "positions", type_="foreignkey"
    )
    op.drop_column("positions", "rolled_from_position_id")
    op.drop_index("ux_position_entries_void_once", table_name="position_entries")
    op.drop_constraint(op.f("ck_position_entries_strike_after"), "position_entries", type_="check")
    op.drop_constraint(op.f("ck_position_entries_void_linked"), "position_entries", type_="check")
    op.drop_constraint(
        op.f("fk_position_entries_config_version_id_config_versions"), "position_entries", type_="foreignkey"
    )
    for col in ("engine_version", "config_version_id", "note", "void_reason", "strike_after"):
        op.drop_column("position_entries", col)
    op.drop_constraint(op.f("ck_position_entries_kind"), "position_entries", type_="check")
    # O downgrade só funciona sem estornos gravados (a 0007 não conhece o tipo `void`).
    op.create_check_constraint(op.f("ck_position_entries_kind"), "position_entries", f"kind IN {OLD_KINDS}")

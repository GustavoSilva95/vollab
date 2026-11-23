"""Volatilidade e eventos (Etapa 3).

PRD §6.2 e §6.4: barras de 5 min e resumo do pregão intradiário (RN-VOL-08), RV por estimador e
janela (RF-VOL-01), IV por negócio e de referência diária (RF-VOL-02, RN-VOL-03/06), estrutura a
termo ATM e prazo constante (RF-VOL-03/05, QA-03) e calendário de eventos (RF-EVT-01/02).
`corporate_actions.event_id` liga o provento manual ao evento ex-dividendo/ex-JCP que o criou.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intraday_bars",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("bar_start", sa.Time(), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("ticker", "trade_date", "bar_start", name=op.f("pk_intraday_bars")),
    )
    op.create_table(
        "intraday_sessions",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("session_open", sa.Time(), nullable=False),
        sa.Column("session_close", sa.Time(), nullable=False),
        sa.Column("bar_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("bars_total", sa.Integer(), nullable=False),
        sa.Column("bars_with_trades", sa.Integer(), nullable=False),
        sa.Column("coverage", sa.Double(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("intraday_variance", sa.Double(), nullable=False),
        sa.Column("trades_used", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("ticker", "trade_date", name=op.f("pk_intraday_sessions")),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(kind IN ('ex_dividend', 'ex_jcp')) = (amount IS NOT NULL)",
            name=op.f("ck_events_amount_by_kind"),
        ),
        sa.CheckConstraint(
            "kind IN ('copom', 'macro') OR ticker IS NOT NULL", name=op.f("ck_events_ticker_by_kind")
        ),
        sa.CheckConstraint(
            "kind IN ('earnings', 'ex_dividend', 'ex_jcp', 'copom', 'macro')", name=op.f("ck_events_kind")
        ),
        sa.CheckConstraint("status IN ('confirmed', 'estimated')", name=op.f("ck_events_status")),
        sa.CheckConstraint("amount IS NULL OR amount > 0", name=op.f("ck_events_amount_positive")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_events_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_user_date", "events", ["user_id", "event_date"], unique=False)
    op.create_table(
        "implied_vols",
        sa.Column("series_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("trade_id", sa.BigInteger(), nullable=False),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("option_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("underlying_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("lag_ms", sa.Integer(), nullable=False),
        sa.Column("strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("days_to_expiry_bd", sa.SmallInteger(), nullable=False),
        sa.Column("rate_continuous", sa.Double(), nullable=False),
        sa.Column("pv_dividends", sa.Double(), nullable=False),
        sa.Column("iv", sa.Double(), nullable=True),
        sa.Column("iv_status", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"], ["option_series.id"], name=op.f("fk_implied_vols_series_id_option_series")
        ),
        sa.PrimaryKeyConstraint("series_id", "trade_date", "trade_id", name=op.f("pk_implied_vols")),
    )
    op.create_table(
        "atm_term_structure",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("days_to_expiry_bd", sa.SmallInteger(), nullable=False),
        sa.Column("forward", sa.Double(), nullable=False),
        sa.Column("atm_iv", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("lower_strike", sa.Double(), nullable=True),
        sa.Column("upper_strike", sa.Double(), nullable=True),
        sa.Column("is_weekly", sa.Boolean(), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'unavailable')", name=op.f("ck_atm_term_structure_status")),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_atm_term_structure_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("ticker", "as_of", "expiry", name=op.f("pk_atm_term_structure")),
    )
    op.create_table(
        "constant_maturity_vols",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("target_bd", sa.SmallInteger(), nullable=False),
        sa.Column("iv", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("lower_expiry", sa.Date(), nullable=True),
        sa.Column("upper_expiry", sa.Date(), nullable=True),
        sa.Column("fallback_expiry", sa.Date(), nullable=True),
        sa.Column("fallback_bd", sa.SmallInteger(), nullable=True),
        sa.Column("fallback_iv", sa.Double(), nullable=True),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('ok', 'unavailable')", name=op.f("ck_constant_maturity_vols_status")),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_constant_maturity_vols_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("ticker", "as_of", "target_bd", name=op.f("pk_constant_maturity_vols")),
    )
    op.create_table(
        "option_daily_quotes",
        sa.Column("series_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("iv", sa.Double(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("trades_valid", sa.Integer(), nullable=False),
        sa.Column("trades_synced", sa.Integer(), nullable=False),
        sa.Column("trades_lag_discarded", sa.Integer(), nullable=False),
        sa.Column("trades_no_solution", sa.Integer(), nullable=False),
        sa.Column("trades_used", sa.Integer(), nullable=False),
        sa.Column("implied_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("underlying_close", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("effective_strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("days_to_expiry_bd", sa.SmallInteger(), nullable=False),
        sa.Column("liquid", sa.Boolean(), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "status IN ('ok', 'low_sample', 'no_iv')", name=op.f("ck_option_daily_quotes_status")
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_option_daily_quotes_config_version_id_config_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["option_series.id"], name=op.f("fk_option_daily_quotes_series_id_option_series")
        ),
        sa.PrimaryKeyConstraint("series_id", "trade_date", name=op.f("pk_option_daily_quotes")),
    )
    op.create_index("ix_option_daily_quotes_date", "option_daily_quotes", ["trade_date"], unique=False)
    op.create_table(
        "realized_vols",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("estimator", sa.Text(), nullable=False),
        sa.Column("window_bd", sa.SmallInteger(), nullable=False),
        sa.Column("variance_annual", sa.Double(), nullable=True),
        sa.Column("vol", sa.Double(), nullable=True),
        sa.Column("missing_days", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "(status = 'ok') = (vol IS NOT NULL AND variance_annual IS NOT NULL)",
            name=op.f("ck_realized_vols_value_status"),
        ),
        sa.CheckConstraint(
            "estimator IN ('close_to_close', 'close_to_close_demeaned', 'parkinson', 'garman_klass', 'rogers_satchell', 'yang_zhang', 'intraday_5m')",
            name=op.f("ck_realized_vols_estimator"),
        ),
        sa.CheckConstraint("status IN ('ok', 'insufficient_data')", name=op.f("ck_realized_vols_status")),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_realized_vols_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("ticker", "as_of", "estimator", "window_bd", name=op.f("pk_realized_vols")),
    )
    op.add_column("corporate_actions", sa.Column("event_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(op.f("uq_corporate_actions_event_id"), "corporate_actions", ["event_id"])
    op.create_foreign_key(
        op.f("fk_corporate_actions_event_id_events"),
        "corporate_actions",
        "events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_corporate_actions_event_id_events"), "corporate_actions", type_="foreignkey")
    op.drop_constraint(op.f("uq_corporate_actions_event_id"), "corporate_actions", type_="unique")
    op.drop_column("corporate_actions", "event_id")
    op.drop_table("realized_vols")
    op.drop_index("ix_option_daily_quotes_date", table_name="option_daily_quotes")
    op.drop_table("option_daily_quotes")
    op.drop_table("constant_maturity_vols")
    op.drop_table("atm_term_structure")
    op.drop_table("implied_vols")
    op.drop_index("ix_events_user_date", table_name="events")
    op.drop_table("events")
    op.drop_table("intraday_sessions")
    op.drop_table("intraday_bars")

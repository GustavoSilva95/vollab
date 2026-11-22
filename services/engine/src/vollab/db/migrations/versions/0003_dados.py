"""Dados: referência, mercado e coleta (Etapa 2).

PRD §6.1–6.3. `trades` é particionada por mês do pregão (PRD-QA-02); as partições são criadas
sob demanda pela ingestão (`vollab.collection.store.ensure_trades_partition`). Sem chave
estrangeira de `trades.raw_file_id`: a checagem por linha encareceria a carga em lote
(~100 mil linhas por pregão de PETR4) e a origem é garantida pela ingestão.

Carga inicial: feriados (QA-02) e o universo inicial BOVA11, BBAS3, PETR4 (STATUS, 2026-11-22).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vollab.data.holidays import seed_holidays

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIXED_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    holidays = op.create_table(
        "exchange_holidays",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source IN ('b3_official', 'national_list', 'b3_rule')", name=op.f("ck_exchange_holidays_source")
        ),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_exchange_holidays")),
    )
    op.create_table(
        "option_series",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("underlying_isin", sa.Text(), nullable=False),
        sa.Column("option_type", sa.Text(), nullable=False),
        sa.Column("strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("style", sa.Text(), nullable=False),
        sa.Column("style_source", sa.Text(), nullable=False),
        sa.Column("is_weekly", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), server_default="b3_cotahist", nullable=False),
        sa.Column("first_trade_date", sa.Date(), nullable=False),
        sa.Column("last_trade_date", sa.Date(), nullable=False),
        sa.CheckConstraint("option_type IN ('call', 'put')", name=op.f("ck_option_series_option_type")),
        sa.CheckConstraint("style IN ('european', 'american')", name=op.f("ck_option_series_style")),
        sa.CheckConstraint(
            "style_source IN ('name_suffix', 'official_registry')", name=op.f("ck_option_series_style_source")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_option_series")),
        sa.UniqueConstraint("code", "expiry", name="uq_option_series_code_expiry"),
    )
    op.create_index(
        "ix_option_series_isin_expiry", "option_series", ["underlying_isin", "expiry"], unique=False
    )
    op.create_table(
        "raw_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("query_key", sa.Text(), nullable=False),
        sa.Column("query_date", sa.Date(), nullable=True),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("http_status", sa.SmallInteger(), nullable=False),
        sa.Column("content_format", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("parse_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "parse_status IN ('pending', 'ok', 'empty', 'error')", name=op.f("ck_raw_files_parse_status")
        ),
        sa.CheckConstraint(
            "source IN ('b3_trades', 'b3_cotahist_daily', 'b3_cotahist_annual', 'bcb_selic', 'yahoo_dividends')",
            name=op.f("ck_raw_files_source"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_files")),
    )
    op.create_index("ix_raw_files_query", "raw_files", ["source", "query_key", "query_date"], unique=False)
    op.create_table(
        "trades",
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("instrument", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("trade_id", sa.BigInteger(), nullable=False),
        sa.Column("update_action", sa.SmallInteger(), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_type", sa.SmallInteger(), nullable=False),
        sa.Column("buyer", sa.Integer(), nullable=True),
        sa.Column("seller", sa.Integer(), nullable=True),
        sa.Column("r4_valid", sa.Boolean(), nullable=False),
        sa.Column("raw_file_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "instrument", "reference_date", "trade_date", "trade_id", "update_action", name="pk_trades"
        ),
        postgresql_partition_by="RANGE (reference_date)",
    )
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("raw_file_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('dividend', 'jcp', 'unknown')", name=op.f("ck_corporate_actions_kind")),
        sa.CheckConstraint(
            "source IN ('manual', 'yahoo', 'b3_strike_adjustment')", name=op.f("ck_corporate_actions_source")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_corporate_actions_amount_positive")),
        sa.ForeignKeyConstraint(
            ["raw_file_id"], ["raw_files.id"], name=op.f("fk_corporate_actions_raw_file_id_raw_files")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_actions")),
        sa.UniqueConstraint("ticker", "ex_date", "source", name="uq_corporate_actions_ticker_day_source"),
    )
    op.create_table(
        "daily_bars",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("avg_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("volume", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("raw_file_id", sa.BigInteger(), nullable=False),
        sa.Column("r4_check", sa.Text(), server_default="not_checked", nullable=False),
        sa.Column("r4_diff", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "r4_check IN ('not_checked', 'ok', 'diverged')", name=op.f("ck_daily_bars_r4_check")
        ),
        sa.ForeignKeyConstraint(
            ["raw_file_id"], ["raw_files.id"], name=op.f("fk_daily_bars_raw_file_id_raw_files")
        ),
        sa.PrimaryKeyConstraint("ticker", "trade_date", name=op.f("pk_daily_bars")),
    )
    op.create_table(
        "option_daily_stats",
        sa.Column("series_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("avg_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("last", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("best_bid", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("best_ask", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("trades_count", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("volume", sa.Numeric(precision=24, scale=2), nullable=False),
        sa.Column("raw_file_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["raw_file_id"], ["raw_files.id"], name=op.f("fk_option_daily_stats_raw_file_id_raw_files")
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["option_series.id"], name=op.f("fk_option_daily_stats_series_id_option_series")
        ),
        sa.PrimaryKeyConstraint("series_id", "trade_date", name=op.f("pk_option_daily_stats")),
    )
    op.create_index("ix_option_daily_stats_date", "option_daily_stats", ["trade_date"], unique=False)
    op.create_table(
        "risk_free_rates",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column("series_code", sa.Integer(), nullable=False),
        sa.Column("raw_file_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["raw_file_id"], ["raw_files.id"], name=op.f("fk_risk_free_rates_raw_file_id_raw_files")
        ),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_risk_free_rates")),
    )
    op.create_table(
        "series_adjustments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("series_id", sa.BigInteger(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("previous_date", sa.Date(), nullable=False),
        sa.Column("old_strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("new_strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("new_series_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["new_series_id"],
            ["option_series.id"],
            name=op.f("fk_series_adjustments_new_series_id_option_series"),
        ),
        sa.ForeignKeyConstraint(
            ["series_id"], ["option_series.id"], name=op.f("fk_series_adjustments_series_id_option_series")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series_adjustments")),
        sa.UniqueConstraint("series_id", "effective_date", name="uq_series_adjustments_day"),
    )
    underlyings = op.create_table(
        "underlyings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ticker ~ '^[A-Z0-9]{4,12}$'", name=op.f("ck_underlyings_ticker_format")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_underlyings_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_underlyings")),
        sa.UniqueConstraint("user_id", "ticker", name="uq_underlyings_user_ticker"),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("origin IN ('manual', 'initial_load')", name=op.f("ck_collection_runs_origin")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'interrupted', 'failed')",
            name=op.f("ck_collection_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_collection_runs_config_version_id_config_versions"),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_collection_runs_job_id_jobs")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_collection_runs_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_runs")),
    )
    op.create_index(
        "uq_collection_runs_one_active",
        "collection_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "collection_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("underlying", sa.Text(), nullable=True),
        sa.Column("phase", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("permanent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_file_id", sa.BigInteger(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source IN ('b3_cotahist_annual', 'b3_cotahist_daily', 'bcb_selic', 'yahoo_dividends', 'b3_trades')",
            name=op.f("ck_collection_items_source"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ok', 'empty', 'failed')", name=op.f("ck_collection_items_status")
        ),
        sa.ForeignKeyConstraint(
            ["raw_file_id"], ["raw_files.id"], name=op.f("fk_collection_items_raw_file_id_raw_files")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["collection_runs.id"], name=op.f("fk_collection_items_run_id_collection_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_items")),
    )
    op.create_index(
        "ix_collection_items_done",
        "collection_items",
        ["source", "key", "trade_date"],
        unique=False,
        postgresql_where=sa.text("status <> 'pending'"),
    )
    op.create_index(
        "ix_collection_items_next",
        "collection_items",
        ["run_id", "phase", sa.text("trade_date DESC"), "id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_collection_items_run_key",
        "collection_items",
        ["run_id", "source", "key", "trade_date"],
        unique=True,
    )

    op.bulk_insert(
        holidays,
        [
            {"day": h.day, "source": h.source, "confirmed": h.confirmed, "note": h.note}
            for h in seed_holidays()
        ],
    )
    # Universo inicial (PRD-NF-04). ISINs conferidos no COTAHIST de 19/11/2026.
    op.bulk_insert(
        underlyings,
        [
            {"user_id": FIXED_USER_ID, "ticker": ticker, "isin": isin, "active": True}
            for ticker, isin in (
                ("BOVA11", "BRBOVACTF003"),
                ("BBAS3", "BRBBASACNOR3"),
                ("PETR4", "BRPETRACNPR6"),
            )
        ],
    )


def downgrade() -> None:
    op.drop_index("uq_collection_items_run_key", table_name="collection_items")
    op.drop_index(
        "ix_collection_items_next",
        table_name="collection_items",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        "ix_collection_items_done",
        table_name="collection_items",
        postgresql_where=sa.text("status <> 'pending'"),
    )
    op.drop_table("collection_items")
    op.drop_index(
        "uq_collection_runs_one_active",
        table_name="collection_runs",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_table("collection_runs")
    op.drop_table("underlyings")
    op.drop_table("series_adjustments")
    op.drop_table("risk_free_rates")
    op.drop_index("ix_option_daily_stats_date", table_name="option_daily_stats")
    op.drop_table("option_daily_stats")
    op.drop_table("daily_bars")
    op.drop_table("corporate_actions")
    op.drop_table("trades")
    op.drop_index("ix_raw_files_query", table_name="raw_files")
    op.drop_table("raw_files")
    op.drop_index("ix_option_series_isin_expiry", table_name="option_series")
    op.drop_table("option_series")
    op.drop_table("exchange_holidays")

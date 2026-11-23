"""Previsão de RV e avaliação de modelos (Etapa 4).

PRD 1.7 §5.7 e §6.4: previsões por modelo, pregão e horizonte com o estado do modelo
(`rv_forecasts`, RF-PRV-01/02), erro por modelo e baseline em janelas não sobrepostas
(`forecast_evaluations`, RF-PRV-03, RN-PRV-01) e as origens avaliadas
(`forecast_evaluation_points`, T-REF-09, CS-03).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODELS = "('ewma', 'combination', 'garch')"
_EVALUATED = "('ewma', 'combination', 'garch', 'rv_c2c_20', 'implied')"


def _config_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["config_version_id"],
        ["config_versions.id"],
        name=op.f(f"fk_{table}_config_version_id_config_versions"),
    )


def upgrade() -> None:
    op.create_table(
        "rv_forecasts",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("horizon_bd", sa.SmallInteger(), nullable=False),
        sa.Column("vol", sa.Double(), nullable=True),
        sa.Column("ci_low", sa.Double(), nullable=True),
        sa.Column("ci_high", sa.Double(), nullable=True),
        sa.Column("ci_origin", sa.Text(), nullable=True),
        sa.Column("ci_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.CheckConstraint(f"model IN {_MODELS}", name=op.f("ck_rv_forecasts_model")),
        sa.CheckConstraint(
            "status IN ('ok', 'insufficient_data', 'unavailable')", name=op.f("ck_rv_forecasts_status")
        ),
        sa.CheckConstraint("(status = 'ok') = (vol IS NOT NULL)", name=op.f("ck_rv_forecasts_value_status")),
        sa.CheckConstraint(
            "ci_origin IS NULL OR ci_origin IN ('estimated', 'approximate')",
            name=op.f("ck_rv_forecasts_ci_origin"),
        ),
        _config_fk("rv_forecasts"),
        sa.PrimaryKeyConstraint("ticker", "as_of", "model", "horizon_bd", name=op.f("pk_rv_forecasts")),
    )
    op.create_table(
        "forecast_evaluations",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("horizon_bd", sa.SmallInteger(), nullable=False),
        sa.Column("n_windows", sa.Integer(), nullable=False),
        sa.Column("discarded", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bias", sa.Double(), nullable=True),
        sa.Column("mae", sa.Double(), nullable=True),
        sa.Column("rmse", sa.Double(), nullable=True),
        sa.Column("rmse_ci_low", sa.Double(), nullable=True),
        sa.Column("rmse_ci_high", sa.Double(), nullable=True),
        sa.Column("ratios", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("log_q_low", sa.Double(), nullable=True),
        sa.Column("log_q_high", sa.Double(), nullable=True),
        sa.Column("first_origin", sa.Date(), nullable=True),
        sa.Column("last_origin", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ci_level", sa.Double(), nullable=False),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"model IN {_EVALUATED}", name=op.f("ck_forecast_evaluations_model")),
        sa.CheckConstraint(
            "status IN ('ok', 'insufficient_data')", name=op.f("ck_forecast_evaluations_status")
        ),
        _config_fk("forecast_evaluations"),
        sa.PrimaryKeyConstraint("ticker", "model", "horizon_bd", name=op.f("pk_forecast_evaluations")),
    )
    op.create_table(
        "forecast_evaluation_points",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("horizon_bd", sa.SmallInteger(), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("forecast", sa.Double(), nullable=True),
        sa.Column("realized", sa.Double(), nullable=True),
        sa.Column("discard_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(f"model IN {_EVALUATED}", name=op.f("ck_forecast_evaluation_points_model")),
        sa.PrimaryKeyConstraint(
            "ticker", "model", "horizon_bd", "origin", name=op.f("pk_forecast_evaluation_points")
        ),
    )


def downgrade() -> None:
    op.drop_table("forecast_evaluation_points")
    op.drop_table("forecast_evaluations")
    op.drop_table("rv_forecasts")

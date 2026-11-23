"""Custos, edge e ranking (Etapa 5).

PRD 1.8 §5.6.1 e §6.2: spread estimado por ativo, pregão e faixa de moneyness
(`option_spread_estimates`, RN-CST-03), calculado no `vol_recompute` a partir dos negócios.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "option_spread_estimates",
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column("n_series", sa.Integer(), nullable=False),
        sa.Column("n_trades", sa.Integer(), nullable=False),
        sa.Column("rel_median", sa.Double(), nullable=True),
        sa.Column("rel_p75", sa.Double(), nullable=True),
        sa.Column("quoted_rel_median", sa.Double(), nullable=True),
        sa.Column("config_version_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "band IN ('low', 'atm', 'high', 'underlying')", name=op.f("ck_option_spread_estimates_band")
        ),
        sa.CheckConstraint("n_series >= 0 AND n_trades >= 0", name=op.f("ck_option_spread_estimates_counts")),
        sa.CheckConstraint(
            "(n_series = 0) = (rel_median IS NULL)", name=op.f("ck_option_spread_estimates_value_counts")
        ),
        sa.CheckConstraint(
            "rel_median IS NULL OR rel_median > 0", name=op.f("ck_option_spread_estimates_positive")
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["config_versions.id"],
            name=op.f("fk_option_spread_estimates_config_version_id_config_versions"),
        ),
        sa.PrimaryKeyConstraint("ticker", "trade_date", "band", name=op.f("pk_option_spread_estimates")),
    )


def downgrade() -> None:
    op.drop_table("option_spread_estimates")

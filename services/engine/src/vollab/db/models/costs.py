"""Spread estimado por ativo, pregão e faixa (PRD 1.8 §5.6.1 e §6.2; RN-CST-03).

Gravado no worker (`vol_recompute`), a partir dos negócios do dia; as telas e o ranking só leem.
Spreads relativos em decimal (spread ÷ preço). Uma linha por faixa sempre, mesmo sem séries
(n_series = 0 e valores nulos): marca o pregão como calculado.
"""

from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, Double, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base

SPREAD_BANDS = ("low", "atm", "high", "underlying")


class OptionSpreadEstimate(Base):
    __tablename__ = "option_spread_estimates"
    __table_args__ = (
        CheckConstraint(f"band IN {SPREAD_BANDS}", name="band"),
        CheckConstraint("n_series >= 0 AND n_trades >= 0", name="counts"),
        CheckConstraint("(n_series = 0) = (rel_median IS NULL)", name="value_counts"),
        CheckConstraint("rel_median IS NULL OR rel_median > 0", name="positive"),
    )

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    band: Mapped[str] = mapped_column(Text, primary_key=True)
    n_series: Mapped[int] = mapped_column(Integer, nullable=False)
    n_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    rel_median: Mapped[float | None] = mapped_column(Double)
    rel_p75: Mapped[float | None] = mapped_column(Double)
    quoted_rel_median: Mapped[float | None] = mapped_column(Double)
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )

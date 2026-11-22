"""Coleta sob demanda (PRD §6.3, ADR-07, RF-DAD-06)."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from vollab.db.base import Base, CreatedAtMixin

RUN_STATUSES = ("queued", "running", "succeeded", "partial", "interrupted", "failed")
ITEM_STATUSES = ("pending", "ok", "empty", "failed")
ITEM_SOURCES = ("b3_cotahist_annual", "b3_cotahist_daily", "bcb_selic", "yahoo_dividends", "b3_trades")


class CollectionRun(CreatedAtMixin, Base):
    """Uma execução da coleta. `partial` = terminou com itens em falha; `interrupted` = parou por
    falhas transitórias seguidas (fonte fora do ar ou bloqueio) e pode ser retomada."""

    __tablename__ = "collection_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
        CheckConstraint("origin IN ('manual', 'initial_load')", name="origin"),
        # Só uma coleta ativa por usuário (ADR-07: o usuário dispara; não há execução paralela).
        Index(
            "uq_collection_runs_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    config_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("config_versions.id"), nullable=False
    )
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("jobs.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)


class CollectionItem(Base):
    """Um item por fonte × chave × pregão (PRD §6.3).

    `key` é o ticker (negócios, Yahoo), o ano (`2026`, COTAHIST anual) ou `-` (COTAHIST diário,
    Selic). `phase` define a ordem: COTAHIST → Selic e proventos → ativo-objeto → opções
    (PRD-NF-04). Status `failed` com `permanent` (HTTP 404) não é tentado de novo.
    """

    __tablename__ = "collection_items"
    __table_args__ = (
        CheckConstraint(f"status IN {ITEM_STATUSES}", name="status"),
        CheckConstraint(f"source IN {ITEM_SOURCES}", name="source"),
        Index("uq_collection_items_run_key", "run_id", "source", "key", "trade_date", unique=True),
        Index(
            "ix_collection_items_next",
            "run_id",
            "phase",
            text("trade_date DESC"),
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_collection_items_done",
            "source",
            "key",
            "trade_date",
            postgresql_where=text("status <> 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("collection_runs.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Ativo-objeto ao qual o item pertence (relatório de lacunas por ativo e data).
    underlying: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    permanent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    raw_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_files.id"))
    rows: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

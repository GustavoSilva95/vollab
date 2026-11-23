"""Execução da coleta no worker (ADR-07/08, RF-DAD-06, PRD-NF-03/10).

- Uma execução (`collection_runs`) vira um job `collection_run` na fila.
- Os itens são processados um a um, com commit por item: o progresso fica visível e uma
  interrupção retoma do próximo item pendente.
- Erro de um item nunca derruba a coleta (PRD-NF-10). Falhas transitórias seguidas
  (fonte fora do ar, bloqueio do Cloudflare) interrompem a execução, que pode ser retomada.
- Antes de baixar, reaproveita o cache bruto da mesma consulta (RF-DAD-04).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from vollab.collection import ingest
from vollab.collection.params import CollectionParams, ensure_config_version, params_from_config
from vollab.collection.planner import (
    PHASE_OPTIONS,
    ItemSpec,
    active_underlyings,
    build_plan,
    option_items_for_day,
    today_sao_paulo,
)
from vollab.data.b3_cotahist import CotahistParseError
from vollab.data.b3_trades import TradesParseError
from vollab.data.bcb import SgsParseError
from vollab.data.http import SourceNotFoundError, SourceResponseError, TransientSourceError
from vollab.data.raw_cache import RawCache
from vollab.data.safe_zip import UnsafeArchiveError
from vollab.data.sources import Fetched, MarketDataSources, build_sources
from vollab.data.yahoo import YahooParseError
from vollab.db.models import CollectionItem, CollectionRun, ConfigVersion, Job, RawFile
from vollab.jobs import queue
from vollab.jobs.control import JobInterruptedError, stop_requested
from vollab.jobs.handlers import register
from vollab.settings import Settings, get_settings

log = structlog.get_logger("vollab.collection")

JOB_KIND = "collection_run"
PARSE_ERRORS = (
    TradesParseError,
    CotahistParseError,
    SgsParseError,
    YahooParseError,
    UnsafeArchiveError,
)
ACTIVE = ("queued", "running")


class ActiveRunError(Exception):
    """Já existe uma coleta em andamento."""


# --- Criação ------------------------------------------------------------------------------


def create_run(session: Session, *, user_id: uuid.UUID, settings: Settings | None = None) -> CollectionRun:
    """Cria a execução e o job do worker. Uma só ativa por usuário (índice único parcial)."""
    settings = settings or get_settings()
    _close_orphan_runs(session, user_id=user_id)
    active = session.scalar(
        select(CollectionRun).where(CollectionRun.user_id == user_id, CollectionRun.status.in_(ACTIVE))
    )
    if active is not None:
        raise ActiveRunError(active.id)
    version = ensure_config_version(session, user_id=user_id)
    previous = session.scalar(
        select(func.count())
        .select_from(CollectionRun)
        .where(CollectionRun.user_id == user_id, CollectionRun.status.in_(("succeeded", "partial")))
    )
    run = CollectionRun(
        user_id=user_id,
        origin="manual" if previous else "initial_load",
        status="queued",
        config_version_id=version.id,
        reference_date=today_sao_paulo(settings),
    )
    session.add(run)
    session.flush()
    job = queue.enqueue(session, user_id=user_id, kind=JOB_KIND, payload={"run_id": run.id}, max_attempts=3)
    run.job_id = job.id
    session.commit()
    return run


def _close_orphan_runs(session: Session, *, user_id: uuid.UUID) -> None:
    """Execução ativa cujo job já falhou de vez (erro inesperado repetido) não pode travar novas coletas."""
    orphans = session.scalars(
        select(CollectionRun)
        .join(Job, Job.id == CollectionRun.job_id)
        .where(CollectionRun.user_id == user_id, CollectionRun.status.in_(ACTIVE), Job.status == "failed")
    ).all()
    for run in orphans:
        run.status = "failed"
        run.finished_at = func.now()
        run.message = "A execução falhou no worker. Inicie uma nova coleta para retomar os itens pendentes."
    if orphans:
        session.commit()


# --- Execução -----------------------------------------------------------------------------


@dataclass
class Outcome:
    status: str  # ok | empty | failed
    permanent: bool = False
    error: str | None = None
    rows: int | None = None
    raw_file_id: int | None = None
    transient: bool = False


class Collector:
    def __init__(
        self,
        session: Session,
        *,
        sources: MarketDataSources,
        cache: RawCache,
        settings: Settings,
        stop: Callable[[], bool] = stop_requested,
    ) -> None:
        self.session = session
        self.sources = sources
        self.cache = cache
        self.settings = settings
        self.stop = stop

    # Planejamento -------------------------------------------------------------------------

    def plan(self, run: CollectionRun, params: CollectionParams) -> None:
        plan = build_plan(self.session, user_id=run.user_id, today=run.reference_date, params=params)
        # Partições de `trades` criadas aqui, numa transação curta, e não dentro de cada item: criar
        # partição trava o pai até o commit (revisão de performance da Etapa 2).
        for month in sorted({d.replace(day=1) for d in plan.intraday_days}):
            ingest.ensure_trades_partition(self.session, month)
        self.session.commit()
        self._insert_items(run.id, plan.items)
        self.session.commit()
        log.info(
            "collection.planned",
            run_id=run.id,
            items=len(plan.items),
            reference_date=str(plan.reference_date),
        )

    def _insert_items(self, run_id: int, specs: list[ItemSpec]) -> None:
        if not specs:
            return
        values = [
            {
                "run_id": run_id,
                "source": s.source,
                "key": s.key,
                "trade_date": s.trade_date,
                "underlying": s.underlying,
                "phase": s.phase,
            }
            for s in specs
        ]
        for start in range(0, len(values), 5000):
            self.session.execute(
                insert(CollectionItem).values(values[start : start + 5000]).on_conflict_do_nothing()
            )

    # Laço ---------------------------------------------------------------------------------

    def execute(self, run: CollectionRun) -> None:
        version = self.session.get(ConfigVersion, run.config_version_id)
        if version is None:
            raise RuntimeError("Configuração da execução não encontrada.")
        params = params_from_config(version)
        run.status = "running"
        run.started_at = run.started_at or func.now()
        self.session.commit()
        self.plan(run, params)
        bound = log.bind(run_id=run.id)
        consecutive = 0
        while True:
            if self.stop():
                bound.info("collection.paused_by_worker_stop")
                raise JobInterruptedError("Worker encerrado; a coleta continua quando ele voltar.")
            item = self.session.scalar(
                select(CollectionItem)
                .where(CollectionItem.run_id == run.id, CollectionItem.status == "pending")
                .order_by(CollectionItem.phase, CollectionItem.trade_date.desc(), CollectionItem.id)
                .limit(1)
            )
            if item is None:
                break
            outcome = self._process(item)
            item.attempts += 1
            item.status = outcome.status
            item.permanent = outcome.permanent
            item.error = outcome.error
            item.rows = outcome.rows
            item.raw_file_id = outcome.raw_file_id
            if item.source == "b3_cotahist_daily" and outcome.status == "ok":
                underlyings = active_underlyings(self.session, user_id=run.user_id)
                self._insert_items(
                    run.id,
                    option_items_for_day(
                        self.session, day=item.trade_date, underlyings=underlyings, params=params
                    ),
                )
            self._heartbeat(run)
            self.session.commit()
            if outcome.status == "failed":
                bound.warning(
                    "collection.item_failed",
                    source=item.source,
                    key=item.key,
                    day=str(item.trade_date),
                    error=item.error,
                )
            consecutive = consecutive + 1 if outcome.transient else 0
            if consecutive >= self.settings.collection_max_consecutive_failures:
                run.status = "interrupted"
                run.finished_at = func.now()
                run.message = (
                    f"Coleta interrompida após {consecutive} falhas seguidas da fonte "
                    "(fora do ar ou bloqueio). Os itens restantes continuam pendentes: tente mais tarde."
                )
                self._enqueue_recompute(run)
                self.session.commit()
                bound.warning("collection.interrupted", consecutive=consecutive)
                return
        failed = self.session.scalar(
            select(func.count())
            .select_from(CollectionItem)
            .where(CollectionItem.run_id == run.id, CollectionItem.status == "failed")
        )
        run.status = "partial" if failed else "succeeded"
        run.finished_at = func.now()
        # Sem números no texto: a interface formata contagens (PRD-UI-03) a partir do progresso.
        run.message = "Há itens com falha: veja o relatório de lacunas." if failed else None
        self._enqueue_recompute(run)
        self.session.commit()
        bound.info("collection.finished", status=run.status, failed=failed)

    def _enqueue_recompute(self, run: CollectionRun) -> None:
        """Recálculos de volatilidade no worker após a coleta (PRD §5.5, PRD-NF-06)."""
        days = list(
            self.session.scalars(
                select(CollectionItem.trade_date)
                .where(
                    CollectionItem.run_id == run.id,
                    CollectionItem.source.in_(("b3_trades", "b3_cotahist_daily")),
                    CollectionItem.status == "ok",
                )
                .distinct()
            )
        )
        # Import tardio: `analytics` depende de `collection` (parâmetros e fases).
        from vollab.analytics.recompute import enqueue_recompute

        enqueue_recompute(self.session, user_id=run.user_id, days=days, reason=f"coleta {run.id}")

    def _heartbeat(self, run: CollectionRun) -> None:
        # Mantém o lock do job recente: uma coleta longa não pode parecer travada (requeue_stale).
        if run.job_id is not None:
            self.session.execute(update(Job).where(Job.id == run.job_id).values(locked_at=func.now()))

    # Um item ------------------------------------------------------------------------------

    def _process(self, item: CollectionItem) -> Outcome:
        try:
            fetched, raw = self._fetch_or_reuse(item)
        except SourceNotFoundError:
            # 404 no rapinegocios = ticker inexistente (Etapa 0 §2): não adianta repetir. Nas demais
            # fontes pode ser arquivo ainda não publicado (ex.: COTAHIST do dia, à noite).
            permanent = item.source == "b3_trades"
            detail = "ticker inexistente" if permanent else "arquivo ainda não publicado ou inexistente"
            return Outcome(
                "failed", permanent=permanent, error=f"Não encontrado na fonte (HTTP 404: {detail})."
            )
        except TransientSourceError as exc:
            return Outcome("failed", error=f"Fonte indisponível: {exc}", transient=True)
        except SourceResponseError as exc:
            return Outcome("failed", error=f"Resposta inesperada da fonte: {exc}")
        except Exception as exc:  # disco cheio, cache com hash divergente etc.: falha do item (PRD-NF-10)
            log.error("collection.fetch_error", source=item.source, key=item.key, error=type(exc).__name__)
            self.session.rollback()
            return Outcome("failed", error=f"Erro ao obter o arquivo ({type(exc).__name__}).")
        try:
            with self.session.begin_nested():
                result = self._ingest(item, fetched.content, raw.id)
        except PARSE_ERRORS as exc:
            raw.parse_status = "error"
            raw.parse_error = str(exc)[:500]
            return Outcome("failed", error=f"Arquivo inválido: {exc}", raw_file_id=raw.id)
        except Exception as exc:  # erro inesperado de um item não derruba a coleta (PRD-NF-10)
            # Só o tipo: a mensagem e o traceback podem ecoar conteúdo da fonte (B-5).
            log.error("collection.item_error", source=item.source, key=item.key, error=type(exc).__name__)
            raw.parse_status = "error"
            raw.parse_error = type(exc).__name__
            return Outcome(
                "failed", error=f"Erro interno ao gravar ({type(exc).__name__}).", raw_file_id=raw.id
            )
        raw.parse_status = "empty" if result.empty else "ok"
        raw.parse_error = None
        return Outcome("empty" if result.empty else "ok", rows=result.rows, raw_file_id=raw.id)

    def _fetch_or_reuse(self, item: CollectionItem) -> tuple[Fetched, RawFile]:
        cached = self.session.scalar(
            select(RawFile)
            .where(
                RawFile.source == item.source,
                RawFile.query_key == item.key,
                RawFile.query_date == item.trade_date,
                RawFile.parse_status.in_(("ok", "empty")),
            )
            .order_by(RawFile.id.desc())
            .limit(1)
        )
        # O anual e o Selic mudam com o tempo: só o diário e os negócios são reaproveitados.
        if cached is not None and item.source in ("b3_cotahist_daily", "b3_trades"):
            content = self.cache.read(cached.relative_path, expected_sha256=cached.sha256)
            return Fetched(cached.http_status, content, cached.content_format), cached
        fetched = self._download(item)
        ext = fetched.content_format if fetched.content_format in ("zip", "json", "csv") else "bin"
        stored = self.cache.store(item.source, fetched.content, ext)
        raw = RawFile(
            source=item.source,
            query_key=item.key,
            query_date=item.trade_date,
            relative_path=stored.relative_path,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            http_status=fetched.http_status,
            content_format=fetched.content_format,
        )
        self.session.add(raw)
        self.session.flush()
        return fetched, raw

    def _download(self, item: CollectionItem) -> Fetched:
        match item.source:
            case "b3_trades":
                return self.sources.trades(item.key, item.trade_date)
            case "b3_cotahist_daily":
                return self.sources.cotahist_daily(item.trade_date)
            case "b3_cotahist_annual":
                return self.sources.cotahist_annual(int(item.key))
            case "bcb_selic":
                start = date(item.trade_date.year - 2, 1, 1)
                return self.sources.selic(start, item.trade_date)
            case "yahoo_dividends":
                return self.sources.dividends(item.key)
        raise ValueError(f"Fonte desconhecida: {item.source}")

    def _ingest(self, item: CollectionItem, content: bytes, raw_file_id: int) -> ingest.IngestResult:
        match item.source:
            case "b3_trades":
                return ingest.ingest_trades(
                    self.session,
                    content=content,
                    raw_file_id=raw_file_id,
                    ticker=item.key,
                    day=item.trade_date,
                    is_underlying=item.phase != PHASE_OPTIONS,
                )
            case "b3_cotahist_daily" | "b3_cotahist_annual":
                return ingest.ingest_cotahist(
                    self.session,
                    content=content,
                    raw_file_id=raw_file_id,
                    annual=item.source == "b3_cotahist_annual",
                    universe=ingest.load_universe(self.session),
                )
            case "bcb_selic":
                return ingest.ingest_selic(self.session, content=content, raw_file_id=raw_file_id)
            case "yahoo_dividends":
                return ingest.ingest_dividends(
                    self.session, content=content, raw_file_id=raw_file_id, ticker=item.key
                )
        raise ValueError(f"Fonte desconhecida: {item.source}")


@register(JOB_KIND)
def run_collection_job(session: Session, payload: dict[str, object]) -> None:
    run_id = payload.get("run_id")
    if not isinstance(run_id, int):
        raise ValueError("Job de coleta sem run_id.")
    run = session.get(CollectionRun, run_id)
    if run is None or run.status not in ACTIVE:
        return
    settings = get_settings()
    sources = build_sources(settings)
    try:
        Collector(session, sources=sources, cache=RawCache(settings.raw_data_dir), settings=settings).execute(
            run
        )
    finally:
        sources.close()

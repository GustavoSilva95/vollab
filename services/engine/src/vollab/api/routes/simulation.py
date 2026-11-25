"""Simulador, dimensionamento e registro da entrada (PRD 1.9 §5.8 e §7; BRD 1.6 RF-SIM-01..05,
RN-SIZ-01..06, RF-DIA-01, RN-EDG-06, CS-01).

`/simulations`, `/sizing` e `/underlyings/{t}/chain` não gravam nada. `POST /positions` é a única
escrita: recalcula tudo no servidor a partir dos insumos e grava o retrato imutável da decisão.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from vollab.analytics.journal import (
    book_of,
    enqueue_marks,
    ledger_entry,
    load_entries,
    lock_position,
    position_view,
    summaries,
)
from vollab.analytics.portfolio import PortfolioComputer
from vollab.analytics.simulation import SimulationComputer, SimulationInputError
from vollab.api.schemas.common import ProblemDetails
from vollab.api.schemas.simulation import (
    ChainResponse,
    PositionCreate,
    PositionOut,
    PositionSummary,
    RollFrom,
    SimulationRequest,
    SimulationResponse,
    SizingRequest,
    SizingResponse,
)
from vollab.collection.params import ensure_config_version
from vollab.db.models import FIXED_USER_ID, ManualInput, Position, PositionEntry
from vollab.db.session import get_session
from vollab.quant.edge import EdgeState
from vollab.quant.journal import EntryKind, LedgerEntry, LedgerError, replay
from vollab.settings import get_settings

router = APIRouter(tags=["simulação"])
SessionDep = Annotated[Session, Depends(get_session)]
ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Ativo não cadastrado."},
    422: {"model": ProblemDetails, "description": "Insumo inválido ou ausente (com o motivo)."},
}
MAX_POSITIONS = 500
# Partes pesadas da resposta que não vão para o retrato (PRD §5.4: "distribuição simulada resumida").
SNAPSHOT_DROP = {"payoff", "hist_edges_brl", "hist_counts"}


def _computer(session: Session) -> SimulationComputer:
    return SimulationComputer(session, user_id=FIXED_USER_ID)


def _run(fn: Any, *args: Any) -> Any:
    try:
        result = fn(*args)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except SimulationInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return result


@router.get(
    "/underlyings/{ticker}/chain",
    response_model=ChainResponse,
    summary="Séries de um vencimento para montar a estrutura",
    responses=ERRORS,
)
def get_chain(
    session: SessionDep,
    ticker: Annotated[str, Path(pattern=r"^[A-Za-z0-9]{4,12}$")],
    expiry: Annotated[date | None, Query(description="Vencimento; sem ele, o mais próximo.")] = None,
) -> ChainResponse:
    chain: ChainResponse = _run(_computer(session).chain, ticker.upper(), expiry)
    return chain


@router.post(
    "/simulations",
    response_model=SimulationResponse,
    summary="Simular uma estrutura (não grava nada)",
    responses=ERRORS,
)
def post_simulation(body: SimulationRequest, session: SessionDep) -> SimulationResponse:
    response: SimulationResponse = _run(_computer(session).compute, body).response
    return response


@router.post(
    "/sizing",
    response_model=SizingResponse,
    summary="Simular e dimensionar: Kelly fracionado e teto (não grava nada)",
    responses=ERRORS,
)
def post_sizing(body: SizingRequest, session: SessionDep) -> SizingResponse:
    out: SizingResponse = _run(_computer(session).sizing_response, body)
    return out


def _roll_entries(session: Session, body: PositionCreate) -> list[PositionEntry]:
    """Lançamentos `roll` na posição de origem, validados pela reexecução do livro (RN-GES-04, RS-06).
    422 se a origem não existir, já estiver encerrada ou se o fechamento for inconsistente."""
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    roll = cast(RollFrom, body.roll_from)
    origin = session.get(Position, roll.position_id)
    if origin is None or origin.user_id != FIXED_USER_ID:
        raise HTTPException(unprocessable, "Rolagem: operação de origem inexistente.")
    if origin.ticker != body.ticker.upper():
        raise HTTPException(unprocessable, "Rolagem: a nova posição deve ser do mesmo ativo-objeto.")
    lock_position(session, origin.id)
    if body.executed_at > datetime.now(UTC):
        raise HTTPException(unprocessable, "Rolagem: data de execução no futuro.")
    rows = load_entries(session, origin.id)
    book = book_of(session, origin.ticker, rows)
    existing = [ledger_entry(e) for e in rows]
    if not replay(existing, book).is_open:
        raise HTTPException(unprocessable, "Rolagem: a operação de origem já está encerrada.")
    version = ensure_config_version(session, user_id=FIXED_USER_ID)
    out: list[PositionEntry] = []
    news: list[LedgerEntry] = []
    for i, leg in enumerate(roll.legs):
        opt = book.options.get(leg.instrument)
        news.append(
            LedgerEntry(
                id=2_000_000_000 + i,
                kind=EntryKind.ROLL,
                instrument=leg.instrument,
                quantity=leg.quantity,
                price=leg.price_brl,
                fees=leg.fees_brl,
                brokerage=leg.brokerage_brl,
                executed_at=body.executed_at,
                series_id=opt.series_id if opt else None,
            )
        )
        out.append(
            PositionEntry(
                position_id=origin.id,
                user_id=FIXED_USER_ID,
                kind="roll",
                instrument=leg.instrument,
                series_id=opt.series_id if opt else None,
                quantity=leg.quantity,
                price=leg.price_brl,
                fees_brl=leg.fees_brl,
                brokerage_brl=leg.brokerage_brl,
                executed_at=body.executed_at,
                note="rolagem",
                config_version_id=version.id,
                engine_version=get_settings().engine_version,
            )
        )
    try:
        replay([*existing, *news], book)
    except LedgerError as exc:
        raise HTTPException(unprocessable, f"Rolagem: {exc}") from None
    return out


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in SNAPSHOT_DROP}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


@router.post(
    "/positions",
    response_model=PositionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar a entrada com o retrato da decisão",
    responses=ERRORS | {409: {"model": ProblemDetails, "description": "A configuração mudou."}},
)
def post_position(body: PositionCreate, session: SessionDep) -> PositionOut:
    computer = _computer(session)
    current = computer.rk.p.version_id
    if body.base_config_version_id != current:
        session.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A configuração mudou desde a simulação (vigente: versão {current}; simulada: versão "
            f"{body.base_config_version_id}). Simule de novo antes de registrar.",
        )
    comp, sizing = _run(computer.sizing, body)
    sim = comp.response
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    # CS-01 por construção: não existe entrada sem semáforo.
    if sim.state == EdgeState.UNAVAILABLE.value:
        raise HTTPException(unprocessable, f"Semáforo indisponível: {sim.reason or 'falta insumo'}.")
    leg_ids = [leg.series_id for leg in body.legs]
    if sorted(e.series_id for e in body.executed_legs) != sorted(leg_ids):
        raise HTTPException(unprocessable, "As pernas executadas devem ser as mesmas da simulação.")
    if sim.stock is not None and (
        body.stock is None or body.stock.quantity != sim.stock.quantity_per_lot * body.lots
    ):
        raise HTTPException(
            unprocessable,
            f"Venda coberta exige a compra de {sim.stock.quantity_per_lot * body.lots} ações em `stock`.",
        )
    reasons = []
    if sim.state != EdgeState.EDGE.value:
        reasons.append(f"semáforo em {sim.state}")
    elif not sim.direction_match:
        reasons.append("direção da estrutura oposta à do sinal")
    if body.lots > sizing.n_final:
        reasons.append(f"{body.lots} lote(s) acima do sugerido ({sizing.n_final})")
    # PR-04: limites da carteira com a nova posição (pró-forma). A rolagem tira a posição de origem.
    roll_entries = _roll_entries(session, body) if body.roll_from is not None else []
    stock_total = body.stock.quantity if body.stock is not None else 0
    # Capital da configuração (PRD 1.10 §5.9; revisão de segurança, M-1).
    limits = PortfolioComputer(session, user_id=FIXED_USER_ID).limits(
        computer.proforma(comp, body.lots, stock_total)
    )
    breached = [x for x in limits.limits if x.state == "breached"]
    if breached:
        reasons.append(
            "limite(s) da carteira ultrapassado(s) com a nova posição: "
            + ", ".join(x.name + (f" ({x.scope})" if x.scope else "") for x in breached)
        )
    if reasons and not body.override_reason:
        raise HTTPException(
            unprocessable,
            "Entrada fora da regra ("
            + "; ".join(reasons)
            + "): informe override_reason com a justificativa.",
        )

    snapshot = _strip(
        {
            "simulation": sim.model_dump(mode="json"),
            "sizing": sizing.model_dump(mode="json"),
            "executed": {
                "lots": body.lots,
                "suggested_lots": sizing.n_final,
                "legs": [e.model_dump(mode="json") for e in body.executed_legs],
                "stock": body.stock.model_dump(mode="json") if body.stock else None,
                "executed_at": body.executed_at.isoformat(),
            },
            "override": {"required": bool(reasons), "reasons": reasons, "reason": body.override_reason},
            "limits": limits.model_dump(mode="json"),
            "roll_from": body.roll_from.model_dump(mode="json") if body.roll_from else None,
        }
    )
    position = Position(
        user_id=FIXED_USER_ID,
        ticker=sim.ticker,
        structure=sim.structure,
        direction=sim.direction,
        expiry=sim.expiry,
        as_of=sim.as_of,
        lots=body.lots,
        edge_state=sim.state,
        model=sim.model,
        config_version_id=sim.config_version_id,
        engine_version=sim.engine_version,
        override_reason=body.override_reason if reasons else None,
        note=body.note,
        decision_snapshot=snapshot,
        rolled_from_position_id=body.roll_from.position_id if body.roll_from else None,
    )
    session.add(position)
    session.flush()
    session.add_all(roll_entries)
    codes = {leg.series_id: leg for leg in sim.legs}
    for e in body.executed_legs:
        leg = codes[e.series_id]
        session.add(
            PositionEntry(
                position_id=position.id,
                user_id=FIXED_USER_ID,
                kind="entry",
                instrument=leg.code,
                series_id=e.series_id,
                quantity=leg.quantity_per_lot * body.lots,
                price=e.price_brl,
                fees_brl=e.fees_brl,
                brokerage_brl=e.brokerage_brl,
                executed_at=body.executed_at,
                config_version_id=sim.config_version_id,
                engine_version=sim.engine_version,
            )
        )
    if body.stock is not None and body.stock.quantity != 0:
        session.add(
            PositionEntry(
                position_id=position.id,
                user_id=FIXED_USER_ID,
                kind="entry",
                instrument=sim.ticker,
                series_id=None,
                quantity=body.stock.quantity,
                price=body.stock.price_brl,
                fees_brl=body.stock.fees_brl,
                brokerage_brl=body.stock.brokerage_brl,
                executed_at=body.executed_at,
                config_version_id=sim.config_version_id,
                engine_version=sim.engine_version,
            )
        )
    manual: list[tuple[str, str, Decimal, Any]] = []
    if body.manual_spot_brl is not None:
        manual.append(("spot", sim.ticker, body.manual_spot_brl, body.manual_spot_at))
    for li in body.legs:
        if li.manual_price_brl is not None:
            manual.append(("option_price", codes[li.series_id].code, li.manual_price_brl, li.manual_price_at))
    if body.margin_per_lot_brl is not None:
        manual.append(("margin", sim.ticker, body.margin_per_lot_brl, body.margin_at))
    for kind, instrument, value, at in manual:
        session.add(
            ManualInput(
                position_id=position.id,
                user_id=FIXED_USER_ID,
                kind=kind,
                instrument=instrument,
                value=value,
                observed_at=at,
            )
        )
    pids = [position.id] + ([body.roll_from.position_id] if body.roll_from else [])
    enqueue_marks(session, user_id=FIXED_USER_ID, position_ids=pids, reason="entrada")
    session.commit()
    return position_view(session, position)


@router.get("/positions", response_model=list[PositionSummary], summary="Operações registradas (diário)")
def list_positions(
    session: SessionDep,
    status_filter: Annotated[
        Literal["open", "closed"] | None, Query(alias="status", description="Filtra pelo status derivado.")
    ] = None,
) -> list[PositionSummary]:
    # Sem o retrato JSONB (~7 KB por linha): a lista só usa o resumo (revisão da Etapa 6, M-2).
    rows = session.scalars(
        select(Position)
        .options(defer(Position.decision_snapshot))
        .where(Position.user_id == FIXED_USER_ID)
        .order_by(Position.id.desc())
        .limit(MAX_POSITIONS)
    ).all()
    out = summaries(session, rows)
    session.commit()
    return [s for s in out if status_filter is None or s.status == status_filter]


@router.get(
    "/positions/{position_id}",
    response_model=PositionOut,
    summary="Uma operação: retrato, lançamentos, marcações D-1 e atribuição",
    responses={404: {"model": ProblemDetails, "description": "Operação inexistente."}},
)
def get_position(position_id: Annotated[int, Path(ge=1)], session: SessionDep) -> PositionOut:
    p = session.get(Position, position_id)
    if p is None or p.user_id != FIXED_USER_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operação inexistente.")
    out = position_view(session, p)
    session.commit()
    return out

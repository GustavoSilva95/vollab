"""Leitura dos alertas e do estado da gestão (PRD 1.11 §5.10 e §7). Só lê o que o job gravou."""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from vollab.api.schemas.alerts import (
    AlertOut,
    AlertsResponse,
    ManagementOut,
    PositionEdgeOut,
    RollOut,
    RuleOut,
)
from vollab.db.models import Alert, Position, PositionManagement

MAX_ALERTS = 200


def alert_out(a: Alert, positions: dict[int, tuple[str, str]]) -> AlertOut:
    ticker, structure = positions.get(a.position_id or 0, (None, None))
    return AlertOut(
        id=a.id,
        kind=cast(Any, a.kind),
        rule=cast(Any, a.rule),
        position_id=a.position_id,
        ticker=ticker,
        structure=structure,
        scope_key=a.scope_key,
        state=cast(Any, a.state),
        triggered_at=a.triggered_at,
        triggered_as_of=a.triggered_as_of,
        last_as_of=a.last_as_of,
        details=a.details,
        config_version_id=a.config_version_id,
        evaluated_config_version_id=a.evaluated_config_version_id,
        engine_version=a.engine_version,
        resolved_at=a.resolved_at,
        resolved_by=cast(Any, a.resolved_by),
        resolution_note=a.resolution_note,
    )


def _positions(session: Session, alerts: Sequence[Alert]) -> dict[int, tuple[str, str]]:
    ids = sorted({a.position_id for a in alerts if a.position_id is not None})
    if not ids:
        return {}
    rows = session.execute(
        select(Position.id, Position.ticker, Position.structure).where(Position.id.in_(ids))
    ).all()
    return {pid: (t, st) for pid, t, st in rows}


def list_alerts(
    session: Session,
    *,
    user_id: Any,
    state: str,
    position_id: int | None,
    kind: str | None,
) -> AlertsResponse:
    """`state`: `open` (não resolvidos, padrão), `active`, `seen`, `resolved` ou `all`. Ordem: ativos
    primeiro, depois o disparo mais recente."""
    stmt = select(Alert).where(Alert.user_id == user_id)
    if state == "open":
        stmt = stmt.where(Alert.state != "resolved")
    elif state != "all":
        stmt = stmt.where(Alert.state == state)
    if position_id is not None:
        stmt = stmt.where(Alert.position_id == position_id)
    if kind is not None:
        stmt = stmt.where(Alert.kind == kind)
    order = case((Alert.state == "active", 0), (Alert.state == "seen", 1), else_=2)
    rows = session.scalars(
        stmt.order_by(order, Alert.triggered_at.desc(), Alert.id.desc()).limit(MAX_ALERTS)
    ).all()
    counts = dict.fromkeys(("active", "seen", "resolved"), 0) | dict(
        session.execute(
            select(Alert.state, func.count()).where(Alert.user_id == user_id).group_by(Alert.state)
        ).all()
    )
    pos = _positions(session, rows)
    return AlertsResponse(alerts=[alert_out(a, pos) for a in rows], counts=cast(Any, counts))


def management_view(session: Session, position: Position) -> ManagementOut | None:
    row = session.get(PositionManagement, position.id)
    if row is None:
        return None
    alerts = session.scalars(
        select(Alert)
        .where(Alert.user_id == position.user_id, Alert.position_id == position.id)
        .order_by(Alert.triggered_at.desc(), Alert.id.desc())
        .limit(50)
    ).all()
    pos = {position.id: (position.ticker, position.structure)}
    return ManagementOut(
        as_of=row.as_of,
        evaluated_at=row.evaluated_at,
        config_version_id=row.config_version_id,
        rules=[RuleOut.model_validate(r) for r in row.rules],
        edge=PositionEdgeOut.model_validate(row.edge) if row.edge else None,
        roll=RollOut.model_validate(row.roll) if row.roll else None,
        alerts=[alert_out(a, pos) for a in alerts],
    )

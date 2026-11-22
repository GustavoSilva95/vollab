"""Modelos SQLAlchemy. Importar aqui registra as tabelas no `Base.metadata` (usado pelo Alembic)."""

from vollab.db.models.collection import CollectionItem, CollectionRun
from vollab.db.models.config_version import ConfigVersion
from vollab.db.models.job import Job, JobStatus
from vollab.db.models.market import DailyBar, OptionDailyStat, RawFile, trades
from vollab.db.models.reference import (
    CorporateAction,
    ExchangeHoliday,
    OptionSeries,
    RiskFreeRate,
    SeriesAdjustment,
    Underlying,
)
from vollab.db.models.user import FIXED_USER_ID, User

__all__ = [
    "FIXED_USER_ID",
    "CollectionItem",
    "CollectionRun",
    "ConfigVersion",
    "CorporateAction",
    "DailyBar",
    "ExchangeHoliday",
    "Job",
    "JobStatus",
    "OptionDailyStat",
    "OptionSeries",
    "RawFile",
    "RiskFreeRate",
    "SeriesAdjustment",
    "Underlying",
    "User",
    "trades",
]

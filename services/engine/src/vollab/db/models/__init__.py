"""Modelos SQLAlchemy. Importar aqui registra as tabelas no `Base.metadata` (usado pelo Alembic)."""

from vollab.db.models.collection import CollectionItem, CollectionRun
from vollab.db.models.config_version import ConfigVersion
from vollab.db.models.costs import OptionSpreadEstimate
from vollab.db.models.events import Event
from vollab.db.models.forecast import ForecastEvaluation, ForecastEvaluationPoint, RvForecast
from vollab.db.models.job import Job, JobStatus
from vollab.db.models.market import DailyBar, OptionDailyStat, RawFile, trades
from vollab.db.models.positions import ManualInput, Position, PositionEntry
from vollab.db.models.reference import (
    CorporateAction,
    ExchangeHoliday,
    OptionSeries,
    RiskFreeRate,
    SeriesAdjustment,
    Underlying,
)
from vollab.db.models.user import FIXED_USER_ID, User
from vollab.db.models.vol import (
    AtmTermPoint,
    ConstantMaturityVol,
    ImpliedVol,
    IntradayBar,
    IntradaySession,
    OptionDailyQuote,
    RealizedVol,
)

__all__ = [
    "FIXED_USER_ID",
    "AtmTermPoint",
    "CollectionItem",
    "CollectionRun",
    "ConfigVersion",
    "ConstantMaturityVol",
    "CorporateAction",
    "DailyBar",
    "Event",
    "ExchangeHoliday",
    "ForecastEvaluation",
    "ForecastEvaluationPoint",
    "ImpliedVol",
    "IntradayBar",
    "IntradaySession",
    "Job",
    "JobStatus",
    "ManualInput",
    "OptionDailyQuote",
    "OptionDailyStat",
    "OptionSeries",
    "OptionSpreadEstimate",
    "Position",
    "PositionEntry",
    "RawFile",
    "RealizedVol",
    "RiskFreeRate",
    "RvForecast",
    "SeriesAdjustment",
    "Underlying",
    "User",
    "trades",
]

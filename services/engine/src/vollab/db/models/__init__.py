"""Modelos SQLAlchemy. Importar aqui registra as tabelas no `Base.metadata` (usado pelo Alembic)."""

from vollab.db.models.alerts import Alert, PositionManagement
from vollab.db.models.collection import CollectionItem, CollectionRun
from vollab.db.models.config_version import ConfigVersion
from vollab.db.models.costs import OptionSpreadEstimate
from vollab.db.models.events import Event
from vollab.db.models.forecast import ForecastEvaluation, ForecastEvaluationPoint, RvForecast
from vollab.db.models.job import Job, JobStatus
from vollab.db.models.journal import CrisisMeasurement, DailyMark, PnlAttribution
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
    "Alert",
    "AtmTermPoint",
    "CollectionItem",
    "CollectionRun",
    "ConfigVersion",
    "ConstantMaturityVol",
    "CorporateAction",
    "CrisisMeasurement",
    "DailyBar",
    "DailyMark",
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
    "PnlAttribution",
    "Position",
    "PositionEntry",
    "PositionManagement",
    "RawFile",
    "RealizedVol",
    "RiskFreeRate",
    "RvForecast",
    "SeriesAdjustment",
    "Underlying",
    "User",
    "trades",
]

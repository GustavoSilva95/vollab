"""Modelos SQLAlchemy. Importar aqui registra as tabelas no `Base.metadata` (usado pelo Alembic)."""

from vollab.db.models.config_version import ConfigVersion
from vollab.db.models.job import Job, JobStatus
from vollab.db.models.user import FIXED_USER_ID, User

__all__ = ["FIXED_USER_ID", "ConfigVersion", "Job", "JobStatus", "User"]

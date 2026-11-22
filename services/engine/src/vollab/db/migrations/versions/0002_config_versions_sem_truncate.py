"""Bloqueia TRUNCATE em config_versions (revisão de segurança da Etapa 1, M-2).

O trigger de linha da 0001 barra UPDATE e DELETE, mas TRUNCATE não dispara triggers de linha.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TRIGGER config_versions_no_truncate
        BEFORE TRUNCATE ON config_versions
        FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER config_versions_no_truncate ON config_versions")

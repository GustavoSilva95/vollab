"""Sobe a API: `python -m vollab.api`. Escuta em ENGINE_HOST (padrão 127.0.0.1, PRD-NF-01)."""

import uvicorn

from vollab.log import configure_logging
from vollab.settings import get_settings


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    uvicorn.run(
        "vollab.api.app:create_app",
        factory=True,
        host=settings.engine_host,
        port=settings.engine_port,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .bot import run
from .config import Settings
from .db import session_factory
from .legacy import import_legacy
from .service import AvitoSource, Service


def main():
    settings = Settings()
    settings.validate_runtime()
    Path("data").mkdir(exist_ok=True)
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                "data/intelligence.log", maxBytes=5_000_000, backupCount=3
            ),
        ],
    )
    sessions = session_factory(settings.database_url)
    imported = import_legacy(sessions, min(settings.allowed_ids))
    if imported:
        logging.getLogger(__name__).info("Импортировано прежних поисков: %s", imported)
    asyncio.run(run(Service(sessions, AvitoSource(settings), settings), settings))


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

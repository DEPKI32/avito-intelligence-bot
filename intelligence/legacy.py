"""Idempotent, non-destructive import of CLI search data."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from .db import Listing, Match, PriceHistory, Search, User

LOG = logging.getLogger(__name__)


def import_legacy(sessions, user_id: int, root: Path = Path(".")) -> int:
    count = 0
    data_root = root / "data" / "searches"
    if not data_root.exists():
        return 0
    with sessions.begin() as db:
        if not db.get(User, user_id):
            db.add(User(id=user_id))
        for folder in data_root.iterdir():
            if not folder.is_dir():
                continue
            config_path = root / "searches" / (folder.name + ".json")
            if not config_path.exists():
                continue
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                raw = (
                    json.loads((folder / "listings.json").read_text(encoding="utf-8"))
                    if (folder / "listings.json").exists()
                    else {}
                )
                if not isinstance(raw, dict):
                    raise TypeError("listings.json не объект")
            except (OSError, ValueError, TypeError, KeyError) as exc:
                LOG.warning("Пропуск старого поиска %s: %s", folder.name, exc)
                continue
            url = config.get("catalog_url")
            if not url:
                continue
            search = db.scalar(
                select(Search).where(Search.user_id == user_id, Search.url == url)
            )
            if search is None:
                search = Search(
                    user_id=user_id,
                    title=config.get("title", folder.name),
                    url=url,
                    city=url.split("/")[3] if len(url.split("/")) > 3 else "",
                    profile=config.get("profile", "goods"),
                    params=config.get("params", {}),
                    status="paused",
                    scan_complete=True,
                )
                db.add(search)
                db.flush()
                count += 1
            for item in raw.values():
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                ident = str(item["id"])
                if not db.get(Listing, ident):
                    price = (item.get("priceDetailed") or {}).get("value")
                    price = int(price) if isinstance(price, (int, float)) else None
                    listing = Listing(
                        id=ident,
                        title=str(item.get("title") or ""),
                        url="https://www.avito.ru"
                        + str(item.get("urlPath") or "").split("?")[0],
                        price=price,
                        description=str(item.get("description") or ""),
                        raw=item,
                    )
                    db.add(listing)
                    if price is not None:
                        db.add(PriceHistory(listing_id=ident, price=price))
                if not db.get(Match, (search.id, ident)):
                    db.add(
                        Match(search_id=search.id, listing_id=ident, state="baseline")
                    )
    return count

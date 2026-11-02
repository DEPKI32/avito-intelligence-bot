"""Optional hosted Avito feed. The bot never sends its Telegram token to Apify."""

from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import urlsplit

import httpx

import avito_client
import link_resolver

from .config import Settings
from .db import Search
from .service import validate_url

ACTOR = "abotapi~avito-ru-scraper"
RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"


def _item(row: dict) -> dict | None:
    ident = str(row.get("id") or "")
    url = str(row.get("url") or "")
    parts = urlsplit(url)
    if not ident.isdecimal() or parts.scheme != "https" or parts.hostname not in {
        "avito.ru", "www.avito.ru"
    } or not parts.path.endswith("_" + ident):
        return None
    price = row.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        price = None
    stamp = row.get("postedAt")
    try:
        timestamp = int(datetime.fromisoformat(stamp).timestamp() * 1000) if stamp else None
    except (ValueError, TypeError, AttributeError):
        timestamp = None
    seller_type = str(row.get("sellerType") or "").lower()
    label = (
        "Частное лицо" if seller_type in {"private", "individual"}
        else "Агентство" if seller_type == "agency"
        else "Компания" if seller_type in {"company", "developer", "dealer"}
        else ""
    )
    closed = row.get("closedListings")
    result = {
        "id": int(ident),
        "title": str(row.get("title") or ""),
        "urlPath": parts.path,
        "priceDetailed": {"value": price},
        "description": str(row.get("description") or ""),
        "sellerId": row.get("sellerKey") or None,
        "closedItemsText": f"{closed} завершённых объявлений" if isinstance(closed, int) else "",
        "coords": {"address_user": str(row.get("address") or "")},
        "sortTimeStamp": timestamp,
        "iva": {"SecondLineStep": [{"payload": {"value": label}}]} if label else {},
        "photoUrls": row.get("photoUrls") if isinstance(row.get("photoUrls"), list) else [],
        "source": "apify",
    }
    return result


class ApifySource:
    """One bounded incremental run per check; Apify retains change state per search."""

    incremental_results = True

    def __init__(self, settings: Settings):
        if not settings.apify_token:
            raise ValueError("Для SOURCE_PROVIDER=apify укажите APIFY_TOKEN")
        self.token = settings.apify_token
        self.max_charge = settings.apify_max_charge_usd

    def resolve(self, url: str) -> link_resolver.ResolvedSearch:
        url = validate_url(url)
        parsed = link_resolver.parse_link(url)
        return link_resolver.ResolvedSearch(
            title=parsed.query.get("q") or parsed.category_slug.replace("_", " ") or "Поиск Авито",
            profile="goods",
            catalog_url=url,
            params={"source": "apify"},
            city="Вся Россия" if parsed.city_slug == "all" else parsed.city_slug,
            total=0,
            filters=["Фильтры из ссылки Авито"],
            samples=[],
            warnings=[],
        )

    def page(self, search: Search, number: int) -> avito_client.Page:
        if number != 1:
            raise ValueError("Источник Apify проверяет первую страницу поиска")
        state_key = f"aib-{search.user_id}-{search.id}-{hashlib.sha256(search.url.encode()).hexdigest()[:12]}"
        payload = {
            "mode": "url",
            "urls": [search.url],
            "maxPages": 1,
            "maxListings": 50,
            "fetchDetails": False,
            "fetchPhones": False,
            "incrementalMode": True,
            "stateKey": state_key,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        try:
            response = httpx.post(
                RUN_URL,
                headers={"Authorization": f"Bearer {self.token}"},
                params={"maxItems": 50, "maxTotalChargeUsd": self.max_charge},
                json=payload,
                timeout=310,
            )
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Apify не вернул объявления: {type(exc).__name__}") from exc
        if not isinstance(rows, list):
            raise TypeError("Apify вернул неожиданный формат ответа")
        items = tuple(item for row in rows if isinstance(row, dict) if (item := _item(row)))
        if rows and not items:
            raise RuntimeError("Apify не вернул распознаваемые объявления")
        return avito_client.Page(1, items, len(items), len(items))

    def stop(self) -> None:
        pass

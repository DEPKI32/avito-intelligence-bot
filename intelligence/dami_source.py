"""Low-cost Avito search feed with known-listing exclusion."""

from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import select

import avito_client

from .apify_source import ApifySource, _item
from .db import Match, Search, session_factory

RUN_URL = (
    "https://api.apify.com/v2/acts/"
    "dami_studio~avito-listings-scraper/run-sync-get-dataset-items"
)


def _url_price_bounds(url: str) -> tuple[int | None, int | None]:
    """Read Avito's encoded price filter without depending on other filter bytes."""
    query = parse_qs(urlsplit(url).query)
    encoded = query.get("f", [""])[0]
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, base64.binascii.Error):
        return None, None
    match = re.search(rb'\{"from":\d+,"to":\d+\}', decoded)
    if not match:
        return None, None
    values = json.loads(match.group())
    return values["from"], values["to"]


def _relevant_to_query(title: str, query: str) -> bool:
    """Reject obvious off-topic actor results while retaining one-word searches."""
    words = re.findall(r"[a-zа-яё0-9]+", query.casefold())
    words = [word for word in words if len(word) >= 3 and not word.isdigit()]
    if not words:
        return True
    title_words = set(re.findall(r"[a-zа-яё0-9]+", title.casefold()))
    return words[0] in title_words


class CompletePage(avito_client.Page):
    """The actor already returned all configured Avito pages in one run."""

    @property
    def is_last(self) -> bool:
        return True


class DamiSource(ApifySource):
    """Check one result page and skip listings already stored for this search."""

    def __init__(self, settings, sessions=None):
        super().__init__(settings)
        self.sessions = sessions or session_factory(settings.database_url)

    def page(self, search: Search, number: int) -> avito_client.Page:
        if number != 1:
            raise ValueError("Источник Apify проверяет первую страницу поиска")
        self._reserve_run()
        with self.sessions() as db:
            known = list(
                db.scalars(
                    select(Match.listing_id)
                    .where(Match.search_id == search.id)
                    .order_by(Match.last_seen.desc())
                    .limit(5000)
                )
            )
        payload = {
            "searchUrls": [search.url],
            "maxItems": 150,
            "maxPagesPerSearch": 3,
            "sort": "newest",
            "excludeListingIds": known,
        }
        try:
            response = httpx.post(
                RUN_URL,
                headers={"Authorization": f"Bearer {self.token}"},
                params={"maxTotalChargeUsd": self.max_charge},
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                f"Apify не вернул объявления: {type(exc).__name__}"
            ) from exc
        if not isinstance(rows, list):
            raise TypeError("Apify вернул неожиданный формат ответа")
        failures = [
            str(row.get("errorCode") or "UNKNOWN")
            for row in rows
            if isinstance(row, dict)
            and row.get("_diagnostic")
            and row.get("errorCode") != "NO_RESULTS"
        ]
        if failures:
            raise RuntimeError(f"Источник Авито не ответил: {', '.join(failures[:3])}")
        items = []
        minimum, maximum = _url_price_bounds(search.url)
        query = parse_qs(urlsplit(search.url).query).get("q", [""])[0]
        for row in rows:
            if (
                not isinstance(row, dict)
                or row.get("_sample")
                or row.get("_diagnostic")
            ):
                continue
            adapted = dict(row)
            adapted["id"] = row.get("listingId")
            adapted["postedAt"] = row.get("publishedAt")
            adapted["photoUrls"] = row.get("images")
            adapted["sellerKey"] = row.get("sellerId")
            adapted["closedListings"] = row.get("closedListings")
            item = _item(adapted)
            price = item["priceDetailed"]["value"] if item else None
            if (
                item
                and (
                    price is None
                    or (minimum is None or price >= minimum)
                    and (maximum is None or price <= maximum)
                )
                and _relevant_to_query(item["title"], query)
            ):
                items.append(item)
        if (
            rows
            and not items
            and not all(
                isinstance(row, dict) and row.get("_diagnostic") for row in rows
            )
        ):
            raise RuntimeError("Apify не вернул распознаваемые объявления")
        return CompletePage(1, tuple(items), len(items), len(items))

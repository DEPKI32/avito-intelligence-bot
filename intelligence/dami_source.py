"""Low-cost Avito search feed with known-listing exclusion."""

from __future__ import annotations

import httpx
from sqlalchemy import select

import avito_client

from .apify_source import ApifySource, _item
from .db import Match, Search, session_factory

RUN_URL = (
    "https://api.apify.com/v2/acts/"
    "dami_studio~avito-listings-scraper/run-sync-get-dataset-items"
)


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
            "maxItems": 50,
            "maxPagesPerSearch": 1,
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
            if item:
                items.append(item)
        if (
            rows
            and not items
            and not all(
                isinstance(row, dict) and row.get("_diagnostic") for row in rows
            )
        ):
            raise RuntimeError("Apify не вернул распознаваемые объявления")
        return avito_client.Page(1, tuple(items), len(items), len(items))

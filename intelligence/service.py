from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy import func, select

import apartments
import avito_client
import link_resolver
import main

from .analysis import assess, calculate_market, group_key, should_alert
from .config import Settings
from .db import (
    ExcludedSeller,
    ImageAnalysis,
    Listing,
    MarketSnapshot,
    Match,
    Notification,
    PriceHistory,
    SavedListing,
    Search,
    TextAnalysis,
    User,
    now,
)
from .vision import ImageFingerprint, similar

LOG = logging.getLogger(__name__)


class Source(Protocol):
    def resolve(self, url: str) -> link_resolver.ResolvedSearch: ...
    def page(self, search: Search, number: int) -> avito_client.Page: ...


class BoundedClient(avito_client.CalmClient):
    """Use the original parser, but leave IP-block waiting to the scheduler."""

    def __init__(self, *, delay: float, log) -> None:
        super().__init__(delay=delay, log=log)
        self.stopping = threading.Event()

    def _pause(self) -> None:
        import random
        import time

        wait = self.delay * random.uniform(0.7, 1.3) - (
            time.monotonic() - self.last_request
        )
        if self.stopping.wait(max(0, wait)):
            raise RuntimeError("Сбор остановлен")

    def _open_session(self, catalog_url: str) -> None:
        self.session = main.requests.Session(
            impersonate=main.HTTP_IMPERSONATE_PROFILE, trust_env=False
        )
        main.set_session_headers(
            self.session, {**main.REQUEST_HEADERS, "Referer": catalog_url}
        )
        self.referer = catalog_url
        kind, _ = self._get(catalog_url, document=True)
        if kind != "ok":
            self.session = None
            raise RuntimeError(f"Источник ограничил доступ: {kind}")
        self.sessions_opened += 1


def validate_url(url: str) -> str:
    if len(url) > 2048:
        raise ValueError("Ссылка слишком длинная")
    parts = urlsplit(url.strip())
    if (
        parts.scheme != "https"
        or parts.hostname not in {"avito.ru", "www.avito.ru"}
        or parts.username
        or parts.password
        or parts.port
    ):
        raise ValueError("Нужна ссылка HTTPS на avito.ru")
    link_resolver.parse_link(url)
    return url.strip()


def seller_key(item: dict[str, Any]) -> str:
    candidates = [item.get("sellerId"), item.get("userId")]
    for field in ("seller", "user"):
        value = item.get(field)
        if isinstance(value, dict):
            candidates.append(value.get("id"))
    return next(
        (
            str(value)[:100]
            for value in candidates
            if isinstance(value, (str, int)) and str(value)
        ),
        "",
    )


class AvitoSource:
    def __init__(self, settings: Settings) -> None:
        self.client = BoundedClient(
            delay=settings.request_delay_seconds,
            log=lambda *a, **kw: LOG.info("Avito: %s", a[0] if a else "event"),
        )
        self.cache_path = Path("data/locations.json")
        self.lock = threading.Lock()

    def stop(self) -> None:
        self.client.stopping.set()

    def resolve(self, url: str) -> link_resolver.ResolvedSearch:
        url = validate_url(url)
        with self.lock:
            cache = (
                json.loads(self.cache_path.read_text())
                if self.cache_path.exists()
                else {}
            )
            result = link_resolver.resolve(self.client, url, locations_cache=cache)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(cache, ensure_ascii=False), encoding="utf-8"
            )
            return result

    def page(self, search: Search, number: int) -> avito_client.Page:
        with self.lock:
            return self.client.page(
                catalog_url=search.url,
                params={**search.params, "s": "104"},
                number=number,
            )


class Service:
    def __init__(self, sessions, source: Source, settings: Settings):
        self.sessions = sessions
        self.source = source
        self.settings = settings
        self.lock = threading.RLock()

    def user_settings(self, user_id: int) -> tuple[int | None, int | None]:
        with self.sessions() as db:
            user = db.get(User, user_id)
            return (user.quiet_start, user.quiet_end) if user else (None, None)

    def set_quiet_hour(self, user_id: int, field: str, value: str) -> None:
        if field not in {"start", "end"}:
            raise ValueError("Неверный параметр")
        if value.strip() in {"-", "нет"}:
            hour = None
        else:
            try:
                hour = int(value)
            except ValueError:
                raise ValueError("Введите час от 0 до 23 или «-»") from None
            if not 0 <= hour <= 23:
                raise ValueError("Введите час от 0 до 23 или «-»")
        with self.sessions.begin() as db:
            user = db.get(User, user_id)
            if user is None:
                user = User(id=user_id)
                db.add(user)
            setattr(user, f"quiet_{field}", hour)

    def digest_enabled(self, user_id: int) -> bool:
        with self.sessions() as db:
            user = db.get(User, user_id)
            return bool(user and user.digest_mode)

    def toggle_digest(self, user_id: int) -> bool:
        with self.sessions.begin() as db:
            user = db.get(User, user_id)
            if user is None:
                user = User(id=user_id)
                db.add(user)
            user.digest_mode = not user.digest_mode
            if user.digest_mode:
                user.last_digest_at = now()
            return user.digest_mode

    def digest_due(self, user_id: int) -> bool:
        with self.sessions() as db:
            user = db.get(User, user_id)
            if not user or not user.digest_mode:
                return False
            stamp = user.last_digest_at
            if stamp is None:
                return True
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            return now() - stamp >= timedelta(hours=12)

    def mark_digest_sent(self, user_id: int, notification_ids: list[int]) -> None:
        with self.sessions.begin() as db:
            for ident in notification_ids:
                note = db.get(Notification, ident)
                if note and note.status == "pending":
                    note.status, note.sent_at = "sent", now()
            db.get(User, user_id).last_digest_at = now()

    def create_search(
        self,
        user_id: int,
        url: str,
        title: str = "",
        target_model: str = "",
        target_memory: str = "",
    ) -> Search:
        url = validate_url(url)
        resolved = self.source.resolve(url)
        with self.sessions.begin() as db:
            if not db.get(User, user_id):
                db.add(User(id=user_id))
                db.flush()
            existing = db.scalar(
                select(Search).where(Search.user_id == user_id, Search.url == url)
            )
            if existing:
                raise ValueError("Этот поиск уже добавлен")
            search = Search(
                user_id=user_id,
                title=(title or resolved.title)[:200],
                url=url,
                city=resolved.city,
                profile=resolved.profile,
                params=resolved.params,
                filters_text="; ".join(resolved.filters),
                target_model=target_model[:120],
                target_memory=target_memory[:30],
                interval_seconds=self.settings.check_interval_seconds,
                status="scanning",
            )
            db.add(search)
            db.flush()
            return search

    def owned(self, db, user_id: int, search_id: int) -> Search:
        search = db.get(Search, search_id)
        if not search or search.user_id != user_id:
            raise ValueError("Поиск не найден")
        return search

    def list_searches(self, user_id: int) -> list[Search]:
        with self.sessions() as db:
            return list(
                db.scalars(
                    select(Search)
                    .where(Search.user_id == user_id)
                    .order_by(Search.id.desc())
                )
            )

    def set_status(self, user_id: int, search_id: int, status: str) -> None:
        if status not in ("active", "paused"):
            raise ValueError("Неверный статус")
        with self.sessions.begin() as db:
            search = self.owned(db, user_id, search_id)
            search.status = status
            search.next_run = now()
            if status == "active" and not search.scan_complete:
                search.status = "scanning"

    def set_filter(self, user_id: int, search_id: int, key: str, value: str) -> None:
        choices = {
            "seller_filter": {"all", "no_shops", "private"},
            "condition_filter": {"all", "new", "used"},
            "notification_mode": {
                "all",
                "below_market",
                "strong",
                "max_price",
                "score",
            },
            "events_mode": {"new", "new_and_price"},
        }
        ints = {
            "discount_percent": (0, 80),
            "min_score": (0, 100),
            "min_price": (0, 1000000000),
            "max_price": (0, 1000000000),
            "max_alert_price": (0, 1000000000),
            "interval_seconds": (300, 86400),
        }
        if key in choices and value not in choices[key]:
            raise ValueError("Недопустимое значение")
        if key in ints:
            if key in {
                "min_price",
                "max_price",
                "max_alert_price",
            } and value.strip().lower() in {"-", "нет"}:
                value = None
            else:
                try:
                    number = int(value)
                except ValueError:
                    raise ValueError("Введите целое число") from None
                lo, hi = ints[key]
                if not lo <= number <= hi:
                    raise ValueError(f"Допустимо от {lo} до {hi}")
                value = number
        elif key not in choices and key not in {
            "title",
            "target_model",
            "target_memory",
        }:
            raise ValueError("Неизвестный параметр")
        if key in {"title", "target_model", "target_memory"}:
            value = value.strip()[:200]
        with self.sessions.begin() as db:
            setattr(self.owned(db, user_id, search_id), key, value)
        if key != "title":
            self.reassess(search_id)

    def delete(self, user_id: int, search_id: int) -> None:
        with self.sessions.begin() as db:
            db.delete(self.owned(db, user_id, search_id))

    def scan_due(self) -> list[int]:
        with self.sessions() as db:
            return list(
                db.scalars(
                    select(Search.id).where(
                        Search.status.in_(["scanning", "active", "source_unavailable"]),
                        (Search.next_run == None) | (Search.next_run <= now()),
                    )
                )
            )

    def scan_one(self, search_id: int) -> dict[str, Any]:
        with self.lock:
            with self.sessions() as db:
                search = db.get(Search, search_id)
                if not search or search.status == "paused":
                    return {"skipped": True}
                number = (
                    search.next_page if not search.scan_complete else search.watch_page
                )
                try:
                    page = self.source.page(search, number)
                except Exception as exc:
                    LOG.exception("Источник недоступен для поиска %s", search_id)
                    with self.sessions.begin() as update:
                        current = update.get(Search, search_id)
                        if current and current.status != "paused":
                            current.status = "source_unavailable"
                            current.last_error = f"{type(exc).__name__}: {exc}"[:300]
                            current.failure_count += 1
                            current.next_run = now() + timedelta(
                                seconds=min(
                                    3600,
                                    current.interval_seconds
                                    * 2 ** min(current.failure_count, 4),
                                )
                            )
                    return {"error": str(exc)}
            count = 0
            with self.sessions.begin() as db:
                search = db.get(Search, search_id)
                if not search or search.status == "paused":
                    return {"skipped": True}
                baseline = not search.scan_complete
                if not baseline and number == 1:
                    search.watch_started = now()
                for item in page.items:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    try:
                        normalized = apartments.listing_from_item(item)
                    except (ValueError, TypeError, KeyError, AttributeError):
                        LOG.warning(
                            "Пропущено повреждённое объявление в поиске %s", search_id
                        )
                        continue
                    ident = str(normalized.id)
                    listing = db.get(Listing, ident)
                    prior_price = listing.price if listing else None
                    if listing is None:
                        listing = Listing(
                            id=ident,
                            title=normalized.title,
                            url=normalized.url,
                            price=normalized.price,
                            description=normalized.description,
                            seller_label=normalized.seller_label,
                            seller_key=seller_key(item),
                            closed_listings=normalized.closed_listings,
                            raw=item,
                        )
                        db.add(listing)
                    else:
                        listing.title, listing.url, listing.price = (
                            normalized.title,
                            normalized.url,
                            normalized.price,
                        )
                        listing.description, listing.seller_label = (
                            normalized.description,
                            normalized.seller_label,
                        )
                        listing.seller_key = seller_key(item) or listing.seller_key
                        listing.closed_listings, listing.raw, listing.last_seen = (
                            normalized.closed_listings,
                            item,
                            now(),
                        )
                    match = db.get(Match, (search_id, ident))
                    is_new = match is None
                    if is_new:
                        match = Match(
                            search_id=search_id,
                            listing_id=ident,
                            state="baseline" if baseline else "new",
                            last_price=normalized.price,
                        )
                        db.add(match)
                    else:
                        match.last_seen = now()
                        if match.state == "not_seen":
                            match.state = "reappeared"
                        if (
                            match.last_price is not None
                            and normalized.price is not None
                            and normalized.price < match.last_price
                            and not baseline
                        ):
                            match.state = "price_drop"
                        match.last_price = normalized.price
                    if normalized.price is not None and (
                        prior_price is None or prior_price != normalized.price
                    ):
                        db.add(PriceHistory(listing_id=ident, price=normalized.price))
                    count += int(is_new)
                search.last_success = now()
                search.last_error = ""
                search.failure_count = 0
                complete = page.is_last or number >= self.settings.scan_page_limit
                if baseline:
                    search.next_page = 1 if complete else number + 1
                    search.scan_complete = complete
                    search.status = "active" if complete else "scanning"
                    next_soon = not complete
                else:
                    search.status = "active"
                    watch_done = page.is_last or number >= self.settings.watch_pages
                    search.watch_page = 1 if watch_done else number + 1
                    next_soon = not watch_done
                    if page.is_last and search.watch_started:
                        for old in db.scalars(
                            select(Match).where(
                                Match.search_id == search_id,
                                Match.last_seen < search.watch_started,
                                Match.state != "not_seen",
                            )
                        ):
                            old.state = "not_seen"
                search.next_run = now() + timedelta(
                    seconds=10 if next_soon else search.interval_seconds
                )
            self.reassess(search_id)
            return {
                "page": number,
                "new": count,
                "complete": complete,
                "baseline": baseline,
                "user_id": search.user_id,
                "title": search.title,
                "limited": baseline
                and number >= self.settings.scan_page_limit
                and not page.is_last,
                "source_total": page.total_count,
            }

    def reassess(self, search_id: int) -> None:
        with self.sessions.begin() as db:
            search = db.get(Search, search_id)
            rows = list(
                db.execute(
                    select(Match, Listing)
                    .join(Listing, Match.listing_id == Listing.id)
                    .where(Match.search_id == search_id)
                )
            )
            listings = [listing for match, listing in rows if match.state != "not_seen"]
            groups = {group_key(item) for item in listings}
            markets = {group: calculate_market(group, listings) for group in groups}
            for group, market in markets.items():
                if market:
                    db.add(
                        MarketSnapshot(
                            search_id=search_id,
                            group_key=group,
                            median=market.median,
                            low=market.low,
                            high=market.high,
                            count=market.count,
                            confidence=market.confidence,
                        )
                    )
            excluded = set(
                db.scalars(
                    select(ExcludedSeller.seller_key).where(
                        ExcludedSeller.user_id == search.user_id
                    )
                )
            )
            disliked = set(
                db.scalars(
                    select(SavedListing.listing_id).where(
                        SavedListing.user_id == search.user_id,
                        SavedListing.interested == False,
                    )
                )
            )
            images = (
                {
                    row.listing_id: row
                    for row in db.scalars(
                        select(ImageAnalysis).where(
                            ImageAnalysis.listing_id.in_(
                                [listing.id for listing in listings]
                            )
                        )
                    )
                }
                if listings
                else {}
            )
            texts = (
                {
                    row.listing_id: row
                    for row in db.scalars(
                        select(TextAnalysis).where(
                            TextAnalysis.listing_id.in_(
                                [listing.id for listing in listings]
                            )
                        )
                    )
                }
                if listings
                else {}
            )
            for match, listing in rows:
                market = markets.get(group_key(listing))
                result = assess(listing, search, market)
                match.score, match.risk, match.market_price = (
                    result.score,
                    result.risk,
                    market.median if market else None,
                )
                match.exclusion = (
                    result.exclusion
                    or (
                        "продавец исключён"
                        if listing.seller_key and listing.seller_key in excluded
                        else ""
                    )
                    or ("неинтересно пользователю" if listing.id in disliked else "")
                )
                match.reasons = list(result.reasons)
                image = images.get(listing.id)
                if image and image.warnings:
                    match.risk = min(100, match.risk + 20)
                    match.score = max(0, match.score - 15)
                    match.reasons += [f"Фото: {warning}" for warning in image.warnings]
                text_analysis = texts.get(listing.id)
                if text_analysis and text_analysis.risks:
                    match.reasons += [
                        f"ИИ предполагает: {risk}" for risk in text_analysis.risks
                    ]
                    if text_analysis.confidence >= 0.8:
                        match.risk = min(100, match.risk + 10)
                        match.score = max(0, match.score - 5)
                if (
                    match.exclusion
                    or match.risk >= 60
                    or match.score < search.min_score
                    or not should_alert(result, listing, search, market)
                ):
                    for note in db.scalars(
                        select(Notification).where(
                            Notification.search_id == search_id,
                            Notification.listing_id == listing.id,
                            Notification.status == "pending",
                        )
                    ):
                        note.status = "cancelled"
                if match.state not in ("new", "price_drop") or match.exclusion:
                    continue
                if match.state == "price_drop" and search.events_mode == "new":
                    continue
                if (
                    match.risk < 60
                    and match.score >= search.min_score
                    and should_alert(result, listing, search, market)
                ):
                    event_key = (
                        f"{match.state}:{listing.price}"
                        if match.state == "price_drop"
                        else "new"
                    )
                    exists = db.scalar(
                        select(Notification.id).where(
                            Notification.search_id == search_id,
                            Notification.listing_id == listing.id,
                            Notification.event_key == event_key,
                        )
                    )
                    if not exists:
                        db.add(
                            Notification(
                                search_id=search_id,
                                listing_id=listing.id,
                                event_key=event_key,
                            )
                        )
                match.state = "seen"

    def favorite(self, user_id: int, listing_id: str, interested: bool) -> None:
        with self.sessions.begin() as db:
            owns = db.scalar(
                select(Match.listing_id)
                .join(Search, Match.search_id == Search.id)
                .where(Search.user_id == user_id, Match.listing_id == listing_id)
                .limit(1)
            )
            if not owns:
                raise ValueError("Объявление не найдено")
            if not db.get(User, user_id):
                db.add(User(id=user_id))
            row = db.get(SavedListing, (user_id, listing_id))
            if row:
                row.interested = interested
            else:
                db.add(
                    SavedListing(
                        user_id=user_id, listing_id=listing_id, interested=interested
                    )
                )
            if not interested:
                search_ids = select(Search.id).where(Search.user_id == user_id)
                for match in db.scalars(
                    select(Match).where(
                        Match.search_id.in_(search_ids), Match.listing_id == listing_id
                    )
                ):
                    match.exclusion = "неинтересно пользователю"
                for note in db.scalars(
                    select(Notification).where(
                        Notification.search_id.in_(search_ids),
                        Notification.listing_id == listing_id,
                        Notification.status == "pending",
                    )
                ):
                    note.status = "cancelled"

    def exclude_seller(self, user_id: int, listing_id: str) -> None:
        with self.sessions.begin() as db:
            owns = db.scalar(
                select(Match.listing_id)
                .join(Search, Match.search_id == Search.id)
                .where(Search.user_id == user_id, Match.listing_id == listing_id)
                .limit(1)
            )
            if not owns:
                raise ValueError("Объявление не найдено")
            listing = db.get(Listing, listing_id)
            if not listing or not listing.seller_key:
                raise ValueError(
                    "Источник не сообщил ID продавца; исключить его надёжно нельзя"
                )
            if not db.get(ExcludedSeller, (user_id, listing.seller_key)):
                db.add(ExcludedSeller(user_id=user_id, seller_key=listing.seller_key))
            search_ids = select(Search.id).where(Search.user_id == user_id)
            matches = db.scalars(
                select(Match)
                .join(Listing, Match.listing_id == Listing.id)
                .where(
                    Match.search_id.in_(search_ids),
                    Listing.seller_key == listing.seller_key,
                )
            )
            for match in matches:
                match.exclusion = "продавец исключён"
                for note in db.scalars(
                    select(Notification).where(
                        Notification.search_id == match.search_id,
                        Notification.listing_id == match.listing_id,
                        Notification.status == "pending",
                    )
                ):
                    note.status = "cancelled"

    def listing_details(self, user_id: int, listing_id: str):
        with self.sessions() as db:
            row = db.execute(
                select(Match, Listing)
                .join(Listing, Match.listing_id == Listing.id)
                .join(Search, Match.search_id == Search.id)
                .where(Search.user_id == user_id, Listing.id == listing_id)
                .limit(1)
            ).first()
            if not row:
                raise ValueError("Объявление не найдено")
            history = list(
                db.scalars(
                    select(PriceHistory)
                    .where(PriceHistory.listing_id == listing_id)
                    .order_by(PriceHistory.observed_at.desc())
                    .limit(10)
                )
            )
            image = db.get(ImageAnalysis, listing_id)
            text_analysis = db.get(TextAnalysis, listing_id)
            return row[0], row[1], history, image, text_analysis

    def cached_text_analysis(self, listing_id: str):
        with self.sessions() as db:
            return db.get(TextAnalysis, listing_id)

    def save_text_analysis(self, listing_id: str, result) -> None:
        risks = [value[:200] for value in result.risks[:10]]
        search_ids = []
        with self.sessions.begin() as db:
            row = db.get(TextAnalysis, listing_id)
            if row is None:
                row = TextAnalysis(
                    listing_id=listing_id,
                    model=result.model,
                    memory=result.memory,
                    risks=risks,
                    summary=result.summary,
                    confidence=result.confidence,
                )
                db.add(row)
            else:
                row.model, row.memory, row.risks = (
                    result.model,
                    result.memory,
                    risks,
                )
                row.summary, row.confidence = result.summary, result.confidence
            search_ids = list(
                db.scalars(
                    select(Match.search_id).where(Match.listing_id == listing_id)
                )
            )
        for search_id in search_ids:
            self.reassess(search_id)

    def cached_image_analysis(self, listing_id: str):
        with self.sessions() as db:
            return db.get(ImageAnalysis, listing_id)

    def save_image_analysis(
        self,
        listing_id: str,
        hashes: list[str],
        warnings: list[str],
        summary: str,
        confidence: float | None,
    ) -> None:
        warnings = [value[:200] for value in warnings[:10]]
        search_ids = []
        with self.sessions.begin() as db:
            if hashes:
                others = db.scalars(
                    select(ImageAnalysis).where(ImageAnalysis.listing_id != listing_id)
                )
                if any(
                    similar(ImageFingerprint(own, 0, 0), ImageFingerprint(other, 0, 0))
                    for row in others
                    for own in hashes
                    for other in row.hashes
                ):
                    warnings = [*warnings, "фотография похожа на другое объявление"]
            row = db.get(ImageAnalysis, listing_id)
            if row is None:
                db.add(
                    ImageAnalysis(
                        listing_id=listing_id,
                        hashes=hashes,
                        warnings=warnings,
                        summary=summary,
                        confidence=confidence,
                    )
                )
            else:
                row.hashes, row.warnings, row.summary, row.confidence = (
                    hashes,
                    warnings,
                    summary,
                    confidence,
                )
            search_ids = list(
                db.scalars(
                    select(Match.search_id).where(Match.listing_id == listing_id)
                )
            )
        for search_id in search_ids:
            self.reassess(search_id)

    def favorites(self, user_id: int):
        with self.sessions() as db:
            return list(
                db.scalars(
                    select(Listing)
                    .join(SavedListing, SavedListing.listing_id == Listing.id)
                    .where(
                        SavedListing.user_id == user_id, SavedListing.interested == True
                    )
                    .limit(30)
                )
            )

    def stats(self, user_id: int, search_id: int) -> dict[str, Any]:
        with self.sessions() as db:
            search = self.owned(db, user_id, search_id)
            total = db.scalar(
                select(func.count())
                .select_from(Match)
                .where(Match.search_id == search_id)
            )
            excluded = db.scalar(
                select(func.count())
                .select_from(Match)
                .where(Match.search_id == search_id, Match.exclusion != "")
            )
            deals = db.scalar(
                select(func.count())
                .select_from(Match)
                .join(Listing, Match.listing_id == Listing.id)
                .where(
                    Match.search_id == search_id,
                    Match.score >= search.min_score,
                    Match.risk < 60,
                    Match.exclusion == "",
                    Match.market_price != None,
                    Listing.price < Match.market_price,
                )
            )
            market = db.scalar(
                select(MarketSnapshot)
                .where(MarketSnapshot.search_id == search_id)
                .order_by(
                    MarketSnapshot.calculated_at.desc(), MarketSnapshot.count.desc()
                )
            )
            return {
                "search": search,
                "total": total,
                "excluded": excluded,
                "deals": deals,
                "market": market,
            }

    def offers(
        self, user_id: int, search_id: int, only_deals: bool = False, limit: int = 20
    ):
        with self.sessions() as db:
            search = self.owned(db, user_id, search_id)
            query = (
                select(Match, Listing)
                .join(Listing, Match.listing_id == Listing.id)
                .where(Match.search_id == search_id)
            )
            if only_deals:
                query = query.where(
                    Match.exclusion == "",
                    Match.market_price != None,
                    Match.score >= search.min_score,
                    Match.risk < 60,
                    Listing.price < Match.market_price,
                )
            return list(db.execute(query.order_by(Match.score.desc()).limit(limit)))

    def pending(self):
        with self.sessions() as db:
            return list(
                db.execute(
                    select(Notification, Search, Match, Listing)
                    .join(Search, Notification.search_id == Search.id)
                    .join(
                        Match,
                        (Match.search_id == Notification.search_id)
                        & (Match.listing_id == Notification.listing_id),
                    )
                    .join(Listing, Listing.id == Notification.listing_id)
                    .where(
                        Notification.status == "pending",
                        Notification.next_attempt <= now(),
                        Search.status == "active",
                    )
                    .order_by(Notification.id)
                    .limit(100)
                )
            )

    def notification_state(self, notification_id: int):
        with self.sessions() as db:
            note = db.get(Notification, notification_id)
            match = db.get(Match, (note.search_id, note.listing_id)) if note else None
            search = db.get(Search, note.search_id) if note else None
            if (
                not note
                or not search
                or search.status != "active"
                or not match
                or match.exclusion
            ):
                return "cancelled", match
            return note.status, match

    def mark_sent(self, notification_id: int, success: bool) -> None:
        with self.sessions.begin() as db:
            row = db.get(Notification, notification_id)
            if not row or row.status != "pending":
                return
            if success:
                row.status, row.sent_at = "sent", now()
            else:
                row.attempts += 1
                row.next_attempt = now() + timedelta(
                    seconds=min(3600, 30 * 2 ** min(row.attempts, 7))
                )

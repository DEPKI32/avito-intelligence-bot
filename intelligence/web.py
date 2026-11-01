"""Telegram Mini App: same service and database as the chat bot."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .service import Service

STATIC = Path(__file__).parent / "static"
AUTH_LIFETIME = 24 * 60 * 60
TICKET_LIFETIME = 10 * 60
_tickets: dict[str, tuple[int, int]] = {}
_sessions: dict[str, tuple[int, int]] = {}
_auth_lock = threading.Lock()


def issue_ticket(user_id: int) -> str:
    """Create a short-lived, single-use login ticket for a chat button."""
    value = secrets.token_urlsafe(32)
    current = int(time.time())
    with _auth_lock:
        for key, entry in list(_tickets.items()):
            if entry[1] <= current:
                del _tickets[key]
        for key, entry in list(_sessions.items()):
            if entry[1] <= current:
                del _sessions[key]
        _tickets[value] = (user_id, current + TICKET_LIFETIME)
    return value


def exchange_ticket(value: str, settings: Settings) -> tuple[str, int]:
    current = int(time.time())
    with _auth_lock:
        entry = _tickets.pop(value, None)
        if not entry or entry[1] <= current or entry[0] not in settings.allowed_ids:
            raise HTTPException(401, "Ссылка входа устарела. Отправьте боту /app снова")
        session = secrets.token_urlsafe(32)
        _sessions[session] = (entry[0], current + AUTH_LIFETIME)
    return session, entry[0]


def session_user(value: str, settings: Settings) -> int:
    if not value:
        raise HTTPException(401, "Требуется вход через Telegram")
    current = int(time.time())
    with _auth_lock:
        entry = _sessions.get(value)
        if not entry or entry[1] <= current or entry[0] not in settings.allowed_ids:
            _sessions.pop(value, None)
            raise HTTPException(401, "Срок входа истёк. Отправьте боту /app")
        return entry[0]


def validated_user(init_data: str, settings: Settings, at: int | None = None) -> int:
    """Verify Telegram's signed initData before trusting its user object."""
    if not init_data or len(init_data) > 8192:
        raise HTTPException(401, "Нужен вход через Telegram")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs) or not data.get("hash"):
            raise ValueError("invalid fields")
        secret = hmac.new(
            b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256
        ).digest()
        signed = "\n".join(
            f"{key}={value}" for key, value in sorted(data.items()) if key != "hash"
        )
        digest = hmac.new(secret, signed.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, data["hash"]):
            raise ValueError("invalid signature")
        current = int(time.time()) if at is None else at
        age = current - int(data["auth_date"])
        if age < -60 or age > AUTH_LIFETIME:
            raise ValueError("expired")
        user = json.loads(data["user"])
        user_id = user["id"]
        if type(user_id) is not int or user_id not in settings.allowed_ids:
            raise ValueError("unknown user")
        return user_id
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "Неверный или устаревший вход Telegram") from None


def stamp(value):
    return value.isoformat() if value else None


def search_data(search, stats=None):
    result = {
        "id": search.id,
        "title": search.title,
        "url": search.url,
        "city": search.city,
        "status": search.status,
        "filters_text": search.filters_text,
        "target_model": search.target_model,
        "target_memory": search.target_memory,
        "min_price": search.min_price,
        "max_price": search.max_price,
        "seller_filter": search.seller_filter,
        "condition_filter": search.condition_filter,
        "notification_mode": search.notification_mode,
        "discount_percent": search.discount_percent,
        "max_alert_price": search.max_alert_price,
        "min_score": search.min_score,
        "events_mode": search.events_mode,
        "interval_seconds": search.interval_seconds,
        "scan_complete": search.scan_complete,
        "next_page": search.next_page,
        "last_success": stamp(search.last_success),
        "next_run": stamp(search.next_run),
        "last_error": search.last_error,
    }
    if stats:
        market = stats["market"]
        result.update(
            total=stats["total"],
            deals=stats["deals"],
            excluded=stats["excluded"],
            market={
                "median": market.median,
                "low": market.low,
                "high": market.high,
                "count": market.count,
                "confidence": market.confidence,
            }
            if market
            else None,
        )
    return result


def listing_data(match, listing):
    return {
        "id": listing.id,
        "title": listing.title,
        "url": listing.url,
        "price": listing.price,
        "description": listing.description,
        "seller_label": listing.seller_label,
        "score": match.score,
        "risk": match.risk,
        "market_price": match.market_price,
        "exclusion": match.exclusion,
        "reasons": match.reasons or [],
        "first_seen": stamp(match.first_seen),
        "last_seen": stamp(match.last_seen),
        "creation_verdict": listing.creation_verdict,
    }


class NewSearch(BaseModel):
    url: str = Field(min_length=15, max_length=2048)
    title: str = Field(default="", max_length=200)
    target_model: str = Field(default="", max_length=120)
    target_memory: str = Field(default="", max_length=30)


class StatusChange(BaseModel):
    status: str


class FilterChange(BaseModel):
    key: str
    value: str


class FavoriteChange(BaseModel):
    interested: bool


class TicketExchange(BaseModel):
    ticket: str = Field(min_length=20, max_length=100)


def create_app(service: Service, settings: Settings) -> FastAPI:
    app = FastAPI(title="Avito Intelligence Mini App", docs_url=None, redoc_url=None)

    def user_id(
        x_telegram_init_data: str = Header(default=""),
        avito_session: str = Cookie(default=""),
    ) -> int:
        if x_telegram_init_data:
            return validated_user(x_telegram_init_data, settings)
        return session_user(avito_session, settings)

    def invalid(exc: ValueError):
        raise HTTPException(400, str(exc)) from None

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/dashboard")
    def dashboard(user: int = Depends(user_id)):
        searches = service.list_searches(user)
        rows = [search_data(s, service.stats(user, s.id)) for s in searches]
        recent = []
        for search in searches[:10]:
            found, _ = service.search_listings(user, search.id, limit=4)
            recent.extend(listing_data(match, listing) for match, listing in found)
        recent.sort(key=lambda row: row["last_seen"] or "", reverse=True)
        return {"searches": rows, "recent": recent[:8]}

    @app.get("/api/deals")
    def deals(user: int = Depends(user_id)):
        return [
            listing_data(match, listing) for match, listing in service.best_deals(user)
        ]

    @app.post("/api/session")
    def login(body: TicketExchange, response: Response):
        session, _ = exchange_ticket(body.ticket, settings)
        response.set_cookie(
            "avito_session",
            session,
            max_age=AUTH_LIFETIME,
            httponly=True,
            secure=True,
            samesite="lax",
        )
        return {"ok": True}

    @app.post("/api/searches", status_code=201)
    def add_search(body: NewSearch, user: int = Depends(user_id)):
        try:
            search = service.create_search(
                user, body.url, body.title, body.target_model, body.target_memory
            )
            return search_data(search)
        except ValueError as exc:
            invalid(exc)

    @app.get("/api/searches/{search_id}")
    def get_search(search_id: int, user: int = Depends(user_id)):
        try:
            info = service.stats(user, search_id)
            return search_data(info["search"], info)
        except ValueError as exc:
            invalid(exc)

    @app.get("/api/searches/{search_id}/market-history")
    def market_history(
        search_id: int,
        days: int = Query(default=30),
        user: int = Depends(user_id),
    ):
        try:
            return [
                {
                    "at": stamp(snapshot.calculated_at),
                    "median": snapshot.median,
                    "low": snapshot.low,
                    "high": snapshot.high,
                    "count": snapshot.count,
                }
                for snapshot in service.market_history(user, search_id, days)
            ]
        except ValueError as exc:
            invalid(exc)

    @app.patch("/api/searches/{search_id}/status")
    def change_status(search_id: int, body: StatusChange, user: int = Depends(user_id)):
        try:
            service.set_status(user, search_id, body.status)
            return get_search(search_id, user)
        except ValueError as exc:
            invalid(exc)

    @app.patch("/api/searches/{search_id}/filter")
    def change_filter(search_id: int, body: FilterChange, user: int = Depends(user_id)):
        try:
            service.set_filter(user, search_id, body.key, body.value)
            return get_search(search_id, user)
        except ValueError as exc:
            invalid(exc)

    @app.post("/api/searches/{search_id}/scan", status_code=202)
    def scan(search_id: int, user: int = Depends(user_id)):
        try:
            service.request_scan(user, search_id)
            return {"queued": True}
        except ValueError as exc:
            invalid(exc)

    @app.delete("/api/searches/{search_id}", status_code=204)
    def delete_search(search_id: int, user: int = Depends(user_id)):
        try:
            service.delete(user, search_id)
            return Response(status_code=204)
        except ValueError as exc:
            invalid(exc)

    @app.get("/api/searches/{search_id}/listings")
    def listings(
        search_id: int,
        q: str = Query(default="", max_length=100),
        sort: str = "recent",
        page: int = Query(default=0, ge=0, le=1000),
        user: int = Depends(user_id),
    ):
        try:
            found, total = service.search_listings(user, search_id, q, sort, page, 12)
            return {
                "items": [listing_data(match, listing) for match, listing in found],
                "total": total,
                "page": page,
            }
        except ValueError as exc:
            invalid(exc)

    @app.get("/api/listings/{listing_id}")
    def listing(listing_id: str, user: int = Depends(user_id)):
        try:
            match, item, history, image, analysis = service.listing_details(
                user, listing_id
            )
            result = listing_data(match, item)
            result.update(
                history=[
                    {"price": h.price, "at": stamp(h.observed_at)} for h in history
                ],
                image_summary=image.summary if image else "",
                text_summary=analysis.summary if analysis else "",
            )
            return result
        except ValueError as exc:
            invalid(exc)

    @app.get("/api/favorites")
    def favorites(user: int = Depends(user_id)):
        return [
            listing_data(match, item) for match, item in service.favorite_details(user)
        ]

    @app.post("/api/listings/{listing_id}/favorite")
    def favorite(listing_id: str, body: FavoriteChange, user: int = Depends(user_id)):
        try:
            service.favorite(user, listing_id, body.interested)
            return {"interested": body.interested}
        except ValueError as exc:
            invalid(exc)

    @app.get("/")
    def index():
        return FileResponse(
            STATIC / "index.html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
    return app


def main():
    import uvicorn

    from .db import session_factory
    from .service import AvitoSource

    settings = Settings()
    settings.validate_runtime()
    service = Service(
        session_factory(settings.database_url), AvitoSource(settings), settings
    )
    uvicorn.run(
        create_app(service, settings),
        host=settings.webapp_host,
        port=settings.webapp_port,
    )


if __name__ == "__main__":
    main()

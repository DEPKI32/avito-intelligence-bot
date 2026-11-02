from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import link_resolver
from intelligence.config import Settings
from intelligence.db import Listing, MarketSnapshot, Match, now, session_factory
from intelligence.service import Service
from intelligence.web import create_app, issue_ticket, validated_user

URL = "https://www.avito.ru/moskva/telefony?q=iphone+15"


class Source:
    def resolve(self, url):
        return link_resolver.ResolvedSearch(
            "iPhone 15", "goods", url, {"q": "iphone 15"}, "Москва", 30, [], [], []
        )


class DeferredSource(Source):
    defer_resolution = True


def signed(settings, user_id=1, auth_date=1_800_000_000, signature=""):
    data = {
        "auth_date": str(auth_date),
        "query_id": "AAE",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"}, separators=(",", ":")
        ),
    }
    if signature:
        data["signature"] = signature
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(
        b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256
    ).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_init_data_signature_age_and_allowlist():
    settings = Settings(telegram_bot_token="123:TEST", telegram_allowed_user_ids="1")
    data = signed(settings)
    assert validated_user(data, settings, at=1_800_000_100) == 1
    assert (
        validated_user(
            signed(settings, signature="example"), settings, at=1_800_000_100
        )
        == 1
    )
    with pytest.raises(HTTPException) as error:
        validated_user(data.replace("Test", "Fake"), settings, at=1_800_000_100)
    assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        validated_user(data, settings, at=1_800_100_000)
    with pytest.raises(HTTPException):
        validated_user(signed(settings, user_id=2), settings, at=1_800_000_100)


def test_public_telegram_users_have_private_searches(tmp_path):
    settings = Settings(
        telegram_bot_token="123:TEST",
        telegram_allowed_user_ids="1",
        public_access=True,
        database_url=f"sqlite:///{tmp_path / 'public.sqlite'}",
    )
    service = Service(session_factory(settings.database_url), Source(), settings)
    client = TestClient(create_app(service, settings), base_url="https://testserver")
    first = {"X-Telegram-Init-Data": signed(settings, auth_date=int(time.time()))}
    second = {
        "X-Telegram-Init-Data": signed(settings, user_id=2, auth_date=int(time.time()))
    }
    assert client.get("/api/dashboard").status_code == 401
    search = client.post("/api/searches", headers=second, json={"url": URL})
    assert search.status_code == 201
    assert len(client.get("/api/dashboard", headers=second).json()["searches"]) == 1
    assert client.get("/api/dashboard", headers=first).json()["searches"] == []
    assert (
        client.get(f"/api/searches/{search.json()['id']}", headers=first).status_code
        == 400
    )
    ticket = issue_ticket(2)
    assert client.post("/api/session", json={"ticket": ticket}).status_code == 200
    assert len(client.get("/api/dashboard").json()["searches"]) == 1


def test_web_api_uses_same_service_and_enforces_ownership(tmp_path):
    settings = Settings(
        telegram_bot_token="123:TEST",
        telegram_allowed_user_ids="1,2",
        database_url=f"sqlite:///{tmp_path / 'mini.sqlite'}",
    )
    service = Service(session_factory(settings.database_url), Source(), settings)
    client = TestClient(create_app(service, settings))
    header = {"X-Telegram-Init-Data": signed(settings, auth_date=int(time.time()))}
    other = {
        "X-Telegram-Init-Data": signed(settings, user_id=2, auth_date=int(time.time()))
    }
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/api/dashboard").status_code == 401
    created = client.post(
        "/api/searches", headers=header, json={"url": URL, "target_model": "iPhone 15"}
    )
    assert created.status_code == 201
    search_id = created.json()["id"]
    dashboard = client.get("/api/dashboard", headers=header)
    assert dashboard.status_code == 200
    assert dashboard.json()["searches"][0]["id"] == search_id
    assert dashboard.headers["cache-control"] == "no-store"
    assert client.get(f"/api/searches/{search_id}", headers=other).status_code == 400
    assert (
        client.patch(
            f"/api/searches/{search_id}/status",
            headers=header,
            json={"status": "paused"},
        ).json()["status"]
        == "paused"
    )
    assert (
        client.post(f"/api/searches/{search_id}/scan", headers=header).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/searches/{search_id}/status",
            headers=header,
            json={"status": "active"},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/searches/{search_id}/scan", headers=header).status_code
        == 202
    )
    assert (
        client.get(f"/api/searches/{search_id}/listings", headers=header).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.delete(f"/api/searches/{search_id}", headers=header).status_code == 204
    )


def test_any_product_search_is_saved_before_avito_responds(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'goods.sqlite'}")
    service = Service(
        session_factory(settings.database_url), DeferredSource(), settings
    )
    search = service.create_search(
        1, "https://www.avito.ru/moskva/mebel_i_interer?q=диван", "Диваны"
    )
    assert search.status == "scanning"
    assert search.city == "Регион уточняется"
    assert "q=%D0%B4%D0%B8%D0%B2%D0%B0%D0%BD" in search.url


def test_personal_chat_ticket_is_single_use(tmp_path):
    settings = Settings(
        telegram_bot_token="123:TEST",
        telegram_allowed_user_ids="1",
        database_url=f"sqlite:///{tmp_path / 'ticket.sqlite'}",
    )
    service = Service(session_factory(settings.database_url), Source(), settings)
    client = TestClient(create_app(service, settings), base_url="https://testserver")
    ticket = issue_ticket(1)
    response = client.post("/api/session", json={"ticket": ticket})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert client.get("/api/dashboard").status_code == 200
    assert client.post("/api/session", json={"ticket": ticket}).status_code == 401


def test_market_history_uses_owned_search_and_real_daily_snapshots(tmp_path):
    settings = Settings(
        telegram_bot_token="123:TEST",
        telegram_allowed_user_ids="1,2",
        database_url=f"sqlite:///{tmp_path / 'history.sqlite'}",
    )
    sessions = session_factory(settings.database_url)
    service = Service(sessions, Source(), settings)
    search = service.create_search(1, URL)
    current = now()
    with sessions.begin() as db:
        for median, offset, group in [
            (60000, 20, "iphone"),
            (70000, 2, "iphone"),
            (71000, 2, "iphone"),
            (72000, 0, "iphone"),
            (90000, 0, "other"),
        ]:
            db.add(
                MarketSnapshot(
                    search_id=search.id,
                    group_key=group,
                    median=median,
                    low=median - 5000,
                    high=median + 5000,
                    count=12,
                    confidence="high",
                    calculated_at=current
                    - timedelta(days=offset, minutes=median // 1000),
                )
            )
    client = TestClient(create_app(service, settings))
    owner = {"X-Telegram-Init-Data": signed(settings, auth_date=int(time.time()))}
    other = {
        "X-Telegram-Init-Data": signed(settings, user_id=2, auth_date=int(time.time()))
    }
    response = client.get(
        f"/api/searches/{search.id}/market-history?days=7", headers=owner
    )
    assert response.status_code == 200
    assert [point["median"] for point in response.json()] == [70000, 72000]
    assert (
        client.get(
            f"/api/searches/{search.id}/market-history?days=90", headers=owner
        ).json()[0]["median"]
        == 60000
    )
    assert (
        client.get(
            f"/api/searches/{search.id}/market-history?days=8", headers=owner
        ).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/searches/{search.id}/market-history", headers=other
        ).status_code
        == 400
    )


def test_deals_collects_all_owned_searches_and_deduplicates(tmp_path):
    settings = Settings(
        telegram_bot_token="123:TEST",
        telegram_allowed_user_ids="1,2",
        database_url=f"sqlite:///{tmp_path / 'deals.sqlite'}",
    )
    sessions = session_factory(settings.database_url)
    service = Service(sessions, Source(), settings)
    first = service.create_search(1, URL)
    second = service.create_search(1, URL.replace("iphone+15", "macbook"))
    foreign = service.create_search(2, URL)
    with sessions.begin() as db:
        for ident, price in [("one", 60000), ("two", 70000), ("private", 10000)]:
            db.add(
                Listing(id=ident, title=ident, price=price, url="https://www.avito.ru/")
            )
        db.flush()
        for search_id, ident, score in [
            (first.id, "one", 90),
            (second.id, "one", 92),
            (second.id, "two", 85),
            (foreign.id, "private", 95),
        ]:
            db.add(
                Match(
                    search_id=search_id,
                    listing_id=ident,
                    score=score,
                    risk=10,
                    market_price=100000,
                    exclusion="",
                )
            )
    client = TestClient(create_app(service, settings))
    owner = {"X-Telegram-Init-Data": signed(settings, auth_date=int(time.time()))}
    response = client.get("/api/deals", headers=owner)
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["one", "two"]
    assert client.get("/api/deals").status_code == 401
    assert (
        client.post(
            "/api/listings/one/favorite", headers=owner, json={"interested": True}
        ).status_code
        == 200
    )
    favorites = client.get("/api/favorites", headers=owner).json()
    assert [(row["id"], row["score"], row["market_price"]) for row in favorites] == [
        ("one", 92, 100000)
    ]

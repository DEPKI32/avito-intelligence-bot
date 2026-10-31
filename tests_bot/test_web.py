from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import link_resolver
from intelligence.config import Settings
from intelligence.db import session_factory
from intelligence.service import Service
from intelligence.web import create_app, issue_ticket, validated_user

URL = "https://www.avito.ru/moskva/telefony?q=iphone+15"


class Source:
    def resolve(self, url):
        return link_resolver.ResolvedSearch(
            "iPhone 15", "goods", url, {"q": "iphone 15"}, "Москва", 30, [], [], []
        )


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

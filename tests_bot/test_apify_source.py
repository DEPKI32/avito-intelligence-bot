from __future__ import annotations

import httpx
from sqlalchemy import select

from intelligence.apify_source import ApifySource
from intelligence.config import Settings
from intelligence.db import Match, session_factory
from intelligence.service import Service


def test_incremental_feed_keeps_existing_listings_and_accepts_new_ones(
    tmp_path, monkeypatch
):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'feed.sqlite3'}",
        telegram_allowed_user_ids="1",
        source_provider="apify",
        apify_token="test-only",
        check_interval_seconds=300,
    )
    sessions = session_factory(settings.database_url)
    source = ApifySource(settings)
    service = Service(sessions, source, settings)
    first = {
        "id": "12345678",
        "url": "https://www.avito.ru/moskva/audio_i_video/naushniki_12345678",
        "title": "AirPods Max",
        "price": 18000,
        "sellerType": "private",
        "address": "Москва",
    }
    second = {
        **first,
        "id": "12345679",
        "url": first["url"].replace("12345678", "12345679"),
    }
    batches = [[first], [], [second]]
    requests = []

    def fake_post(url, *, headers, params, json, timeout):
        requests.append((url, headers, params, json, timeout))
        return httpx.Response(
            200, json=batches.pop(0), request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    search = service.create_search(
        1, "https://www.avito.ru/moskva/audio_i_video?q=airpods"
    )
    assert service.scan_one(search.id)["complete"] is True
    assert service.scan_one(search.id)["new"] == 0
    assert service.scan_one(search.id)["new"] == 1

    with sessions() as db:
        matches = list(db.scalars(select(Match).order_by(Match.listing_id)))
        assert [match.state for match in matches] == ["baseline", "seen"]
    assert all(call[3]["incrementalMode"] is True for call in requests)
    assert all(call[3]["urls"] == [search.url] for call in requests)
    assert all(call[2]["maxTotalChargeUsd"] == 0.25 for call in requests)
    assert all(call[4] == 310 for call in requests)


def test_apify_error_does_not_look_like_empty_search(tmp_path, monkeypatch):
    settings = Settings(
        apify_token="test-only", database_url=f"sqlite:///{tmp_path / 'feed.sqlite3'}"
    )
    source = ApifySource(settings)

    def bad_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", bad_post)
    search = type(
        "Search", (), {"id": 1, "user_id": 1, "url": "https://www.avito.ru/all?q=диван"}
    )()
    try:
        source.page(search, 1)
    except RuntimeError as exc:
        assert "Apify не вернул" in str(exc)
    else:
        raise AssertionError("Неудачный запрос принят за пустую выдачу")


def test_daily_free_plan_limit_blocks_extra_run(tmp_path, monkeypatch):
    settings = Settings(
        apify_token="test-only",
        apify_daily_run_limit=1,
        database_url=f"sqlite:///{tmp_path / 'feed.sqlite3'}",
    )
    source = ApifySource(settings)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=[], request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    search = type(
        "Search", (), {"id": 1, "user_id": 1, "url": "https://www.avito.ru/all?q=диван"}
    )()
    assert source.page(search, 1).items == ()
    try:
        source.page(search, 1)
    except RuntimeError as exc:
        assert "Дневной лимит" in str(exc)
    else:
        raise AssertionError("Превышен дневной лимит бесплатного тарифа")
    assert len(calls) == 1

from __future__ import annotations

import httpx
from sqlalchemy import select

from intelligence.config import Settings
from intelligence.dami_source import DamiSource
from intelligence.db import Match, session_factory
from intelligence.service import Service


def test_dami_excludes_known_ids_and_accepts_empty_check(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'feed.sqlite3'}",
        telegram_allowed_user_ids="1",
        source_provider="apify_dami",
        apify_token="test-only",
        apify_daily_run_limit=3,
    )
    sessions = session_factory(settings.database_url)
    source = DamiSource(settings, sessions)
    service = Service(sessions, source, settings)
    row = {
        "listingId": "12345678",
        "url": "https://www.avito.ru/moskva/audio_i_video/naushniki_12345678",
        "title": "AirPods Max",
        "price": 18000,
        "publishedAt": "2026-11-02T18:40:35.000Z",
        "sellerType": "private",
        "images": [],
    }
    batches = [[row], [{"_diagnostic": True, "errorCode": "NO_RESULTS"}]]
    requests = []

    def fake_post(url, *, headers, params, json, timeout):
        requests.append((url, params, json, timeout))
        return httpx.Response(
            201, json=batches.pop(0), request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    search = service.create_search(1, "https://www.avito.ru/moskva/audio_i_video?q=airpods")
    assert service.scan_one(search.id)["complete"] is True
    assert service.scan_one(search.id)["new"] == 0
    assert requests[0][2]["excludeListingIds"] == []
    assert requests[1][2]["excludeListingIds"] == ["12345678"]
    assert requests[0][2]["searchUrls"] == [search.url]
    assert requests[0][2]["maxPagesPerSearch"] == 1
    with sessions() as db:
        match = db.scalar(select(Match))
        assert match.state == "baseline"


def test_dami_blocked_response_does_not_clear_monitor(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'feed.sqlite3'}",
        telegram_allowed_user_ids="1",
        apify_token="test-only",
    )
    sessions = session_factory(settings.database_url)
    source = DamiSource(settings, sessions)
    service = Service(sessions, source, settings)

    def fake_post(url, **kwargs):
        return httpx.Response(
            201,
            json=[{"_diagnostic": True, "errorCode": "NOT_SERVED"}],
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    search = service.create_search(1, "https://www.avito.ru/moskva/audio_i_video?q=airpods")
    assert "NOT_SERVED" in service.scan_one(search.id)["error"]

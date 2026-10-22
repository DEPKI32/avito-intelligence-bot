import json

from sqlalchemy import func, select

from intelligence.db import Listing, Search, session_factory
from intelligence.legacy import import_legacy


def test_idempotent_legacy_import(tmp_path):
    search_config = tmp_path / "searches" / "old.json"
    old_dir = tmp_path / "data" / "searches" / "old"
    search_config.parent.mkdir(parents=True)
    old_dir.mkdir(parents=True)
    search_config.write_text(
        json.dumps(
            {
                "title": "Старый поиск",
                "catalog_url": "https://www.avito.ru/moskva/telefony",
                "profile": "goods",
                "params": {"q": "iphone"},
            }
        ),
        encoding="utf-8",
    )
    (old_dir / "listings.json").write_text(
        json.dumps(
            {
                "123": {
                    "id": 123,
                    "title": "iPhone",
                    "priceDetailed": {"value": 40000},
                    "urlPath": "/moskva/telefony/iphone_123",
                }
            }
        ),
        encoding="utf-8",
    )
    sessions = session_factory(f"sqlite:///{tmp_path / 'bot.db'}")
    assert import_legacy(sessions, 1, tmp_path) == 1
    assert import_legacy(sessions, 1, tmp_path) == 0
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Search)) == 1
        assert db.scalar(select(func.count()).select_from(Listing)) == 1
        assert db.scalar(select(Search)).status == "paused"
    assert search_config.exists() and (old_dir / "listings.json").exists()

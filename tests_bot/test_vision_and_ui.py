import io

import pytest
from PIL import Image, ImageDraw, UnidentifiedImageError

from intelligence.bot import menu, search_buttons
from intelligence.config import Settings
from intelligence.vision import analyze_vision, fingerprint, similar


def png(color):
    image = Image.new("RGB", (80, 80), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_hash_and_broken_data():
    def patterned(vertical):
        image = Image.new("RGB", (80, 80), "white")
        ImageDraw.Draw(image).rectangle(
            (0, 0, 39, 79) if vertical else (0, 0, 79, 39), fill="black"
        )
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    first = fingerprint(patterned(True))
    assert similar(first, fingerprint(patterned(True)))
    assert not similar(first, fingerprint(patterned(False)), 0)
    with pytest.raises(UnidentifiedImageError):
        fingerprint(b"not an image")


@pytest.mark.asyncio
async def test_vision_disabled():
    assert await analyze_vision([], Settings()) is None
    assert await analyze_vision(["https://example.com/x.png"], Settings()) is None


def test_all_main_buttons_have_data():
    main = {button.callback_data for row in menu().inline_keyboard for button in row}
    assert main == {
        "searches",
        "new",
        "markets",
        "deals",
        "database",
        "settings",
        "help",
    }
    card = {
        button.callback_data.split(":")[0]
        for row in search_buttons(1, "active").inline_keyboard
        for button in row
    }
    assert card == {
        "pause",
        "filters",
        "stats",
        "offers",
        "browse",
        "scan_now",
        "export",
        "delete",
        "home",
    }
    paused = {
        button.callback_data.split(":")[0]
        for row in search_buttons(1, "paused").inline_keyboard
        for button in row
    }
    assert "resume" in paused


@pytest.mark.asyncio
async def test_vision_valid_invalid_and_budget(monkeypatch, tmp_path):
    from intelligence import vision

    monkeypatch.setattr(vision, "_BUDGET_FILE", tmp_path / "usage.json")

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, *args, **kwargs):
            return Response(
                '{"warnings": ["царапина"], "confidence": 0.7, "summary": "видна царапина"}'
            )

    monkeypatch.setattr(vision.httpx, "AsyncClient", Client)
    settings = Settings(
        ai_enabled=True,
        ai_api_key="test",
        ai_model="test",
        ai_base_url="https://api.example.com",
        ai_daily_request_limit=1,
    )
    result = await vision.analyze_vision(["https://img.avito.st/x.png"], settings)
    assert result and result.warnings == ["царапина"]
    assert await vision.analyze_vision(["https://img.avito.st/x.png"], settings) is None
    assert (
        await vision.analyze_vision(["https://internal.example.com/x.png"], settings)
        is None
    )
    assert not vision.allowed_image_url("https://img.avito.st:bad/x.png")


@pytest.mark.asyncio
async def test_inspect_images_only_from_actual_bytes(monkeypatch):
    from intelligence import vision

    raw = {
        "photos": [
            {"url": "https://img.avito.st/a.png"},
            {"url": "https://evil.test/b.png"},
        ]
    }
    requested = []

    async def fake_download(url):
        requested.append(url)
        return png("red")

    monkeypatch.setattr(vision, "download_image", fake_download)
    hashes, semantic = await vision.inspect_images(raw, Settings())
    assert len(hashes) == 1
    assert requested == ["https://img.avito.st/a.png"]
    assert semantic is None


@pytest.mark.asyncio
async def test_text_ai_fallback_and_json_validation(monkeypatch, tmp_path):
    from intelligence import text_ai, vision

    monkeypatch.setattr(vision, "_BUDGET_FILE", tmp_path / "usage.json")
    assert await text_ai.analyze_text("phone", "works", Settings()) is None

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class Client:
        output = ""

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, *args, **kwargs):
            return Response(self.output)

    monkeypatch.setattr(text_ai.httpx, "AsyncClient", Client)
    settings = Settings(
        ai_enabled=True,
        ai_api_key="test",
        ai_model="test",
        ai_base_url="https://api.example.com",
        ai_daily_request_limit=6,
    )
    Client.output = "not-json"
    assert (
        await text_ai.analyze_text("iPhone 15", "Face ID не работает", settings) is None
    )
    Client.output = '{"model":"iPhone 15","memory":"128 GB","risks":["Face ID неисправен"],"confidence":0.9,"summary":"в описании заявлен дефект"}'
    result = await text_ai.analyze_text("iPhone 15", "Face ID не работает", settings)
    assert result and result.risks == ["Face ID неисправен"]

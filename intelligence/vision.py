"""Actual image hashing and optional structured vision API."""

from __future__ import annotations

import io
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import imagehash
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from .config import Settings


class VisionResult(BaseModel):
    warnings: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(max_length=500)


@dataclass(frozen=True)
class ImageFingerprint:
    perceptual_hash: str
    width: int
    height: int


_BUDGET_LOCK = threading.Lock()
_BUDGET_FILE = Path("data/ai_usage.json")
LOG = logging.getLogger(__name__)


def allowed_image_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        return (
            parts.scheme == "https"
            and not parts.username
            and not parts.password
            and parts.port is None
            and (host == "avito.ru" or host.endswith((".avito.ru", ".avito.st")))
        )
    except ValueError:
        return False


def image_urls(raw: dict, limit: int = 5) -> list[str]:
    """Find only public Avito image URLs in an untrusted listing payload."""
    found: list[str] = []
    stack = [raw]
    visited = 0
    while stack and visited < 2000 and len(found) < limit:
        value = stack.pop()
        visited += 1
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value[:100])
        elif (
            isinstance(value, str)
            and len(value) <= 2048
            and allowed_image_url(value)
            and (urlsplit(value).hostname or "").endswith(".avito.st")
            and value not in found
        ):
            found.append(value)
    return found


async def inspect_images(
    raw: dict, settings: Settings
) -> tuple[list[str], VisionResult | None]:
    hashes: list[str] = []
    processed_urls: list[str] = []
    for url in image_urls(raw, settings.ai_max_images or 2):
        try:
            data = await download_image(url)
            hashes.append(fingerprint(data).perceptual_hash)
            processed_urls.append(url)
        except (httpx.HTTPError, OSError, ValueError):
            LOG.warning("Не удалось обработать фотографию объявления")
    semantic = (
        await analyze_vision(processed_urls, settings) if processed_urls else None
    )
    return hashes, semantic


def reserve_request(settings: Settings) -> bool:
    if settings.ai_daily_request_limit <= 0:
        return False
    with _BUDGET_LOCK:
        today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
        try:
            current = json.loads(_BUDGET_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        count = current.get("count", 0) if current.get("date") == today else 0
        if not isinstance(count, int) or count < 0:
            count = 0
        if count >= settings.ai_daily_request_limit:
            return False
        try:
            _BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = _BUDGET_FILE.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"date": today, "count": count + 1}), encoding="utf-8"
            )
            os.replace(temporary, _BUDGET_FILE)
            return True
        except OSError:
            LOG.warning("Не удалось сохранить лимит AI-запросов; анализ пропущен")
            return False


def fingerprint(data: bytes) -> ImageFingerprint:
    with Image.open(io.BytesIO(data)) as checked, Image.open(io.BytesIO(data)) as image:
        checked.verify()
        if image.width * image.height > 25_000_000:
            raise ValueError("Изображение слишком большое")
        return ImageFingerprint(str(imagehash.phash(image)), image.width, image.height)


def similar(a: ImageFingerprint, b: ImageFingerprint, threshold: int = 8) -> bool:
    return (
        imagehash.hex_to_hash(a.perceptual_hash)
        - imagehash.hex_to_hash(b.perceptual_hash)
        <= threshold
    )


async def download_image(url: str, max_bytes: int = 5_000_000) -> bytes:
    if not allowed_image_url(url):
        raise ValueError("Недопустимый адрес изображения")
    async with (
        httpx.AsyncClient(timeout=12, follow_redirects=False) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        chunks = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("Изображение слишком большое")
            chunks.append(chunk)
        return b"".join(chunks)


async def analyze_vision(
    image_urls: list[str], settings: Settings
) -> VisionResult | None:
    if not settings.ai_enabled or not settings.ai_api_key or not image_urls:
        return None
    urls = image_urls[: settings.ai_max_images]
    if not urls or not all(allowed_image_url(url) for url in urls):
        return None
    # The provider must support OpenAI-compatible chat completions and JSON mode.
    payload = {
        "model": settings.ai_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "Describe only visible defects. Return JSON: warnings array, confidence 0..1, summary. Never claim authenticity or functionality.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Проверь видимые повреждения товара."}
                ]
                + [{"type": "image_url", "image_url": {"url": url}} for url in urls],
            },
        ],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(3):
            if not reserve_request(settings):
                return None
            try:
                response = await client.post(
                    settings.ai_base_url.rstrip("/") + "/chat/completions",
                    json=payload,
                    headers={"Authorization": "Bearer " + settings.ai_api_key},
                )
                response.raise_for_status()
                return VisionResult.model_validate(
                    json.loads(response.json()["choices"][0]["message"]["content"])
                )
            except (
                httpx.TimeoutException,
                httpx.TransportError,
                httpx.HTTPStatusError,
                KeyError,
                ValueError,
                ValidationError,
            ):
                if attempt == 2:
                    return None
    return None

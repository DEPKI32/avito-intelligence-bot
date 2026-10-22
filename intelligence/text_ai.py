"""Optional, bounded LLM text extraction. Deterministic analysis remains primary."""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import Settings
from .vision import reserve_request

LOG = logging.getLogger(__name__)


class TextResult(BaseModel):
    model: str = Field(default="", max_length=100)
    memory: str = Field(default="", max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(max_length=500)


async def analyze_text(
    title: str, description: str, settings: Settings
) -> TextResult | None:
    if (
        not settings.ai_enabled
        or not settings.ai_api_key
        or not settings.ai_base_url
        or not settings.ai_model
    ):
        return None
    payload = {
        "model": settings.ai_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "Extract only explicit facts from an Avito listing. Return JSON with model, memory, risks array, confidence 0..1, summary. Negated defects are not risks. Never claim a working condition is confirmed.",
            },
            {
                "role": "user",
                "content": f"Название: {title[:500]}\nОписание: {description[:5000]}",
            },
        ],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(3):
            if not reserve_request(settings):
                return None
            try:
                response = await client.post(
                    settings.ai_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + settings.ai_api_key},
                    json=payload,
                )
                response.raise_for_status()
                return TextResult.model_validate(
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
                LOG.warning("Дополнительный анализ текста недоступен")
    return None

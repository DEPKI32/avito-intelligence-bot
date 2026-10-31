"""Conservative, explainable listing analysis; no AI claims without API evidence."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

from .db import Listing, Search

_BAD = [
    (r"на\s+запчаст|на\s+разбор|донор", "продаётся на запчасти"),
    (
        r"не\s+работает|не\s+включается|разбит|треснут|утоплен|после\s+воды",
        "заявлена неисправность",
    ),
    (r"face\s*id\s+не\s+работает|не\s+работает\s+face\s*id", "Face ID не работает"),
    (
        r"icloud\s+lock|activation\s+lock|заблокирован|блокировка\s+оператора|\bmdm\b",
        "упомянута блокировка",
    ),
]
_SHOP = [
    r"наш\s+магазин",
    r"работаем\s+ежедневно",
    r"опт\s+и\s+розниц",
    r"гарантия\s+магазина",
    r"в\s+наличии\s+много",
    r"trade.?in",
]
_MEMORY = re.compile(r"\b(\d{2,4})\s*(гб|gb|тб|tb)\b", re.IGNORECASE)
_IPHONE = re.compile(
    r"\biphone\s*(\d{1,2})(?:\s*(pro\s*max|pro|plus|mini))?\b", re.IGNORECASE
)
_COMPACT_MEMORY = re.compile(r"\b(\d{1,2})\s*/\s*(\d{2,4})\b")
_SCREEN_SIZE = re.compile(
    r"\b\d{1,2}(?:[.,]\d)?\s*(?:дюйм(?:а|ов)?|inch(?:es)?)\b", re.IGNORECASE
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яё0-9]+", text.casefold())


def model_key(text: str) -> str:
    match = _IPHONE.search(text)
    if match:
        return (
            "iphone "
            + match[1]
            + (" " + re.sub(r"\s+", " ", match[2].lower()) if match[2] else "")
        )
    core = text.split(",")[0]
    core = _COMPACT_MEMORY.sub(" ", core)
    core = _SCREEN_SIZE.sub(" ", core)
    core = _MEMORY.sub(" ", core)
    return " ".join(_words(core)[:4])[:100]


def model_matches(title: str, target: str) -> bool:
    if _IPHONE.search(target):
        return model_key(title) == model_key(target)
    wanted = _words(target)
    found = _words(title)
    return bool(wanted) and any(
        found[index : index + len(wanted)] == wanted
        for index in range(len(found) - len(wanted) + 1)
    )


def memory_values(text: str) -> tuple[int, ...]:
    pair = _COMPACT_MEMORY.search(text)
    if pair and 4 <= int(pair[1]) <= 64 and 64 <= int(pair[2]) <= 4096:
        return int(pair[1]), int(pair[2])
    return tuple(
        int(amount) * (1024 if unit.lower() in ("тб", "tb") else 1)
        for amount, unit in _MEMORY.findall(text)
    )[:2]


def memory_key(text: str) -> str:
    return "-".join(f"{amount}gb" for amount in memory_values(text))


def memory_matches(text: str, target: str) -> bool:
    wanted = memory_values(target)
    found = memory_values(text)
    return bool(wanted) and all(amount in found for amount in wanted)


def condition_key(text: str) -> str:
    value = text.lower()
    if re.search(r"\b(?:б/у|бу|использовался|пользовались|не новый)\b", value):
        return "used"
    if re.search(r"\b(?:новый|новая|новое|запечатан|не распакован)\b", value):
        return "new"
    return "unknown"


def group_key(listing: Listing) -> str:
    text = listing.title + " " + listing.description
    return f"{model_key(listing.title)}|{memory_key(listing.title) or memory_key(listing.description)}|{condition_key(text)}"


def defects(text: str) -> list[str]:
    clean = text.lower()
    # Explicit denial must not become a defect.
    clean = re.sub(
        r"никаких\s+проблем\s+с\s+face\s*id\s+нет|face\s*id\s+работает|не\s+бит(?:ый|ая|ое)",
        "",
        clean,
    )
    return [
        reason for pattern, reason in _BAD if re.search(pattern, clean, re.IGNORECASE)
    ]


@dataclass(frozen=True)
class SellerVerdict:
    kind: str
    confidence: float
    reasons: tuple[str, ...]


def seller_type(label: str, description: str, closed: int | None) -> SellerVerdict:
    lower = (label + " " + description).lower()
    lower = re.sub(r"\bне\s+(?:наш\s+)?магазин\b", "", lower)
    points = 0
    reasons = []
    if re.search(r"магазин|компания|профессионал", label, re.IGNORECASE):
        points += 3
        reasons.append("тип профиля Авито")
    phrases = sum(bool(re.search(p, lower, re.IGNORECASE)) for p in _SHOP)
    if phrases >= 2:
        points += 2
        reasons.append("несколько коммерческих фраз")
    elif phrases == 1:
        points += 1
        reasons.append("коммерческая фраза")
    if closed is not None and closed >= 100:
        points += 2
        reasons.append(f"{closed} завершённых объявлений")
    if points >= 3:
        return SellerVerdict("shop", min(0.95, 0.65 + points * 0.05), tuple(reasons))
    if points == 2:
        return SellerVerdict("reseller", 0.65, tuple(reasons))
    if points == 1:
        return SellerVerdict("uncertain", 0.45, tuple(reasons))
    if label and closed is not None and closed < 20:
        return SellerVerdict("likely_private", 0.6, ("мало завершённых объявлений",))
    return SellerVerdict("unknown", 0.2, ("недостаточно сведений",))


@dataclass(frozen=True)
class Market:
    group: str
    median: int
    low: int
    high: int
    count: int
    confidence: str


def calculate_market(group: str, listings: Iterable[Listing]) -> Market | None:
    prices = sorted(
        {
            (str(item.id), item.price)
            for item in listings
            if item.price
            and item.price >= 100
            and group_key(item) == group
            and not defects(item.title + " " + item.description)
        }
    )
    values = [price for _, price in prices]
    if len(values) < 5:
        return None
    center = statistics.median(values)
    deviations = [abs(x - center) for x in values]
    mad = statistics.median(deviations)
    # MAD may be zero when many sellers use the same rounded price.
    tolerance = max(3 * 1.4826 * mad, center * 0.15)
    kept = sorted(x for x in values if abs(x - center) <= tolerance)
    if len(kept) < 5:
        return None
    q1, q3 = statistics.quantiles(kept, n=4)[0], statistics.quantiles(kept, n=4)[2]
    return Market(
        group,
        round(statistics.median(kept)),
        round(q1),
        round(q3),
        len(kept),
        "high" if len(kept) >= 20 else "medium" if len(kept) >= 10 else "low",
    )


@dataclass(frozen=True)
class Assessment:
    score: int
    risk: int
    exclusion: str
    reasons: tuple[str, ...]
    discount_percent: float | None


def assess(listing: Listing, search: Search, market: Market | None) -> Assessment:
    reasons: list[str] = []
    bad = defects(listing.title + " " + listing.description)
    seller = seller_type(
        listing.seller_label, listing.description, listing.closed_listings
    )
    exclusion = ""
    if search.target_model and not model_matches(listing.title, search.target_model):
        exclusion = "другая модель"
    elif search.target_memory and not memory_matches(
        listing.title + " " + listing.description, search.target_memory
    ):
        exclusion = "другой объём памяти"
    elif listing.price is None or listing.price < 100:
        exclusion = "цена отсутствует или недостоверна"
    elif search.min_price and listing.price < search.min_price:
        exclusion = "ниже заданной минимальной цены"
    elif search.max_price and listing.price > search.max_price:
        exclusion = "выше заданной максимальной цены"
    elif (
        search.condition_filter != "all"
        and condition_key(listing.title + " " + listing.description)
        != search.condition_filter
    ):
        exclusion = "состояние не соответствует фильтру или не указано"
    elif bad:
        exclusion = "; ".join(bad)
    elif search.seller_filter == "private" and seller.kind not in ("likely_private",):
        exclusion = "тип продавца не подтверждён как частный"
    elif search.seller_filter == "no_shops" and seller.kind == "shop":
        exclusion = "вероятный магазин"
    risk = 15 + (
        20 if seller.kind == "unknown" else 10 if seller.kind == "uncertain" else 0
    )
    if bad:
        risk += 65
        reasons.extend(bad)
    if seller.reasons:
        reasons.extend(seller.reasons)
    discount = None
    score = 40
    if market and listing.price:
        discount = (market.median - listing.price) / market.median * 100
        if discount > 55:
            risk += 35
            reasons.append("подозрительно низкая цена")
        score += max(-30, min(45, round(discount * 1.8)))
        reasons.append(f"цена отличается от медианы на {discount:+.1f}%")
    else:
        reasons.append("недостаточно данных для надёжной оценки рынка")
    score = max(0, min(100, score - risk // 2))
    if exclusion:
        score = min(score, 20)
    return Assessment(score, min(100, risk), exclusion, tuple(reasons), discount)


def should_alert(
    assessment: Assessment, listing: Listing, search: Search, market: Market | None
) -> bool:
    if assessment.exclusion or assessment.risk >= 60 or listing.price is None:
        return False
    mode = search.notification_mode
    if mode == "all":
        return True
    if mode == "max_price":
        return (
            search.max_alert_price is not None
            and listing.price <= search.max_alert_price
        )
    if mode == "score":
        return assessment.score >= search.min_score and market is not None
    if not market or assessment.discount_percent is None:
        return False
    threshold = max(search.discount_percent, 25 if mode == "strong" else 0)
    # Account for spread so ordinary low-end offers do not flood the chat.
    spread_threshold = max(0, (market.median - market.low) / market.median * 100)
    return (
        assessment.discount_percent >= max(threshold, spread_threshold)
        and assessment.score >= search.min_score
    )

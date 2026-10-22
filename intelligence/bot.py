from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import link_resolver

from .config import Settings
from .export import export_search
from .service import Service, validate_url
from .text_ai import analyze_text
from .vision import image_urls, inspect_images

LOG = logging.getLogger(__name__)
router = Router()
SERVICE: Service
SETTINGS: Settings


class Access(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or user.id not in SETTINGS.allowed_ids:
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            return None
        return await handler(event, data)


class NewSearch(StatesGroup):
    url = State()
    model = State()
    memory = State()
    name = State()


class Edit(StatesGroup):
    value = State()


class UserEdit(StatesGroup):
    value = State()


def button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("🔎 Мои мониторинги", "searches"), button("➕ Новый поиск", "new")],
            [
                button("📊 Анализ рынка", "markets"),
                button("💎 Лучшие предложения", "deals"),
            ],
            [
                button("📋 База объявлений", "database"),
                button("⚙️ Настройки", "settings"),
            ],
            [button("❓ Помощь", "help")],
        ]
    )


def back():
    return InlineKeyboardMarkup(inline_keyboard=[[button("🏠 Главное меню", "home")]])


def search_buttons(search_id: int, status: str):
    action = "resume" if status == "paused" else "pause"
    label = "▶️ Запустить" if status == "paused" else "⏸ Остановить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(label, f"{action}:{search_id}"),
                button("⚙️ Изменить фильтры", f"filters:{search_id}"),
            ],
            [
                button("📊 Статистика", f"stats:{search_id}"),
                button("💎 Выгодные варианты", f"offers:{search_id}"),
            ],
            [button("📥 Скачать Excel", f"export:{search_id}")],
            [button("🗑 Удалить", f"delete:{search_id}"), button("🏠 Меню", "home")],
        ]
    )


def money(value):
    return f"{value:,} ₽".replace(",", " ") if value is not None else "—"


def date(value):
    if not value:
        return "ещё не было"
    return (
        value.replace(tzinfo=ZoneInfo("UTC"))
        .astimezone(ZoneInfo(SETTINGS.timezone))
        .strftime("%d.%m.%Y %H:%M")
    )


async def display(target, text: str, keyboard=None):
    if isinstance(target, CallbackQuery):
        await target.answer()
        try:
            await target.message.edit_text(
                text,
                reply_markup=keyboard or back(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except (TypeError, ValueError, RuntimeError, TelegramBadRequest):
            await target.message.answer(
                text,
                reply_markup=keyboard or back(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        await target.answer(
            text,
            reply_markup=keyboard or back(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await display(
        message,
        "Привет! Я слежу за объявлениями Авито и показываю подходящие предложения. Выберите действие:",
        menu(),
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await display(
        message,
        "Пришлите ссылку на страницу поиска Авито или нажмите «Новый поиск». После добавления я начну собирать рынок. Настройки и Excel доступны в карточке поиска. Оценка рынка основана на ценах объявлений, а не на подтверждённых сделках.",
    )


@router.message(Command("searches"))
async def searches_command(message: Message):
    await show_searches(message)


@router.message(Command("status"))
async def status_command(message: Message):
    rows = await asyncio.to_thread(SERVICE.list_searches, message.from_user.id)
    await display(
        message,
        f"Мониторингов: {len(rows)}. Активных: {sum(x.status in ('active', 'scanning') for x in rows)}.",
    )


@router.message(Command("settings"))
async def settings_command(message: Message):
    await show_settings(message)


@router.callback_query(F.data == "home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await display(call, "Главное меню:", menu())


@router.callback_query(F.data == "help")
async def help_callback(call: CallbackQuery):
    await display(
        call,
        "Создайте поиск ссылкой Авито. Первичный сбор идёт постранично; новые события после него проверяются регулярно. Остановить и изменить условия можно в карточке мониторинга.",
    )


@router.callback_query(F.data == "searches")
async def searches_callback(call: CallbackQuery):
    await show_searches(call)


async def show_searches(target):
    rows = await asyncio.to_thread(SERVICE.list_searches, target.from_user.id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [button(f"{s.title[:30]} · {s.status}", f"search:{s.id}")] for s in rows
        ]
        + [[button("➕ Новый поиск", "new"), button("🏠 Меню", "home")]]
    )
    await display(
        target, "Ваши мониторинги:" if rows else "Пока нет мониторингов.", keyboard
    )


@router.callback_query(F.data == "new")
async def new_search(call: CallbackQuery, state: FSMContext):
    await state.set_state(NewSearch.url)
    await display(
        call,
        "Отправьте ссылку на страницу поиска Авито. Можно вставить её и без этой кнопки.",
    )


@router.message(NewSearch.url)
async def receive_url(message: Message, state: FSMContext):
    try:
        url = validate_url(message.text or "")
    except ValueError as exc:
        await message.answer(
            f"{html.escape(str(exc))}. Отправьте правильную ссылку ещё раз."
        )
        return
    await state.update_data(url=url)
    await state.set_state(NewSearch.model)
    parsed = link_resolver.parse_link(url)
    await display(
        message,
        (
            f"Ссылка принята. По URL: регион — {html.escape(parsed.city_slug)}, "
            f"категория — {html.escape(parsed.category_slug or 'не указана')}. "
            "Фильтры Авито проверю при сохранении. Укажите точную модель "
            "(например, iPhone 15) или отправьте «-», чтобы сравнивать группы автоматически."
        ),
    )


@router.message(NewSearch.model)
async def receive_model(message: Message, state: FSMContext):
    await state.update_data(
        model="" if message.text == "-" else (message.text or "")[:120]
    )
    await state.set_state(NewSearch.memory)
    await display(
        message, "Объём памяти (например, 128 ГБ) или «-», если это не требуется:"
    )


@router.message(NewSearch.memory)
async def receive_memory(message: Message, state: FSMContext):
    await state.update_data(
        memory="" if message.text == "-" else (message.text or "")[:30]
    )
    await state.set_state(NewSearch.name)
    await display(message, "Название мониторинга или «-» для названия из ссылки:")


@router.message(NewSearch.name)
async def receive_name(message: Message, state: FSMContext):
    data = await state.get_data()
    await display(
        message, "Проверяю ссылку на Авито. Это может занять несколько минут…"
    )
    try:
        search = await asyncio.to_thread(
            SERVICE.create_search,
            message.from_user.id,
            data["url"],
            "" if message.text == "-" else (message.text or ""),
            data["model"],
            data["memory"],
        )
    except Exception as exc:
        LOG.exception("Создание поиска не удалось")
        await display(
            message,
            f"Не удалось создать поиск: {html.escape(str(exc)[:250])}. Проверьте ссылку и попробуйте снова.",
            menu(),
        )
        await state.clear()
        return
    await state.clear()
    await display(
        message,
        f"✅ Создан «{html.escape(search.title)}». Регион: {html.escape(search.city)}. Фильтры Авито: {html.escape(search.filters_text or 'не определены')}. Первичный сбор начнётся автоматически.",
        search_buttons(search.id, search.status),
    )


@router.message(F.text.regexp(r"^https://"))
async def pasted_url(message: Message, state: FSMContext):
    await state.set_state(NewSearch.url)
    await receive_url(message, state)


@router.callback_query(F.data.startswith("search:"))
async def search_card(call: CallbackQuery):
    await search_card_with_id(call, int(call.data.split(":")[1]))


async def search_card_with_id(call: CallbackQuery, search_id: int):
    try:
        info = await asyncio.to_thread(SERVICE.stats, call.from_user.id, search_id)
    except ValueError as exc:
        await display(call, str(exc), menu())
        return
    s = info["search"]
    market = info["market"]
    text = (
        f"<b>{html.escape(s.title)}</b>\nСтатус: {s.status}\nРегион: {html.escape(s.city)}\n"
        f"Модель: {html.escape(s.target_model or 'по ссылке')} {html.escape(s.target_memory)}\n"
        f"Объявлений: {info['total']}; интересных: {info['deals']}\n"
        f"Последняя успешная проверка: {date(s.last_success)}\n"
        f"Рынок{f' (по данным от {date(market.calculated_at)})' if market else ''}: {money(market.median) if market else 'Недостаточно данных для надёжной оценки рынка'}\n"
        f"Порог: {s.discount_percent}% ниже рынка; оценка от {s.min_score}/100"
    )
    if s.last_error:
        text += f"\nИсточник временно недоступен: {html.escape(s.last_error[:150])}"
    await display(call, text, search_buttons(s.id, s.status))


@router.callback_query(F.data.startswith(("pause:", "resume:")))
async def toggle(call: CallbackQuery):
    action, raw_id = call.data.split(":")
    await asyncio.to_thread(
        SERVICE.set_status,
        call.from_user.id,
        int(raw_id),
        "paused" if action == "pause" else "active",
    )
    await search_card_with_id(call, int(raw_id))


@router.callback_query(F.data.startswith("delete:"))
async def delete_confirm(call: CallbackQuery):
    search_id = int(call.data.split(":")[1])
    await display(
        call,
        "Удалить мониторинг? История поиска будет удалена; общая база объявлений сохранится.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button("Да, удалить", f"delete_yes:{search_id}"),
                    button("Отмена", f"search:{search_id}"),
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("delete_yes:"))
async def delete_yes(call: CallbackQuery):
    await asyncio.to_thread(
        SERVICE.delete, call.from_user.id, int(call.data.split(":")[1])
    )
    await display(call, "Мониторинг удалён.", menu())


FILTERS = [
    ("title", "Название"),
    ("target_model", "Точная модель"),
    ("target_memory", "Память"),
    ("min_price", "Мин. цена"),
    ("max_price", "Макс. цена"),
    ("discount_percent", "Скидка, %"),
    ("max_alert_price", "Лимит уведомления, ₽"),
    ("min_score", "Мин. оценка"),
    ("interval_seconds", "Интервал, сек"),
]


@router.callback_query(F.data.startswith("filters:"))
async def filters(call: CallbackQuery):
    await show_filters(call, int(call.data.split(":")[1]))


async def show_filters(call: CallbackQuery, search_id: int):
    info = await asyncio.to_thread(SERVICE.stats, call.from_user.id, search_id)
    s = info["search"]
    rows = [[button(label, f"edit:{search_id}:{key}")] for key, label in FILTERS]
    rows += [
        [button(f"Продавцы: {s.seller_filter}", f"seller:{search_id}")],
        [button(f"Состояние: {s.condition_filter}", f"condition:{search_id}")],
        [button(f"Уведомления: {s.notification_mode}", f"mode:{search_id}")],
        [button(f"События: {s.events_mode}", f"events:{search_id}")],
        [button("◀️ Назад", f"search:{search_id}")],
    ]
    await display(
        call,
        "Настройки мониторинга. Выберите параметр:",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("edit:"))
async def edit_prompt(call: CallbackQuery, state: FSMContext):
    _, search_id, key = call.data.split(":")
    await state.set_state(Edit.value)
    await state.update_data(search_id=int(search_id), key=key)
    await display(
        call,
        f"Введите новое значение для «{dict(FILTERS)[key]}». Для отмены нажмите главное меню.",
    )


@router.message(Edit.value)
async def edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await asyncio.to_thread(
            SERVICE.set_filter,
            message.from_user.id,
            data["search_id"],
            data["key"],
            message.text or "",
        )
    except ValueError as exc:
        await message.answer(html.escape(str(exc)) + ". Повторите ввод.")
        return
    await state.clear()
    await display(
        message,
        "Настройка сохранена.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [button("⚙️ Настройки поиска", f"filters:{data['search_id']}")]
            ]
        ),
    )


@router.callback_query(F.data.startswith(("seller:", "condition:", "mode:", "events:")))
async def choice(call: CallbackQuery):
    kind, raw_id = call.data.split(":")
    search_id = int(raw_id)
    options = {
        "seller": [
            ("all", "Все"),
            ("no_shops", "Без магазинов"),
            ("private", "Только вероятно частные"),
        ],
        "condition": [
            ("all", "Любое"),
            ("new", "Только новые"),
            ("used", "Только б/у"),
        ],
        "mode": [
            ("all", "Все подходящие"),
            ("below_market", "Ниже рынка"),
            ("strong", "Значительно ниже"),
            ("max_price", "Не дороже суммы"),
            ("score", "По оценке"),
        ],
        "events": [("new", "Только новые"), ("new_and_price", "Новые и снижение цены")],
    }
    await display(
        call,
        "Выберите вариант:",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [button(label, f"set:{search_id}:{kind}:{value}")]
                for value, label in options[kind]
            ]
            + [[button("◀️ Назад", f"filters:{search_id}")]]
        ),
    )


@router.callback_query(F.data.startswith("set:"))
async def set_choice(call: CallbackQuery):
    _, raw_id, kind, value = call.data.split(":")
    key = {
        "seller": "seller_filter",
        "condition": "condition_filter",
        "mode": "notification_mode",
        "events": "events_mode",
    }[kind]
    await asyncio.to_thread(
        SERVICE.set_filter, call.from_user.id, int(raw_id), key, value
    )
    await show_filters(call, int(raw_id))


@router.callback_query(F.data.startswith("stats:"))
async def stats_callback(call: CallbackQuery):
    search_id = int(call.data.split(":")[1])
    info = await asyncio.to_thread(SERVICE.stats, call.from_user.id, search_id)
    s = info["search"]
    market = info["market"]
    text = (
        f"📊 <b>{html.escape(s.title)}</b>\nСобрано: {info['total']}\nИсключено: {info['excluded']}\n"
        f"Интересных: {info['deals']}\nПоследняя проверка: {date(s.last_success)}\n"
    )
    text += (
        f"Оценка предложений: {money(market.median)}; типичный диапазон {money(market.low)}–{money(market.high)}. Выборка: {market.count}; доверие: {market.confidence}. Рассчитано: {date(market.calculated_at)}."
        if market
        else "Недостаточно данных для надёжной оценки рынка."
    )
    await display(
        call,
        text,
        InlineKeyboardMarkup(
            inline_keyboard=[[button("◀️ Назад", f"search:{search_id}")]]
        ),
    )


@router.callback_query(F.data.startswith("offers:"))
async def offers_callback(call: CallbackQuery):
    search_id = int(call.data.split(":")[1])
    rows = await asyncio.to_thread(SERVICE.offers, call.from_user.id, search_id, True)
    text = "💎 Выгодные варианты:\n" + (
        "\n".join(
            f"• {html.escape(l.title[:70])} — {money(l.price)} · {m.score}/100"
            for m, l in rows[:10]
        )
        if rows
        else "Пока нет предложений, прошедших условия."
    )
    await display(
        call,
        text,
        InlineKeyboardMarkup(
            inline_keyboard=[[button("◀️ Назад", f"search:{search_id}")]]
        ),
    )


@router.callback_query(F.data.startswith("export:"))
async def export_callback(call: CallbackQuery):
    search_id = int(call.data.split(":")[1])
    await call.answer("Готовлю Excel…")
    output = Path("output") / f"intelligence-{search_id}.xlsx"
    try:
        await asyncio.to_thread(
            export_search, SERVICE.sessions, call.from_user.id, search_id, output
        )
        await call.message.answer_document(
            BufferedInputFile(output.read_bytes(), filename=output.name)
        )
    except Exception:
        LOG.exception("Не удалось выгрузить Excel")
        await call.message.answer("Не удалось подготовить Excel. Попробуйте позже.")


@router.callback_query(F.data.in_({"markets", "deals", "database"}))
async def overview(call: CallbackQuery):
    rows = await asyncio.to_thread(SERVICE.list_searches, call.from_user.id)
    if not rows:
        await display(call, "Сначала создайте мониторинг.", menu())
        return
    target = {"markets": "stats", "deals": "offers", "database": "database_search"}[
        call.data
    ]
    await display(
        call,
        "Выберите мониторинг:",
        InlineKeyboardMarkup(
            inline_keyboard=[[button(s.title[:40], f"{target}:{s.id}")] for s in rows]
            + (
                [[button("⭐ Избранное", "favorites")]]
                if call.data == "database"
                else []
            )
            + [[button("🏠 Меню", "home")]]
        ),
    )


@router.callback_query(F.data.startswith("database_search:"))
async def database_search(call: CallbackQuery):
    search_id = int(call.data.split(":")[1])
    rows = await asyncio.to_thread(SERVICE.offers, call.from_user.id, search_id, False)
    details = [
        [button(f"🔍 {listing.title[:32]}", f"analysis:{listing.id}")]
        for _, listing in rows[:10]
    ]
    await display(
        call,
        f"Показаны последние {len(rows)} объявлений:\n"
        + "\n".join(
            f"• {html.escape(l.title[:65])} — {money(l.price)}" for _, l in rows[:15]
        ),
        InlineKeyboardMarkup(
            inline_keyboard=details
            + [
                [
                    button("📥 Excel", f"export:{search_id}"),
                    button("◀️ Назад", "database"),
                ]
            ]
        ),
    )


@router.callback_query(F.data == "favorites")
async def favorites_callback(call: CallbackQuery):
    rows = await asyncio.to_thread(SERVICE.favorites, call.from_user.id)
    keyboard = [
        [button(f"🔍 {listing.title[:35]}", f"analysis:{listing.id}")]
        for listing in rows
    ]
    keyboard.append([button("◀️ Назад", "database")])
    await display(
        call,
        f"⭐ Избранное: {len(rows)} объявлений."
        if rows
        else "Избранных объявлений пока нет.",
        InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


async def show_settings(target):
    start, end = await asyncio.to_thread(SERVICE.user_settings, target.from_user.id)
    digest = await asyncio.to_thread(SERVICE.digest_enabled, target.from_user.id)
    await display(
        target,
        f"Интервал по умолчанию: {SETTINGS.check_interval_seconds // 60} мин.\n"
        f"Тихие часы: {start if start is not None else '—'}–{end if end is not None else '—'} (часовой пояс {html.escape(SETTINGS.timezone)}).\n"
        f"Сводка: {'включена, раз в 12 часов' if digest else 'выключена'}.\n"
        "Условия отдельных поисков меняются в их карточках.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    button("Начало тихих часов", "quiet:start"),
                    button("Конец", "quiet:end"),
                ],
                [button("🔔 Переключить сводку", "digest_toggle")],
                [button("🏠 Меню", "home")],
            ]
        ),
    )


@router.callback_query(F.data == "settings")
async def settings_callback(call: CallbackQuery):
    await show_settings(call)


@router.callback_query(F.data == "digest_toggle")
async def digest_toggle(call: CallbackQuery):
    await asyncio.to_thread(SERVICE.toggle_digest, call.from_user.id)
    await show_settings(call)


@router.callback_query(F.data.startswith("quiet:"))
async def quiet_prompt(call: CallbackQuery, state: FSMContext):
    field = call.data.split(":")[1]
    await state.set_state(UserEdit.value)
    await state.update_data(field=field)
    await display(
        call,
        "Введите час от 0 до 23 или «-» для сброса. Оба часа должны быть заданы, чтобы режим действовал.",
    )


@router.message(UserEdit.value)
async def quiet_value(message: Message, state: FSMContext):
    field = (await state.get_data())["field"]
    try:
        await asyncio.to_thread(
            SERVICE.set_quiet_hour, message.from_user.id, field, message.text or ""
        )
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    await state.clear()
    await show_settings(message)


@router.callback_query(F.data.startswith(("save:", "hide:", "exclude:", "analysis:")))
async def listing_action(call: CallbackQuery):
    action, ident = call.data.split(":", 1)
    if action in ("save", "hide"):
        await asyncio.to_thread(
            SERVICE.favorite, call.from_user.id, ident, action == "save"
        )
        result = "Сохранено" if action == "save" else "Скрыто из предпочтений"
    elif action == "exclude":
        try:
            await asyncio.to_thread(SERVICE.exclude_seller, call.from_user.id, ident)
        except ValueError as exc:
            result = str(exc)
        else:
            result = "Продавец исключён"
    else:
        match, listing, history, image, text_analysis = await asyncio.to_thread(
            SERVICE.listing_details, call.from_user.id, ident
        )
        text = (
            f"<b>{html.escape(listing.title)}</b>\nЦена: {money(listing.price)}\n"
            f"Рынок: {money(match.market_price)}\nОценка: {match.score or 0}/100; риск: {match.risk or 0}/100\n"
            f"Продавец: {html.escape(listing.seller_label or 'неизвестно')}\n"
            f"Исключение: {html.escape(match.exclusion or 'нет')}\n"
            f"Причины: {html.escape('; '.join(match.reasons or []))}\n"
            f"История цен: {', '.join(money(x.price) for x in history) or 'нет'}\n"
            f"Фото: {html.escape(image.summary if image else 'не анализировались')}\n"
            f"Дополнительный анализ текста: {html.escape(text_analysis.summary if text_analysis else 'недоступен')}\n"
            f'<a href="{html.escape(listing.url, quote=True)}">Открыть на Авито</a>'
        )
        await display(
            call,
            text,
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        button("⭐ Сохранить", f"save:{ident}"),
                        button("🚫 Неинтересно", f"hide:{ident}"),
                    ],
                    [
                        button("👤 Исключить продавца", f"exclude:{ident}"),
                        button("🏠 Меню", "home"),
                    ],
                ]
            ),
        )
        return
    await call.answer(result, show_alert=True)


async def in_quiet_hours(user_id: int) -> bool:
    user_start, user_end = await asyncio.to_thread(SERVICE.user_settings, user_id)
    start = user_start if user_start is not None else SETTINGS.quiet_hours_start
    end = user_end if user_end is not None else SETTINGS.quiet_hours_end
    if start is None or end is None:
        return False
    hour = datetime.now(ZoneInfo(SETTINGS.timezone)).hour
    return (start < end and start <= hour < end) or (
        start > end and (hour >= start or hour < end)
    )


async def prepare_candidate(listing):
    if await asyncio.to_thread(SERVICE.cached_text_analysis, listing.id) is None:
        text_result = await analyze_text(listing.title, listing.description, SETTINGS)
        if text_result:
            await asyncio.to_thread(SERVICE.save_text_analysis, listing.id, text_result)
    cached = await asyncio.to_thread(SERVICE.cached_image_analysis, listing.id)
    if cached is None or (not cached.hashes and image_urls(listing.raw)):
        hashes, semantic = await inspect_images(listing.raw, SETTINGS)
        await asyncio.to_thread(
            SERVICE.save_image_analysis,
            listing.id,
            hashes,
            semantic.warnings if semantic else [],
            semantic.summary
            if semantic
            else (
                "Фото обработаны локально; семантический анализ недоступен"
                if hashes
                else "Фотографии не обнаружены"
            ),
            semantic.confidence if semantic else None,
        )


async def scheduler(bot: Bot):
    while True:
        try:
            for search_id in await asyncio.to_thread(SERVICE.scan_due):
                progress = await asyncio.to_thread(SERVICE.scan_one, search_id)
                if progress.get("baseline") and (
                    progress["page"] == 1
                    or progress["page"] % 5 == 0
                    or progress["complete"]
                ):
                    try:
                        if progress["complete"]:
                            info = await asyncio.to_thread(
                                SERVICE.stats, progress["user_id"], search_id
                            )
                            market = info["market"]
                            summary = (
                                f"✅ Первичный сбор «{html.escape(progress['title'])}» завершён.\n"
                                f"Обнаружено: {info['total']}; подходит по фильтрам: {info['total'] - info['excluded']}; исключено: {info['excluded']}; "
                                f"потенциально интересных: {info['deals']}.\n"
                                f"Рынок: {money(market.median) if market else 'недостаточно данных'}; "
                                f"в расчёте: {market.count if market else 0}."
                            )
                            if progress["limited"]:
                                summary += "\n⚠️ Достигнут лимит страниц; рынок может быть неполным."
                        else:
                            summary = f"⏳ «{html.escape(progress['title'])}»: собрана страница {progress['page']}, новых записей на ней {progress['new']}."
                        await bot.send_message(
                            progress["user_id"], summary, parse_mode="HTML"
                        )
                    except Exception:
                        LOG.exception("Не удалось отправить ход первичного сбора")
            pending_rows = await asyncio.to_thread(SERVICE.pending)
            digest_groups = {}
            for row in pending_rows:
                user_id = row[1].user_id
                if user_id not in digest_groups and await asyncio.to_thread(
                    SERVICE.digest_enabled, user_id
                ):
                    digest_groups[user_id] = []
                if user_id in digest_groups:
                    digest_groups[user_id].append(row)
            for user_id, rows in digest_groups.items():
                if await in_quiet_hours(user_id) or not await asyncio.to_thread(
                    SERVICE.digest_due, user_id
                ):
                    continue
                selected = []
                digest_text = "📋 <b>Сводка предложений</b>"
                for row in rows[:40]:
                    note, _, _, listing = row
                    await prepare_candidate(listing)
                    status, match = await asyncio.to_thread(
                        SERVICE.notification_state, note.id
                    )
                    if status != "pending":
                        continue
                    line = f"\n• {html.escape(listing.title[:45])} — {money(listing.price)} · {match.score}/100"
                    if len(digest_text) + len(line) > 3500:
                        break
                    selected.append(row)
                    digest_text += line
                try:
                    await bot.send_message(user_id, digest_text, parse_mode="HTML")
                except Exception:
                    LOG.exception("Не удалось отправить сводку")
                    for note, _, _, _ in selected:
                        await asyncio.to_thread(SERVICE.mark_sent, note.id, False)
                else:
                    await asyncio.to_thread(
                        SERVICE.mark_digest_sent,
                        user_id,
                        [note.id for note, _, _, _ in selected],
                    )
            for note, search, match, listing in pending_rows:
                if search.user_id in digest_groups:
                    continue
                if await in_quiet_hours(search.user_id):
                    continue
                await prepare_candidate(listing)
                status, match = await asyncio.to_thread(
                    SERVICE.notification_state, note.id
                )
                if status != "pending":
                    continue
                lines = [
                    f"💎 <b>{html.escape(listing.title)}</b>",
                    f"Цена: {money(listing.price)}",
                ]
                if match.market_price:
                    lines.append(f"Рынок: {money(match.market_price)}")
                    lines.append(
                        f"Ниже рынка: {(match.market_price - listing.price) / match.market_price:.1%}"
                    )
                lines += [
                    f"Продавец: {html.escape(listing.seller_label or 'неизвестно')}",
                    f"Оценка: {match.score}/100 · риск: {match.risk}/100",
                    "Причины: " + html.escape("; ".join(match.reasons or [])),
                    f'<a href="{html.escape(listing.url, quote=True)}">Открыть объявление</a>',
                ]
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🔗 Открыть", url=listing.url),
                            button("🔍 Анализ", f"analysis:{listing.id}"),
                        ],
                        [
                            button("⭐ Сохранить", f"save:{listing.id}"),
                            button("🚫 Неинтересно", f"hide:{listing.id}"),
                        ],
                        [
                            button("👤 Исключить продавца", f"exclude:{listing.id}"),
                            button("⚙️ Настройки", f"filters:{search.id}"),
                        ],
                    ]
                )
                try:
                    await bot.send_message(
                        search.user_id,
                        "\n".join(lines),
                        parse_mode="HTML",
                        reply_markup=keyboard,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    LOG.exception("Telegram недоступен для уведомления %s", note.id)
                    await asyncio.to_thread(SERVICE.mark_sent, note.id, False)
                else:
                    await asyncio.to_thread(SERVICE.mark_sent, note.id, True)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Ошибка фонового цикла")
        await asyncio.sleep(10)


async def run(service: Service, settings: Settings):
    global SERVICE, SETTINGS
    SERVICE, SETTINGS = service, settings
    router.message.middleware(Access())
    router.callback_query.middleware(Access())
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    task = asyncio.create_task(scheduler(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        if hasattr(service.source, "stop"):
            service.source.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await bot.session.close()

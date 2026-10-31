from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from intelligence import bot
from intelligence.config import Settings


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(bot, "SETTINGS", Settings(), raising=False)


def fake_message(text=""):
    return SimpleNamespace(
        text=text, from_user=SimpleNamespace(id=1), answer=AsyncMock()
    )


def fake_call(data):
    return SimpleNamespace(
        data=data, from_user=SimpleNamespace(id=1), answer=AsyncMock()
    )


@pytest.mark.asyncio
async def test_start_and_invalid_link():
    state = SimpleNamespace(
        clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock()
    )
    message = fake_message()
    await bot.start(message, state)
    state.clear.assert_awaited_once()
    assert message.answer.await_args.kwargs["reply_markup"] == bot.menu()
    bad = fake_message("https://evilavito.ru/moskva")
    await bot.receive_url(bad, state)
    assert "Нужна ссылка" in bad.answer.await_args.args[0]
    state.update_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_mini_app_button(monkeypatch):
    monkeypatch.setattr(
        bot,
        "SETTINGS",
        Settings(webapp_url="https://example.trycloudflare.com/"),
        raising=False,
    )
    message = fake_message()
    await bot.app_command(message)
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].web_app.url.startswith(
        "https://example.trycloudflare.com/?ticket="
    )
    assert any(
        button.callback_data == "home"
        for row in keyboard.inline_keyboard
        for button in row
    )


@pytest.mark.asyncio
async def test_pause_resume_delete_and_filter_menu(monkeypatch):
    search = SimpleNamespace(
        id=7,
        title="iPhone 15",
        city="Москва",
        target_model="iPhone 15",
        target_memory="128 ГБ",
        status="active",
        last_success=None,
        discount_percent=15,
        min_score=70,
        last_error="",
        seller_filter="all",
        condition_filter="all",
        notification_mode="below_market",
        events_mode="new_and_price",
    )
    service = SimpleNamespace(
        set_status=Mock(),
        delete=Mock(),
        stats=Mock(
            return_value={
                "search": search,
                "total": 1,
                "deals": 0,
                "market": None,
                "excluded": 0,
            }
        ),
    )
    monkeypatch.setattr(bot, "SERVICE", service, raising=False)
    call = fake_call("pause:7")
    await bot.toggle(call)
    service.set_status.assert_called_once_with(1, 7, "paused")
    assert "iPhone 15" in call.answer.await_args.args[0]
    call = fake_call("delete:7")
    await bot.delete_confirm(call)
    buttons = [
        b.callback_data
        for row in call.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert buttons == ["delete_yes:7", "search:7"]
    call = fake_call("delete_yes:7")
    await bot.delete_yes(call)
    service.delete.assert_called_once_with(1, 7)
    call = fake_call("filters:7")
    await bot.filters(call)
    assert "Настройки" in call.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_access_rejects_unknown_user():
    handler = AsyncMock(return_value="ok")
    event = fake_message("/start")
    event.from_user.id = 99
    result = await bot.Access()(handler, event, {})
    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_quiet_hours_blocks_overnight(monkeypatch):
    from datetime import datetime

    class Clock:
        @staticmethod
        def now(zone):
            return datetime(2026, 1, 1, 23, tzinfo=zone)

    monkeypatch.setattr(bot, "datetime", Clock)
    monkeypatch.setattr(
        bot,
        "SERVICE",
        SimpleNamespace(user_settings=Mock(return_value=(22, 7))),
        raising=False,
    )
    assert await bot.in_quiet_hours(1)


@pytest.mark.asyncio
async def test_browse_and_manual_scan_buttons(monkeypatch):
    listing = SimpleNamespace(id="42", title="iPhone 15", price=32000)
    match = SimpleNamespace(score=84)
    service = SimpleNamespace(
        search_listings=Mock(return_value=([(match, listing)], 17)),
        request_scan=Mock(),
    )
    state = SimpleNamespace(get_data=AsyncMock(return_value={}))
    monkeypatch.setattr(bot, "SERVICE", service, raising=False)
    call = fake_call("browse:7:cheap:1")
    await bot.browse_callback(call, state)
    service.search_listings.assert_called_once_with(1, 7, "", "cheap", 1, 8)
    buttons = [
        entry.callback_data
        for row in call.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for entry in row
    ]
    assert "analysis:42" in buttons
    assert "browse:7:cheap:0" in buttons
    assert "browse:7:cheap:2" in buttons
    scan_call = fake_call("scan_now:7")
    await bot.scan_now(scan_call)
    service.request_scan.assert_called_once_with(1, 7)
    assert "очередь" in scan_call.answer.await_args.args[0]

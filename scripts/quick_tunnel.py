"""Keep a temporary localhost.run URL alive for the locally running Mini App.

Run separately from the bot. After a tunnel expires, /app and the Telegram chat
menu use the new URL from data/webapp_url.txt.
"""

from __future__ import annotations

import asyncio
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import MenuButtonWebApp, WebAppInfo

from intelligence.config import Settings

URL_FILE = Path("data/webapp_url.txt")
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.lhr\.life")
STOP = threading.Event()


def healthy(url: str) -> bool:
    try:
        with urlopen(url, timeout=8) as response:
            return response.status == 200
    except (OSError, URLError, TimeoutError):
        return False


async def update_menu(settings: Settings, url: str) -> None:
    bot = Bot(settings.telegram_bot_token)
    try:
        button = MenuButtonWebApp(
            text="Открыть приложение", web_app=WebAppInfo(url=url)
        )
        await bot.set_chat_menu_button(menu_button=button)
        for user_id in settings.allowed_ids:
            await bot.set_chat_menu_button(chat_id=user_id, menu_button=button)
    finally:
        await bot.session.close()


def read_lines(process: subprocess.Popen[str], output: queue.Queue[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        output.put(line)


def launch(ssh: str) -> tuple[subprocess.Popen[str], str | None]:
    process = subprocess.Popen(
        [
            ssh,
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ServerAliveInterval=60",
            "-o",
            "ExitOnForwardFailure=yes",
            "-R",
            "80:localhost:8080",
            "nokey@localhost.run",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output: queue.Queue[str] = queue.Queue()
    threading.Thread(target=read_lines, args=(process, output), daemon=True).start()
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline and not STOP.is_set() and process.poll() is None:
        try:
            line = output.get(timeout=1)
        except queue.Empty:
            continue
        match = URL_PATTERN.search(line)
        if match:
            return process, match.group(0)
    return process, None


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    settings = Settings()
    settings.validate_runtime()
    ssh = shutil.which("ssh")
    if not ssh:
        raise SystemExit("Нужен установленный SSH-клиент для временного HTTPS-туннеля")
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    while not STOP.is_set():
        process, url = launch(ssh)
        try:
            if url:
                print(f"Проверяю новый адрес: {url}", flush=True)
                for _ in range(12):
                    if STOP.is_set() or process.poll() is not None:
                        break
                    if healthy(url):
                        URL_FILE.parent.mkdir(parents=True, exist_ok=True)
                        URL_FILE.write_text(url + "\n", encoding="utf-8")
                        try:
                            asyncio.run(update_menu(settings, url))
                        except (TelegramAPIError, OSError, TimeoutError):
                            print("Кнопка Telegram не обновилась", flush=True)
                        print(f"Mini App: {url}", flush=True)
                        failures = 0
                        while not STOP.wait(20) and process.poll() is None:
                            failures = 0 if healthy(url) else failures + 1
                            if failures >= 2:
                                print(
                                    "Временный адрес недоступен; обновляю туннель",
                                    flush=True,
                                )
                                break
                        break
                    STOP.wait(3)
        finally:
            stop_process(process)
        STOP.wait(3)


if __name__ == "__main__":
    main()

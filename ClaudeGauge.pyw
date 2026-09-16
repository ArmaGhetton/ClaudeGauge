# -*- coding: utf-8 -*-
"""
ClaudeGauge  —  виджет лимитов Claude для Windows 11
Показывает расход лимитов аккаунта Claude: 5-часовая сессия, недельный лимит,
недельные лимиты Sonnet/Opus и дополнительный расход (extra usage).

Данные берутся из того же источника, что и команда /usage в Claude Code:
GET https://api.anthropic.com/api/oauth/usage

Зависимостей нет — только стандартная библиотека Python.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone

import tkinter as tk
from tkinter import font as tkfont

try:
    import winreg
except ImportError:
    winreg = None

try:
    import winsound
except ImportError:
    winsound = None


# --------------------------------------------------------------------------
#  Константы
# --------------------------------------------------------------------------

APP_NAME = "ClaudeGauge"
APP_TITLE = "ClaudeGauge"
APP_VERSION = "1.2"

# Под этими именами виджет жил раньше: из них переносятся настройки
# и удаляются устаревшие записи автозапуска.
LEGACY_APP_NAMES = ["ClaudeUsageWidget"]

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Без этого User-Agent эндпоинт агрессивно режет запросы (429).
HTTP_USER_AGENT = "claude-code/2.1.32"
BETA_HEADER = "oauth-2025-04-20"

# Эндпоинт не любит частые запросы. 180 секунд — безопасный интервал.
MIN_REFRESH_SECONDS = 120
DEFAULT_REFRESH_SECONDS = 180

# --------------------------------------------------------------------------
#  Локализация
# --------------------------------------------------------------------------

# Текущий язык интерфейса. Синхронизируется с settings["language"] при
# старте (Widget.__init__) и при переключении в настройках (on_language).
LANG = "ru"

MONTHS = {
    "ru": ["янв", "фев", "мар", "апр", "мая", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

MONTHS_FULL = {
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}

WEEKDAYS = {
    "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}

# Все переводимые тексты интерфейса. Ключ — смысловое имя, значение —
# словарь {"ru": ..., "en": ...}. t() возвращает строку для текущего LANG
# и при наличии именованных аргументов подставляет их через .format().
STRINGS = {
    "status_starting": {"ru": "Запуск…", "en": "Starting…"},
    "status_updating": {"ru": "Обновляю…", "en": "Updating…"},
    "status_updated": {"ru": "Обновлено в {time}.", "en": "Updated at {time}."},
    "status_update_failed": {"ru": "Сбой обновления.", "en": "Update failed."},
    "status_shortcut_created": {"ru": "Ярлык создан на рабочем столе.",
                                "en": "Shortcut created on the desktop."},

    "err_token_refresh_http": {"ru": "Не удалось обновить токен ({code}).",
                               "en": "Failed to refresh the token ({code})."},
    "hint_login": {"ru": "Запусти Claude Code и выполни /login.",
                   "en": "Run Claude Code and execute /login."},
    "err_timeout_refresh": {"ru": "Сервер не отвечает.", "en": "Server is not responding."},
    "hint_timeout_refresh": {"ru": "Не дождались ответа при обновлении токена.",
                             "en": "Timed out while refreshing the token."},
    "err_token_refresh_other": {"ru": "Нет связи при обновлении токена.",
                                "en": "No connection while refreshing the token."},
    "err_token_missing": {"ru": "Сервер не вернул новый токен.",
                          "en": "Server did not return a new token."},
    "err_no_login": {"ru": "Не найден вход в Claude.", "en": "Not logged in to Claude."},
    "hint_no_login": {"ru": "Установи Claude Code и выполни /login, либо вставь токен в настройках.",
                      "en": "Install Claude Code and run /login, or paste a token in settings."},
    "err_token_expired": {"ru": "Токен доступа устарел.", "en": "Access token expired."},
    "hint_token_expired": {"ru": "Запусти Claude Code — он обновит токен сам.",
                           "en": "Run Claude Code — it will refresh the token itself."},
    "err_token_rejected": {"ru": "Токен отклонён.", "en": "Token rejected."},
    "hint_token_rejected": {"ru": "Обновляю доступ…", "en": "Refreshing access…"},
    "err_rate_limited": {"ru": "Слишком частые запросы.", "en": "Too many requests."},
    "hint_rate_limited": {"ru": "Увеличь интервал обновления в настройках.",
                          "en": "Increase the refresh interval in settings."},
    "err_server": {"ru": "Ошибка сервера {code}.", "en": "Server error {code}."},
    "err_no_connection": {"ru": "Нет соединения.", "en": "No connection."},
    "err_timeout_fetch": {"ru": "Сервер не отвечает.", "en": "Server is not responding."},
    "hint_timeout_fetch": {"ru": "Не дождались ответа, попробую снова позже.",
                           "en": "Timed out, will try again later."},
    "err_fetch_other": {"ru": "Не удалось получить данные.", "en": "Failed to fetch data."},

    "err_shortcut_windows_only": {"ru": "Ярлык создаётся только в Windows.",
                                  "en": "Shortcuts can only be created on Windows."},
    "err_shortcut_missing_file": {"ru": "Не найден файл ClaudeGauge.pyw.",
                                  "en": "ClaudeGauge.pyw file not found."},
    "hint_shortcut_missing_file": {"ru": "Он должен лежать рядом с запущенным виджетом.",
                                   "en": "It must be next to the running widget."},
    "err_shortcut_prepare": {"ru": "Не удалось подготовить ярлык.",
                             "en": "Failed to prepare the shortcut."},
    "err_shortcut_create": {"ru": "Не удалось создать ярлык.", "en": "Failed to create the shortcut."},
    "err_shortcut_powershell": {"ru": "PowerShell не смог создать ярлык.",
                                "en": "PowerShell failed to create the shortcut."},
    "hint_shortcut_log": {"ru": "Подробности в error.log.", "en": "Details in error.log."},

    "row_waiting": {"ru": "Ожидание данных…", "en": "Waiting for data…"},
    "row_no_active_window": {"ru": "Нет активного окна.", "en": "No active window."},
    "row_reset_prefix": {"ru": "Сброс", "en": "Reset"},
    "row_reset_template": {"ru": "{prefix} через {delta} · {date}.",
                           "en": "{prefix} in {delta} · {date}."},
    "row_title_session": {"ru": "Сессия · 5 часов", "en": "Session · 5 hours"},
    "row_title_week_all": {"ru": "Неделя · Все модели", "en": "Week · All models"},
    "row_title_week_sonnet": {"ru": "Неделя · Sonnet", "en": "Week · Sonnet"},
    "row_title_week_opus": {"ru": "Неделя · Opus", "en": "Week · Opus"},
    "row_title_extra": {"ru": "Дополнительный расход", "en": "Extra usage"},
    "limit_not_active": {"ru": "Лимит пока не задействован.", "en": "Limit not active yet."},
    "extra_off": {"ru": "Выкл.", "en": "Off"},
    "extra_not_enabled": {"ru": "Дополнительный расход не подключён.",
                          "en": "Extra usage is not enabled."},
    "extra_used_of": {"ru": "Использовано {used} из {limit}.", "en": "Used {used} of {limit}."},
    "extra_enabled": {"ru": "Включён.", "en": "Enabled."},

    "today_at": {"ru": "Сегодня в {time}", "en": "Today at {time}"},
    "tomorrow_at": {"ru": "Завтра в {time}", "en": "Tomorrow at {time}"},
    "date_full_month": {"ru": "{day} {month} · {time}", "en": "{month} {day} · {time}"},
    "date_short": {"ru": "{day} {month}, {weekday}, {time}", "en": "{month} {day}, {weekday}, {time}"},
    "just_now": {"ru": "вот-вот", "en": "any moment"},

    "menu_refresh": {"ru": "Обновить сейчас", "en": "Refresh now"},
    "menu_settings": {"ru": "Настройки…", "en": "Settings…"},
    "menu_create_shortcut": {"ru": "Создать ярлык на рабочем столе", "en": "Create desktop shortcut"},
    "menu_always_on_top": {"ru": "Поверх всех окон", "en": "Always on top"},
    "menu_compact": {"ru": "Компактный режим", "en": "Compact mode"},
    "menu_quit": {"ru": "Выход", "en": "Exit"},

    "settings_title": {"ru": "Настройки · ClaudeGauge", "en": "Settings · ClaudeGauge"},
    "section_appearance": {"ru": "Внешний вид", "en": "Appearance"},
    "section_data": {"ru": "Данные", "en": "Data"},
    "section_system": {"ru": "Система", "en": "System"},
    "label_language": {"ru": "Язык", "en": "Language"},
    "label_opacity": {"ru": "Прозрачность", "en": "Opacity"},
    "label_scale": {"ru": "Размер виджета", "en": "Widget size"},
    "label_theme": {"ru": "Тема", "en": "Theme"},
    "theme_dark": {"ru": "Тёмная", "en": "Dark"},
    "theme_oled": {"ru": "OLED", "en": "OLED"},
    "theme_light": {"ru": "Светлая", "en": "Light"},
    "theme_aurora": {"ru": "Аврора", "en": "Aurora"},
    "theme_sunset": {"ru": "Закат", "en": "Sunset"},
    "label_accent": {"ru": "Акцент", "en": "Accent"},
    "chk_stay_above_fullscreen": {"ru": "Поверх полноэкранных приложений",
                                  "en": "Stay above fullscreen apps"},
    "chk_hide_taskbar": {"ru": "Скрывать с панели задач", "en": "Hide from taskbar"},
    "chk_glass": {"ru": "Эффект стекла (блюр Windows)", "en": "Glass effect (Windows blur)"},
    "chk_locked": {"ru": "Закрепить позицию (не перетаскивается)",
                   "en": "Lock position (disable dragging)"},
    "chk_show_model_limits": {"ru": "Показывать недельные лимиты Sonnet и Opus",
                              "en": "Show weekly Sonnet and Opus limits"},
    "chk_show_extra_usage": {"ru": "Показывать дополнительный расход", "en": "Show extra usage"},
    "label_interval": {"ru": "Интервал, сек", "en": "Interval, sec"},
    "hint_interval_min": {"ru": "Минимум 120 — иначе сервер ответит 429.",
                          "en": "Minimum 120 — otherwise the server responds 429."},
    "label_threshold": {"ru": "Порог тревоги, %", "en": "Warning threshold, %"},
    "chk_sound_on_warn": {"ru": "Звуковой сигнал при достижении порога", "en": "Sound alert at threshold"},
    "chk_autostart": {"ru": "Запускать при входе в Windows", "en": "Launch at Windows sign-in"},
    "chk_auto_refresh_token": {"ru": "Обновлять токен доступа самостоятельно",
                               "en": "Refresh access token automatically"},
    "label_manual_token": {"ru": "Свой токен (необязательно)", "en": "Custom token (optional)"},
    "hint_manual_token": {"ru": "Оставь пустым — токен возьмётся из Claude Code автоматически.",
                          "en": "Leave empty — the token will be taken from Claude Code automatically."},
    "btn_done": {"ru": "Готово", "en": "Done"},
}


def t(key, **kwargs):
    text = STRINGS[key][LANG]
    return text.format(**kwargs) if kwargs else text


THEMES = {
    "dark": {
        "bg": "#1B1A19",
        "card": "#242220",
        "track": "#3A3734",
        "text": "#F2F0EA",
        "muted": "#918C85",
        "border": "#35322E",
        "hover": "#312E2B",
    },
    "oled": {
        "bg": "#000000",
        "card": "#000000",
        "track": "#262626",
        "text": "#EFEFEF",
        "muted": "#8C8C8C",
        "border": "#1E1E1E",
        "hover": "#141414",
    },
    "light": {
        "bg": "#F7F5F0",
        "card": "#FFFFFF",
        "track": "#E2DED6",
        "text": "#1F1E1D",
        "muted": "#6E6A64",
        "border": "#DEDAD2",
        "hover": "#ECE9E2",
    },
    "aurora": {
        "bg": "#15131C",
        "card": "#1E1B29",
        "track": "#3A3550",
        "text": "#F2F0EA",
        "muted": "#9791A8",
        "border": "#2C2839",
        "hover": "#282438",
        "gradient": ("#7C5CFC", "#2FD1C5"),
    },
    "sunset": {
        "bg": "#1F1512",
        "card": "#2A1C17",
        "track": "#4A2E22",
        "text": "#F5ECE6",
        "muted": "#B08A78",
        "border": "#3A2620",
        "hover": "#33211B",
        "gradient": ("#FF7A59", "#FFC24B"),
    },
}

ACCENTS = {
    "Кирпичный": "#D97757",
    "Синий": "#4C8DF6",
    "Зелёный": "#3FA96B",
    "Фиолетовый": "#9B6BD6",
    "Бирюзовый": "#2FB3AE",
    "Розовый": "#E06C9F",
}

COLOR_WARN = "#E0A33B"
COLOR_DANGER = "#E05B4C"

# Цвет-ключ для эффекта стекла: -transparentcolor делает пиксели этого
# цвета полностью прозрачными и пропускает блюр Windows позади окна.
# Кислотная магента — ни одна тема так не красит, коллизий не будет,
# а если где-то протечёт по ошибке, будет сразу заметно.
GLASS_KEY_COLOR = "#FF00FE"


def lerp_color(color1, color2, t):
    """Промежуточный HEX-цвет между color1 и color2, t от 0 до 1."""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
    r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
    return "#%02X%02X%02X" % (round(r1 + (r2 - r1) * t),
                              round(g1 + (g2 - g1) * t),
                              round(b1 + (b2 - b1) * t))


def draw_horizontal_gradient(canvas, width, height, color1, color2):
    """Заливает canvas слева направо градиентом тонкими полосками."""
    canvas.delete("all")
    width = max(1, int(width))
    step = 2
    x = 0
    while x < width:
        seg_end = min(width, x + step)
        color = lerp_color(color1, color2, (x + seg_end) / 2.0 / width)
        canvas.create_rectangle(x, 0, seg_end, height, fill=color, outline=color)
        x = seg_end


DEFAULT_SETTINGS = {
    "opacity": 94,               # 30..100
    "scale": 100,                # 80..170
    "theme": "dark",
    "accent": "#D97757",
    "always_on_top": True,
    "stay_above_fullscreen": False,
    "hide_from_taskbar": True,
    "compact": False,
    "glass": False,
    "show_model_limits": True,
    "show_extra_usage": True,
    "refresh_seconds": DEFAULT_REFRESH_SECONDS,
    "warn_threshold": 80,
    "sound_on_warn": False,
    "autostart": False,
    "auto_refresh_token": True,
    "manual_token": "",
    "x": None,
    "y": None,
    "locked": False,
    "language": "ru",
}


# --------------------------------------------------------------------------
#  Настройки
# --------------------------------------------------------------------------

def script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.path.dirname(os.path.abspath(sys.argv[0]))


ICON_PATH = os.path.join(script_dir(), "ClaudeGauge.ico")


def config_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return os.path.expanduser("~")

    # Первый запуск под новым именем — забираем настройки из старой папки.
    if not os.path.exists(os.path.join(path, "settings.json")):
        for legacy in LEGACY_APP_NAMES:
            old_dir = os.path.join(base, legacy)
            if not os.path.isfile(os.path.join(old_dir, "settings.json")):
                continue
            for name in ("settings.json", "token_cache.json"):
                source = os.path.join(old_dir, name)
                if os.path.isfile(source):
                    try:
                        shutil.copy2(source, os.path.join(path, name))
                    except OSError:
                        pass
            break
    return path


SETTINGS_PATH = os.path.join(config_dir(), "settings.json")
TOKEN_CACHE_PATH = os.path.join(config_dir(), "token_cache.json")
LOG_PATH = os.path.join(config_dir(), "error.log")


def log_error(message):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (datetime.now().isoformat(timespec="seconds"), message))
    except OSError:
        pass


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict):
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    data[key] = saved[key]
    except (OSError, ValueError):
        pass
    return data


def save_settings(settings):
    try:
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except OSError as exc:
        log_error("Не удалось сохранить настройки: %s" % exc)


# --------------------------------------------------------------------------
#  Форматирование времени по-русски
# --------------------------------------------------------------------------

def parse_iso(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def plural(number, one, few, many):
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not (12 <= number % 100 <= 14):
        return few
    return many


def human_delta(seconds):
    seconds = int(seconds)
    if seconds <= 0:
        return t("just_now")
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if LANG == "ru":
        if days:
            return "%d %s %d %s" % (days, plural(days, "день", "дня", "дней"),
                                    hours, plural(hours, "час", "часа", "часов"))
        if hours:
            return "%d ч %02d мин" % (hours, minutes)
        if minutes:
            return "%d мин %02d сек" % (minutes, secs)
        return "%d сек" % secs
    if days:
        return "%dd %dh" % (days, hours)
    if hours:
        return "%dh %02dm" % (hours, minutes)
    if minutes:
        return "%dm %02ds" % (minutes, secs)
    return "%ds" % secs


def clock(dt):
    return dt.strftime("%H:%M")


def date_and_clock(dt, full_month=False):
    now = datetime.now(dt.tzinfo)
    if dt.date() == now.date():
        return t("today_at", time=clock(dt))
    delta_days = (dt.date() - now.date()).days
    if delta_days == 1:
        return t("tomorrow_at", time=clock(dt))
    if full_month:
        return t("date_full_month", day=dt.day, month=MONTHS_FULL[LANG][dt.month - 1],
                 time=clock(dt))
    return t("date_short", day=dt.day, month=MONTHS[LANG][dt.month - 1],
             weekday=WEEKDAYS[LANG][dt.weekday()], time=clock(dt))


# --------------------------------------------------------------------------
#  Токен и запрос к API
# --------------------------------------------------------------------------

class UsageError(Exception):
    """Ошибка с уже готовым (переведённым) текстом для показа в виджете.

    kind — машинный признак для логики (например, "token_rejected"), чтобы
    код мог распознать причину ошибки без сравнения переведённого текста.
    """

    def __init__(self, message, hint="", kind=None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.kind = kind


def credentials_candidates():
    paths = []
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        paths.append(os.path.join(env_dir, ".credentials.json"))
    home = os.path.expanduser("~")
    paths.append(os.path.join(home, ".claude", ".credentials.json"))
    profile = os.environ.get("USERPROFILE")
    if profile:
        paths.append(os.path.join(profile, ".claude", ".credentials.json"))
    seen, result = set(), []
    for path in paths:
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            seen.add(norm)
            result.append(path)
    return result


def read_credentials_file():
    """Возвращает (путь, весь_json, блок_claudeAiOauth) или (None, None, None)."""
    for path in credentials_candidates():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            log_error("Не читается %s: %s" % (path, exc))
            continue
        block = data.get("claudeAiOauth") if isinstance(data, dict) else None
        if not isinstance(block, dict):
            block = data if isinstance(data, dict) and "accessToken" in data else None
        if block and block.get("accessToken"):
            return path, data, block
    return None, None, None


def read_token_cache():
    try:
        with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("accessToken"):
            return data
    except (OSError, ValueError):
        pass
    return None


def write_token_cache(block):
    try:
        tmp = TOKEN_CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(block, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, TOKEN_CACHE_PATH)
    except OSError as exc:
        log_error("Не удалось сохранить кэш токена: %s" % exc)


def write_credentials_file(path, whole, block):
    """Аккуратно обновляет .credentials.json, сохраняя резервную копию."""
    try:
        backup = path + ".backup"
        if not os.path.exists(backup):
            with open(path, "r", encoding="utf-8") as src:
                content = src.read()
            with open(backup, "w", encoding="utf-8") as dst:
                dst.write(content)
        if isinstance(whole, dict) and isinstance(whole.get("claudeAiOauth"), dict):
            whole["claudeAiOauth"] = block
        else:
            whole = block
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(whole, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log_error("Не удалось обновить credentials: %s" % exc)
        return False


def token_expired(block, buffer_seconds=120):
    expires_at = block.get("expiresAt")
    if not expires_at:
        return False
    try:
        expires_at = float(expires_at) / 1000.0
    except (TypeError, ValueError):
        return False
    return expires_at - buffer_seconds <= time.time()


def refresh_access_token(refresh_token):
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", HTTP_USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UsageError(t("err_token_refresh_http", code=exc.code), t("hint_login"))
    except TimeoutError:
        raise UsageError(t("err_timeout_refresh"), t("hint_timeout_refresh"))
    except Exception as exc:
        raise UsageError(t("err_token_refresh_other"), str(exc)[:80])
    access = data.get("access_token")
    if not access:
        raise UsageError(t("err_token_missing"), t("hint_login"))
    return {
        "accessToken": access,
        "refreshToken": data.get("refresh_token") or refresh_token,
        "expiresAt": int((time.time() + float(data.get("expires_in", 3600))) * 1000),
    }


class TokenProvider:
    """Достаёт рабочий access token: ручной → кэш → файл Claude Code."""

    def __init__(self, settings):
        self.settings = settings

    def get_token(self, force_refresh=False):
        manual = (self.settings.get("manual_token") or "").strip()
        if manual:
            return manual

        env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()

        path, whole, file_block = read_credentials_file()
        cache_block = read_token_cache()

        block = None
        source = None
        if file_block and cache_block:
            file_exp = float(file_block.get("expiresAt") or 0)
            cache_exp = float(cache_block.get("expiresAt") or 0)
            if cache_exp > file_exp:
                block, source = cache_block, "cache"
            else:
                block, source = file_block, "file"
        elif file_block:
            block, source = file_block, "file"
        elif cache_block:
            block, source = cache_block, "cache"

        if block is None:
            if env_token:
                return env_token
            raise UsageError(t("err_no_login"), t("hint_no_login"))

        needs_refresh = force_refresh or token_expired(block)
        if needs_refresh and self.settings.get("auto_refresh_token", True):
            refresh = block.get("refreshToken")
            if refresh:
                fresh = refresh_access_token(refresh)
                for key in ("subscriptionType", "rateLimitTier", "scopes"):
                    if key in block:
                        fresh[key] = block[key]
                write_token_cache(fresh)
                if path and source == "file":
                    write_credentials_file(path, whole, fresh)
                return fresh["accessToken"]

        if needs_refresh and not self.settings.get("auto_refresh_token", True):
            if env_token:
                return env_token
            raise UsageError(t("err_token_expired"), t("hint_token_expired"))

        return block["accessToken"]

    def subscription_type(self):
        _, _, block = read_credentials_file()
        cache = read_token_cache() or {}
        value = (block or {}).get("subscriptionType") or cache.get("subscriptionType")
        names = {"pro": "Pro", "max": "Max", "team": "Team",
                 "enterprise": "Enterprise", "free": "Free"}
        if value:
            return names.get(str(value).lower(), str(value).title())
        return ""


def fetch_usage(token):
    request = urllib.request.Request(USAGE_URL, method="GET")
    request.add_header("Authorization", "Bearer %s" % token)
    request.add_header("anthropic-beta", BETA_HEADER)
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", HTTP_USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise UsageError(t("err_token_rejected"), t("hint_token_rejected"),
                             kind="token_rejected")
        if exc.code == 429:
            raise UsageError(t("err_rate_limited"), t("hint_rate_limited"))
        raise UsageError(t("err_server", code=exc.code), "")
    except urllib.error.URLError as exc:
        raise UsageError(t("err_no_connection"), str(getattr(exc, "reason", ""))[:60])
    except TimeoutError:
        raise UsageError(t("err_timeout_fetch"), t("hint_timeout_fetch"))
    except Exception as exc:
        raise UsageError(t("err_fetch_other"), str(exc)[:60])


# --------------------------------------------------------------------------
#  Элементы интерфейса
# --------------------------------------------------------------------------

class ProgressBar(tk.Canvas):
    def __init__(self, parent, width, height, theme):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, bg=theme["card"])
        self.bar_width = width
        self.bar_height = height
        self.theme = theme

    def _pill(self, x1, x2, color):
        h = self.bar_height
        if x2 - x1 < h:
            x2 = x1 + h
        self.create_oval(x1, 0, x1 + h, h, fill=color, outline=color)
        self.create_oval(x2 - h, 0, x2, h, fill=color, outline=color)
        self.create_rectangle(x1 + h / 2, 0, x2 - h / 2, h, fill=color, outline=color)

    def _pill_gradient(self, x1, x2, colors):
        h = self.bar_height
        if x2 - x1 < h:
            x2 = x1 + h
        total = self.bar_width
        step = 2
        x = x1
        while x < x2:
            seg_end = min(x2, x + step)
            color = lerp_color(colors[0], colors[1], (x + seg_end) / 2.0 / total)
            self.create_rectangle(x, 0, seg_end, h, fill=color, outline=color)
            x = seg_end
        left_color = lerp_color(colors[0], colors[1], x1 / total)
        right_color = lerp_color(colors[0], colors[1], x2 / total)
        self.create_oval(x1, 0, x1 + h, h, fill=left_color, outline=left_color)
        self.create_oval(x2 - h, 0, x2, h, fill=right_color, outline=right_color)

    def render(self, percent, color, gradient=None):
        self.delete("all")
        self._pill(0, self.bar_width, self.theme["track"])
        percent = max(0.0, min(100.0, float(percent)))
        if percent > 0:
            filled = max(self.bar_height, self.bar_width * percent / 100.0)
            if gradient:
                self._pill_gradient(0, filled, gradient)
            else:
                self._pill(0, filled, color)


class UsageRow:
    """Одна строка: заголовок, проценты, полоса, подпись о сбросе."""

    def __init__(self, parent, app, title, width, weekly=False):
        self.app = app
        theme = app.theme
        self.reset_at = None
        self.percent = 0.0
        self.weekly = weekly

        self.frame = tk.Frame(parent, bg=theme["card"])
        self.frame.pack(fill="x", pady=(0, app.px(11)))

        head = tk.Frame(self.frame, bg=theme["card"])
        head.pack(fill="x")

        self.title_label = tk.Label(head, text=title, bg=theme["card"],
                                    fg=theme["muted"], font=app.font_small,
                                    anchor="w")
        self.title_label.pack(side="left")

        self.value_label = tk.Label(head, text="—", bg=theme["card"],
                                    fg=theme["text"], font=app.font_value,
                                    anchor="e")
        self.value_label.pack(side="right")

        self.bar = ProgressBar(self.frame, width, app.px(7), theme)
        self.bar.pack(fill="x", pady=(app.px(5), app.px(4)))

        self.prefix = t("row_reset_prefix")
        self.sub_label = tk.Label(self.frame, text=t("row_waiting"),
                                  bg=theme["card"], fg=theme["muted"],
                                  font=app.font_tiny, anchor="w")
        self.sub_label.pack(fill="x")

        for widget in (self.frame, head, self.title_label, self.value_label,
                       self.bar, self.sub_label):
            app.make_draggable(widget)

    def color_for(self, percent):
        if percent >= 95:
            return COLOR_DANGER
        if percent >= self.app.settings["warn_threshold"]:
            return COLOR_WARN
        return self.app.settings["accent"]

    def gradient_for(self, color):
        """Градиент темы применяется только к обычному цвету полосы,
        не к жёлтому/красному предупреждению."""
        if color != self.app.settings["accent"]:
            return None
        return self.app.theme.get("gradient")

    def update(self, percent, reset_at, prefix=None):
        self.percent = float(percent or 0.0)
        self.reset_at = reset_at
        self.prefix = prefix if prefix is not None else t("row_reset_prefix")
        color = self.color_for(self.percent)
        self.value_label.config(text="%.0f%%" % self.percent, fg=color)
        self.bar.render(self.percent, color, gradient=self.gradient_for(color))
        if reset_at is None:
            self.sub_label.config(text=t("row_no_active_window"))
        else:
            self.tick()

    def update_text(self, value_text, sub_text):
        self.value_label.config(text=value_text, fg=self.app.theme["text"])
        self.sub_label.config(text=sub_text)

    def tick(self):
        if not self.reset_at:
            return
        left = (self.reset_at - datetime.now(self.reset_at.tzinfo)).total_seconds()
        self.sub_label.config(
            text=t("row_reset_template", prefix=self.prefix, delta=human_delta(left),
                  date=date_and_clock(self.reset_at, full_month=self.weekly))
        )


# --------------------------------------------------------------------------
#  Окно настроек
# --------------------------------------------------------------------------

class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.settings = app.settings
        self._scale_job = None
        self._theme_cards = {}
        self._accent_dots = []
        self._drag = (0, 0)
        self.title(t("settings_title"))
        self.overrideredirect(True)
        self.configure(bg=app.theme["bg"])
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        app.apply_icon(self)

        # Настоящие цвета темы, без подмены "card" на ключ прозрачности
        # для эффекта стекла — у окна настроек своя обычная рамка.
        theme = THEMES.get(app.settings.get("theme", "dark"), THEMES["dark"])
        self._chrome_theme = theme
        label_font = ("Segoe UI", 9)
        head_font = ("Segoe UI Semibold", 10)

        # Отдельная внутренняя рамка вместо паддингов на самом Toplevel —
        # перетаскивание вешаем только на неё, иначе клик по любому слайдеру
        # или чекбоксу тоже двигал бы окно (Toplevel входит в bindtags каждого
        # дочернего виджета).
        content = tk.Frame(self, bg=theme["bg"], padx=16, pady=14)
        content.pack(fill="both", expand=True)
        self.make_draggable(content)

        def section(text):
            label = tk.Label(content, text=text, bg=theme["bg"], fg=theme["text"],
                             font=head_font, anchor="w")
            label.pack(fill="x", pady=(10, 2))
            self.make_draggable(label)

        def row():
            frame = tk.Frame(content, bg=theme["bg"])
            frame.pack(fill="x", pady=1)
            self.make_draggable(frame)
            return frame

        def check(parent, text, key, command=None):
            var = tk.BooleanVar(value=bool(self.settings.get(key)))

            def changed():
                self.settings[key] = var.get()
                save_settings(self.settings)
                if command:
                    command()

            box = tk.Checkbutton(parent, text=text, variable=var, command=changed,
                                 bg=theme["bg"], fg=theme["text"], font=label_font,
                                 activebackground=theme["bg"],
                                 activeforeground=theme["text"],
                                 selectcolor=theme["card"], anchor="w",
                                 highlightthickness=0, bd=0)
            box.pack(side="left", fill="x")
            return var

        # --- Внешний вид ---
        section(t("section_appearance"))

        frame = row()
        tk.Label(frame, text=t("label_language"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="w").pack(side="left")
        self.lang_var = tk.StringVar(value=self.settings.get("language", "ru"))
        self._lang_labels = {}
        # Названия языков не переводятся — каждое показывается на себе самом.
        for code, caption in (("ru", "Русский"), ("en", "English")):
            lbl = tk.Label(frame, text=caption, bg=theme["bg"], font=label_font,
                          cursor="hand2", padx=8)
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, c=code: self.on_language(c))
            self._lang_labels[code] = lbl
        self._paint_lang_labels()

        frame = row()
        tk.Label(frame, text=t("label_opacity"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="w").pack(side="left")
        self.opacity_value = tk.Label(frame, text="", bg=theme["bg"],
                                      fg=theme["text"], font=label_font, width=5)
        self.opacity_value.pack(side="right")
        self.opacity = tk.Scale(frame, from_=30, to=100, orient="horizontal",
                                showvalue=False, bg=self.settings["accent"], fg=theme["text"],
                                troughcolor=theme["card"], highlightthickness=0,
                                bd=0, sliderrelief="flat",
                                activebackground=self.settings["accent"])
        # set() сам вызывает command — присваиваем его только после того, как
        # выставили стартовое значение, иначе одно только открытие настроек
        # заново применяет прозрачность/пересобирает окно виджета.
        self.opacity.set(self.settings["opacity"])
        self.opacity.config(command=self.on_opacity)
        self.opacity.pack(side="left", fill="x", expand=True)

        frame = row()
        tk.Label(frame, text=t("label_scale"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="w").pack(side="left")
        self.scale_value = tk.Label(frame, text="", bg=theme["bg"],
                                    fg=theme["text"], font=label_font, width=5)
        self.scale_value.pack(side="right")
        self.scale = tk.Scale(frame, from_=80, to=170, orient="horizontal",
                              showvalue=False, bg=self.settings["accent"], fg=theme["text"],
                              troughcolor=theme["card"], highlightthickness=0,
                              bd=0, sliderrelief="flat",
                              activebackground=self.settings["accent"])
        self.scale.set(self.settings["scale"])
        self.scale.config(command=self.on_scale)
        self.scale.pack(side="left", fill="x", expand=True)

        frame = row()
        tk.Label(frame, text=t("label_theme"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="n").pack(side="left", anchor="n")
        self.theme_var = tk.StringVar(value=self.settings["theme"])
        for value, caption in (("dark", t("theme_dark")), ("oled", t("theme_oled")),
                               ("light", t("theme_light")), ("aurora", t("theme_aurora")),
                               ("sunset", t("theme_sunset"))):
            self._build_theme_card(frame, value, caption).pack(side="left", padx=(0, 10))

        frame = row()
        tk.Label(frame, text=t("label_accent"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="n").pack(side="left", anchor="n")
        for color in ACCENTS.values():
            self._build_accent_dot(frame, color).pack(side="left")

        check(row(), t("menu_always_on_top"), "always_on_top", self.app.apply_topmost)
        check(row(), t("chk_stay_above_fullscreen"), "stay_above_fullscreen",
              self.app.apply_window_styles)
        check(row(), t("chk_hide_taskbar"), "hide_from_taskbar",
              self.app.apply_window_styles)
        check(row(), t("menu_compact"), "compact", self.app.rebuild)
        check(row(), t("chk_glass"), "glass", self.app.rebuild)
        check(row(), t("chk_locked"), "locked")

        # --- Данные ---
        section(t("section_data"))

        check(row(), t("chk_show_model_limits"), "show_model_limits", self.app.rebuild)
        check(row(), t("chk_show_extra_usage"), "show_extra_usage", self.app.rebuild)

        frame = row()
        tk.Label(frame, text=t("label_interval"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="w").pack(side="left")
        self.interval = tk.Spinbox(frame, from_=MIN_REFRESH_SECONDS, to=3600,
                                   increment=30, width=8, font=label_font,
                                   bg=theme["card"], fg=theme["text"],
                                   buttonbackground=theme["card"],
                                   insertbackground=theme["text"],
                                   highlightthickness=0, bd=0,
                                   command=self.on_interval)
        self.interval.delete(0, "end")
        self.interval.insert(0, str(self.settings["refresh_seconds"]))
        self.interval.bind("<FocusOut>", lambda _e: self.on_interval())
        self.interval.bind("<Return>", lambda _e: self.on_interval())
        self.interval.pack(side="left")
        tk.Label(frame, text=t("hint_interval_min"),
                 bg=theme["bg"], fg=theme["muted"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

        frame = row()
        tk.Label(frame, text=t("label_threshold"), bg=theme["bg"], fg=theme["muted"],
                 font=label_font, width=16, anchor="w").pack(side="left")
        self.threshold_value = tk.Label(frame, text="", bg=theme["bg"],
                                        fg=theme["text"], font=label_font, width=5)
        self.threshold_value.pack(side="right")
        self.threshold = tk.Scale(frame, from_=50, to=99, orient="horizontal",
                                  showvalue=False, bg=self.settings["accent"], fg=theme["text"],
                                  troughcolor=theme["card"], highlightthickness=0,
                                  bd=0, sliderrelief="flat",
                                  activebackground=self.settings["accent"])
        self.threshold.set(self.settings["warn_threshold"])
        self.threshold.config(command=self.on_threshold)
        self.threshold.pack(side="left", fill="x", expand=True)

        check(row(), t("chk_sound_on_warn"), "sound_on_warn")

        # --- Система ---
        section(t("section_system"))

        check(row(), t("chk_autostart"), "autostart", self.on_autostart)
        check(row(), t("chk_auto_refresh_token"), "auto_refresh_token")

        frame = row()
        tk.Label(frame, text=t("label_manual_token"), bg=theme["bg"],
                 fg=theme["muted"], font=label_font, anchor="w").pack(fill="x")
        self.token_entry = tk.Entry(content, show="•", font=("Consolas", 9),
                                    bg=theme["card"], fg=theme["text"],
                                    insertbackground=theme["text"],
                                    highlightthickness=1,
                                    highlightbackground=theme["border"],
                                    highlightcolor=self.settings["accent"], bd=0)
        self.token_entry.insert(0, self.settings.get("manual_token", ""))
        self.token_entry.pack(fill="x", ipady=4, pady=(2, 0))
        tk.Label(content, text=t("hint_manual_token"),
                 bg=theme["bg"], fg=theme["muted"], font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", pady=(2, 0))

        # --- Кнопки ---
        buttons = tk.Frame(content, bg=theme["bg"])
        buttons.pack(fill="x", pady=(16, 0))

        tk.Button(buttons, text=t("menu_refresh"), command=self.app.request_refresh,
                  bg=theme["card"], fg=theme["text"], font=label_font,
                  relief="flat", bd=0, padx=12, pady=6, cursor="hand2",
                  activebackground=theme["hover"],
                  activeforeground=theme["text"]).pack(side="left")

        tk.Button(buttons, text=t("btn_done"), command=self.close,
                  bg=self.settings["accent"], fg="#FFFFFF", font=label_font,
                  relief="flat", bd=0, padx=18, pady=6, cursor="hand2",
                  activebackground=self.settings["accent"],
                  activeforeground="#FFFFFF").pack(side="right")

        self.update_labels()
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry("%dx%d+%d+%d" % (width, height, max(0, x), max(0, y)))
        self.deiconify()

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, radius=8, **kwargs):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _build_theme_card(self, parent, value, caption):
        """Карточка темы: мини-превью виджета в её цветах + подпись."""
        theme = self._chrome_theme
        w, h = 76, 54

        wrap = tk.Frame(parent, bg=theme["bg"])
        canvas = tk.Canvas(wrap, width=w, height=h, bg=theme["bg"],
                           highlightthickness=0, bd=0, cursor="hand2")
        canvas.pack()
        label = tk.Label(wrap, text=caption, bg=theme["bg"], font=("Segoe UI", 8),
                         cursor="hand2")
        label.pack(pady=(4, 0))

        self._theme_cards[value] = (canvas, label)
        self._paint_theme_card(value)

        def select(_e=None):
            self.theme_var.set(value)
            self.on_theme()

        canvas.bind("<Button-1>", select)
        label.bind("<Button-1>", select)
        return wrap

    def _paint_theme_card(self, value):
        canvas, label = self._theme_cards[value]
        colors = THEMES[value]
        theme = self._chrome_theme
        w, h = 76, 54

        canvas.delete("all")
        selected = self.theme_var.get() == value
        border_color = self.settings["accent"] if selected else colors["border"]
        self._round_rect(canvas, 1, 1, w - 1, h - 1, 10, fill=colors["bg"],
                         outline=border_color, width=2 if selected else 1)
        # мини-карточка лимита внутри превью
        self._round_rect(canvas, 10, 10, w - 10, 26, 5, fill=colors["card"], outline="")
        canvas.create_line(15, 16, w - 22, 16, fill=colors["muted"], width=2,
                           capstyle="round")
        canvas.create_line(15, 21, w - 34, 21, fill=colors["text"], width=2,
                           capstyle="round")
        # мини-полоса прогресса текущим акцентом (или градиентом темы)
        self._round_rect(canvas, 10, 33, w - 10, 39, 2, fill=colors["track"], outline="")
        fill_x2 = 10 + (w - 20) * 0.55
        gradient = colors.get("gradient")
        if gradient:
            x = 10
            while x < fill_x2:
                seg_end = min(fill_x2, x + 3)
                t = (x + seg_end - 20) / 2.0 / (w - 20)
                color = lerp_color(gradient[0], gradient[1], t)
                canvas.create_rectangle(x, 33, seg_end, 39, fill=color, outline=color)
                x = seg_end
        else:
            self._round_rect(canvas, 10, 33, fill_x2, 39, 2,
                             fill=self.settings["accent"], outline="")
        label.config(fg=theme["text"] if selected else theme["muted"])

    def _repaint_theme_cards(self):
        for value in self._theme_cards:
            self._paint_theme_card(value)

    def _build_accent_dot(self, parent, color):
        """Круглая точка акцентного цвета с кольцом вокруг выбранной."""
        theme = self._chrome_theme
        size, pad = 22, 6
        total = size + pad * 2

        canvas = tk.Canvas(parent, width=total, height=total, bg=theme["bg"],
                           highlightthickness=0, bd=0, cursor="hand2")
        self._accent_dots.append((canvas, color))
        self._paint_accent_dot(canvas, color)

        canvas.bind("<Button-1>", lambda _e, c=color: self.on_accent(c))
        return canvas

    def _paint_accent_dot(self, canvas, color):
        theme = self._chrome_theme
        size, pad = 22, 6
        total = size + pad * 2

        canvas.delete("all")
        if self.settings["accent"].lower() == color.lower():
            canvas.create_oval(1, 1, total - 1, total - 1, outline=theme["text"], width=2)
        canvas.create_oval(pad, pad, pad + size, pad + size, fill=color, outline="")

    def _repaint_accent_dots(self):
        for canvas, color in self._accent_dots:
            self._paint_accent_dot(canvas, color)

    def _paint_lang_labels(self):
        theme = self._chrome_theme
        selected_font = ("Segoe UI Semibold", 9)
        normal_font = ("Segoe UI", 9)
        for code, lbl in self._lang_labels.items():
            selected = self.lang_var.get() == code
            lbl.config(fg=self.settings["accent"] if selected else theme["muted"],
                      font=selected_font if selected else normal_font)

    def on_language(self, code):
        global LANG
        if code == self.settings.get("language", "ru"):
            return
        self.lang_var.set(code)
        self.settings["language"] = code
        # Не потерять ещё не сохранённый вручную введённый токен —
        # окно настроек будет пересоздано целиком.
        self.settings["manual_token"] = self.token_entry.get().strip()
        save_settings(self.settings)
        LANG = code
        self.app.settings_window = None
        self.destroy()
        self.app.rebuild()
        self.app.open_settings()

    def update_labels(self):
        self.opacity_value.config(text="%d%%" % int(self.opacity.get()))
        self.scale_value.config(text="%d%%" % int(self.scale.get()))
        self.threshold_value.config(text="%d%%" % int(self.threshold.get()))

    def on_opacity(self, _value=None):
        self.settings["opacity"] = int(self.opacity.get())
        self.app.apply_opacity()
        self.update_labels()
        save_settings(self.settings)

    def on_scale(self, _value=None):
        self.settings["scale"] = int(self.scale.get())
        self.update_labels()
        save_settings(self.settings)
        if self._scale_job is not None:
            try:
                self.after_cancel(self._scale_job)
            except tk.TclError:
                pass
        self._scale_job = self.after(300, self.app.rebuild)

    def on_threshold(self, _value=None):
        self.settings["warn_threshold"] = int(self.threshold.get())
        self.update_labels()
        save_settings(self.settings)
        self.app.redraw_data()

    def on_theme(self):
        self.settings["theme"] = self.theme_var.get()
        save_settings(self.settings)
        self.app.rebuild()
        self._repaint_theme_cards()

    def on_accent(self, color):
        self.settings["accent"] = color
        save_settings(self.settings)
        self.app.redraw_data()
        self._repaint_theme_cards()
        self._repaint_accent_dots()
        for slider in (self.opacity, self.scale, self.threshold):
            slider.config(bg=color, activebackground=color)

    def on_interval(self):
        try:
            value = int(self.interval.get())
        except ValueError:
            value = DEFAULT_REFRESH_SECONDS
        value = max(MIN_REFRESH_SECONDS, min(3600, value))
        self.interval.delete(0, "end")
        self.interval.insert(0, str(value))
        self.settings["refresh_seconds"] = value
        save_settings(self.settings)

    def on_autostart(self):
        set_autostart(self.settings["autostart"])

    def close(self):
        self.settings["manual_token"] = self.token_entry.get().strip()
        save_settings(self.settings)
        self.app.settings_window = None
        self.destroy()
        self.app.request_refresh()

    def make_draggable(self, widget):
        widget.bind("<Button-1>", self.on_press)
        widget.bind("<B1-Motion>", self.on_drag)

    def on_press(self, event):
        self._drag = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def on_drag(self, event):
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self.geometry("+%d+%d" % (x, y))


def pythonw_launcher():
    """Путь к pythonw.exe — он запускает виджет без окна консоли."""
    launcher = sys.executable or "pythonw.exe"
    lower = launcher.lower()
    if lower.endswith("python.exe"):
        candidate = launcher[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate):
            return candidate
    return launcher


def create_desktop_shortcut():
    """Кладёт на рабочий стол ярлык ClaudeGauge с нашей иконкой.

    Путь к папке передаётся через файл .ps1 в кодировке UTF-8 с BOM,
    а не через командную строку — иначе кириллица в пути искажается.
    """
    if sys.platform != "win32":
        raise UsageError(t("err_shortcut_windows_only"), "")

    target = os.path.join(script_dir(), "ClaudeGauge.pyw")
    if not os.path.isfile(target):
        raise UsageError(t("err_shortcut_missing_file"), t("hint_shortcut_missing_file"))

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    icon = ICON_PATH if os.path.isfile(ICON_PATH) else pythonw_launcher()
    script = "\n".join([
        "$shell = New-Object -ComObject WScript.Shell",
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        "$link = $shell.CreateShortcut((Join-Path $desktop 'ClaudeGauge.lnk'))",
        "$link.TargetPath = %s" % quote(pythonw_launcher()),
        "$link.Arguments = %s" % quote('"%s"' % target),
        "$link.WorkingDirectory = %s" % quote(script_dir()),
        "$link.IconLocation = %s" % quote("%s,0" % icon),
        "$link.Description = 'ClaudeGauge'",
        "$link.Save()",
    ])

    path = os.path.join(config_dir(), "make_shortcut.ps1")
    try:
        with open(path, "w", encoding="utf-8-sig") as fh:
            fh.write(script)
    except OSError as exc:
        raise UsageError(t("err_shortcut_prepare"), str(exc)[:60])

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True, timeout=30,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception as exc:
        raise UsageError(t("err_shortcut_create"), str(exc)[:60])

    if result.returncode != 0:
        details = (result.stderr or b"").decode("utf-8", "replace").strip()
        log_error("Ярлык: %s" % details)
        raise UsageError(t("err_shortcut_powershell"), t("hint_shortcut_log"))


def set_autostart(enabled):
    if winreg is None:
        return
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    script = os.path.abspath(sys.argv[0])
    launcher = sys.executable
    if launcher.lower().endswith("python.exe"):
        candidate = launcher[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate):
            launcher = candidate
    command = '"%s" "%s"' % (launcher, script)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
            for legacy in LEGACY_APP_NAMES:
                try:
                    winreg.DeleteValue(key, legacy)
                except FileNotFoundError:
                    pass
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        log_error("Автозапуск: %s" % exc)


# --------------------------------------------------------------------------
#  Главное окно
# --------------------------------------------------------------------------

class Widget(tk.Tk):
    def __init__(self):
        super().__init__()
        global LANG
        self.settings = load_settings()
        LANG = self.settings.get("language", "ru")
        self.token_provider = TokenProvider(self.settings)
        self.settings_window = None
        self.data = None
        self.status_text = t("status_starting")
        self.status_hint = ""
        self.plan = ""
        self.last_update = None
        self.warned = set()
        self.busy = False
        self.rows = {}
        self._drag = (0, 0)
        self.results = queue.Queue()

        self.withdraw()
        self.title(APP_TITLE)
        self.overrideredirect(True)
        self.configure(bg=self.theme["bg"])

        self._glass_active = False
        self.apply_glass()
        self.build()
        self.place_window()
        self.apply_icon()
        self.apply_opacity()
        self.apply_topmost()
        self.apply_rounded_corners()
        self.deiconify()
        self.apply_window_styles()
        self.reassert_topmost()

        self.bind("<Escape>", lambda _e: self.quit_app())
        self.after(600, self.request_refresh)
        self.poll_results()
        self.tick()

    # ---------- служебное ----------

    @property
    def theme(self):
        base = THEMES.get(self.settings.get("theme", "dark"), THEMES["dark"])
        if self.settings.get("glass") and getattr(self, "_glass_active", False):
            base = dict(base)
            base["card"] = GLASS_KEY_COLOR
        return base

    def px(self, value):
        return max(1, int(round(value * self.settings.get("scale", 100) / 100.0)))

    def setup_fonts(self):
        scale = self.settings.get("scale", 100) / 100.0

        def size(value):
            return max(6, int(round(value * scale)))

        self.font_brand = tkfont.Font(family="Segoe UI Semibold", size=size(11))
        self.font_value = tkfont.Font(family="Segoe UI Semibold", size=size(13))
        self.font_small = tkfont.Font(family="Segoe UI", size=size(9))
        self.font_tiny = tkfont.Font(family="Segoe UI", size=size(8))
        self.font_icon = tkfont.Font(family="Segoe UI", size=size(11))
        self.font_icon_large = tkfont.Font(family="Segoe UI", size=size(13))
        self.font_icon_small = tkfont.Font(family="Segoe UI", size=size(10))

    def make_draggable(self, widget):
        widget.bind("<Button-1>", self.on_press)
        widget.bind("<B1-Motion>", self.on_drag)
        widget.bind("<ButtonRelease-1>", self.on_release)
        widget.bind("<Button-3>", self.show_menu)

    def on_press(self, event):
        self._drag = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def on_drag(self, event):
        if self.settings.get("locked"):
            return
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self.geometry("+%d+%d" % (x, y))

    def on_release(self, _event):
        self.settings["x"] = self.winfo_x()
        self.settings["y"] = self.winfo_y()
        save_settings(self.settings)

    def place_window(self):
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = self.settings.get("x")
        y = self.settings.get("y")
        if x is None or y is None:
            x = self.winfo_screenwidth() - width - 32
            y = 64
        x = max(0, min(x, self.winfo_screenwidth() - 60))
        y = max(0, min(y, self.winfo_screenheight() - 60))
        self.geometry("%dx%d+%d+%d" % (width, height, x, y))

    def apply_opacity(self):
        try:
            self.attributes("-alpha", self.settings.get("opacity", 94) / 100.0)
        except tk.TclError:
            pass
        self.sync_taskbar_style()

    def apply_glass(self):
        """Эффект стекла: -transparentcolor делает "card" дырой в окне,
        а блюр Windows позади заполняет её. Если что-то пошло не так —
        просто остаёмся без эффекта, ничего не ломаем."""
        wanted = bool(self.settings.get("glass")) and sys.platform == "win32"
        if wanted:
            try:
                self.attributes("-transparentcolor", GLASS_KEY_COLOR)
            except tk.TclError:
                wanted = False
        if wanted:
            self._glass_active = self.set_blur_behind(True)
        else:
            self.set_blur_behind(False)
            self._glass_active = False
            if sys.platform == "win32":
                try:
                    self.attributes("-transparentcolor", "")
                except tk.TclError:
                    pass

    def set_blur_behind(self, on):
        """Включает/выключает акриловый блюр окна через недокументированный
        SetWindowCompositionAttribute. Может перестать работать в будущих
        сборках Windows — тогда просто тихо не сработает."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            class AccentPolicy(ctypes.Structure):
                _fields_ = [
                    ("AccentState", ctypes.c_int),
                    ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint),
                    ("AnimationId", ctypes.c_int),
                ]

            class WindowCompositionAttributeData(ctypes.Structure):
                _fields_ = [
                    ("Attribute", ctypes.c_int),
                    ("Data", ctypes.POINTER(AccentPolicy)),
                    ("SizeOfData", ctypes.c_size_t),
                ]

            ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
            ACCENT_DISABLED = 0
            WCA_ACCENT_POLICY = 19

            tint = "#FFFFFF" if self.settings.get("theme") == "light" else "#000000"
            r, g, b = int(tint[1:3], 16), int(tint[3:5], 16), int(tint[5:7], 16)
            gradient_color = (0x33 << 24) | (b << 16) | (g << 8) | r

            policy = AccentPolicy()
            policy.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND if on else ACCENT_DISABLED
            policy.AccentFlags = 0
            policy.GradientColor = gradient_color
            policy.AnimationId = 0

            data = WindowCompositionAttributeData()
            data.Attribute = WCA_ACCENT_POLICY
            data.Data = ctypes.pointer(policy)
            data.SizeOfData = ctypes.sizeof(policy)

            handle = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            ok = ctypes.windll.user32.SetWindowCompositionAttribute(handle, ctypes.byref(data))
            return bool(ok)
        except Exception:
            return False

    def apply_topmost(self):
        try:
            self.attributes("-topmost", bool(self.settings.get("always_on_top", True)))
        except tk.TclError:
            pass
        self.sync_taskbar_style()

    def sync_taskbar_style(self):
        """Восстанавливает биты TOOLWINDOW/APPWINDOW/NOACTIVATE в GWL_EXSTYLE.

        Tk на Windows при каждой обработке "wm attributes" (-alpha,
        -topmost — см. apply_opacity/apply_topmost) пересобирает весь
        GWL_EXSTYLE окна по своим внутренним данным и стирает то, что
        выставлено вручную через SetWindowLongW. Без повторного вызова
        после каждого такого attributes галочка "Скрывать с панели задач"
        переставала действовать уже после первого обновления данных
        (force_repaint вызывает apply_opacity)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            handle = user32.GetParent(self.winfo_id()) or self.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_NOACTIVATE = 0x08000000
            style = user32.GetWindowLongW(handle, GWL_EXSTYLE)
            if self.settings.get("hide_from_taskbar", True):
                style = (style & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
            else:
                style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if self.settings.get("stay_above_fullscreen"):
                style |= WS_EX_NOACTIVATE
            else:
                style &= ~WS_EX_NOACTIVATE
            user32.SetWindowLongW(handle, GWL_EXSTYLE, style)
        except Exception:
            pass

    def apply_icon(self, window=None):
        """Ставит иконку главному окну или окну настроек."""
        if not os.path.isfile(ICON_PATH):
            return
        target = window if window is not None else self
        try:
            target.iconbitmap(ICON_PATH)
        except tk.TclError:
            pass

    def apply_window_styles(self):
        """Расширенные стили окна: запись в панели задач и перехват фокуса.

        withdraw()/deiconify() здесь обязательны: без пересоздания окна на
        экране Windows не обновит существующую кнопку в панели задач при
        одной лишь смене GWL_EXSTYLE."""
        if sys.platform != "win32":
            return
        try:
            self.withdraw()
            self.apply_opacity()
            self.apply_topmost()
            self.sync_taskbar_style()
            self.deiconify()
            self.apply_rounded_corners()
        except Exception as exc:
            log_error("Стили окна: %s" % exc)

    def reassert_topmost(self):
        """Возвращает виджет наверх раз в две секунды.

        Полноэкранные приложения объявляют себя поверх всех окон и вытесняют
        нас вниз. Перестановка без активации возвращает виджет обратно,
        не отбирая фокус. Эксклюзивный полноэкранный DirectX так не перекрыть.
        """
        if (sys.platform == "win32"
                and self.settings.get("stay_above_fullscreen")
                and self.settings.get("always_on_top", True)):
            try:
                import ctypes
                user32 = ctypes.windll.user32
                handle = user32.GetParent(self.winfo_id()) or self.winfo_id()
                HWND_TOPMOST = -1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                user32.SetWindowPos(handle, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
            except Exception:
                pass
        self.after(2000, self.reassert_topmost)

    def apply_rounded_corners(self):
        """Скругление углов средствами Windows 11 (DWM)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            handle = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            preference = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                handle, 33, ctypes.byref(preference), ctypes.sizeof(preference))
        except Exception:
            pass

    # ---------- сборка интерфейса ----------

    def build(self):
        self.setup_fonts()
        theme = self.theme
        self.configure(bg=theme["border"])

        self.shell = tk.Frame(self, bg=theme["card"],
                              padx=self.px(16), pady=self.px(14))
        self.shell.pack(fill="both", expand=True, padx=1, pady=1)
        self.make_draggable(self.shell)

        content_width = self.px(300)

        gradient = theme.get("gradient")
        if gradient:
            strip_height = self.px(3)
            strip = tk.Canvas(self.shell, width=content_width, height=strip_height,
                              highlightthickness=0, bd=0, bg=theme["card"])
            strip.pack(fill="x", pady=(0, self.px(10)))
            draw_horizontal_gradient(strip, content_width, strip_height, *gradient)
            self.make_draggable(strip)

        # Шапка
        header = tk.Frame(self.shell, bg=theme["card"], width=content_width)
        header.pack(fill="x", pady=(0, self.px(12)))
        self.make_draggable(header)

        brand = tk.Frame(header, bg=theme["card"])
        brand.pack(side="left")
        self.make_draggable(brand)

        title = tk.Label(brand, text="Claude", bg=theme["card"], fg=theme["text"],
                         font=self.font_brand)
        title.pack(side="left")
        self.make_draggable(title)

        self.plan_label = tk.Label(brand, text=self.plan, bg=theme["card"],
                                   fg=self.settings["accent"], font=self.font_tiny)
        self.plan_label.pack(side="left", padx=(self.px(7), 0), pady=(self.px(3), 0))
        self.make_draggable(self.plan_label)

        for symbol, command, tip, font in (
                ("✕", self.quit_app, "Закрыть", self.font_icon),
                ("⚙", self.open_settings, "Настройки", self.font_icon_small),
                ("⟳", self.request_refresh, "Обновить", self.font_icon_large)):
            button = tk.Label(header, text=symbol, bg=theme["card"],
                              fg=theme["muted"], font=font,
                              cursor="hand2", padx=self.px(5))
            button.pack(side="right")
            button.bind("<Button-1>", lambda _e, c=command: c())
            button.bind("<Enter>", lambda e: e.widget.config(fg=self.theme["text"]))
            button.bind("<Leave>", lambda e: e.widget.config(fg=self.theme["muted"]))
            button.bind("<Button-3>", self.show_menu)

        # Строки лимитов
        body = tk.Frame(self.shell, bg=theme["card"])
        body.pack(fill="x")
        self.make_draggable(body)
        self.body = body

        self.rows = {}
        self.rows["five_hour"] = UsageRow(body, self, t("row_title_session"), content_width,
                                          weekly=False)
        self.rows["seven_day"] = UsageRow(body, self, t("row_title_week_all"), content_width,
                                          weekly=True)

        if not self.settings.get("compact") and self.settings.get("show_model_limits"):
            self.rows["seven_day_sonnet"] = UsageRow(body, self, t("row_title_week_sonnet"),
                                                      content_width, weekly=True)
            self.rows["seven_day_opus"] = UsageRow(body, self, t("row_title_week_opus"),
                                                    content_width, weekly=True)
        if not self.settings.get("compact") and self.settings.get("show_extra_usage"):
            self.rows["extra_usage"] = UsageRow(body, self, t("row_title_extra"), content_width,
                                                weekly=False)

        # Подвал
        footer = tk.Frame(self.shell, bg=theme["card"], width=content_width)
        footer.pack(fill="x", pady=(self.px(2), 0))
        self.make_draggable(footer)

        top_text, bottom_text = self.status_lines()
        self.status_label = tk.Label(footer, text=top_text, bg=theme["card"],
                                     fg=theme["muted"], font=self.font_tiny, anchor="w",
                                     justify="left", wraplength=content_width)
        self.status_label.pack(fill="x")
        self.make_draggable(self.status_label)

        self.hint_label = tk.Label(footer, text=bottom_text, bg=theme["card"],
                                   fg=theme["muted"], font=self.font_tiny, anchor="w",
                                   justify="left", wraplength=content_width)
        self.hint_label.pack(fill="x")
        self.make_draggable(self.hint_label)

        self.menu = tk.Menu(self, tearoff=0, bg=theme["card"], fg=theme["text"],
                            activebackground=self.settings["accent"],
                            activeforeground="#FFFFFF", bd=0,
                            font=("Segoe UI", 9))
        self.menu.add_command(label=t("menu_refresh"), command=self.request_refresh)
        self.menu.add_command(label=t("menu_settings"), command=self.open_settings)
        self.menu.add_command(label=t("menu_create_shortcut"), command=self.make_shortcut)
        self.menu.add_separator()
        self.menu.add_command(label=t("menu_always_on_top"), command=self.toggle_topmost)
        self.menu.add_command(label=t("menu_compact"), command=self.toggle_compact)
        self.menu.add_separator()
        self.menu.add_command(label=t("menu_quit"), command=self.quit_app)

    def rebuild(self):
        x, y = self.winfo_x(), self.winfo_y()
        for child in self.winfo_children():
            if child is not self.settings_window:
                child.destroy()
        self.apply_glass()
        self.build()
        self.update_idletasks()
        self.geometry("%dx%d+%d+%d" % (self.winfo_reqwidth(),
                                       self.winfo_reqheight(), x, y))
        self.redraw_data()
        self.apply_rounded_corners()
        self.force_repaint()

    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_topmost(self):
        self.settings["always_on_top"] = not self.settings.get("always_on_top", True)
        save_settings(self.settings)
        self.apply_topmost()

    def toggle_compact(self):
        self.settings["compact"] = not self.settings.get("compact", False)
        save_settings(self.settings)
        self.rebuild()

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = SettingsWindow(self)

    def make_shortcut(self):
        try:
            create_desktop_shortcut()
        except UsageError as exc:
            self.set_status(exc.message, exc.hint)
        except Exception as exc:
            log_error(traceback.format_exc())
            self.set_status(t("err_shortcut_create"), str(exc)[:60])
        else:
            self.set_status(t("status_shortcut_created"), "")

    def quit_app(self):
        self.settings["x"] = self.winfo_x()
        self.settings["y"] = self.winfo_y()
        save_settings(self.settings)
        self.destroy()

    # ---------- данные ----------

    def request_refresh(self):
        if self.busy:
            return
        self.busy = True
        self.set_status(t("status_updating"), "")
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            token = self.token_provider.get_token()
            try:
                payload = fetch_usage(token)
            except UsageError as exc:
                if exc.kind == "token_rejected":
                    token = self.token_provider.get_token(force_refresh=True)
                    payload = fetch_usage(token)
                else:
                    raise
            plan = self.token_provider.subscription_type()
            self.results.put(("ok", payload, plan))
        except UsageError as exc:
            self.results.put(("error", exc.message, exc.hint))
        except Exception as exc:
            log_error(traceback.format_exc())
            self.results.put(("error", t("status_update_failed"), str(exc)[:60]))

    def poll_results(self):
        """Крутится в главном потоке — только он имеет право трогать интерфейс."""
        try:
            while True:
                kind, first, second = self.results.get_nowait()
                if kind == "ok":
                    self.on_success(first, second)
                else:
                    self.on_failure(first, second)
        except queue.Empty:
            pass
        self.after(200, self.poll_results)

    def on_success(self, payload, plan):
        self.busy = False
        self.data = payload
        self.last_update = datetime.now()
        if plan:
            self.plan = plan
            self.plan_label.config(text=plan)
        self.set_status(t("status_updated", time=self.last_update.strftime("%H:%M:%S")), "")
        self.redraw_data()
        self.schedule_next()

    def on_failure(self, message, hint):
        self.busy = False
        self.set_status(message, hint)
        self.schedule_next()

    def schedule_next(self):
        delay = max(MIN_REFRESH_SECONDS,
                    int(self.settings.get("refresh_seconds", DEFAULT_REFRESH_SECONDS)))
        self.after(delay * 1000, self.request_refresh)

    def status_lines(self):
        """Однострочный статус уходит в нижнюю строку, верхняя остаётся пустой."""
        if self.status_hint:
            return self.status_text, self.status_hint
        return "", self.status_text

    def set_status(self, text, hint):
        self.status_text = text
        self.status_hint = hint or ""
        if hasattr(self, "status_label"):
            top_text, bottom_text = self.status_lines()
            self.status_label.config(text=top_text)
            self.hint_label.config(text=bottom_text)
            self.fit_window()

    def fit_window(self):
        """Подгоняет высоту окна под содержимое, не трогая позицию."""
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        if (width, height) != (self.winfo_width(), self.winfo_height()):
            self.geometry("%dx%d+%d+%d" % (width, height,
                                           self.winfo_x(), self.winfo_y()))
            self.update_idletasks()
        self.force_repaint()

    def force_repaint(self):
        """Стирает остатки старого текста.

        Окно полупрозрачное, поэтому Windows рисует его через отдельный буфер
        и после смены текста на более короткий может оставить прежние пиксели.
        Полная перерисовка с очисткой фона убирает такие следы.
        """
        self.update_idletasks()
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                handle = user32.GetParent(self.winfo_id()) or self.winfo_id()
                RDW_INVALIDATE = 0x0001
                RDW_ERASE = 0x0004
                RDW_ALLCHILDREN = 0x0080
                RDW_UPDATENOW = 0x0100
                user32.RedrawWindow(handle, None, None,
                                    RDW_INVALIDATE | RDW_ERASE
                                    | RDW_ALLCHILDREN | RDW_UPDATENOW)
            except Exception:
                pass
        # Повторная установка прозрачности заставляет Windows обновить буфер.
        self.apply_opacity()

    def redraw_data(self):
        if not self.data:
            return
        threshold = self.settings.get("warn_threshold", 80)

        for key in ("five_hour", "seven_day", "seven_day_sonnet", "seven_day_opus"):
            row = self.rows.get(key)
            if row is None:
                continue
            block = self.data.get(key)
            if not isinstance(block, dict):
                row.update(0, None)
                row.value_label.config(text="—", fg=self.theme["muted"])
                row.sub_label.config(text=t("limit_not_active"))
                row.bar.render(0, self.settings["accent"])
                continue
            percent = float(block.get("utilization") or 0.0)
            row.update(percent, parse_iso(block.get("resets_at")))
            if percent >= threshold and key not in self.warned:
                self.warned.add(key)
                if self.settings.get("sound_on_warn") and winsound:
                    try:
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except Exception:
                        pass
            elif percent < threshold:
                self.warned.discard(key)

        row = self.rows.get("extra_usage")
        if row is not None:
            extra = self.data.get("extra_usage") or {}
            if not extra.get("is_enabled"):
                row.update_text(t("extra_off"), t("extra_not_enabled"))
                row.bar.render(0, self.settings["accent"])
            else:
                used = extra.get("used_credits")
                limit = extra.get("monthly_limit")
                utilization = extra.get("utilization")
                if utilization is None and used is not None and limit:
                    utilization = float(used) / float(limit) * 100.0
                percent = float(utilization or 0.0)
                color = row.color_for(percent)
                row.value_label.config(text="%.0f%%" % percent, fg=color)
                row.bar.render(percent, color, gradient=row.gradient_for(color))
                if used is not None and limit:
                    row.sub_label.config(text=t("extra_used_of", used=fmt_number(used),
                                               limit=fmt_number(limit)))
                else:
                    row.sub_label.config(text=t("extra_enabled"))
                row.reset_at = None

        self.plan_label.config(fg=self.settings["accent"])

    def tick(self):
        for key, row in self.rows.items():
            if key != "extra_usage":
                row.tick()
        self.after(1000, self.tick)


def fmt_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = "{:,}".format(int(number)) if number == int(number) else "{:,.2f}".format(number)
    # По-русски разряды разделяются пробелом, по-английски — обычная запятая.
    return text if LANG == "en" else text.replace(",", " ")


# --------------------------------------------------------------------------

def main():
    app = Widget()
    app.mainloop()


if __name__ == "__main__":
    main()

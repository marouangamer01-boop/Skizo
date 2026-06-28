# full x.main.py — Drive removed; worker forwarding added

import asyncio
import html as html_mod
import os
import json
import re
import time
import urllib.parse
import hashlib
from datetime import datetime
from keep_alive import keep_alive
import requests
from urllib3.exceptions import InsecureRequestWarning
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# Configuration
OWNER_ID = 1249057893
CHANNEL_USERNAME = "@cookiesnetflix1"  # make sure the bot is admin in this channel
CHANNEL_ID = None  # optional numeric channel id (-100...)

# Import netflix_account.py (must be present)
from netflix_account import fetch_account_info_sync

# File forwarding helper (forwards uploaded files to the separate worker/carrier service)
from worker_client import post_file_to_worker_background

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

BOT_DISPLAY_NAME = "Flexible X"
BOT_USERNAME = "@Flexible_x_bot"

# Conversation state
WAITING_FOR_FILE = 1

# Archive (kept for compatibility but we will not write locally or to Drive)
ARCHIVE_FOLDER = "archive_files"
HASHES_FILE = "hashes.txt"

# Netflix iOS API params
API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
QUERY_PARAMS = {
    "appVersion": "15.48.1",
    "config": '{"gamesInTrailersEnabled":"false","isTrailersEvidenceEnabled":"false","cdsMyListSortEnabled":"true","kidsBillboardEnabled":"true","addHorizontalBoxArtToVideoSummariesEnabled":"false[...]',
    "device_type": "NFAPPL-02-",
    "esn": "NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "idiom": "phone",
    "iosVersion": "15.8.5",
    "isTablet": "false",
    "languages": "en-US",
    "locale": "en-US",
    "maxDeviceWidth": "375",
    "model": "saget",
    "modelType": "IPHONE8-1",
    "odpAware": "true",
    "pathFormat": "graph",
    "pixelDensity": "2.0",
    "progressive": "false",
    "responseFormat": "json",
}
BASE_HEADERS = {
    "User-Agent": "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "x-netflix.request.attempt": "1",
    "x-netflix.request.client.user.guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.context.profile-guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.request.routing": '{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
    "x-netflix.context.app-version": "15.48.1",
    "x-netflix.argo.translated": "true",
    "x-netflix.context.form-factor": "phone",
    "x-netflix.context.sdk-version": "2012.4",
    "x-netflix.client.appversion": "15.48.1",
    "x-netflix.context.max-device-width": "375",
    "x-netflix.tracing.cl.useractionid": "4DC655F2-9C3C-4343-8229-CA1B003C3053",
    "x-netflix.client.type": "argo",
    "x-netflix.client.ftl.esn": "NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "x-netflix.context.locales": "en-US",
    "x-netflix.context.top-level-uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.client.iosversion": "15.8.5",
    "accept-language": "en-US;q=1",
    "x-netflix.context.os-version": "15.8.5",
    "x-netflix.request.client.context": '{"appState":"foreground"}',
    "x-netflix.context.ui-flavor": "argo",
    "x-netflix.argo.nfnsm": "9",
    "x-netflix.context.pixel-density": "2.0",
    "x-netflix.request.toplevel.uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.request.client.timezoneid": "Asia/Dhaka",
}

COOKIE_KEYS = ("NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent")
REQUIRED_COOKIE = "NetflixId"

# File protection
MAX_FILE_SIZE_KB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_KB * 1024
COMPRESSED_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"}

user_states = {}

# Messages
def _welcome_text() -> str:
    return (
        f"{BOT_DISPLAY_NAME} ({BOT_USERNAME}) — Netflix Token Checker 🎬\n\n"
        "Available for PC and mobile (Android & iPhone).\n\n"
        "Send your Netflix cookies (Netscape export, JSON array, or plain cookie header text) and I will:\n"
        " • extract a direct login link (nftoken) usable on PC, Android, and iPhone\n"
        " • attempt to retrieve account info (plan, email, country, profiles, features)\n\n"
        "How to use:\n"
        " • Press the 📥 Scan New File button, then upload a small .txt with cookies, OR\n"
        " • Paste the cookie text directly while the bot is waiting.\n"
        " • After processing, tap the Login button for PC / Android / iPhone.\n\n"
        f"To use the bot you must be subscribed to our channel: {CHANNEL_USERNAME}\n"
        "Only check cookies you own or have permission to test. This tool is provided for educational purposes."
    )


def _ask_for_file_text() -> str:
    return "Please send the cookie file now (upload a .txt or paste the cookie text). I will check it and reply with results."


def _invalid_cookie_user_message() -> str:
    return (
        "❌ Failed — Could not retrieve a valid token for this cookie.\n\n"
        "This usually means the cookie is incomplete, expired, malformed, or Netflix blocked the request.\n"
        "Steps you can try:\n"
        " • Make sure you pasted the full cookie (including NetflixId)\n"
        " • Try converting Netscape cookies to JSON using the converter tool\n"
        " • Try again later (network or Netflix protections can cause temporary failures)\n\n"
        "If you're stuck, click a button below or send /start to reset the bot."
    )

# Cookie parsing & token fetch helpers
def _get_file_extension(filename: str) -> str:
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


def _is_compressed_file(filename: str) -> bool:
    ext = _get_file_extension(filename)
    return ext in COMPRESSED_EXTENSIONS


def _calculate_file_hash(file_bytes: bytes) -> str:
    return hashlib.md5(file_bytes).hexdigest()


def _decode_cookie_value(value):
    if isinstance(value, str) and "%" in value:
        try:
            return urllib.parse.unquote(value)
        except Exception:
            return value
    return value


def extract_cookie_dict(text):
    cookie_dict = {}
    for key in COOKIE_KEYS:
        match = re.search(rf"(?<!\w){re.escape(key)}=([^;,\s]+)", text)
        if match:
            cookie_dict[key] = _decode_cookie_value(match.group(1))
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\s+", line)
        if len(parts) >= 2:
            name = parts[-2].strip()
            value = parts[-1].strip()
            if name in COOKIE_KEYS and name not in cookie_dict:
                cookie_dict[name] = _decode_cookie_value(value)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        for cookie in data:
            name = cookie.get("name")
            value = cookie.get("value")
            if name in COOKIE_KEYS and isinstance(value, str):
                cookie_dict[name] = _decode_cookie_value(value)
    elif isinstance(data, dict):
        if any(key in data for key in COOKIE_KEYS):
            for key in COOKIE_KEYS:
                value = data.get(key)
                if isinstance(value, str):
                    cookie_dict[key] = _decode_cookie_value(value)
        elif isinstance(data.get("cookies"), list):
            for cookie in data["cookies"]:
                name = cookie.get("name")
                value = cookie.get("value")
                if name in COOKIE_KEYS and isinstance(value, str):
                    cookie_dict[name] = _decode_cookie_value(value)
    return cookie_dict


def _sg(d, *keys, default="N/A"):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    val = d
    if val in ("", {}, []):
        return default
    return str(val)


def _make_cookie_str(cookie_dict):
    nid = cookie_dict.get("NetflixId", "")
    snid = cookie_dict.get("SecureNetflixId", "")
    parts = [f"NetflixId={nid}"]
    if snid:
        parts.append(f"SecureNetflixId={snid}")
    for k in ("nfvdid", "OptanonConsent"):
        v = cookie_dict.get(k)
        if v:
            parts.append(f"{k}={v}")
    return "; ".join(parts)


def fetch_netflix_data(cookie_dict):
    netflix_id = cookie_dict.get(REQUIRED_COOKIE)
    if not netflix_id:
        raise ValueError("Could not find 'NetflixId' in the provided text.")
    cookie_str = _make_cookie_str(cookie_dict)
    headers = dict(BASE_HEADERS)
    headers["Cookie"] = cookie_str
    params = list(QUERY_PARAMS.items()) + [("path", '["account","token","default"]')]
    response = requests.get(API_URL, params=params, headers=headers, timeout=30, verify=False)
    response.raise_for_status()
    raw = response.json()
    val = raw.get("value") or {}
    account = val.get("account") or {}
    token_data = (account.get("token") or {}).get("default") or {}
    token = token_data.get("token")
    expires = token_data.get("expires")
    if not token:
        raise ValueError("Operation failed — the server did not return a token.")
    if isinstance(expires, int) and len(str(expires)) == 13:
        expires //= 1000
    return {"token": token, "expires": expires}


def format_expiry(expires):
    if not isinstance(expires, (int, float)):
        return "Unknown"
    try:
        return datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(expires)

# Rate limiting & registration
RATE_FILE = "rate_limits.json"
USERS_FILE = "users.txt"
BATCH_LIMIT = 5
BATCH_COOLDOWN = 5 * 60
DAILY_LIMIT = 24
DAILY_WINDOW = 24 * 60 * 60

def _load_rates() -> dict:
    if os.path.exists(RATE_FILE):
        try:
            with open(RATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_rates(data: dict) -> None:
    with open(RATE_FILE, "w") as f:
        json.dump(data, f)


def _check_rate_limit(user_id: int):
    if user_id == OWNER_ID:
        return True, None
    now = time.time()
    rates = _load_rates()
    uid = str(user_id)
    user = rates.get(uid, {
        "batch_count": 0,
        "batch_reset_at": 0,
        "daily_count": 0,
        "daily_reset_at": now + DAILY_WINDOW,
    })
    if now >= user.get("daily_reset_at", 0):
        user["daily_count"] = 0
        user["daily_reset_at"] = now + DAILY_WINDOW
    if user.get("daily_count", 0) >= DAILY_LIMIT:
        remaining = int(user["daily_reset_at"] - now)
        h, m = divmod(remaining // 60, 60)
        return False, (
            f"⛔ <b>Daily limit reached.</b>\n"
            f"You can process up to {DAILY_LIMIT} files per 24 hours.\n"
            f"Try again in <b>{h}h {m}m</b>."
        )
    if now >= user.get("batch_reset_at", 0):
        user["batch_count"] = 0
    if user.get("batch_count", 0) >= BATCH_LIMIT:
        remaining = int(user["batch_reset_at"] - now)
        m, s = divmod(remaining, 60)
        return False, (
            f"⏳ <b>Slow down!</b>\n"
            f"You sent {BATCH_LIMIT} files in a row.\n"
            f"Please wait <b>{m}m {s}s</b> before sending more."
        )
    user["batch_count"] = user.get("batch_count", 0) + 1
    user["daily_count"] = user.get("daily_count", 0) + 1
    if user["batch_count"] >= BATCH_LIMIT:
        user["batch_reset_at"] = now + BATCH_COOLDOWN
    rates[uid] = user
    _save_rates(rates)
    return True, None


def _register_user(user_id: int) -> bool:
    existing: set[str] = set()
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            existing = {line.strip() for line in f if line.strip()}
    uid = str(user_id)
    if uid in existing:
        return False
    with open(USERS_FILE, "a") as f:
        f.write(uid + "\n")
    return True


def _get_common_keyboard():
    channel_url = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}" if CHANNEL_USERNAME else "https://t.me/"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Channel", url=channel_url)],
        [InlineKeyboardButton("📥 Scan New File", callback_data="scan_file")],
    ])


async def _send_error_response(target_update_or_message, error_text: str, user_id: int):
    user_states[user_id] = None
    fallback_instruction = "\n\nIf you are stuck, please click the button below or send /start to reset the bot."
    full_error_text = error_text + fallback_instruction
    common_keyboard = _get_common_keyboard()
    if isinstance(target_update_or_message, Update):
        await target_update_or_message.message.reply_text(
            full_error_text,
            parse_mode="HTML",
            reply_markup=common_keyboard,
            disable_web_page_preview=True
        )
    else:
        await target_update_or_message.edit_text(
            full_error_text,
            parse_mode="HTML",
            reply_markup=common_keyboard,
            disable_web_page_preview=True
        )

# Subscription helper
async def _is_user_subscribed(bot, user_id: int) -> bool:
    chat_id = CHANNEL_ID if CHANNEL_ID else CHANNEL_USERNAME
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

# Callback: Scan button (checks subscription)
async def scan_file_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    subscribed = await _is_user_subscribed(context.bot, user_id)
    if not subscribed:
        join_text = (
            f"To use this bot you must subscribe to our channel: {CHANNEL_USERNAME}\n\n"
            "Please join the channel, then press the button below and I will check again."
        )
    ... (truncated content)
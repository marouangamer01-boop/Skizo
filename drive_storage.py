"""Google Drive storage helper for the bot.

This module uploads files directly to Google Drive using a service account JSON provided via
GDRIVE_SERVICE_ACCOUNT_JSON environment variable. No server-local files are written. Files are
uploaded into GDRIVE_FOLDER_ID when provided. Files are tagged with an appProperty 'md5' so we can
check for duplicates.

Environment variables used:
- GDRIVE_SERVICE_ACCOUNT_JSON = (service account JSON content)
- GDRIVE_FOLDER_ID = (optional) Drive folder ID to upload into
- USE_GDRIVE = '1'|'true' to indicate Drive usage (checked by main.py)

API:
- init_from_env()
- store_file_from_bytes(file_bytes, original_name, user_id, message_id) -> (file_id, created_bool)
- file_exists(md5_hash) -> bool

Note: requires google-api-python-client and google-auth packages which will be added to requirements.txt.
"""

import os
import io
import json
import hashlib
import datetime
from typing import Optional, Tuple

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from googleapiclient.errors import HttpError
except Exception:  # runtime import may fail until requirements are installed
    service_account = None
    build = None
    MediaIoBaseUpload = None
    HttpError = Exception

_drive_service = None
_folder_id: Optional[str] = None
_initialized = False


def _md5_of_bytes(b: bytes) -> str:
    m = hashlib.md5()
    m.update(b)
    return m.hexdigest()


def init_from_env(service_account_json_env: str = "GDRIVE_SERVICE_ACCOUNT_JSON", folder_id_env: str = "GDRIVE_FOLDER_ID") -> None:
    """Initialize Drive client from environment variables."""
    global _drive_service, _folder_id, _initialized
    if _initialized:
        return

    sa_json = os.environ.get(service_account_json_env)
    if not sa_json:
        raise RuntimeError(f"Environment variable {service_account_json_env} is not set")
    try:
        info = json.loads(sa_json)
    except Exception as exc:
        raise RuntimeError("Invalid JSON in GDRIVE_SERVICE_ACCOUNT_JSON") from exc

    if service_account is None:
        raise RuntimeError("google-auth packages not installed; add google-api-python-client and google-auth to requirements")

    creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)

    _folder_id = os.environ.get(folder_id_env)
    _initialized = True


def _ensure_initialized():
    if not _initialized:
        init_from_env()


def file_exists(md5_hash: str) -> bool:
    if not md5_hash:
        return False
    _ensure_initialized()
    q_parts = [f"appProperties has {{ key = 'md5' and value = '{md5_hash}' }}", "trashed = false"]
    if _folder_id:
        q_parts.append(f"'{_folder_id}' in parents")
    q = " and ".join(q_parts)
    try:
        resp = _drive_service.files().list(q=q, spaces='drive', fields='files(id)', pageSize=1, supportsAllDrives=True).execute()
        files = resp.get('files', [])
        return len(files) > 0
    except HttpError:
        return False


def store_file_from_bytes(file_bytes: bytes, original_name: Optional[str], user_id: Optional[int], message_id: Optional[int]) -> Tuple[str, bool]:
    """Upload bytes to Drive without writing to local disk.

    Returns (file_id, created_bool) where created_bool is False if duplicate detected.
    """
    _ensure_initialized()
    md5 = _md5_of_bytes(file_bytes)
    # check duplicate
    try:
        q_parts = [f"appProperties has {{ key = 'md5' and value = '{md5}' }}", "trashed = false"]
        if _folder_id:
            q_parts.append(f"'{_folder_id}' in parents")
        q = " and ".join(q_parts)
        resp = _drive_service.files().list(q=q, spaces='drive', fields='files(id, name)', pageSize=1, supportsAllDrives=True).execute()
        files = resp.get('files', [])
        if files:
            return files[0]['id'], False
    except HttpError:
        pass

    now = datetime.datetime.utcnow()
    safe_name = (original_name or f"file-{md5[:8]}")[:180]
    filename = f"{now:%Y-%m-%d}_{md5[:16]}_{safe_name}"

    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype='text/plain', resumable=False)
    body = {
        'name': filename,
        'mimeType': 'text/plain',
        'appProperties': {
            'md5': md5,
            'uploader_id': str(user_id or ""),
            'message_id': str(message_id or ""),
        },
    }
    if _folder_id:
        body['parents'] = [_folder_id]

    try:
        created = _drive_service.files().create(body=body, media_body=media, fields='id, name, createdTime', supportsAllDrives=True).execute()
        return created.get('id') or created.get('name'), True
    except HttpError:
        raise

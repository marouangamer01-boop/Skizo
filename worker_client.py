import os
import json
import hashlib
import threading
import requests

# Worker endpoint configuration (the worker service that will store files)
WORKER_URL = os.environ.get("WORKER_URL", "")  # e.g. https://skizo-carrier.railway.app
WORKER_API_KEY = os.environ.get("WORKER_API_KEY", "")

# This helper posts a file to the worker service in a background thread so the bot is not blocked.
# It intentionally returns immediately after starting the background thread.

def post_file_to_worker_background(file_bytes: bytes, original_name: str, uploader_id: int, message_id: int):
    def _post():
        try:
            md5 = hashlib.md5(file_bytes).hexdigest()
            files = {"file": (original_name or "upload.txt", file_bytes)}
            meta = {"uploader_id": str(uploader_id or ""), "message_id": str(message_id or ""), "md5": md5}
            headers = {"X-API-KEY": WORKER_API_KEY} if WORKER_API_KEY else {}
            url = WORKER_URL.rstrip("/") + "/store"
            resp = requests.post(url, files=files, data={"meta": json.dumps(meta)}, headers=headers, timeout=20)
            if resp.status_code not in (200, 201, 409):
                print("Worker returned error:", resp.status_code, resp.text)
        except Exception as e:
            print("Worker POST failed:", e)

    try:
        threading.Thread(target=_post, daemon=True).start()
    except Exception as e:
        print("Failed to start worker post thread:", e)

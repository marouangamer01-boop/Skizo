# netflix_account.py
# Robust extractor focused on accurate profile names + other account metadata.
# Uses BeautifulSoup when available, but will still work without bs4.
# Filtering removes device / identifier entries (Chrome, Windows, api, akiraBuildIdentifier, etc.)

import re
import json
import requests

# Try to import BeautifulSoup; if not present, we still work with fallbacks
try:
    from bs4 import BeautifulSoup  # type: ignore
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False

# Blacklist fragments that commonly represent devices / technical IDs
_DEVICE_TOKENS = {
    "chrome", "windows", "api", "akirabuildidentifier", "android", "ios",
    "edge", "safari", "ps4", "xbox", "roku", "tv", "device", "chromium",
    "linux", "mac", "opera", "appletv", "smarttv", "firetv", "apple",
    "chromeos", "playstation", "roku", "netflix", "windowsphone"
}

def decode_hex_escapes(s: str) -> str:
    if not s:
        return s
    s = re.sub(r'\\x([0-9A-Fa-f]{2})', lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r'\\u([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return s

def _looks_machine_like(name: str) -> bool:
    """
    Heuristics to determine if a candidate string is a technical/device identifier
    rather than a human profile name.
    Returns True if it looks machine-like and should be filtered out.
    """
    if not name or len(name) < 2:
        return True

    lower = name.lower()

    # contains explicit blacklist token
    for token in _DEVICE_TOKENS:
        if token in lower:
            return True

    # contains URL-escaped artifact like x20, x2 or similar (e.g., Unitedx20States)
    if "x20" in lower or "\\x20" in name or "%20" in name:
        return True

    # looks like a UUID / long hex (very unlikely to be a person name)
    if re.fullmatch(r"[0-9a-fA-F\-]{8,}", name):
        return True

    # mostly digits or symbols (e.g., serials) -> filter out
    digits_and_symbols = len(re.findall(r'[^A-Za-z]', name))
    if digits_and_symbols / max(1, len(name)) > 0.6:
        return True

    # very long single-token without vowels (likely machine)
    if len(name) > 20 and not re.search(r'[aeiouyAEIOUY]', name):
        return True

    # short tokens of 1 char or nonsense -> filter
    if len(name) == 1:
        return True

    # otherwise consider it human-like
    return False

def _find_json_array_by_key(html_text: str, key: str) -> str | None:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*\[', html_text)
    if not m:
        return None
    open_idx = html_text.find('[', m.end() - 1)
    if open_idx == -1:
        return None
    depth = 0
    end_idx = None
    for i in range(open_idx, len(html_text)):
        ch = html_text[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    if end_idx:
        return html_text[open_idx:end_idx + 1]
    return None

def _parse_profiles_from_json_array(array_text: str) -> list:
    names = []
    seen = set()
    try:
        arr = json.loads(array_text)
        if isinstance(arr, list):
            for obj in arr:
                if not isinstance(obj, dict):
                    continue
                # try common fields
                for fld in ("profileName", "displayName", "name"):
                    val = obj.get(fld)
                    if isinstance(val, str):
                        clean = val.strip()
                        if clean and clean not in seen and not _looks_machine_like(clean):
                            seen.add(clean)
                            names.append(clean)
                        break
    except Exception:
        return []
    return names

def _extract_profile_names_regex(html_text: str) -> list:
    candidates = []
    seen = set()
    for patt in (r'"profileName"\s*:\s*"([^"]+)"', r'"displayName"\s*:\s*"([^"]+)"', r'"name"\s*:\s*"([^"]+)"'):
        for m in re.finditer(patt, html_text):
            name = decode_hex_escapes(m.group(1)).strip()
            if name and name not in seen and not _looks_machine_like(name):
                seen.add(name)
                candidates.append(name)
    if not candidates and HAS_BS4:
        try:
            soup = BeautifulSoup(html_text, "lxml")
            for sel in (".profile-name", ".profileName", ".profile-title", ".profile-title-text"):
                for el in soup.select(sel):
                    text = el.get_text(strip=True)
                    if text and text not in seen and not _looks_machine_like(text):
                        seen.add(text)
                        candidates.append(text)
        except Exception:
            pass
    return candidates

def _extract_profiles(html_text: str) -> list:
    arr_text = _find_json_array_by_key(html_text, "profiles")
    if arr_text:
        names = _parse_profiles_from_json_array(arr_text)
        if names:
            return names
    names = _extract_profile_names_regex(html_text)
    if names:
        return names
    return []

def _extract_from_embedded_json(html_text: str) -> dict:
    patterns = {
        "localizedPlanName": r'"localizedPlanName"\s*:\s*\{\s*"fieldType"\s*:\s*"String"\s*,\s*"value"\s*:\s*"([^"]+)"',
        "emailAddress": r'"emailAddress"\s*:\s*"([^"]+)"',
        "countryOfSignup": r'"countryOfSignup"\s*:\s*"([^"]+)"',
        "accountId": r'"accountId"\s*:\s*"([^"]+)"',
    }
    result = {}
    for k, pat in patterns.items():
        m = re.search(pat, html_text)
        result[k] = decode_hex_escapes(m.group(1)) if m else None
    return result

def extract_info_from_page(html_text: str) -> dict:
    try:
        info = _extract_from_embedded_json(html_text)
        profile_names = _extract_profiles(html_text)
        profiles_count = len(profile_names) if profile_names else None
        memberships_count = len(re.findall(r'"membership"', html_text)) or len(re.findall(r'"memberships"', html_text)) or None
        page_text = re.sub(r'<[^>]+>', ' ', html_text)
        if HAS_BS4:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_text, "lxml")
                page_text = soup.get_text(" ", strip=True)
            except Exception:
                pass
        lower = page_text.lower()
        features = []
        if any(v in lower for v in ("ultra hd", "ultrahd", "uhd", "4k")):
            features.append("Ultra HD")
        if any(v in lower for v in ("hd", "720p", "1080p")):
            if "HD" not in features:
                features.append("HD")
        if "hdr" in lower:
            features.append("HDR")
        if any(v in lower for v in ("dolby", "dolby vision", "dolby atmos")):
            features.append("Dolby")
        return {
            "localizedPlanName": info.get("localizedPlanName"),
            "emailAddress": info.get("emailAddress"),
            "countryOfSignup": info.get("countryOfSignup"),
            "accountId": info.get("accountId"),
            "profile_names": profile_names,
            "profiles_count": profiles_count,
            "memberships_count": memberships_count,
            "features": features,
        }
    except Exception:
        return {
            "localizedPlanName": None,
            "emailAddress": None,
            "countryOfSignup": None,
            "accountId": None,
            "profile_names": [],
            "profiles_count": None,
            "memberships_count": None,
            "features": [],
        }

def fetch_account_info_sync(cookie_dict: dict, timeout: int = 15) -> dict:
    session = requests.Session()
    for k, v in cookie_dict.items():
        if isinstance(v, str) and v:
            session.cookies.set(k, v)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    })
    try:
        resp = session.get("https://www.netflix.com/YourAccount", timeout=timeout, allow_redirects=True, verify=True)
    except Exception:
        return {
            "valid": False,
            "plan": None,
            "email": None,
            "country": None,
            "profile_names": [],
            "profiles_count": None,
            "memberships_count": None,
            "features": [],
            "extra_members_allowed": False,
            "account_id": None,
        }
    if resp.status_code >= 400:
        return {
            "valid": False,
            "plan": None,
            "email": None,
            "country": None,
            "profile_names": [],
            "profiles_count": None,
            "memberships_count": None,
            "features": [],
            "extra_members_allowed": False,
            "account_id": None,
        }
    html = resp.text
    if "Sign In" in html or "Sign in" in html:
        return {
            "valid": False,
            "plan": None,
            "email": None,
            "country": None,
            "profile_names": [],
            "profiles_count": None,
            "memberships_count": None,
            "features": [],
            "extra_members_allowed": False,
            "account_id": None,
        }
    info = extract_info_from_page(html)
    extra_members_allowed = False
    try:
        probe = session.get("https://www.netflix.com/accountowner/addextramember", allow_redirects=False, timeout=8)
        if probe.status_code == 200:
            extra_members_allowed = True
    except Exception:
        extra_members_allowed = False
    return {
        "valid": True,
        "plan": info.get("localizedPlanName") or "Unknown",
        "email": info.get("emailAddress") or "Unknown",
        "country": info.get("countryOfSignup") or "Unknown",
        "profile_names": info.get("profile_names") or [],
        "profiles_count": info.get("profiles_count"),
        "memberships_count": info.get("memberships_count"),
        "features": info.get("features") or [],
        "extra_members_allowed": bool(extra_members_allowed),
        "account_id": info.get("accountId"),
    }

"""Shared utilities: config loading, HTTP calls, error formatting.

Configuration lives in two places:

  ~/.a9fund/accounts/<exchange_account_id>.json   -- credentials only
      (token/api_key + exchange_account_id + base_url_http / _ws_private /
       _ws_public). Written by the STEP 2 terminal snippet from the A9Fund
       account detail page; scripts read-only from here.

  <skill-root>/state.json                          -- per-skill runtime state
      (active_account_id + mode + phase + initial_balance + active_exchange)
      Written by `config.py bind`.

This split means:
  - Credentials never get overwritten by state changes.
  - The skill directory is the "current binding"; install two skill copies
    to operate two accounts in parallel.
  - Deleting state.json drops the binding (not the credentials).

Response-envelope tolerance
---------------------------
A9Fund's REST layer sits in front of the same propdesk backend, but the
published examples show BARE bodies (e.g. `{"order_id": "...", "status":
"PENDING"}`) and `{"detail": "..."}` on errors, while the coded error table
uses business codes 10001-10008. So `http_request` accepts BOTH shapes:

  - `{"code": 0, "msg": "ok", "data": {...}}`  (enveloped)
  - bare `{...}` / `{"detail": "..."}`          (unwrapped)

`unwrap()` returns `data` when present, otherwise the whole body. Callers use
`resp.get("data", resp)` or `unwrap(resp)` and work either way.

Public API:
    load_config() -> merged dict with creds+state for the active account
    save_state(state) / load_state() -> raw state.json R/W
    load_credentials(account_id) -> raw credentials file
    http_request(...), unwrap(), die(), print_json(), server_utc_ts_from_headers()
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error
import urllib.parse

# Skill root = the directory that contains scripts/_common.py
SKILL_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = SKILL_ROOT / "state.json"

CREDENTIALS_DIR = Path.home() / ".a9fund" / "accounts"
LEGACY_CONFIG_PATH = Path.home() / ".a9fund" / "config.json"

# Honest, self-identifying User-Agent (best practice for an API client). We do
# NOT send the anonymous urllib default: some edges / WAFs flag "Python-urllib"
# as a scraping-library signature. Override with the A9FUND_USER_AGENT env var.
import os


def _default_user_agent() -> str:
    try:
        ver = (SKILL_ROOT / "VERSION").read_text().strip()
    except OSError:
        ver = "unknown"
    return f"a9fund-skill/{ver}"


USER_AGENT = os.environ.get("A9FUND_USER_AGENT", _default_user_agent())

# Credential fields required for HTTP calls to work. The auth secret may be
# stored under either "token" or "api_key" (the A9Fund snippet labels it
# "API key"); `auth_secret()` accepts either.
CREDENTIAL_REQUIRED = ["exchange_account_id", "base_url_http"]

# Placeholders used only by legacy `config.py bootstrap` when the caller
# doesn't pass explicit URLs. The normal flow (STEP 2 terminal snippet +
# `config.py bind`) writes real URLs from the platform into
# ~/.a9fund/accounts/<id>.json and never consults these defaults.
DEFAULT_BASE_URLS = {
    "base_url_http": "https://<A9FUND_HOST>/api/v1",
    "base_url_ws_private": "wss://<A9FUND_HOST>/realtime_private",
    "base_url_ws_public": "wss://<A9FUND_HOST>/realtime_public",
}


# ---------------------------------------------------------------------------
# State (skill-local)
# ---------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    """Return the skill's state.json contents, or {} if absent."""
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError as e:
        die(f"Failed to parse {STATE_PATH}: {e}")


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Credentials (~/.a9fund/accounts/<id>.json)
# ---------------------------------------------------------------------------

def list_credential_account_ids() -> list[str]:
    """Return account_ids for every credential file under ~/.a9fund/accounts/."""
    if not CREDENTIALS_DIR.is_dir():
        return []
    return sorted(p.stem for p in CREDENTIALS_DIR.glob("*.json"))


def credential_path(account_id: str) -> Path:
    return CREDENTIALS_DIR / f"{account_id}.json"


def auth_secret(creds: dict[str, Any]) -> str:
    """Return the bearer secret, accepting either `api_key` or `token`."""
    return str(creds.get("api_key") or creds.get("token") or "")


def load_credentials(account_id: str) -> dict[str, Any]:
    """Read ~/.a9fund/accounts/<id>.json. Exit if missing or invalid."""
    path = credential_path(account_id)
    if not path.exists():
        die(
            f"Credentials not found: {path}\n"
            f"Paste the STEP 2 terminal snippet from the A9Fund account detail "
            f"page (/app/agent-api) to create it."
        )
    try:
        creds = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        die(f"Failed to parse {path}: {e}")
    missing = [k for k in CREDENTIAL_REQUIRED if not creds.get(k)]
    if not auth_secret(creds):
        missing.append("api_key/token")
    if missing:
        die(
            f"Credentials at {path} missing required fields: {missing}. "
            f"Re-paste the STEP 2 snippet to rewrite it."
        )
    return creds


def save_credentials(account_id: str, creds: dict[str, Any]) -> None:
    """Write ~/.a9fund/accounts/<id>.json (600 on Unix)."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    path = credential_path(account_id)
    path.write_text(json.dumps(creds, indent=2, ensure_ascii=False))
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows ACLs don't respect POSIX mode; home dir already restricts


# ---------------------------------------------------------------------------
# Merged config (what business scripts see)
# ---------------------------------------------------------------------------

def load_config() -> dict[str, Any]:
    """Return the merged config: credentials + state for the active account."""
    state = load_state()
    active_id = state.get("active_account_id")
    if not active_id:
        available = list_credential_account_ids()
        hint = f" Available credentials: {available}." if available else ""
        die(
            f"No active account bound to this skill.\n"
            f"Ask the user for their account id and run:\n"
            f"  python3 scripts/config.py bind --account-id <id>\n"
            f"First-time setup: A9Fund account detail page (/app/agent-api).{hint}"
        )

    creds = load_credentials(active_id)
    cfg: dict[str, Any] = {}
    cfg.update(creds)
    cfg.update({k: v for k, v in state.items() if k != "active_account_id"})
    cfg["exchange_account_id"] = active_id  # credentials file is authoritative
    cfg["_auth_secret"] = auth_secret(creds)
    return cfg


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def unwrap(parsed: Any) -> Any:
    """Return the payload regardless of envelope shape.

    Enveloped `{"code":0,"msg":"ok","data":{...}}` -> the `data` object.
    Bare `{...}` (A9Fund's published example shape)  -> the object itself.
    """
    if isinstance(parsed, dict) and "data" in parsed and (
        "code" in parsed or "msg" in parsed
    ):
        return parsed.get("data")
    return parsed


def http_request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    timeout: int = 30,
    return_headers: bool = False,
) -> Any:
    """Send an HTTP request to the A9Fund/propdesk API and return parsed JSON.

    - method: GET / POST / PUT / DELETE
    - path: API path starting with `/`, e.g. `/createOrder`
    - query: query string parameters
    - json_body: request body
    - cfg: config dict; loaded automatically if None
    - return_headers: if True, returns (parsed_body, response_headers_dict).
    """
    if cfg is None:
        cfg = load_config()

    base = cfg["base_url_http"].rstrip("/")
    url = base + path
    if query:
        q = {k: v for k, v in query.items() if v is not None and v != ""}
        if q:
            url += "?" + urllib.parse.urlencode(q)

    secret = cfg.get("_auth_secret") or auth_secret(cfg)
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        # Identify the client explicitly (see USER_AGENT above).
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    data = json.dumps(json_body).encode() if json_body is not None else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    response_headers: dict[str, str] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            response_headers = dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            err = json.loads(body)
        except json.JSONDecodeError:
            err = {"detail": body or e.reason}
        die(_format_http_error(e.code, err, method, url))
    except urllib.error.URLError as e:
        die(f"Network error calling {method} {url}: {e.reason}")

    if not body:
        parsed: Any = {}
    else:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as e:
            die(f"Response is not valid JSON: {e}\nRaw response: {body[:500]}")

    # Enveloped business error: {"code": <non-zero>, "msg": ...}
    if isinstance(parsed, dict) and parsed.get("code") not in (0, None):
        die(_format_business_error(parsed, method, url))

    if return_headers:
        return parsed, response_headers
    return parsed


def fetch_active_exchange(cfg: dict[str, Any] | None = None) -> str | None:
    """Call /market/metadata and return the server's `active_exchange`."""
    resp = http_request("GET", "/market/metadata", cfg=cfg)
    data = unwrap(resp) or {}
    if not isinstance(data, dict):
        return None
    active = data.get("active_exchange")
    if active:
        return active
    exchanges = data.get("exchanges") or []
    if exchanges:
        return exchanges[0].get("exchange")
    return None


def get_active_exchange(cfg: dict[str, Any] | None = None, *, refresh: bool = False) -> str | None:
    """Return the active_exchange, cached in state.json."""
    state = load_state()
    if not refresh:
        cached = state.get("active_exchange")
        if cached:
            return cached
    active = fetch_active_exchange(cfg=cfg)
    if active:
        state["active_exchange"] = active
        save_state(state)
    return active


def server_utc_ts_from_headers(response_headers: dict[str, str]) -> int:
    """Parse HTTP response `Date` header into a UTC unix timestamp (seconds)."""
    date_header = response_headers.get("Date") or response_headers.get("date")
    if date_header:
        try:
            dt = parsedate_to_datetime(date_header)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.astimezone(timezone.utc).timestamp())
        except (TypeError, ValueError) as e:
            print(
                f"warn: could not parse server Date header ({date_header!r}): {e}; "
                "falling back to local UTC clock",
                file=sys.stderr,
            )
    else:
        print(
            "warn: server response has no Date header; falling back to local UTC clock",
            file=sys.stderr,
        )
    return int(datetime.now(timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# Errors / output
# ---------------------------------------------------------------------------

def _err_message(err: dict) -> str:
    """Pull a human message out of either error shape (`detail` or `msg`)."""
    return str(err.get("detail") or err.get("msg") or "")


def _format_http_error(status: int, err: dict, method: str, url: str) -> str:
    code = err.get("code", status)
    msg = _err_message(err)
    hint = ""
    if status == 401 or code == 10002:
        hint = ("\n-> Auth failed. Re-paste the STEP 2 snippet from the A9Fund "
                "account detail page (/app/agent-api) to refresh credentials.")
    elif status == 403 or code == 10003:
        hint = ("\n-> Permission denied; the bound account may not be authorized "
                "for this API key. Run `python3 scripts/auth_check.py`.")
    elif status == 429 or code == 10008:
        hint = "\n-> Rate limit hit (max 5 orders per second per account). Slow down."
    return f"HTTP {status} on {method} {url}\n  code={code} msg={msg}{hint}"


def _format_business_error(parsed: dict, method: str, url: str) -> str:
    return (
        f"Business error on {method} {url}\n  "
        f"code={parsed.get('code')} msg={_err_message(parsed)}"
    )


def die(msg: str, exit_code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(exit_code)


def print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))

"""Manage the skill's state + account credentials.

Subcommands:
  show                              dump state.json + current credentials (redacted)
  list-accounts                     list available credential files
  bind --account-id <id>            bind the skill to an account:
                                      1) verify ~/.a9fund/accounts/<id>.json exists
                                      2) read mode/phase/initial_balance from
                                         /exchange-accounts (program_id + phase +
                                         baseline). Falls back to manual flags.
                                      3) write state.json
                                    Also used for "rebinding" (same command, new id).
  migrate                           move legacy ~/.a9fund/config.json into the new
                                    accounts/<id>.json + state.json layout

Legacy:
  bootstrap --api-key <...>         agent-driven first-time setup (secret passes
                                    through the agent). Prefer the terminal snippet
                                    + `bind` flow, which keeps the key out of chat.

Mode / phase model (A9Fund catalog, see references/challenge-rules.md):
  program_id -> mode:  starter_5k -> starter-5k, standard_25k -> standard-25k,
                       fast_10k -> fast-10k, ...
  account_phase:       "challenge" (Standard only) / "fund" (Starter, Fast, and
                       Standard after it passes). Leverage cap follows phase:
                       challenge 10x, fund 5x.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from _common import (
    CREDENTIALS_DIR,
    CREDENTIAL_REQUIRED,
    DEFAULT_BASE_URLS,
    LEGACY_CONFIG_PATH,
    STATE_PATH,
    auth_secret,
    credential_path,
    die,
    fetch_active_exchange,
    http_request,
    list_credential_account_ids,
    load_credentials,
    load_state,
    print_json,
    save_credentials,
    save_state,
    unwrap,
)

# Tracks recognised in A9Fund's catalog (catalog.py). Tier suffix is free-form
# (5k / 10k / 25k / 50k) so the skill keeps working if pricing tiers shift.
_KNOWN_TRACKS = ("starter", "standard", "fast")


def _mode_from_program_id(program_id: str) -> str | None:
    """Map a catalog program_id to a skill mode key.

    "starter_5k" -> "starter-5k", "standard_25k" -> "standard-25k",
    "fast_10k" -> "fast-10k". Returns None for unrecognised values so the
    caller can fall back to manual flags.
    """
    if not program_id:
        return None
    pid = program_id.strip().lower().replace("-", "_")
    parts = pid.split("_")
    if len(parts) >= 2 and parts[0] in _KNOWN_TRACKS:
        return f"{parts[0]}-{parts[1]}"
    return None


def _phase_default_for_track(track: str) -> str:
    """Starter/Fast are funded on purchase; Standard starts in challenge."""
    return "challenge" if track == "standard" else "fund"


def _tier_from_capital(capital) -> str | None:
    try:
        cap = float(capital)
    except (TypeError, ValueError):
        return None
    if cap <= 0:
        return None
    return f"{int(round(cap / 1000))}k"


def _infer_mode_from_risk(program_id: str, max_dd, capital) -> str | None:
    """Best-effort mode when the account carries no program_id.

    The A9Fund /exchange-accounts response has no program_id/sku, but the risk
    sub-object exposes the cumulative-loss red line, whose value is track-
    specific: Standard = 8%, Starter/Fast = 6%. Combine that with the capital
    tier to name the mode. Starter vs Fast at the same 6% line and same tier
    (only the $10k overlap) is genuinely ambiguous from this data -> returns
    None so the caller asks for --mode.
    """
    mode = _mode_from_program_id(program_id)
    if mode:
        return mode
    tier = _tier_from_capital(capital)
    if tier is None:
        return None
    try:
        dd = float(max_dd) if max_dd not in (None, "") else None
    except (TypeError, ValueError):
        dd = None
    if dd is not None and dd >= 7:          # 8% line -> Standard ($25k/$50k/$100k)
        return f"standard-{tier}"
    # 6% line -> Starter ($5k/$10k) or Fast ($10k/$25k/$50k)
    if tier == "5k":                         # only Starter is issued at $5k
        return f"starter-{tier}"
    if tier in ("25k", "50k"):               # at 6% line, $25k/$50k is Fast
        return f"fast-{tier}"
    return None                              # $10k @ 6% -> starter_10k vs fast_10k ambiguous


def _dig(obj: dict, *keys: str) -> Any:
    """Return the first present, non-empty value among top-level `keys`,
    also looking one level into common sub-objects (risk / aixfund / account).
    """
    for k in keys:
        if obj.get(k) not in (None, ""):
            return obj.get(k)
    for sub in ("aixfund", "risk", "account", "challenge"):
        child = obj.get(sub)
        if isinstance(child, dict):
            for k in keys:
                if child.get(k) not in (None, ""):
                    return child.get(k)
    return None


def _program_type_via_context(minimal_cfg: dict, account_id: str) -> str | None:
    """Exact program id from /event-contracts/context (`program_type`, e.g.
    "standard_50k"). This endpoint returns it even though /exchange-accounts
    does not. Best-effort — returns None if unavailable."""
    try:
        resp = http_request("GET", "/event-contracts/context",
                            query={"account_id": account_id}, cfg=minimal_cfg)
    except SystemExit:
        return None
    data = unwrap(resp)
    if isinstance(data, dict):
        pt = data.get("program_type")
        if not pt and isinstance(data.get("event_contract"), dict):
            pt = data["event_contract"].get("program_type")
        return pt or None
    return None


def _find_account(minimal_cfg: dict, account_id: str) -> dict | None:
    """Locate the account object in /exchange-accounts, tolerant of envelope
    and key naming (exchange_accounts / accounts / bare list)."""
    resp = http_request("GET", "/exchange-accounts", cfg=minimal_cfg)
    data = unwrap(resp)
    accounts: list = []
    if isinstance(data, dict):
        accounts = data.get("exchange_accounts") or data.get("accounts") or []
    elif isinstance(data, list):
        accounts = data
    for a in accounts:
        if str(a.get("exchange_account_id") or a.get("id")) == str(account_id):
            return a
    return None


def _infer_mode_phase_balance(secret: str, base_url_http: str, account_id: str
                              ) -> tuple[str | None, str | None, int | None]:
    """Derive (mode, phase, initial_balance) from /exchange-accounts.

    Returns Nones where a field can't be resolved so the caller can prompt for
    manual flags rather than guess.
    """
    minimal_cfg = {
        "api_key": secret,
        "base_url_http": base_url_http,
        "exchange_account_id": account_id,
    }
    acc = _find_account(minimal_cfg, account_id)
    if acc is None:
        return None, None, None

    program_id = _dig(acc, "program_id", "sku", "program") or ""
    # /exchange-accounts carries no program_id today; the event-contracts
    # context endpoint does (`program_type`). Prefer that exact value, then
    # fall back to inferring the track from the risk drawdown signature.
    if not _mode_from_program_id(str(program_id)):
        pt = _program_type_via_context(minimal_cfg, account_id)
        if pt:
            program_id = pt
    baseline = _dig(acc, "baseline_equity", "initial_capital", "initial_balance")
    max_dd = _dig(acc, "max_drawdown_pct")  # from the risk sub-object via _dig
    mode = _infer_mode_from_risk(str(program_id), max_dd, baseline)

    phase = _dig(acc, "account_phase", "phase")
    phase = str(phase).lower() if phase else None
    if not phase and mode:
        phase = _phase_default_for_track(mode.split("-")[0])

    try:
        initial_balance = int(float(baseline)) if baseline not in (None, "") else None
    except (TypeError, ValueError):
        initial_balance = None

    return mode, phase, initial_balance


def _redact(secret: str) -> str:
    if not secret or len(secret) < 12:
        return "***"
    return f"{secret[:6]}...{secret[-4:]}"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_show(_args) -> None:
    out: dict[str, Any] = {
        "skill_state_path": str(STATE_PATH),
        "credentials_dir": str(CREDENTIALS_DIR),
        "available_accounts": list_credential_account_ids(),
    }
    state: dict[str, Any] = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError) as e:
            out["state"] = None
            out["state_error"] = f"{type(e).__name__}: {e}"
            out["recovery_hint"] = (
                "Delete state.json and rebind: "
                "`python3 scripts/config.py bind --account-id <id>`."
            )
            print_json(out)
            return

    out["state"] = state
    active_id = state.get("active_account_id")
    if active_id:
        try:
            creds = load_credentials(active_id)
            redacted = {**creds}
            for k in ("api_key", "token"):
                if redacted.get(k):
                    redacted[k] = _redact(str(redacted[k]))
            out["active_credentials"] = redacted
        except SystemExit:
            out["active_credentials"] = f"<missing file for {active_id}>"
    print_json(out)


def cmd_list_accounts(_args) -> None:
    print_json({
        "available_accounts": list_credential_account_ids(),
        "active_account_id": load_state().get("active_account_id"),
    })


def cmd_bind(args) -> None:
    """Bind the skill to an account (first-time setup OR switching accounts)."""
    account_id = str(args.account_id)
    creds = load_credentials(account_id)  # exits if missing
    secret = auth_secret(creds)

    mode, phase, initial_balance = args.mode, args.phase, args.initial_balance
    if not args.skip_lookup:
        got_mode, got_phase, got_balance = _infer_mode_phase_balance(
            secret=secret, base_url_http=creds["base_url_http"], account_id=account_id,
        )
        mode = mode or got_mode
        phase = phase or got_phase
        initial_balance = initial_balance if initial_balance is not None else got_balance

    if not mode:
        die(
            "Could not determine the account's mode from /exchange-accounts.\n"
            "Set it explicitly:\n"
            "  python3 config.py bind --account-id <id> --skip-lookup \\\n"
            "    --mode <starter-5k|starter-10k|standard-25k|standard-50k|fast-10k|fast-25k> \\\n"
            "    --phase <challenge|fund> --initial-balance <amount>"
        )
    if not phase:
        phase = _phase_default_for_track(mode.split("-")[0])

    prev = load_state()
    prev_active = prev.get("active_account_id")
    rebinding = prev_active and prev_active != account_id

    new_state: dict[str, Any] = {
        "active_account_id": account_id,
        "mode": mode,
        "phase": phase,
        "initial_balance": initial_balance,
    }

    # Best-effort cache of active_exchange; never block bind on it.
    try:
        active_exchange = fetch_active_exchange(cfg={
            "api_key": secret, "base_url_http": creds["base_url_http"],
            "exchange_account_id": account_id,
        })
        if active_exchange:
            new_state["active_exchange"] = active_exchange
    except SystemExit:
        pass

    save_state(new_state)

    action = "Rebound" if rebinding else "Bound"
    print(f"{action} skill to account {account_id} "
          f"(mode={mode}, phase={phase}, initial_balance={initial_balance})",
          file=sys.stderr)
    if rebinding:
        print(f"  (previous active: {prev_active})", file=sys.stderr)
    print_json({"state": new_state, "skill_state_path": str(STATE_PATH)})


def cmd_migrate(_args) -> None:
    """Move legacy ~/.a9fund/config.json into the new layout."""
    if not LEGACY_CONFIG_PATH.exists():
        die(f"No legacy file at {LEGACY_CONFIG_PATH}; nothing to migrate.")
    try:
        legacy = json.loads(LEGACY_CONFIG_PATH.read_text())
    except json.JSONDecodeError as e:
        die(f"Failed to parse {LEGACY_CONFIG_PATH}: {e}")

    account_id = str(legacy.get("exchange_account_id") or "").strip()
    if not account_id:
        die("Legacy config lacks exchange_account_id; cannot migrate.")

    creds = {
        "api_key": auth_secret(legacy),
        "exchange_account_id": account_id,
        "base_url_http": legacy.get("base_url_http") or DEFAULT_BASE_URLS["base_url_http"],
        "base_url_ws_private": legacy.get("base_url_ws_private") or DEFAULT_BASE_URLS["base_url_ws_private"],
        "base_url_ws_public": legacy.get("base_url_ws_public") or DEFAULT_BASE_URLS["base_url_ws_public"],
    }
    missing = [k for k in CREDENTIAL_REQUIRED if not creds.get(k)]
    if not auth_secret(creds):
        missing.append("api_key/token")
    if missing:
        die(f"Legacy config missing {missing}; cannot migrate.")
    save_credentials(account_id, creds)

    state: dict[str, Any] = {"active_account_id": account_id}
    for k in ("mode", "phase", "initial_balance"):
        if legacy.get(k) is not None:
            state[k] = legacy[k]
    save_state(state)

    backup = LEGACY_CONFIG_PATH.with_suffix(".json.migrated")
    LEGACY_CONFIG_PATH.rename(backup)
    print(f"Migrated legacy {LEGACY_CONFIG_PATH.name} -> credentials + state. "
          f"Backup at {backup}.", file=sys.stderr)
    print_json({
        "credentials_path": str(credential_path(account_id)),
        "state_path": str(STATE_PATH),
        "state": state,
    })


def cmd_bootstrap(args) -> None:
    """Agent-driven first-time setup (secret passes through the agent)."""
    secret = args.api_key
    base_urls = DEFAULT_BASE_URLS
    minimal_cfg = {"api_key": secret, **base_urls}
    acc = None
    if args.exchange_account_id:
        acc = _find_account(minimal_cfg, args.exchange_account_id)
        if acc is None:
            die(f"--exchange-account-id {args.exchange_account_id} not authorized for this key.")
        account_id = str(args.exchange_account_id)
    else:
        resp = http_request("GET", "/exchange-accounts", cfg=minimal_cfg)
        data = unwrap(resp)
        accounts = (data.get("exchange_accounts") or data.get("accounts") or []) if isinstance(data, dict) else (data or [])
        if not accounts:
            die("Key is valid but no exchange accounts are authorized for it.")
        if len(accounts) > 1:
            listing = "\n".join(f"  - {a.get('exchange_account_id') or a.get('id')}" for a in accounts)
            die(f"Multiple accounts authorized; pass --exchange-account-id:\n{listing}")
        account_id = str(accounts[0].get("exchange_account_id") or accounts[0].get("id"))

    save_credentials(account_id, {"api_key": secret, "exchange_account_id": account_id, **base_urls})
    cmd_bind(argparse.Namespace(
        account_id=account_id, skip_lookup=False, mode=None, phase=None, initial_balance=None,
    ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Manage the A9Fund skill state + account credentials")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show").set_defaults(func=cmd_show)
    sub.add_parser("list-accounts").set_defaults(func=cmd_list_accounts)

    sp_bind = sub.add_parser("bind", help="Bind (or rebind) the skill to an account.")
    sp_bind.add_argument("--account-id", required=True)
    sp_bind.add_argument("--skip-lookup", action="store_true",
                         help="Don't call /exchange-accounts; requires --mode")
    sp_bind.add_argument("--mode", help="e.g. standard-25k (used with --skip-lookup, or to override)")
    sp_bind.add_argument("--phase", choices=["challenge", "fund"], help="Override account phase")
    sp_bind.add_argument("--initial-balance", type=int, help="Funded baseline (USDT)")
    sp_bind.set_defaults(func=cmd_bind)

    sub.add_parser("migrate",
                   help="Move legacy ~/.a9fund/config.json into accounts/<id>.json + state.json"
                   ).set_defaults(func=cmd_migrate)

    sp_boot = sub.add_parser("bootstrap", help="Legacy agent-driven first-time setup.")
    sp_boot.add_argument("--api-key", required=True)
    sp_boot.add_argument("--exchange-account-id", default=None)
    sp_boot.set_defaults(func=cmd_bootstrap)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

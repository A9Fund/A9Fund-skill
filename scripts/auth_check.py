"""GET /exchange-accounts: validate the API key and list authorized accounts.

Output JSON: {"valid": true, "current_exchange_account_id": ..., "accounts": [...]}
"""
from __future__ import annotations

from _common import http_request, load_config, print_json, unwrap


def main() -> None:
    cfg = load_config()
    data = unwrap(http_request("GET", "/exchange-accounts", cfg=cfg))
    if isinstance(data, dict):
        accounts = data.get("exchange_accounts") or data.get("accounts") or []
    else:
        accounts = data or []
    print_json({
        "valid": True,
        "current_exchange_account_id": cfg.get("exchange_account_id"),
        "accounts": accounts,
    })


if __name__ == "__main__":
    main()

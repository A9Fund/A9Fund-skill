"""POST /setLeverage.

Caps follow the account PHASE (A9Fund catalog: CHALLENGE_MAX_LEVERAGE=10,
FUND_MAX_LEVERAGE=5):
  challenge phase (Standard pre-pass): 10X
  fund phase (Starter, Fast, passed Standard): 5X

The cap is enforced for real by propdesk at order time (this backend is not on
the trade path), so this client check is a courtesy guard. When the bound
phase is unknown it defaults to the looser challenge cap and lets propdesk be
the authority. Trust the value propdesk accepts at order time.
"""
from __future__ import annotations

import argparse

from _common import die, http_request, load_config, print_json, unwrap

CHALLENGE_MAX_LEVERAGE = 10
FUND_MAX_LEVERAGE = 5


def main() -> None:
    p = argparse.ArgumentParser(description="Set leverage")
    p.add_argument("--symbol", required=True)
    p.add_argument("--leverage", type=int, required=True)
    p.add_argument("--margin-mode", default="CROSS", choices=["CROSS", "ISOLATED"])
    args = p.parse_args()

    cfg = load_config()
    phase = str(cfg.get("phase", "")).lower()
    if phase == "fund":
        max_lev, stage = FUND_MAX_LEVERAGE, "Fund"
    else:
        max_lev, stage = CHALLENGE_MAX_LEVERAGE, "Challenge"

    if args.leverage > max_lev:
        die(f"Leverage {args.leverage} exceeds the {stage}-phase cap of {max_lev}X "
            f"(current phase={phase or 'unknown'}). propdesk enforces this at order time.")

    body = {
        "exchange_account_id": cfg["exchange_account_id"],
        "symbol": args.symbol,
        "leverage": args.leverage,
        "margin_mode": args.margin_mode,
    }
    print_json(unwrap(http_request("POST", "/setLeverage", json_body=body, cfg=cfg)))


if __name__ == "__main__":
    main()

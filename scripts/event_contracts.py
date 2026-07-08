"""Event Contracts (prediction market) -- A9Fund-only feature.

A binary-style contract: pick a direction (UP/DOWN) on a symbol over a fixed
duration; a fixed 80% payout on a win, lose the premium otherwise.

Typical flow (see references/event-contracts.md):
  1. context   GET  /event-contracts/context?account_id=<id>
  2. catalog   GET  /event-contracts/catalog?account_id=<id>
  3. quote     POST /event-contracts/quote
  4. order     POST /event-contracts/orders
  5. list      GET  /event-contracts/orders?account_id=<id>&status=all&page=1&page_size=20
  6. detail    GET  /event-contracts/orders/{order_id}?account_id=<id>

Input whitelist enforced by the backend (service.py):
  symbol    ∈ {BTCUSDT, ETHUSDT}
  direction ∈ {UP, DOWN}
  duration  ∈ {10m, 30m, 1h, 1d}
  premium   > 0
Activation: the account's event-contract profit only counts toward passing
after 6 settled (WIN/LOSS) contracts. Any open/disputed contract blocks
challenge pass and payout.

NOTE: event-contract endpoints scope by `account_id` (NOT exchange_account_id).
The quote/order request bodies are assembled from documented fields; if the
backend expects different names, use api.py with an explicit --json body.
"""
from __future__ import annotations

import argparse
import json

from _common import die, http_request, load_config, print_json, unwrap

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
DIRECTIONS = ["UP", "DOWN"]
DURATIONS = ["10m", "30m", "1h", "1d"]


def _merge_extra(body: dict, extra: str | None) -> dict:
    if extra:
        try:
            body.update(json.loads(extra))
        except json.JSONDecodeError as e:
            die(f"Failed to parse --extra: {e}")
    return body


def cmd_context(_args, cfg):
    print_json(unwrap(http_request("GET", "/event-contracts/context",
               query={"account_id": cfg["exchange_account_id"]}, cfg=cfg)))


def cmd_catalog(_args, cfg):
    print_json(unwrap(http_request("GET", "/event-contracts/catalog",
               query={"account_id": cfg["exchange_account_id"]}, cfg=cfg)))


def cmd_quote(args, cfg):
    if float(args.premium) <= 0:
        die("--premium must be > 0.")
    body = _merge_extra({
        "account_id": cfg["exchange_account_id"],
        "symbol": args.symbol,
        "direction": args.direction,
        "duration": args.duration,
        "premium": args.premium,
    }, args.extra)
    print_json(unwrap(http_request("POST", "/event-contracts/quote", json_body=body, cfg=cfg)))


def cmd_order(args, cfg):
    if float(args.premium) <= 0:
        die("--premium must be > 0.")
    body = {
        "account_id": cfg["exchange_account_id"],
        "symbol": args.symbol,
        "direction": args.direction,
        "duration": args.duration,
        "premium": args.premium,
    }
    if args.quote_id:
        body["quote_id"] = args.quote_id
    body = _merge_extra(body, args.extra)
    print_json(unwrap(http_request("POST", "/event-contracts/orders", json_body=body, cfg=cfg)))


def cmd_list(args, cfg):
    q = {"account_id": cfg["exchange_account_id"], "status": args.status,
         "page": args.page, "page_size": args.page_size}
    print_json(unwrap(http_request("GET", "/event-contracts/orders", query=q, cfg=cfg)))


def cmd_detail(args, cfg):
    print_json(unwrap(http_request("GET", f"/event-contracts/orders/{args.order_id}",
               query={"account_id": cfg["exchange_account_id"]}, cfg=cfg)))


def main() -> None:
    p = argparse.ArgumentParser(description="Event Contracts (prediction market)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("context").set_defaults(func=cmd_context)
    sub.add_parser("catalog").set_defaults(func=cmd_catalog)

    for name in ("quote", "order"):
        sp = sub.add_parser(name)
        sp.add_argument("--symbol", required=True, choices=SYMBOLS)
        sp.add_argument("--direction", required=True, choices=DIRECTIONS)
        sp.add_argument("--duration", required=True, choices=DURATIONS)
        sp.add_argument("--premium", required=True, help="Stake amount (USDT, > 0)")
        sp.add_argument("--extra", default=None, help="Extra body fields as JSON to merge")
        if name == "order":
            sp.add_argument("--quote-id", default=None, help="quote_id returned by `quote`")
            sp.set_defaults(func=cmd_order)
        else:
            sp.set_defaults(func=cmd_quote)

    sp = sub.add_parser("list")
    sp.add_argument("--status", default="all")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--page-size", type=int, default=20)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("detail"); sp.add_argument("--order-id", required=True); sp.set_defaults(func=cmd_detail)

    args = p.parse_args()
    cfg = load_config()
    args.func(args, cfg)


if __name__ == "__main__":
    main()

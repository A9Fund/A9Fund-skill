"""Cancel regular orders.

  --order-id <id> --symbol <sym>   POST /cancelOrder  (single)
  --all           --symbol <sym>   POST /cancelOrders (batch by symbol)

This handles REGULAR (LIMIT/MARKET) orders. To cancel a standalone
conditional order (STOP / TAKE_PROFIT trigger order created via
conditional_order.py), use `conditional_order.py cancel --id <id>` which hits
DELETE /conditional-orders/{id}.
"""
from __future__ import annotations

import argparse

from _common import http_request, load_config, print_json, unwrap


def main() -> None:
    p = argparse.ArgumentParser(description="Cancel a regular order or all orders for a symbol")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--order-id", help="exchange_order_id (single cancel)")
    g.add_argument("--all", action="store_true", help="Cancel all orders for the given symbol")
    p.add_argument("--symbol", required=True)
    p.add_argument("--trace-id", default="")
    args = p.parse_args()

    cfg = load_config()

    if args.all:
        body = {"exchange_account_id": cfg["exchange_account_id"], "symbol": args.symbol}
        resp = http_request("POST", "/cancelOrders", json_body=body, cfg=cfg)
    else:
        body = {
            "exchange_account_id": cfg["exchange_account_id"],
            "exchange_order_id": args.order_id,
            "trace_id": args.trace_id or args.order_id,
            "symbol": args.symbol,
        }
        resp = http_request("POST", "/cancelOrder", json_body=body, cfg=cfg)

    print_json(unwrap(resp))


if __name__ == "__main__":
    main()

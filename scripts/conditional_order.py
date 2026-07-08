"""Standalone conditional (trigger) orders -- the dedicated A9Fund resource.

Unlike attached TP/SL (place_order.py --tp-price/--sl-price, an OCO pair on an
entry), a standalone conditional order rests in its own queue until its trigger
fires, then submits a LIMIT/MARKET order. After it triggers, the resulting
regular order is linked via `triggered_order_id`.

Subcommands:
  create   POST   /conditional-orders
  list     GET    /conditional-orders           [--symbol]
  history  GET    /conditional-orders/history   [--symbol] [--page] [--limit]
  cancel   DELETE /conditional-orders/{id}

Create example (stop-entry long on ETH):
  python3 conditional_order.py create --symbol ETH-USDT --side BUY --size 1 \\
      --trigger-price 1582.77 --trigger-direction GTE \\
      --trigger-order-type LIMIT --order-price 1583
"""
from __future__ import annotations

import argparse
import time
import uuid

from _common import die, http_request, load_config, print_json, unwrap


def cmd_create(args, cfg):
    if args.trigger_order_type == "LIMIT" and not args.order_price:
        die("--order-price is required when --trigger-order-type is LIMIT.")

    body = {
        "exchange_account_id": cfg["exchange_account_id"],
        "symbol": args.symbol,
        "side": args.side,
        "size": args.size,
        "trigger_price": args.trigger_price,
        "trigger_price_type": args.trigger_price_type,
        "trigger_direction": args.trigger_direction,
        "trigger_order_type": args.trigger_order_type,
        "order_price": args.order_price,
        "reduce_only": args.reduce_only,
        "trace_id": args.trace_id or f"cond-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
        "is_open_tpsl_order": bool(args.tp_price or args.sl_price),
        "is_set_open_tp": bool(args.tp_price),
        "is_set_open_sl": bool(args.sl_price),
    }
    if args.tp_price:
        body["open_tp_param"] = {"trigger_price": args.tp_price, "trigger_price_type": args.tpsl_trigger_type}
    if args.sl_price:
        body["open_sl_param"] = {"trigger_price": args.sl_price, "trigger_price_type": args.tpsl_trigger_type}

    resp = http_request("POST", "/conditional-orders", json_body=body, cfg=cfg)
    print_json(unwrap(resp))


def cmd_list(args, cfg):
    q = {"exchange_account_id": cfg["exchange_account_id"]}
    if args.symbol:
        q["symbol"] = args.symbol
    resp = http_request("GET", "/conditional-orders", query=q, cfg=cfg)
    print_json(unwrap(resp))


def cmd_history(args, cfg):
    q = {"exchange_account_id": cfg["exchange_account_id"]}
    for k, v in (("symbol", args.symbol), ("page", args.page), ("limit", args.limit)):
        if v not in (None, ""):
            q[k] = v
    resp = http_request("GET", "/conditional-orders/history", query=q, cfg=cfg)
    print_json(unwrap(resp))


def cmd_cancel(args, cfg):
    # account id passed as a query param alongside the path id, since other
    # A9Fund endpoints scope by exchange_account_id.
    q = {"exchange_account_id": cfg["exchange_account_id"]}
    resp = http_request("DELETE", f"/conditional-orders/{args.id}", query=q, cfg=cfg)
    print_json(unwrap(resp))


def main() -> None:
    p = argparse.ArgumentParser(description="Standalone conditional (trigger) orders")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("create")
    sc.add_argument("--symbol", required=True)
    sc.add_argument("--side", required=True, choices=["BUY", "SELL"])
    sc.add_argument("--size", required=True)
    sc.add_argument("--trigger-price", required=True)
    sc.add_argument("--trigger-price-type", default="MARKET", choices=["INDEX", "MARKET", "MARK"])
    sc.add_argument("--trigger-direction", required=True, choices=["GTE", "LTE"],
                    help="GTE = fire when price rises to/above trigger; LTE = falls to/below")
    sc.add_argument("--trigger-order-type", default="MARKET", choices=["LIMIT", "MARKET"])
    sc.add_argument("--order-price", default="", help="Required for LIMIT trigger_order_type")
    sc.add_argument("--reduce-only", action="store_true")
    sc.add_argument("--trace-id", default="")
    sc.add_argument("--tp-price", default="", help="Optional attached take-profit trigger price")
    sc.add_argument("--sl-price", default="", help="Optional attached stop-loss trigger price")
    sc.add_argument("--tpsl-trigger-type", default="MARK", choices=["INDEX", "MARKET", "MARK"])
    sc.set_defaults(func=cmd_create)

    sl = sub.add_parser("list"); sl.add_argument("--symbol"); sl.set_defaults(func=cmd_list)

    sh = sub.add_parser("history")
    sh.add_argument("--symbol"); sh.add_argument("--page", type=int); sh.add_argument("--limit", type=int)
    sh.set_defaults(func=cmd_history)

    scx = sub.add_parser("cancel"); scx.add_argument("--id", required=True); scx.set_defaults(func=cmd_cancel)

    args = p.parse_args()
    cfg = load_config()
    args.func(args, cfg)


if __name__ == "__main__":
    main()

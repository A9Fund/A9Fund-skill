"""POST /createOrder -- regular MARKET / LIMIT order, optional attached TP/SL.

- exchange_account_id is auto-injected from config.
- client_order_id auto-generated as agent-{ms}-{uuid8} when not supplied.

Attached TP/SL (A9Fund shape): pass --tp-price / --sl-price. This sets
`is_open_tpsl_order=true` and builds `open_tp_param` / `open_sl_param`
objects `{trigger_price, trigger_price_type}`. The two legs are managed as an
OCO pair (one triggers -> the other auto-cancels).

Standalone STOP / TAKE_PROFIT trigger orders use the dedicated
`/conditional-orders` resource -- see conditional_order.py, NOT this script.

Reasoning: OPTIONAL on A9Fund. The account-level API does not require a
per-order rationale ("API 订单不需要提交额外推理说明"). Pass --reasoning to
attach one anyway (some agent-graded programs still sample it); it is only
validated for length, never required. Max 4096 bytes UTF-8.
"""
from __future__ import annotations

import argparse
import time
import uuid

from _common import die, http_request, load_config, print_json, unwrap

REASONING_MAX_BYTES = 4096


def main() -> None:
    p = argparse.ArgumentParser(description="Place a MARKET/LIMIT order (optional attached TP/SL)")
    p.add_argument("--symbol", required=True, help="e.g. BTC-USDT")
    p.add_argument("--side", required=True, choices=["BUY", "SELL"])
    p.add_argument("--order-type", required=True, choices=["MARKET", "LIMIT"])
    p.add_argument("--size", required=True, help="Quantity (string)")
    p.add_argument("--price", default="", help="Price (required for LIMIT)")
    p.add_argument("--tif", default=None, choices=[None, "GTC", "FOK", "IOC", "POST_ONLY"])
    p.add_argument("--reduce-only", action="store_true")
    p.add_argument("--client-order-id", default=None)
    # Attach TP / SL to this opening order.
    p.add_argument("--tp-price", default="", help="Take-profit trigger price attached to this order")
    p.add_argument("--sl-price", default="", help="Stop-loss trigger price attached to this order")
    p.add_argument("--tpsl-trigger-type", default="MARK",
                   choices=["INDEX", "MARKET", "MARK"],
                   help="Trigger reference for attached TP/SL (default MARK; ORACLE not supported)")
    p.add_argument("--reasoning", default="",
                   help="OPTIONAL rationale for this order (max 4096 bytes UTF-8). "
                        "Not required by A9Fund; attached only if provided.")
    args = p.parse_args()

    if args.order_type == "LIMIT" and not args.price:
        die("--price is required for LIMIT orders.")

    reasoning_text = (args.reasoning or "").strip()
    if reasoning_text and len(reasoning_text.encode("utf-8")) > REASONING_MAX_BYTES:
        die(f"--reasoning is over {REASONING_MAX_BYTES} bytes (UTF-8). Shorten it and retry.")

    cfg = load_config()
    cid = args.client_order_id or f"agent-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

    tp_on, sl_on = bool(args.tp_price), bool(args.sl_price)
    body = {
        "exchange_account_id": cfg["exchange_account_id"],
        "client_order_id": cid,
        "symbol": args.symbol,
        "side": args.side,
        "size": args.size,
        "price": args.price,
        "order_type": args.order_type,
        "time_in_force": args.tif or ("GTC" if args.order_type == "LIMIT" else ""),
        "reduce_only": args.reduce_only,
        # createOrder attaches TP/SL via the boolean flags + FLAT trigger fields
        # (verified against the live API: the open_tp_param/open_sl_param object
        # form the UI table shows is NOT accepted here — createOrder wants
        # tp_trigger_price / sl_trigger_price). Sending only the flags returns
        # 10001 "tp_trigger_price is required when is_set_open_tp=true".
        "is_open_tpsl_order": tp_on or sl_on,
        "is_set_open_tp": tp_on,
        "is_set_open_sl": sl_on,
        "tp_trigger_price": args.tp_price if tp_on else "",
        "tp_trigger_price_type": args.tpsl_trigger_type if tp_on else "",
        "sl_trigger_price": args.sl_price if sl_on else "",
        "sl_trigger_price_type": args.tpsl_trigger_type if sl_on else "",
    }
    if reasoning_text:
        body["reasoning"] = reasoning_text

    resp = http_request("POST", "/createOrder", json_body=body, cfg=cfg)
    print_json(unwrap(resp))


if __name__ == "__main__":
    main()

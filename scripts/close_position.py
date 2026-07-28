"""Close an existing position with a market reduce-only order.

Queries /positions for the given symbol (or all if --all), derives side +
size, and sends the opposite-side MARKET reduce-only order via /createOrder.

Reasoning is OPTIONAL on A9Fund (see place_order.py). Pass --reasoning to
attach one; it is not required.

Cleans up stale TP/SL legs after closing: standalone conditional orders
(created via conditional_order.py / set-position-tpsl) are NOT OCO-paired with
each other -- only attached entry-time TP/SL is a true OCO pair. If a
position is closed some other way (market close, one leg triggering) while
its sibling TP/SL leg is still
resting, that leg stays active and could misfire later -- e.g. against a
future, unrelated position opened on the same symbol. After each successful
close, this script cancels any remaining active reduce_only conditional orders
on that symbol whose side matches the position that was just closed. Pass
`--keep-tpsl` to skip this (e.g. if you're closing part of a position and
intentionally want to keep protection on the rest -- though note this script
always closes the FULL position, so that's rarely the right call).
"""
from __future__ import annotations

import argparse
import time
import uuid

from _common import die, http_request, load_config, print_json, unwrap


def fetch_positions(cfg, symbol: str | None) -> list[dict]:
    q = {"exchange_account_id": cfg["exchange_account_id"]}
    if symbol:
        q["symbol"] = symbol
    resp = http_request("GET", "/positions", query=q, cfg=cfg)
    data = unwrap(resp)
    positions = data.get("positions") if isinstance(data, dict) else data
    out = []
    for p in (positions or []):
        qty = p.get("quantity", p.get("size", 0))
        try:
            if float(qty or 0) > 0:
                out.append(p)
        except (TypeError, ValueError):
            continue
    return out


def _cleanup_stale_tpsl(cfg, symbol: str, closing_side: str) -> list[str]:
    """Cancel active conditional orders on `symbol` matching `closing_side`.

    These are leftover standalone TP/SL legs from before this close -- since
    they're not OCO'd against each other, the one that didn't trigger (or
    wasn't otherwise touched) would otherwise keep resting indefinitely.
    """
    resp = http_request("GET", "/conditional-orders",
                        query={"exchange_account_id": cfg["exchange_account_id"], "symbol": symbol}, cfg=cfg)
    data = unwrap(resp)
    orders = (data.get("conditional_orders") or data.get("orders")) if isinstance(data, dict) else data
    cancelled = []
    for o in (orders or []):
        if str(o.get("side", "")).upper() != closing_side:
            continue
        oid = o.get("condition_order_id") or o.get("order_id")
        if not oid:
            continue
        http_request("DELETE", f"/conditional-orders/{oid}",
                    query={"exchange_account_id": cfg["exchange_account_id"]}, cfg=cfg)
        cancelled.append(oid)
    return cancelled


def close_one(cfg, pos: dict, reasoning: str, keep_tpsl: bool) -> dict:
    side = "SELL" if str(pos["side"]).upper() == "LONG" else "BUY"
    size = pos.get("quantity", pos.get("size"))
    symbol = pos["symbol"]

    body = {
        "exchange_account_id": cfg["exchange_account_id"],
        "client_order_id": f"agent-close-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
        "symbol": symbol,
        "side": side,
        "size": size,
        "price": "",
        "order_type": "MARKET",
        "time_in_force": "",
        "reduce_only": True,
        "is_open_tpsl_order": False,
    }
    if reasoning:
        body["reasoning"] = reasoning
    resp = http_request("POST", "/createOrder", json_body=body, cfg=cfg)

    out = {"symbol": symbol, "side": side, "size": size, "result": unwrap(resp)}
    if not keep_tpsl:
        out["cancelled_stale_tpsl"] = _cleanup_stale_tpsl(cfg, symbol, closing_side=side)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Close position(s) via market reduce-only order")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="Close the position for this symbol")
    g.add_argument("--all", action="store_true", help="Close every open position")
    p.add_argument("--reasoning", default="", help="OPTIONAL rationale (max 4096 bytes UTF-8).")
    p.add_argument("--keep-tpsl", action="store_true",
                   help="Don't cancel remaining standalone TP/SL legs on the symbol after closing.")
    p.add_argument("--account-id", default=None,
                   help="Assert the bound account before closing (guards state drift; also A9FUND_ACCOUNT_ID).")
    args = p.parse_args()

    reasoning_text = (args.reasoning or "").strip()
    if reasoning_text and len(reasoning_text.encode("utf-8")) > 4096:
        die("--reasoning exceeds 4096 bytes (UTF-8). Shorten it and retry.")

    cfg = load_config(expected_account_id=args.account_id)
    positions = fetch_positions(cfg, None if args.all else args.symbol)
    if not positions:
        die("No open position to close." if args.symbol else "No open positions.")

    results = [close_one(cfg, pos, reasoning_text, args.keep_tpsl) for pos in positions]
    print_json(results if len(results) > 1 else results[0])


if __name__ == "__main__":
    main()

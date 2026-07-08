"""Close an existing position with a market reduce-only order.

Queries /positions for the given symbol (or all if --all), derives side +
size, and sends the opposite-side MARKET reduce-only order via /createOrder.

Reasoning is OPTIONAL on A9Fund (see place_order.py). Pass --reasoning to
attach one; it is not required.
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


def close_one(cfg, pos: dict, reasoning: str) -> dict:
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
    return {"symbol": symbol, "side": side, "size": size, "result": unwrap(resp)}


def main() -> None:
    p = argparse.ArgumentParser(description="Close position(s) via market reduce-only order")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="Close the position for this symbol")
    g.add_argument("--all", action="store_true", help="Close every open position")
    p.add_argument("--reasoning", default="", help="OPTIONAL rationale (max 4096 bytes UTF-8).")
    args = p.parse_args()

    reasoning_text = (args.reasoning or "").strip()
    if reasoning_text and len(reasoning_text.encode("utf-8")) > 4096:
        die("--reasoning exceeds 4096 bytes (UTF-8). Shorten it and retry.")

    cfg = load_config()
    positions = fetch_positions(cfg, None if args.all else args.symbol)
    if not positions:
        die("No open position to close." if args.symbol else "No open positions.")

    results = [close_one(cfg, pos, reasoning_text) for pos in positions]
    print_json(results if len(results) > 1 else results[0])


if __name__ == "__main__":
    main()

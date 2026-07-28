"""Standalone conditional (trigger) orders -- the dedicated A9Fund resource.

Unlike attached TP/SL (place_order.py --tp-price/--sl-price, an OCO pair on an
entry), a standalone conditional order rests in its own queue until its trigger
fires, then submits a LIMIT/MARKET order. After it triggers, the resulting
regular order is linked via `triggered_order_id`.

Two easily-confused views (different endpoints):
  * conditional_order.py list  -> GET /conditional-orders  = ACTIVE standalone
    conditional orders only (UNTRIGGERED).
  * query.py condition-orders  -> GET /conditionOrders      = MIXED view incl.
    history (TRIGGERED / CANCELED) and attached TP/SL legs.
  Use `list` (or `history`) here for the standalone-conditional lifecycle;
  use `query.py condition-orders` for the full/historical picture.

Subcommands:
  create             POST   /conditional-orders
  list               GET    /conditional-orders           [--symbol]   (active / UNTRIGGERED)
  history            GET    /conditional-orders/history   [--symbol] [--page] [--limit]
  cancel             DELETE /conditional-orders/{id}
  set-position-tpsl  Set/replace TP/SL for an ALREADY-OPEN position (see below)

Create example (stop-entry long on ETH):
  python3 conditional_order.py create --symbol ETH-USDT --side BUY --size 1 \\
      --trigger-price 1582.77 --trigger-direction GTE \\
      --trigger-order-type LIMIT --order-price 1583

## Adding TP/SL to a position that's already open -- use `set-position-tpsl`,
## NOT a freehand `create`

`place_order.py --tp-price/--sl-price` only attaches TP/SL at entry time (a new
order). If a position is already open and the user asks to "add" or "set"
TP/SL for it, hand-rolling a `create` call is a real footgun: you must get
`--side` (the CLOSING side, opposite of the position), `--size` (the full
position quantity), and `--reduce-only` exactly right, or the leg can end up on
the wrong side / wrong size and leave a stray order sitting in the book after
the position is gone (observed in production: an agent free-handed `create`
without `--reduce-only` and with the entry's original side, which left a
leftover LIMIT BUY order after the position was later sold via a correctly-side
manual close).

`set-position-tpsl` mirrors EXACTLY what the A9Fund web terminal's own
"Position TP/SL" dialog does (reverse-engineered from
`frontend-v2/src/app/app/terminal/position-tpsl-modal.tsx` -- there is no
separate "attach to position" API; the web UI uses this same
`/conditional-orders` endpoint, just with hardcoded-safe parameters):

1. Reads the current position for `--symbol` -> derives the closing side
   (SELL for a LONG, BUY for a SHORT) and the full position quantity.
2. Cancels any of the account's existing ACTIVE conditional orders on that
   symbol whose `side` matches the closing side (i.e. prior TP/SL legs for
   this position) -- so requests never stack duplicate legs.
3. Creates fresh conditional order(s) for whichever of `--tp-price`/`--sl-price`
   is given, always with: side = closing side, size = full position quantity,
   `trigger_order_type` = TAKE_PROFIT_MARKET / STOP_MARKET (never LIMIT),
   `reduce_only = true`, and no `trigger_direction` (the order type alone
   disambiguates it -- exactly what the web app sends).

Example:
  python3 conditional_order.py set-position-tpsl --symbol BTC-USDT \\
      --tp-price 90000 --sl-price 60000
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


def _fetch_position(cfg, symbol: str) -> dict | None:
    resp = http_request("GET", "/positions",
                        query={"exchange_account_id": cfg["exchange_account_id"], "symbol": symbol}, cfg=cfg)
    data = unwrap(resp)
    positions = data.get("positions") if isinstance(data, dict) else data
    for p in (positions or []):
        try:
            if float(p.get("quantity", p.get("size", 0)) or 0) > 0:
                return p
        except (TypeError, ValueError):
            continue
    return None


def _fetch_active_conditionals(cfg, symbol: str) -> list[dict]:
    resp = http_request("GET", "/conditional-orders",
                        query={"exchange_account_id": cfg["exchange_account_id"], "symbol": symbol}, cfg=cfg)
    data = unwrap(resp)
    orders = data.get("conditional_orders") or data.get("orders") if isinstance(data, dict) else data
    return orders or []


def cmd_set_position_tpsl(args, cfg):
    if not args.tp_price and not args.sl_price and not args.clear_tp and not args.clear_sl:
        die("Pass at least one of --tp-price / --sl-price (or --clear-tp / --clear-sl to remove a leg).")

    pos = _fetch_position(cfg, args.symbol)
    if pos is None:
        die(f"No open position on {args.symbol} -- nothing to attach TP/SL to. "
            f"Use place_order.py --tp-price/--sl-price to attach at entry instead.")

    side = str(pos.get("side", "")).upper()
    closing_side = "SELL" if side == "LONG" else "BUY" if side == "SHORT" else None
    if closing_side is None:
        die(f"Unrecognised position side {side!r} for {args.symbol}.")
    size = args.size or pos.get("quantity") or pos.get("size")

    # Read existing legs BEFORE cancelling. Any leg not explicitly touched by
    # this call (no --tp-price/--sl-price AND no --clear-tp/--clear-sl) is
    # re-created unchanged, matching the web terminal's modal (which
    # pre-fills both fields from the existing legs before resubmitting).
    # Silently dropping the untouched leg was a real bug: an agent that meant
    # "only update SL" would otherwise lose the existing TP with no warning.
    existing = _fetch_active_conditionals(cfg, args.symbol)
    existing = [o for o in existing if str(o.get("side", "")).upper() == closing_side]
    existing_tp = next((o for o in existing if "TAKE_PROFIT" in str(o.get("order_type", "")).upper()), None)
    existing_sl = next((o for o in existing if "STOP" in str(o.get("order_type", "")).upper()), None)

    tp_price = args.tp_price
    if not tp_price and not args.clear_tp and existing_tp:
        tp_price = existing_tp.get("trigger_price")
    sl_price = args.sl_price
    if not sl_price and not args.clear_sl and existing_sl:
        sl_price = existing_sl.get("trigger_price")

    cancelled = []
    for o in existing:
        oid = o.get("condition_order_id") or o.get("order_id")
        if not oid:
            continue
        q = {"exchange_account_id": cfg["exchange_account_id"]}
        http_request("DELETE", f"/conditional-orders/{oid}", query=q, cfg=cfg)
        cancelled.append(oid)

    created = {}
    for kind, price, order_type in (("take_profit", tp_price, "TAKE_PROFIT_MARKET"),
                                     ("stop_loss", sl_price, "STOP_MARKET")):
        if not price:
            continue
        body = {
            "exchange_account_id": cfg["exchange_account_id"],
            "symbol": args.symbol,
            "side": closing_side,
            "size": size,
            "trigger_price": price,
            "trigger_price_type": args.trigger_price_type,
            "trigger_direction": "",  # order_type alone disambiguates, matching the web app
            "trigger_order_type": order_type,
            "reduce_only": True,
            "trace_id": f"a9-postpsl-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}",
        }
        resp = http_request("POST", "/conditional-orders", json_body=body, cfg=cfg)
        created[kind] = unwrap(resp)

    print_json({
        "symbol": args.symbol,
        "position_side": side,
        "closing_side": closing_side,
        "size": size,
        "cancelled_prior_legs": cancelled,
        "preserved_unchanged": {
            "take_profit": tp_price if (existing_tp and not args.tp_price and not args.clear_tp) else None,
            "stop_loss": sl_price if (existing_sl and not args.sl_price and not args.clear_sl) else None,
        },
        "created": created,
    })


def main() -> None:
    p = argparse.ArgumentParser(description="Standalone conditional (trigger) orders")
    p.add_argument("--account-id", default=None,
                   help="Assert the bound account before acting (guards state drift; also A9FUND_ACCOUNT_ID).")
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

    sp = sub.add_parser("set-position-tpsl",
                        help="Set/replace TP/SL for an already-open position (safe, mirrors the web terminal).")
    sp.add_argument("--symbol", required=True)
    sp.add_argument("--tp-price", default="",
                    help="Take-profit trigger price. Omit to leave an existing TP leg untouched "
                         "(re-created as-is); pass --clear-tp to remove it instead.")
    sp.add_argument("--sl-price", default="",
                    help="Stop-loss trigger price. Omit to leave an existing SL leg untouched "
                         "(re-created as-is); pass --clear-sl to remove it instead.")
    sp.add_argument("--clear-tp", action="store_true", help="Remove the take-profit leg (don't recreate it)")
    sp.add_argument("--clear-sl", action="store_true", help="Remove the stop-loss leg (don't recreate it)")
    sp.add_argument("--trigger-price-type", default="MARK", choices=["INDEX", "MARKET", "MARK"])
    sp.add_argument("--size", default="", help="Override size (default: full position quantity)")
    sp.set_defaults(func=cmd_set_position_tpsl)

    args = p.parse_args()
    cfg = load_config(expected_account_id=args.account_id)
    args.func(args, cfg)


if __name__ == "__main__":
    main()

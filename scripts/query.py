"""Unified query entry (A9Fund query endpoints).

Subcommands:
  positions         [--symbol]
  balance                                # GET /portfolio/balances
  open-orders       [--symbol]           # GET /openOrders  (regular LIMIT/MARKET)
  condition-orders  [--symbol]           # GET /conditionOrders (TP/SL + trigger orders)
  history-orders    [--symbol] [--page] [--limit]
  trades            [--symbol] [--page] [--limit]
  pnl-closed        [--symbol] [--start <unix-microsec>] [--end <unix-microsec>] [--page] [--limit]
  leverage          [--symbol]           # GET /getLeverage
  accounts                               # GET /exchange-accounts (list + risk sub-object)
"""
from __future__ import annotations

import argparse

from _common import http_request, load_config, print_json, unwrap


def _q(cfg, extra: dict | None = None) -> dict:
    q = {"exchange_account_id": cfg["exchange_account_id"]}
    if extra:
        q.update({k: v for k, v in extra.items() if v not in (None, "")})
    return q


def cmd_positions(args, cfg):
    print_json(unwrap(http_request("GET", "/positions", query=_q(cfg, {"symbol": args.symbol}), cfg=cfg)))


def cmd_balance(_args, cfg):
    print_json(unwrap(http_request("GET", "/portfolio/balances", query=_q(cfg), cfg=cfg)))


def cmd_open_orders(args, cfg):
    print_json(unwrap(http_request("GET", "/openOrders", query=_q(cfg, {"symbol": args.symbol}), cfg=cfg)))


def cmd_condition_orders(args, cfg):
    print_json(unwrap(http_request("GET", "/conditionOrders", query=_q(cfg, {"symbol": args.symbol}), cfg=cfg)))


def cmd_history_orders(args, cfg):
    print_json(unwrap(http_request("GET", "/historyOrders",
               query=_q(cfg, {"symbol": args.symbol, "page": args.page, "limit": args.limit}), cfg=cfg)))


def cmd_trades(args, cfg):
    print_json(unwrap(http_request("GET", "/trades",
               query=_q(cfg, {"symbol": args.symbol, "page": args.page, "limit": args.limit}), cfg=cfg)))


def cmd_pnl_closed(args, cfg):
    extra = {"symbol": args.symbol, "start_time": args.start, "end_time": args.end,
             "page": args.page, "limit": args.limit}
    print_json(unwrap(http_request("GET", "/pnl/closed", query=_q(cfg, extra), cfg=cfg)))


def cmd_leverage(args, cfg):
    print_json(unwrap(http_request("GET", "/getLeverage", query=_q(cfg, {"symbol": args.symbol}), cfg=cfg)))


def cmd_accounts(_args, cfg):
    print_json(unwrap(http_request("GET", "/exchange-accounts", cfg=cfg)))


def main() -> None:
    p = argparse.ArgumentParser(description="Query endpoints")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("positions"); sp.add_argument("--symbol"); sp.set_defaults(func=cmd_positions)
    sub.add_parser("balance").set_defaults(func=cmd_balance)
    sp = sub.add_parser("open-orders"); sp.add_argument("--symbol"); sp.set_defaults(func=cmd_open_orders)
    sp = sub.add_parser("condition-orders"); sp.add_argument("--symbol"); sp.set_defaults(func=cmd_condition_orders)

    sp = sub.add_parser("history-orders")
    sp.add_argument("--symbol"); sp.add_argument("--page", type=int); sp.add_argument("--limit", type=int)
    sp.set_defaults(func=cmd_history_orders)

    sp = sub.add_parser("trades")
    sp.add_argument("--symbol"); sp.add_argument("--page", type=int); sp.add_argument("--limit", type=int)
    sp.set_defaults(func=cmd_trades)

    sp = sub.add_parser("pnl-closed")
    sp.add_argument("--symbol")
    sp.add_argument("--start", type=int, help="Unix microseconds")
    sp.add_argument("--end", type=int, help="Unix microseconds")
    sp.add_argument("--page", type=int); sp.add_argument("--limit", type=int)
    sp.set_defaults(func=cmd_pnl_closed)

    sp = sub.add_parser("leverage"); sp.add_argument("--symbol"); sp.set_defaults(func=cmd_leverage)
    sub.add_parser("accounts").set_defaults(func=cmd_accounts)

    args = p.parse_args()
    cfg = load_config()
    args.func(args, cfg)


if __name__ == "__main__":
    main()

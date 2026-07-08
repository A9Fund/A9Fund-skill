"""Risk snapshot: /portfolio/balances + /positions + /exchange-accounts,
compared against A9Fund per-track thresholds.

Enforcement note (see references/risk-rules.md): A9Fund's backend is NOT on
the trade write path. Real-time risk (cumulative + daily drawdown, leverage,
position/stake caps) is enforced by propdesk. These thresholds are the
published values the agent must trade within; propdesk is the authority that
actually fails an account.
"""
from __future__ import annotations

from _common import get_active_exchange, http_request, load_config, print_json, unwrap


# A9Fund catalog thresholds, per track (rules-authoritative.md sections 三/四).
# daily_loss_pct / cum_loss_pct = drawdown red lines. alert_pct = soft warning
# line (Standard only). consistency_pct = single-day profit-share cap (enforced
# at payout, not at trade time). profit_target_pct is the pass target.
_STARTER = {
    "profit_target_pct": 8, "daily_loss_pct": 3, "cum_loss_pct": 6, "alert_pct": None,
    "min_profitable_days": 2, "consistency_pct": 45, "profit_split_pct": 70,
}
_STANDARD = {
    # Two-phase: 8% (phase1) then 5% (phase2). Shown as a note; use current phase target.
    "profit_target_pct": "8 -> 5 (two-phase)", "daily_loss_pct": 4, "cum_loss_pct": 8, "alert_pct": 5,
    "min_profitable_days": 3, "consistency_pct": 40, "profit_split_pct": 80,
}
_FAST = {
    "profit_target_pct": 10, "daily_loss_pct": 3, "cum_loss_pct": 6, "alert_pct": None,
    "min_profitable_days": 3, "consistency_pct": 35, "profit_split_pct": 80,
}

THRESHOLDS_BY_TRACK = {"starter": _STARTER, "standard": _STANDARD, "fast": _FAST}

RULE_REMINDERS = [
    "Drawdown is death: cumulative-loss red line (Starter/Fast 6%, Standard 8%) "
    "and daily-loss line (Starter/Fast 3%, Standard 4%) are enforced by propdesk "
    "in real time -- one breach fails the account. Standard also has a 5% alert line.",
    "Leverage caps: challenge phase 10X, fund phase 5X (propdesk enforces at order time).",
    "Rate limit: max 5 orders per second per account.",
    "Profitable days: need >= 2 (Starter) / 3 (Standard, Fast) profitable trading days to pass or to be payout-eligible.",
    "Event contracts: odds 0.2-0.8, stake 0.5-2% of equity, max 3 open, max 1 per symbol; "
    "profit counts toward passing only after 6 settled; any open/disputed contract blocks pass and payout.",
    "Inactivity: account goes inactive after 30 calendar days with no real fill. "
    "Only an executed trade resets the clock (logins, market-data reads, unfilled/cancelled orders do NOT).",
    "Consistency: a single day's profit may not exceed 45%/40%/35% (Starter/Standard/Fast) "
    "of total profit -- checked at payout, not at trade time.",
    "Payout: first eligible 14 days after fund activation, then every 14 days; needs KYC done, "
    "no open positions, no unsettled event contracts; single-cycle cap ~5% of account size (first cycle up to 3%).",
    "Forbidden: multi-account trading/hedging, quote-latency/mispricing exploits, "
    "high-frequency cancel/replace, trading unsupported markets or above max leverage, fraud. "
    "Report backend bugs instead of trading on them (profits are clawback-eligible).",
]


def _status(current: float, limit, *, warn_ratio: float = 0.8) -> str:
    if limit in (None, 0) or not isinstance(limit, (int, float)):
        return "n/a"
    ratio = round(current, 2) / limit
    if ratio >= 1:
        return "violated"
    if ratio >= warn_ratio:
        return "warning"
    return "ok"


def _to_float(v, default=None):
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _find_account_risk(cfg) -> dict:
    """Return the bound account's `risk` sub-object from /exchange-accounts, or {}."""
    try:
        data = unwrap(http_request("GET", "/exchange-accounts", cfg=cfg))
    except SystemExit:
        return {}
    accounts = []
    if isinstance(data, dict):
        accounts = data.get("exchange_accounts") or data.get("accounts") or []
    elif isinstance(data, list):
        accounts = data
    for a in accounts:
        if str(a.get("exchange_account_id") or a.get("id")) == str(cfg["exchange_account_id"]):
            risk = a.get("risk")
            return risk if isinstance(risk, dict) else {}
    return {}


def main() -> None:
    cfg = load_config()
    mode = cfg.get("mode", "")
    phase = str(cfg.get("phase", "")).lower()
    track = mode.split("-")[0] if mode else ""
    th = THRESHOLDS_BY_TRACK.get(track, {})

    bal_data = unwrap(http_request("GET", "/portfolio/balances",
                      query={"exchange_account_id": cfg["exchange_account_id"]}, cfg=cfg))
    if isinstance(bal_data, dict) and "balances" in bal_data:
        balances = bal_data.get("balances") or []
        bal = balances[0] if balances else {}
    else:
        bal = bal_data if isinstance(bal_data, dict) else {}

    total_equity = _to_float(bal.get("total_equity_value") or bal.get("total"), 0.0)
    wallet_balance = _to_float(bal.get("wallet_balance"), None)
    unrealized_pnl = _to_float(bal.get("unrealized_pnl"), None)
    realized_pnl = _to_float(bal.get("realized_pnl"), None)
    initial_balance = _to_float(cfg.get("initial_balance"), None) or total_equity

    pos_data = unwrap(http_request("GET", "/positions",
                      query={"exchange_account_id": cfg["exchange_account_id"]}, cfg=cfg))
    positions = pos_data.get("positions") if isinstance(pos_data, dict) else pos_data
    open_pos_count = len(positions or [])

    pnl_pct = ((total_equity - initial_balance) / initial_balance * 100) if initial_balance else 0

    # Prefer propdesk's authoritative figures from the account risk sub-object.
    # The account reports its OWN red lines (max_drawdown_pct etc.), which are
    # the ground truth — override the per-track table with them when present.
    risk = _find_account_risk(cfg)
    live_cum_limit = _to_float(risk.get("max_drawdown_pct"))
    live_daily_limit = _to_float(risk.get("max_daily_drawdown_pct"))
    live_alert = _to_float(risk.get("alert_drawdown_pct"))
    cum_limit = live_cum_limit if live_cum_limit is not None else th.get("cum_loss_pct")
    daily_limit = live_daily_limit if live_daily_limit is not None else th.get("daily_loss_pct")
    alert_limit = live_alert if live_alert is not None else th.get("alert_pct")

    cum_loss = _to_float(risk.get("max_cumulative_loss_pct"))
    loss_pct = cum_loss if cum_loss is not None else max(0.0, -pnl_pct)
    last_daily_dd = _to_float(risk.get("last_daily_drawdown_pct"))
    if initial_balance in (None, 0):
        bl = _to_float(risk.get("baseline_equity"))
        if bl:
            initial_balance = bl
            pnl_pct = (total_equity - initial_balance) / initial_balance * 100 if initial_balance else 0

    try:
        active_exchange = get_active_exchange(cfg=cfg)
    except SystemExit:
        active_exchange = None

    daily_block = {"limit_pct": daily_limit}
    if last_daily_dd is not None:
        daily_block["last_daily_drawdown_pct"] = round(last_daily_dd, 4)
        daily_block["status"] = _status(abs(last_daily_dd), daily_limit)
        daily_block["note"] = "From /exchange-accounts risk (daily worker snapshot); not intraday real-time."
    else:
        daily_block["note"] = ("Enforced by propdesk in real time; not derivable client-side here. "
                               "Watch equity vs previous-day equity.")

    output = {
        "exchange_account_id": cfg["exchange_account_id"],
        "active_exchange": active_exchange,
        "mode": mode,
        "phase": phase or None,
        "track": track or None,
        "initial_balance": initial_balance,
        "total_equity_value": total_equity,
        "wallet_balance": wallet_balance,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl,
        "current_pnl_pct": round(pnl_pct, 2),
        "profit_target_pct": th.get("profit_target_pct"),
        "leverage_cap": 5 if phase == "fund" else 10,
        "thresholds": {
            "cumulative_loss": {
                "limit_pct": cum_limit,
                "alert_pct": alert_limit,
                "current_pct": round(loss_pct, 2),
                "status": _status(loss_pct, cum_limit),
            },
            "daily_loss": daily_block,
            "min_profitable_days_required": th.get("min_profitable_days"),
            "consistency_single_day_cap_pct": th.get("consistency_pct"),
        },
        "profit_split_pct": th.get("profit_split_pct"),
        "open_positions_count": open_pos_count,
        "rule_reminders": RULE_REMINDERS,
    }
    print_json(output)


if __name__ == "__main__":
    main()

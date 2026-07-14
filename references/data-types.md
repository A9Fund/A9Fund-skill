# Data types and field reference (A9Fund)

## General rules

- **Money fields** are strings (decimal), e.g. `"60000"`, `"0.1"` — avoids float
  precision issues.
- **Timestamps** are Unix microseconds (int64) unless noted, e.g.
  `1712534400000000`. Some embedded arrays use milliseconds (`create_at`).
- **IDs** in responses are strings.
- **Response envelope** may be enveloped (`{"code":0,"msg":"ok","data":{...}}`)
  or bare (`{...}` / `{"detail":"..."}` on error). The scripts handle both.

## Order fields (openOrders / historyOrders)

| Field | Notes |
|---|---|
| order_id | Internal order id |
| exchange_order_id | Exchange-side order id (may be `""` on the paper venue) |
| exchange | Exchange identifier; runtime-resolved on the server |
| exchange_account_id | Account id |
| client_order_id | Client-supplied idempotency id (`agent-{ms}-{uuid8}` from `place_order.py`) |
| symbol | Trading pair |
| side | BUY / SELL |
| order_type | LIMIT / MARKET (standalone triggers live under conditional orders) |
| price | Submitted price |
| size / filled_size | Submitted / filled quantity |
| avg_price | Average fill price |
| status | See enum below |
| take_profit[] / stop_loss[] | On an entry order: embedded PENDING TP/SL legs (always present, possibly empty). Each carries a `condition_order_id` — cancel it via the conditional-order path |
| fee | Fee amount |
| created_at / updated_at | Unix microseconds |

### Order status enum

`PENDING` (submitted, unfilled) · `FILLED` · `PARTIALLY_FILLED` · `CANCELED` ·
`REJECTED` · `EXPIRED`. Trust the API response when in doubt.

## Position fields (/positions)

| Field | Notes |
|---|---|
| exchange_account_id | Account id |
| symbol | Trading pair |
| side | LONG / SHORT |
| quantity (or size) | Position size |
| entry_price / mark_price / last_price | Prices |
| leverage | Current leverage |
| margin_mode | CROSS / ISOLATED |
| position_value | Notional value |
| liquidation_price | Liquidation price |
| unrealized_pnl / unrealized_pnl_percent | Floating PnL |
| funding_fee | Cumulative settled funding for this position. **Positive = paid by user, negative = received.** `"0"` when none |

## Balance fields (/portfolio/balances)

Published example is bare: `{"total": "...", "available": "...",
"unrealized_pnl": "..."}`. The fuller propdesk shape (when enveloped under
`balances[]`) includes:

| Field | Notes |
|---|---|
| total_equity_value | Live equity incl. unrealized PnL (`wallet_balance + unrealized_pnl`) |
| available_balance | `wallet_balance − initial_margin − frozen_for_orders`; headroom for new orders |
| initial_margin / maintenance_margin | Margin locked by positions / tier-based maintenance |
| frozen_for_orders | Margin pre-frozen by OPEN LIMIT orders (released on cancel/reject/fill) |
| unrealized_pnl | Floating PnL by mark price |
| realized_pnl | **Gross** realized PnL (before fees/funding) |
| realized_pnl_net | Net = `realized_pnl − cumulative_fee + cumulative_funding` |
| cumulative_fee / cumulative_funding | Lifetime fees / funding (funding sign: positive = paid by user) |
| wallet_balance | `initial_capital + realized_pnl − cumulative_fee + cumulative_funding` |

> `risk_status.py` reads `total_equity_value` (falling back to `total`) and
> `wallet_balance` when present.

## Closed-PnL fields (/pnl/closed)

| Field | Notes |
|---|---|
| side | **Opening direction**: `BUY` = LONG / `SELL` = SHORT |
| leverage | int; leverage in effect at close (snapshot), never 0 |
| funding_fee | Same sign convention: positive = paid by user, negative = received |

## Risk sub-object (/exchange-accounts → per-account `risk`)

`risk_status.py` reads these when present; otherwise it computes from balances.

| Field | Notes |
|---|---|
| max_drawdown_pct | Cumulative-loss red line (percent) — the threshold |
| alert_drawdown_pct | Alert line (Standard only) |
| max_daily_drawdown_pct | Daily-drawdown red line |
| max_cumulative_loss_pct | Current cumulative loss rate = `(baseline − min(trough, current)) / baseline × 100`; `"0"` while in profit. **Use this for the max-loss figure** (same basis as `max_drawdown_pct`) |
| current_drawdown_pct | Pullback from the historical peak — display only, NOT comparable to the red line |
| last_daily_drawdown_pct | Previous-day drawdown (daily worker snapshot), ≤ 0; `"0"` = flat/profit/first day |
| current_equity / baseline_equity / peak_equity / trough_equity | Equity figures |
| short_hold_count_7d | Legacy counter from the shared propdesk backend — **no A9Fund rule is attached to it**; ignore (do not infer a minimum-holding-time rule from its presence) |

## Attached TP/SL field shapes (differ by endpoint)

Verified live:
- **`/createOrder`** uses **flat** fields: `is_set_open_tp` / `is_set_open_sl`
  (bool) + `tp_trigger_price` / `tp_trigger_price_type` + `sl_trigger_price` /
  `sl_trigger_price_type`.
- **`/conditional-orders`** uses **objects**: `is_set_open_tp` / `is_set_open_sl`
  + `open_tp_param` / `open_sl_param` = `{trigger_price, trigger_price_type}`.

Both embed the resulting legs in the response's `take_profit[]` / `stop_loss[]`
arrays.

## trigger_price_type values

`INDEX` (index price) · `MARKET` (market price) · `MARK` (mark price). `ORACLE`
is not supported for attached TP/SL.

## time_in_force values

`GTC` (Good-Till-Cancel, LIMIT default) · `FOK` (Fill-Or-Kill) · `IOC`
(Immediate-Or-Cancel) · `POST_ONLY`.

## Event-contract fields

See `event-contracts.md`. Inputs: `symbol` ∈ {BTCUSDT, ETHUSDT}, `direction` ∈
{UP, DOWN}, `duration` ∈ {10m, 30m, 1h, 1d}, `premium` > 0. Settled states are
WIN / LOSS; 6 settled unlock activation.

---
name: a9fund-trading
description: Use when the user wants to trade on the A9Fund prop-trading platform. Covers credential binding, order placement / cancellation, attached and standalone conditional (TP/SL) orders, leverage, position / balance / order / trade queries, market data, event contracts (prediction market), and risk-status checks. Trigger on mentions of A9Fund, prop trading, Starter / Standard / Fast challenge, funded account, propdesk, event contract / prediction market, or any concrete action like "place order", "cancel order", "check positions", "check balance", "set leverage", "buy an UP contract".
---

# A9Fund Trading Skill

Autonomous prop-trading agent skill for the A9Fund platform. Wraps the propdesk
HTTP API: credential binding, trading actions, event contracts, and a risk
snapshot. A9Fund's backend is not on the trade write path — **propdesk enforces
all real-time risk** (drawdown, leverage, stake caps); this skill trades within
the published rules and reads state back.

**Version:** see the `VERSION` file at the skill root
(`cat skills/a9fund-skill/VERSION`), format `YYYY-MM-DD.N`.

## Storage layout

- `~/.a9fund/accounts/<account_id>.json` — **credentials only** (API key +
  exchange_account_id + three base URLs). Written by the STEP 2 terminal snippet
  the user pastes from the A9Fund account detail page (`/app/agent-api`). Scripts
  are read-only here — **the API key never passes through the agent's chat**.
- `<skill-root>/state.json` — per-skill runtime state: `active_account_id`,
  `mode`, `phase`, `initial_balance`, cached `active_exchange`. Written by
  `config.py bind`.

One skill install = one bound account. To run two accounts in parallel, install
the skill twice.

## Workflow on first invocation in a session

### Step 1 — check current binding

```bash
python3 skills/a9fund-skill/scripts/config.py show
```

- **No `active_account_id`**: not bound. If `~/.a9fund/accounts/` is also empty,
  the user hasn't pasted the STEP 2 snippet — direct them to the A9Fund account
  detail page (`/app/agent-api`) to copy it. **Do NOT ask the user for their API
  key**; it must never enter the agent context.
- **Bound**: skip to Step 3.

### Step 2 — bind the skill to an account

Trigger phrases like "Initialize account, account_id: xxxxx" or "Rebind,
account_id: yyyyy" both map to:

```bash
python3 skills/a9fund-skill/scripts/config.py bind --account-id <id>
```

`bind` verifies the credential file exists, reads `mode` / `phase` /
`initial_balance` from `/exchange-accounts` (program_id → mode; `starter_5k` →
`starter-5k`), caches `active_exchange`, and writes `state.json`. Same command
switches accounts later. If the lookup can't resolve the mode:

```bash
python3 skills/a9fund-skill/scripts/config.py bind --account-id <id> --skip-lookup \
  --mode <starter-5k|starter-10k|standard-25k|standard-50k|fast-10k|fast-25k> \
  --phase <challenge|fund> --initial-balance <amount>
```

### Step 3 — risk snapshot

```bash
python3 skills/a9fund-skill/scripts/risk_status.py
```

Summarize back to the user: account, current PnL, cumulative-loss usage vs the
red line, phase / leverage cap, and rule reminders.

### Step 4 — autonomous trading

After the summary, act on the user's strategy without confirming each order.
Before any risk-sensitive action, re-run `risk_status.py` and note how close each
threshold is.

**Guard against binding drift.** `state.json`'s `active_account_id` is only
changed by `config.py bind`, but if you juggle multiple accounts (or run
parallel tests) a stray re-bind can point the skill at the wrong / a disabled
account — every call then 403s. Pin the intended account so scripts refuse to act
on a mismatch: pass `--account-id <id>` to any trading/query script, or export
`A9FUND_ACCOUNT_ID=<id>` once for the session.

## Command cheatsheet

See `scripts/README.md` for the full list. Common ones:

```bash
# Place order (MARKET / LIMIT)
python3 scripts/place_order.py --symbol BTC-USDT --side BUY --order-type MARKET --size 0.001
python3 scripts/place_order.py --symbol BTC-USDT --side BUY --order-type LIMIT --size 0.1 --price 60000

# Open with attached TP/SL (one atomic call, OCO pair)
python3 scripts/place_order.py --symbol BTC-USDT --side BUY --order-type MARKET --size 0.001 \
  --tp-price 80000 --sl-price 75000

# Standalone conditional (trigger) order — dedicated resource
python3 scripts/conditional_order.py create --symbol ETH-USDT --side BUY --size 1 \
  --trigger-price 1582.77 --trigger-direction GTE --trigger-order-type LIMIT --order-price 1583
python3 scripts/conditional_order.py list
python3 scripts/conditional_order.py cancel --id <id>

# Close position (market reduce-only)
python3 scripts/close_position.py --symbol BTC-USDT
python3 scripts/close_position.py --all

# Cancel regular orders
python3 scripts/cancel_order.py --order-id 1234 --symbol BTC-USDT
python3 scripts/cancel_order.py --all --symbol BTC-USDT

# Queries
python3 scripts/query.py positions
python3 scripts/query.py balance
python3 scripts/query.py open-orders          # regular LIMIT/MARKET
python3 scripts/query.py condition-orders     # TP/SL + trigger orders
python3 scripts/query.py trades
python3 scripts/query.py accounts             # list + per-account risk

# Market data
python3 scripts/markets.py board
python3 scripts/markets.py metadata           # shows active_exchange
python3 scripts/markets.py kline --symbol BTC-USDT --interval 1m --limit 100
python3 scripts/markets.py orderbook --symbol BTC-USDT

# Leverage (cap: challenge 10X / fund 5X)
python3 scripts/set_leverage.py --symbol BTC-USDT --leverage 5

# Event contracts (prediction market)
python3 scripts/event_contracts.py catalog
python3 scripts/event_contracts.py order --symbol BTCUSDT --direction UP --duration 1h --premium 50

# Risk
python3 scripts/risk_status.py
```

## TP/SL mental model

Two ways to set a stop-loss / take-profit:

1. **Attach on entry** (`place_order.py --tp-price X --sl-price Y`) — one atomic
   call. The script sets `is_set_open_tp` / `is_set_open_sl` plus the flat
   `tp_trigger_price` / `sl_trigger_price` fields that `createOrder` expects; the
   legs form an OCO pair (one triggers → the other auto-cancels). While the entry
   LIMIT is resting, the legs are embedded in the entry row under `take_profit[]`
   / `stop_loss[]` (see `query.py open-orders`). Once filled, they move to
   `query.py condition-orders`.
2. **Standalone conditional order** (`conditional_order.py create`) — a separate
   trigger order in the `/conditional-orders` resource; cancel it with
   `conditional_order.py cancel --id <id>`.

Prefer #1 when opening; use #2 to add / adjust after entry. The backend
cascade-cancels attached legs when you cancel an unfilled LIMIT entry — no extra
cleanup needed.

## Reasoning is optional

A9Fund's account-level API does **not** require a per-order reasoning string.
`place_order.py` / `close_position.py` accept an optional `--reasoning` (length-
checked ≤ 4096 bytes UTF-8) but never block on it — useful only as your own
audit trail.

## Critical rules (agent must internalize)

Full detail in `references/risk-rules.md` and `references/challenge-rules.md`.
Summary — **propdesk enforces these in real time; one breach is terminal**:

- **Drawdown red lines (per track):** cumulative loss Starter/Fast **6%**,
  Standard **8%** (Standard alerts at 5%); daily loss Starter/Fast **3%**,
  Standard **4%**. Reaching the cumulative line fails the account.
- **Leverage caps:** challenge phase **10X**, fund phase **5X**. Single scalar —
  ignore any per-asset numbers shown in the UI; trust what propdesk accepts.
- **Rate limit:** max **5 orders/sec** per account (sleep ≥ 250 ms when batching).
- **Profitable days to pass / payout:** Starter **2**, Fast **3**, Standard
  **3 per phase**. A profitable day = a UTC calendar day with positive
  **realized** PnL.
- **Profit targets:** Starter 8%, Standard 8% → 5% (two-phase), Fast 10%.
  **Only realized profit counts toward the target** — floating PnL doesn't;
  realize gains before treating the target as met.
- **Consistency:** a single day's profit ≤ 45% / 40% / 35% (Starter / Standard /
  Fast) of total profit (Standard: of the current **phase's** profit) — unmet
  consistency blocks pass/payout (temporary blocker, not a fail).
- **Event contracts:** symbols {BTCUSDT, ETHUSDT}, direction {UP, DOWN}, duration
  {10m, 30m, 1h, 1d}, **odds 0.2–0.8**, **stake 0.5–2% of equity** (min 10 USDT),
  **max 3 open**, **max 1 per symbol**, fixed **80%** payout. Profit counts toward
  passing only after **6 settled**; any open/disputed contract blocks pass and
  payout. **Same-asset exclusivity:** a trading position and a prediction on the
  same crypto must not coexist — check positions before buying a prediction and
  vice versa. See `references/event-contracts.md`.
- **Inactivity:** account goes inactive after **30 days** with no real fill —
  only an executed trade resets the clock.
- **Forbidden:** multi-account trading/hedging, quote-latency/mispricing
  exploits, high-frequency cancel/replace, trading unsupported markets or above
  the account's max leverage, and fraud. Report backend bugs instead of trading
  on them (profits are clawback-eligible).
- **Payout:** profit share, first eligible **14 days after fund activation** then
  every 14 days; trader **70%** Starter / **80%** Standard·Fast (up to 90%
  healthy); min request $50 / $100; **single-cycle cap ~5% of account size**
  (first cycle up to 3%); requires **KYC**, no open positions, no unsettled event
  contracts. Wallet withdrawal min $100, 1% fee, days 8/18/28, networks
  ARB/POL/BSC, coins USDT/USDC.

## Failure fallback

If a `scripts/xxx.py` invocation fails:

1. Use the generic caller: `python3 scripts/api.py <METHOD> <PATH> [--query ...]
   [--json '...'] [--inject-account]`.
2. If that also fails, use curl from `references/api-http.md`. The API key and
   `exchange_account_id` live in `~/.a9fund/accounts/<id>.json`.

## Reference docs

- `references/api-http.md` — HTTP API reference + curl examples + error codes.
- `references/api-websocket.md` — WebSocket protocol (no script wrapper in MVP).
- `references/event-contracts.md` — prediction-market flow + rules.
- `references/data-types.md` — field definitions, order statuses, risk fields.
- `references/challenge-rules.md` — account paths, tiers, pass/fail, payout.
- `references/risk-rules.md` — drawdown lines, forbidden behavior, agent guidance.
- `scripts/README.md` — full script command reference.

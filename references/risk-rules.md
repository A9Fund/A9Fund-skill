# Risk and violation rules (A9Fund)

> Source of truth: A9Fund backend code (`docs/rules-authoritative.md`,
> `RULES_VERSION = "2026-06-21.v1"`). Real-time risk is enforced by **propdesk**;
> the backend publishes parameters, records terminal results, and reconciles.

## Drawdown red lines (per track)

| | Starter | Standard | Fast |
|---|---|---|---|
| Daily max loss     | 3% | 4% | 3% |
| Cumulative max loss | 6% | 8% | 6% |
| Alert line          | none | 5% | none |

**Enforcement:**
- **Cumulative drawdown** → propdesk real-time (`DRAWDOWN_BREACH`); backend
  re-checks daily as a backstop. Reaching the line (`≥`) fails the account.
- **Daily drawdown** → **propdesk only**, two-strike: `DAILY_DRAWDOWN_ALERT`
  first, then `DAILY_DRAWDOWN_BREACH` fails the account. The backend does not
  independently fail on daily drawdown.
- **Alert line (Standard 5%)** → parameter only; a soft warning, not a failure.

A drawdown breach is terminal — one hit and the account is done. There is no
human waiver.

## Leverage caps

| Stage | Cap |
|---|---|
| Challenge (Standard pre-pass) | **10X** |
| Fund (Starter, Fast, passed Standard) | **5X** |

Single scalar per stage — **no per-asset table in the backend** (front-end
per-asset numbers are display copy). propdesk rejects an order above the cap at
submission time. Trust the value accepted at order time.

## Rate limit

- **Max 5 orders per second per account** (`429` / biz code `10008`). Sleep
  ≥ 250 ms between batched orders.

## Inactivity (30 days)

An account goes **inactive after 30 calendar days with no effective fill**. Only
an executed trade (a real propdesk fill) resets the clock. These do **NOT** count:

- Logging in / viewing the dashboard.
- Reading market data (`markets.py board / kline / metadata`).
- Connecting the agent / running `risk_status.py`.
- Placing an order that never fills, or cancelling orders.
- Deposits / withdrawals, system auto-liquidations.

Guidance: "watching and waiting" quietly burns the 30-day budget. Check the most
recent fill (`query.py trades`, newest `created_at`); if it has been > 20 days,
consider a small, plan-consistent trade rather than risk suspension. A suspended
account cannot trade, request payout, or pass.

## Consistency (single-day profit cap)

Single-day profit may not exceed **45% (Starter) / 40% (Standard, measured
against the current phase's total profit) / 35% (Fast)** of total profit.
Checked at **pass and payout** (not at trade time); unmet consistency is a
**temporary blocker** — keep trading until the profit distribution satisfies the
rule, the account does not fail. Practically: don't let one lucky day carry the
whole account, or the pass/payout gate blocks the request.

Related pass-basis rule: **only realized profit counts toward the pass target**
(a profitable day = UTC calendar day with positive realized PnL; floating PnL
never counts). Use `risk_status.py`'s `realized_pnl_pct` for pass progress.

## Reasoning (NOT required)

A9Fund's account-level API does **not** require a per-order reasoning string
("API 订单不需要提交额外推理说明"). `place_order.py` / `close_position.py` accept an
optional `--reasoning` and only length-check it (≤ 4096 bytes UTF-8); they never
block on it.

## Retired rules — do NOT re-import from the aixfunded reference

Officially confirmed retired (FAQ "风控、Breach 与 Blocker": "都不再作为 A9Fund
fail 或 blocker"):

- **Minimum 1-minute holding time**, incl. the min-holding alert/breach
  counters (`short_hold_count_7d` may still appear in risk payloads — ignore it
  as a rule).
- **AI reasoning score** / platform AI quality score (this is why `--reasoning`
  is optional above).
- **Separate manual vs. agent pass standards** (no manual/agent boundary rule).

The aixfunded reference skill enforces all three; they do not apply on A9Fund.
Don't "fix" the skill by re-adding them.

## Payout

Two independent channels — different rules:

### Profit share (funded profit → platform balance)

- Cycle: rolling **14 days**. First eligibility: **14 days after Fund Account
  activation**; then every 14 days. Review target **1–3 business days**.
- Trader split: **70%** (Starter) / **80%** (Standard, Fast; up to 90% healthy).
  Payout coins **USDC / USDT**.
- Minimum request: **$50** (Starter) / **$100** (Standard·Fast).
- **Single-cycle cap: ~5% of account size** (first cycle up to **3%**).
- Eligibility (all must hold, per published rules): **KYC completed**; account
  active and in profit; not in daily/max-loss breach; **no open crypto
  positions**; **no unsettled/disputed** event contracts; consistency `best_day`
  OK; enough profitable days (2/3/3); request ≥ minimum and ≤ cycle cap.

> ⚠️ The code snapshot did not yet enforce KYC or the 5%/3% cycle cap in the
> funds path, but the public rules page lists both — follow the published rules.

### Wallet withdrawal (platform balance → chain)

| Rule | Value |
|---|---|
| Minimum withdrawal | **$100 (everyone)** |
| Fee | **1%** |
| Withdrawal days | **8 / 18 / 28** each month |
| Networks | **ARB / POL / BSC** |
| Coins | **USDT / USDC** |
| Balance check | available ≥ amount |

> Mainnet withdrawal is not yet live (network mode defaults to testnet; mainnet
> token contracts are placeholders). KYC is **not** a coded precondition. Note
> the two different "minimums": profit-share minimum profit ($50 Starter) vs
> wallet-withdrawal minimum ($100 everyone).

## Forbidden behavior

Published failure triggers (qa.a9fund.com/rules §08): hitting the max-loss limit,
hitting the daily-loss limit, **trading an unsupported account or market**,
**exceeding the account's max leverage**, and **abnormal trading / fraud** (the
platform may freeze the account for manual review).

Additional prohibited behavior (standard prop-firm rules):

| # | Behavior |
|---|---|
| 1 | Multi-account trading (positions on 2+ accounts at once). |
| 2 | Cross-account hedging / mirroring / copy-trading. |
| 3 | Exploiting quote latency / stale prices / mispricing. |
| 4 | High-frequency cancel/replace spamming. |
| 5 | Third-party / bot account management beyond the sanctioned agent-API path. |
| 6 | Exploiting backend bugs — report mispriced fills / stale data / calc bugs instead of trading on them. |
| 7 | Identity / quota evasion (duplicate accounts, synthetic identity, key sharing). |

Rewards, payouts, and profits from any of the above are **clawback-eligible**.

## Practical guidance for the agent

1. **Risk-first:** run `risk_status.py` before opening new exposure. Stop opening
   when cumulative loss is within ~1 pt of the cap (≥ 5% on a 6% Starter/Fast
   cap; ≥ 7% on an 8% Standard cap).
2. **Order pacing:** sleep ≥ 250 ms between orders (5/s limit).
3. **Same-direction only:** never open opposing positions on the same symbol in
   one account (avoids hedge classification).
4. **Live quotes:** use `markets.py orderbook` snapshots, not stale tickers,
   before MARKET orders.
5. **Keep the account active:** if no fill in > 20 days, weigh a small
   plan-consistent trade against inactivity suspension.
6. **Event contracts:** any open/disputed contract blocks pass and payout;
   contracts only count toward passing after 6 settled — see
   `references/event-contracts.md`.
7. **Report, don't exploit:** stop and report a backend bug; profits from it are
   clawed back.

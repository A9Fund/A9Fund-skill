# Risk and violation rules (A9Fund)

> Sources: live API (always wins when available — this pass could NOT
> live-verify, test key expired with `401 invalid or expired token`); published
> rules page i18n source (`marketingRules` in `messages/{locale}.json`,
> re-checked 2026-07-15); backend code snapshot (`docs/rules-authoritative.md`,
> `RULES_VERSION = "2026-06-21.v1"`). Real-time risk is enforced by
> **propdesk**; the backend publishes parameters, records terminal results, and
> reconciles. See `challenge-rules.md` for the catalog/pricing side of the same
> re-check, including a caveat that these tables have changed more than once.

## Drawdown red lines (per track)

Per the published rules page (§07, re-checked 2026-07-15 — **note this changed
from the previously-documented numbers**, see caveat below):

| | Starter | Standard | Fast |
|---|---|---|---|
| Daily max loss      | 4% | 5% | 4% |
| Cumulative max loss | 8% (static) | 8% (static) | 6% (static) |
| Alert line          | not published | not published (may still exist live) | not published |

**Enforcement:**
- **Cumulative drawdown** → propdesk real-time (`DRAWDOWN_BREACH`); backend
  re-checks daily as a backstop. Reaching the line (`≥`) fails the account.
  "Static" per the rules page means the line is fixed against baseline
  capital, not a rolling/relative figure.
- **Daily drawdown** → **propdesk only**. The rules page no longer describes a
  two-strike alert/breach sequence for daily drawdown; treat any daily-loss
  line hit as potentially terminal, not just a warning.
- **`risk_status.py` always prefers the account's LIVE `max_drawdown_pct` /
  `max_daily_drawdown_pct` / `alert_drawdown_pct`** (from `/exchange-accounts`)
  over this table — this table is only the fallback when live data isn't
  available. Trust the live numbers.

A drawdown breach is terminal — one hit and the account is done. There is no
human waiver.

> ⚠️ **Changed since the last check (2026-07-13 → 2026-07-15):** previously
> documented as Starter 3%/6%, Standard 4%/8%+5% alert, Fast 3%/6% (this matched
> a live API read on a Standard account back on 2026-07-06: daily 4%, max 8%,
> alert 5% — consistent with the *old* table, not the new one). The daily-loss
> lines and Starter's max-loss line have since moved on the published page.
> **Re-verify against a live account before trading close to any of these
> lines** — this file could not be re-verified live this pass.

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

## Reasoning (optional)

A9Fund's account-level API does **not** require a per-order reasoning string.
`place_order.py` / `close_position.py` accept an optional `--reasoning` and only
length-check it (≤ 4096 bytes UTF-8); they never block on it.

## Payout

Two independent channels — different rules:

### Profit share (funded profit → platform balance)

- Cycle: **14 days**. First eligibility: **14 days after Fund Account
  activation**; then every 14 days since the last payout. Review target
  **1–3 business days**.
- **Per-cycle profit target:** remaining profit must reach **Starter 8% / Fast
  10% / Standard 5%**, re-evaluated each request — in addition to, not instead
  of, the minimum dollar amount below.
- Trader split: **70%** (Starter) / **80%** (Standard, up to 90% healthy) /
  **85%** (Fast). Payout coins **USDC / USDT** (USDC preferred).
- Minimum request: **$50** (Starter) / **$100** (Standard·Fast).
- Profitable days required: **3 / 3 / 3** (Starter / Standard / Fast) — same
  basis as passing.
- Consistency: same caps as passing (45/40/35%), **recalculated after each
  successful payout**.
- Eligibility (all must hold, per published rules): **KYC completed**; account
  active and in profit; not in daily/max-loss breach; **no open crypto
  positions**; **no unsettled/disputed** event contracts; no same-asset
  conflict; event-contract data reconciled; account not under abnormal review
  (incl. AI-abuse review); at most **one successful payout per calendar day**;
  amount ≥ minimum and ≤ currently available profit.
- **Final check:** the trading system re-validates the real deductible balance
  at execution — a request can still be rejected here even after passing every
  check above.

> ⚠️ **Three-way conflict on the payout cap.** Whether there's a fixed
> percent-of-account cap is stated inconsistently: the **rules page**
> (2026-07-15) states no % cap (just "once/day" + "≤ available profit"); the
> **FAQ** (`faq-content.ts`) states "5% of account size per cycle, first cycle
> up to 3% soft cap"; the **backend code snapshot** has no cap coded at all
> (also no coded KYC gate). Don't quote a user a specific payout ceiling beyond
> "your available profit, checked at request time" until this is resolved —
> see `challenge-rules.md` for the same caveat with full source citations.

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

Published failure triggers (qa.a9fund.com/rules §08, cross-checked against the
FAQ): hitting the max-loss limit, hitting the daily-loss limit, **trading an
unsupported account or market**, **exceeding the account's max leverage**, and
**abnormal trading / fraud** (the platform may freeze the account for manual
review).

> ⚠️ **§08's "违规失败" (violation-failure) table currently looks corrupted in
> the rules page's i18n source** (re-checked 2026-07-15): its rows are
> byte-for-byte identical to the "暂时阻塞" (blocker) table right below it
> (profitable-days unmet, consistency unmet, open positions, unsettled
> predictions...) — those are blocker conditions, not the real breach causes,
> and the column count doesn't even match the header. The list above (max-loss,
> daily-loss, unsupported market, over-leverage, fraud) is preserved from an
> earlier, uncorrupted read and cross-confirmed by the FAQ ("Max loss breach、
> Daily loss breach、Unauthorized account / symbol、超过账户级杠杆限制、fraud"),
> so it's kept as the more trustworthy list — but this should be reported to
> the content/dev team as a likely authoring bug (see `A9Fund-API-issues.md`).

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
   when cumulative loss is within ~1 pt of the cap (≥ 5% on Fast's 6% cap;
   ≥ 7% on Starter/Standard's 8% cap — always confirm against the account's
   live `max_drawdown_pct`, not just this table).
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

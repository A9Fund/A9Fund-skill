# Challenge rules (A9Fund)

> Sources, most authoritative first: (1) live API responses
> (`/exchange-accounts` risk object, `/event-contracts/context`) — always wins
> when available, and **this file was live-verified on 2026-07-15 across four
> accounts** (two Standard, one Fast, spanning two purchase dates — see the
> vintage-locking finding below); (2) A9Fund's published rules page,
> re-checked 2026-07-15. Sources 1 and 2 have drifted apart on several numbers
> (catalog tiers/pricing, profitable-days count, payout cap) — each is
> flagged below. **No Starter test account was available**, so Starter's
> numbers are still page-sourced, not live-confirmed.

**Architecture premise (decides "who enforces what").** Order placement,
cancellation, and leverage changes go straight to A9Fund's trading backend —
this crate is not on the trade write path. All *real-time* risk (drawdown,
leverage, position, event-contract odds/stake) is enforced there in real
time. Rule parameters (drawdown lines, leverage cap, etc.) are set **once, at
account creation**, and don't retroactively change when the published catalog
updates later — the account keeps whatever it was created with.

> **Confirmed consequence — risk parameters are vintage-locked.** An
> account's actual risk thresholds reflect the catalog *at the time it was
> purchased*, not whatever the catalog says today. Live-verified 2026-07-15:
> two Standard accounts purchased before some date both show
> `max_daily_drawdown_pct = 4`, while a fresh Standard purchase that same day
> shows `= 5` (matching the current published rules page exactly). **Always
> read an account's own live risk fields — never assume a rules-page number
> applies to an account that might predate it.** `risk_status.py` already
> does this correctly (always prefers live data); this note is for anyone
> reading the docs by hand.

## Account paths and tiers

Three paths, six SKUs. Pricing/tiers per the published rules page (re-checked
2026-07-15 — **the catalog has changed more than once**; see the caveat below):

| SKU | Path | Size | Price | Stage(s) | Profit target | Min profitable days | Profit split |
|---|---|---|---|---|---|---|---|
| `starter_2k`    | Starter  | $2,000   | $49  | 1-stage (funded on purchase) | 8%      | 3 | 70% |
| `starter_5k`    | Starter  | $5,000   | $119 | 1-stage                      | 8%      | 3 | 70% |
| `standard_25k`  | Standard | $25,000  | $199 | 2-stage (8% → 5%)            | 8% → 5% | 3 **per phase** | 80% (90% when healthy) |
| `standard_50k`  | Standard | $50,000  | $349 | 2-stage (8% → 5%)            | 8% → 5% | 3 **per phase** | 80% (90% when healthy) |
| `fast_10k`      | Fast     | $10,000  | $179 | 1-stage                      | 10%     | 3 | 85% |
| `fast_25k`      | Fast     | $25,000  | $449 | 1-stage                      | 10%     | 3 | 85% |

- Standard $50K is the default recommended plan.
- Pricing model: one-time challenge fee + funded-account profit split. No
  subscription fee, no extra charge for prediction markets or the AI Assistant;
  **A9 Alpha currently shows a limited-time $100 free AI-assistant credit.**
- Global constants: single-user total account-value quota **$200,000**;
  challenge-stage max leverage **10X**, fund-stage **5X**.

> The `mode` key this skill stores is `starter-5k` / `standard-50k` / `fast-25k`
> etc. `config.py bind` resolves it from `/event-contracts/context`
> (`program_type`) or, failing that, from the `/exchange-accounts` risk
> drawdown signature + capital tier; set it manually with
> `--skip-lookup --mode <...>` if neither resolves it.

> ⚠️ **Catalog keeps changing — treat this table as a snapshot, not a
> constant.** Timeline observed across repeated checks of the same page:
> 2026-07-07 → 6 SKUs (Starter $5k/$10k, Fast $10k/$25k, profit split Fast
> 80%); 2026-07-13 briefly → 8 SKUs (added Standard $100k, Fast $50k);
> 2026-07-15 → back to 6 SKUs but with **Starter retiered to $2k/$5k** and
> **Fast's profit split raised to 85%**, plus new prices for Starter/Fast.
> Standard's tiers/pricing/split have stayed constant throughout. Do not
> hardcode tier assumptions anywhere outside `config.py`'s inference helpers —
> and re-verify this table before relying on it for anything price-sensitive
> (e.g. quoting a user a challenge fee).

## Markets

- **Crypto trading:** first-launch pairs **BTCUSDT, ETHUSDT** (per the
  2026-07-15 rules page — **SOLUSDT has been removed from the launch list**
  since the prior check, which had BTCUSDT/ETHUSDT/SOLUSDT). Account-level
  leverage only, no per-pair leverage. Accounts are **Binance-referenced
  simulation** (real market data, no real exchange orders — `account_type:
  "paper"` in API responses). The FAQ separately lists
  BNB/XRP/DOGE/LINK/AVAX/ADA/SUI as later *candidates*, not commitments —
  trust `markets.py metadata` for what's actually tradeable right now rather
  than any static list here (this one included).
- **Prediction / event contracts:** BTCUSDT, ETHUSDT (see
  `event-contracts.md`, including the total-risk-budget rule). A trading
  position and a prediction on the same crypto must not coexist.
- **Not supported:** political / sports / war / entertainment prediction
  markets, low-liquidity new coins, or any market where slippage / order-book
  depth can't be computed reliably.

## A9 AI Assistant vs. this skill

The **A9 AI Assistant** is the platform's built-in advisory chat: it explains
markets, rules, and risk state, but **does not create bots, submit trade
intents, or place orders**, and cannot bypass KYC, blockers, or risk limits.
This skill is a different thing — it drives the **account-level Agent API**
(the platform's sanctioned programmatic trading path, `/app/agent-api`). Don't
conflate the two when reading the rules page.

## Stage model

- **Starter / Fast** → **fund** stage on purchase (no challenge stage). They are
  effectively funded accounts that still must hit a profit target as the first
  assessment.
- **Standard** → **challenge** stage, two phases (earn 8% in phase 1, then 5% in
  phase 2). On pass it upgrades to a **fund** account.

Leverage cap follows the stage: **challenge 10X, fund 5X**. Because Starter/Fast
are funded from purchase, their cap is **5X**.

## Pass / fail

Passing requires **all of these at the same time** (published §06): profit
target reached, enough profitable days, consistency satisfied, no violation
failure, and no active temporary blocker.

- **Only REALIZED profit counts toward the pass target.** Floating/unrealized
  PnL does not count — an account sitting on a big open winner has NOT passed
  until it realizes the gain. (`risk_status.py`'s `current_pnl_pct` is
  equity-based and includes floating PnL; don't read it as pass progress.)
- **Profitable day** = a UTC calendar day whose **realized** PnL is positive.
- **Consistency:** max single-day profit ≤ **45%** (Starter) / **40%**
  (Standard, measured against the **current phase's** total profit) / **35%**
  (Fast) of total profit. Unmet consistency is a temporary blocker, not a fail.
- **Unsettled prediction-market profit** does not count toward the target.
- **Pass (Standard):** Standard's multi-phase completion is decided by the
  backend risk system, not computed independently by A9Fund.
- **Standard pass upgrade** is blocked while the account has any unsettled /
  disputed / unreconciled event contract — settle those first.
- **Fail:** cumulative drawdown reaching the red line (`cumulative loss% ≥
  max_drawdown_pct`, `≥` triggers) fails the account in real time, backstopped
  by a daily re-check. On fail: challenge fee is **not** refunded, no new
  account is created.

## Minimum profitable days

Starter = **3**, Fast = **3**, Standard = **3 per phase** (published §03/§06).
A profitable day is a UTC calendar day with positive **realized** PnL.

## Inactivity / termination

- **Inactivity: 30 calendar days** with no effective fill → account set
  `inactive`; a warning window opens with <10 days left. Only a real
  executed **fill** counts as activity.
- **No challenge time limit** currently in effect.
- **Real-time breach termination:** a `DRAWDOWN_BREACH` /
  `DAILY_DRAWDOWN_BREACH` event suspends the account, fails the order, and
  freezes its snapshot.

## Leverage caps

- Challenge stage: **10X**. Fund stage: **5X**. This is the account-level cap
  set at account creation.

> ⚠️ **Correction:** an earlier version of this file claimed per-asset
> leverage was "display copy only" with no real enforcement. That was
> **wrong** — the platform genuinely enforces **three** leverage caps combined
> by MINIMUM: the account-level stage cap above, an account-specific max
> (separate from the stage default), and **the symbol's own risk-tier max
> leverage** (currently 100X for BTC-USDT/ETH-USDT, 50X for every other
> listed symbol — see the metadata table below). Today's account-level caps
> (5X/10X) are always the lowest of the three, so they're the ones that
> actually bind — but the symbol tier is a real, live-enforced number, not
> marketing copy. Trust whatever the API accepts at order time.

## Rules that are not enforced by A9Fund's account layer

The following appear in requirement docs / marketing UI but are **not**
independently enforced by A9Fund's own account/business layer — if enforced
at all, it happens in the real-time trading backend:

- Max concurrent positions (docs: Starter 2 / Standard 4 / Fast 3).
- Per-trade risk ≤ 1% / 0.75%; single-position size ≤ 35%/50%/40% of account;
  same-direction exposure ≤ 45%/60%/50%.
- Per-asset leverage table (see the correction above — this one IS real,
  just enforced deeper in the stack than the account layer).

Do not assume A9Fund's own layer will stop you on the unconfirmed ones above —
an order may still be rejected at submission time by the deeper system.

## Payout / profit share

See `references/risk-rules.md` §Payout for the full detail. Summary (published
rules §11, re-checked 2026-07-15):

- **Profit share** (funded-account profit → platform balance). Every request is
  re-validated against current account state, remaining profit, risk record,
  positions, and event-contract status — passing once doesn't guarantee the
  next request passes.
  - **Time window:** first eligibility **14 days after Fund Account
    activation**; then every **14 days** since the last payout. Review target
    **1–3 business days**.
  - **Per-cycle profit target (new, not previously documented):** remaining
    profit must reach **Starter 8% / Fast 10% / Standard 5%**, re-evaluated
    against current remaining profit at each request — this is *in addition
    to* the minimum dollar amount below, not a replacement for it.
  - **Minimum request amount:** **$50** (Starter) / **$100** (Standard, Fast).
  - **Profitable days:** Starter 3 / Standard 3 / Fast 3 (same basis as pass).
  - **Consistency:** same caps as passing (45/40/35%), **recalculated fresh
    after each successful payout**.
  - No daily/max-loss breach; **no open crypto positions**; **no
    unsettled/disputed** event contracts; no same-asset conflict; event-contract
    data reconciled (snapshot + balance); **KYC completed**; account not under
    abnormal review (incl. **AI-abuse review**).
  - **Request limit:** at most **one successful payout per calendar day**;
    requested amount cannot exceed currently available profit.
  - **Final check:** the trading system re-validates the actual deductible
    balance at execution time — a request can still be rejected here even after
    passing every check above, if real profit turns out insufficient.
  - Trader split **70%** (Starter) / **80%** (Standard, up to 90% when
    healthy) / **85%** (Fast). Payout coins **USDC / USDT** (USDC preferred).
- **Wallet withdrawal** (platform balance → chain): minimum **$100** for
  everyone, **1%** fee, withdrawal days **8 / 18 / 28**, networks **ARB / POL /
  BSC**, coins **USDT / USDC**. Mainnet withdrawal is not yet live (testnet
  default; mainnet token contracts are placeholders).

> ⚠️ **Conflict on the payout cap — needs clarification.** Whether there's a
> fixed percent-of-account payout cap is stated inconsistently across
> sources: the current published rules page states no % cap — only "once per
> day" + "≤ currently available profit"; the FAQ page states "Max payout per
> cycle = 5% of account size, first cycle up to 3% soft cap" (not necessarily
> refreshed on the same cadence as the rules page). Until this is resolved,
> do not promise a user a specific payout ceiling beyond "your available
> profit, checked at request time" — quoting the 5%/3% figure risks being
> wrong if the rules page is more current.

## The three iron laws

| Law | How it is enforced |
|---|---|
| 🚫 **Drawdown = out** | Cumulative drawdown is a hard, immediate line on BOTH phases — one hit force-closes and freezes the account. Daily drawdown is much softer and phase-dependent: challenge phase is log-only (never freezes on this alone); fund phase is a rolling 7-day two-strike (1st hit = warning, 2nd = force-close). See `references/risk-rules.md` for the full breakdown. |
| 🚫 **No one-shot clear** | Event contracts need 6 settled before they count; profit target is cumulative, no single trade clears it. |
| 🚫 **Must earn on enough days** | Profitable-days check at pass and at payout (Starter 3 / Standard 3 per phase / Fast 3). |

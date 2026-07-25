# Challenge rules (A9Fund)

> Sources, in the order this file trusts them: (1) live API responses
> (`/exchange-accounts` risk object, `/event-contracts/context`) — always wins
> when available; (2) the published rules page, sourced from its i18n data
> (`frontend-v2/src/messages/{locale}.json` key `marketingRules`, structured
> `navGroups`/`sections`, per `docs/customer_service/knowledge_source.md`) —
> re-checked 2026-07-15; (3) the backend code snapshot
> (`docs/rules-authoritative.md`, `RULES_VERSION = "2026-06-21.v1"`). Sources
> 2 and 3 have drifted apart on several numbers (catalog tiers/pricing, loss
> limits, profitable-days count, payout cap) — each is flagged below.
> **This pass could not be live-verified** (the test API key had expired,
> `401 invalid or expired token`) — re-run the live checks in
> `scripts/config.py bind` / `risk_status.py` once a fresh key is available.

**Architecture premise (decides "who enforces what").** This backend is NOT on
the trade write path — order placement / cancel / leverage go straight from the
front-end to **propdesk** (the external matching + risk engine). All *real-time*
risk (drawdown, leverage, position, event-contract odds/stake) is enforced by
**propdesk**. The backend only (1) publishes rule parameters to propdesk, (2)
records propdesk's terminal results, and (3) does a daily reconciliation pass.
So "the agent must trade within these numbers" — but propdesk is the thing that
actually fails an account.

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
- **Pass (Standard):** the backend trusts propdesk's `final_challenge_pass=True`
  — it does not compute Standard's multi-phase completion itself.
- **Standard pass upgrade** is blocked while the account has any unsettled /
  disputed / unreconciled event contract — settle those first.
- **Fail:** cumulative drawdown reaching the red line (`cumulative loss% ≥
  max_drawdown_pct`, `≥` triggers). propdesk pushes `DRAWDOWN_BREACH` in real
  time; the backend re-checks as a daily backstop. On fail: challenge fee is
  **not** refunded, no new account is created.

## Minimum profitable days

Starter = **3**, Fast = **3**, Standard = **3 per phase** (published §03/§06).
A profitable day is a UTC calendar day with positive **realized** PnL.

> ⚠️ **Code vs published:** the backend snapshot (`rules-authoritative.md`) had
> Starter at **2** days and counted Standard's days with scope `total` (3
> cumulative, not per-phase). The rules page now says Starter needs **3** and
> Standard is per-phase — plan for the stricter published numbers until the
> backend confirms which is authoritative.

## Inactivity / termination

- **Inactivity: 30 calendar days** with no effective fill → account set
  `inactive` (`INACTIVITY_LIMIT_DAYS=30`); a warning window opens with <10 days
  left. Only a real propdesk **fill** counts as activity.
- **No challenge time limit.** The `max_duration_days` field is unset in the
  catalog, so the expiry branch never fires.
- **Real-time breach termination:** propdesk pushes `DRAWDOWN_BREACH` /
  `DAILY_DRAWDOWN_BREACH` → account `suspended_breach`, order failed, snapshot
  frozen.

## Leverage caps

- Challenge stage: **10X**. Fund stage: **5X**. Single scalar per stage — there
  is **no per-asset leverage table in the backend**.

> ⚠️ Front-end pages may show per-asset leverage (e.g. BTC 5X, SOL 3X). That is
> **display copy only** — the backend publishes a single scalar
> (challenge 10 / fund 5). If per-asset caps are enforced, it happens inside
> propdesk. Trust the value propdesk accepts at order time.

## Rules that live only in propdesk (not this backend)

The following appear in requirement docs / UI but are **not** enforced by the
A9Fund backend — if enforced at all, propdesk does it:

- Max concurrent positions (docs: Starter 2 / Standard 4 / Fast 3).
- Per-trade risk ≤ 1% / 0.75%; single-position size ≤ 35%/50%/40% of account;
  same-direction exposure ≤ 45%/60%/50%.
- Per-asset leverage table.

Do not assume the backend will stop you on these — propdesk may reject the order
at submission time instead.

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

> ⚠️ **Three-way conflict on the payout cap — needs dev clarification.**
> Whether there's a fixed percent-of-account payout cap is stated
> inconsistently across sources:
> - **Rules page (2026-07-15, current):** no % cap — only "once per day" +
>   "≤ currently available profit".
> - **FAQ (`faq-content.ts`, same repo, not necessarily same freshness):**
>   "Max payout per cycle = 5% of account size, first cycle up to 3% soft cap."
> - **Backend code snapshot (`rules-authoritative.md`):** no cap coded in the
>   funds path at all (only "≤ available profit"); KYC also not coded there.
>
> Until this is resolved, do not promise a user a specific payout ceiling
> beyond "your available profit, checked at request time" — quoting the 5%/3%
> figure from the FAQ risks being wrong if the rules page is more current.

## The three iron laws

| Law | How it is enforced |
|---|---|
| 🚫 **Drawdown = out** | Cumulative drawdown: propdesk real-time + backend backstop. Daily drawdown: propdesk only — treat any hit as potentially terminal (the published page no longer describes a two-strike alert/breach sequence). |
| 🚫 **No one-shot clear** | Event contracts need 6 settled before they count; profit target is cumulative, no single trade clears it. |
| 🚫 **Must earn on enough days** | Profitable-days check at pass and at payout (Starter 3 / Standard 3 per phase / Fast 3). |

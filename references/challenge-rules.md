# Challenge rules (A9Fund)

> Source of truth: the A9Fund backend code (`backend_next` + `frontend-v2`),
> captured in `docs/rules-authoritative.md`. Rules version (in code):
> `RULES_VERSION = "2026-06-21.v1"`. Where a product/marketing doc disagrees
> with the code, the code wins.

**Architecture premise (decides "who enforces what").** This backend is NOT on
the trade write path — order placement / cancel / leverage go straight from the
front-end to **propdesk** (the external matching + risk engine). All *real-time*
risk (drawdown, leverage, position, event-contract odds/stake) is enforced by
**propdesk**. The backend only (1) publishes rule parameters to propdesk, (2)
records propdesk's terminal results, and (3) does a daily reconciliation pass.
So "the agent must trade within these numbers" — but propdesk is the thing that
actually fails an account.

## Account paths and tiers

Three paths, six SKUs (published rules qa.a9fund.com/rules, Updated 2026-06-24,
re-checked 2026-07-13):

| SKU | Path | Size | Price | Stage(s) | Profit target | Min profitable days | Profit split |
|---|---|---|---|---|---|---|---|
| `starter_5k`    | Starter  | $5,000   | $49  | 1-stage (funded on purchase) | 8%      | 2 | 70% |
| `starter_10k`   | Starter  | $10,000  | $99  | 1-stage                      | 8%      | 2 | 70% |
| `standard_25k`  | Standard | $25,000  | $199 | 2-stage (8% → 5%)            | 8% → 5% | 3 **per phase** | 80% (90% when healthy) |
| `standard_50k`  | Standard | $50,000  | $349 | 2-stage (8% → 5%)            | 8% → 5% | 3 **per phase** | 80% (90% when healthy) |
| `fast_10k`      | Fast     | $10,000  | $149 | 1-stage                      | 10%     | 3 | 80% |
| `fast_25k`      | Fast     | $25,000  | $299 | 1-stage                      | 10%     | 3 | 80% |

- Standard $50K is the default recommended plan.
- Pricing model: one-time challenge fee + funded-account profit split. No
  subscription fee, no extra charge for prediction markets or the AI Assistant;
  **A9 Alpha currently shows a limited-time $100 free AI-assistant credit.**
- Global constants: single-user total account-value quota **$200,000**;
  challenge-stage max leverage **10X**, fund-stage **5X**.

> The `mode` key this skill stores is `starter-5k` / `standard-50k` / `fast-25k`
> etc. `config.py bind` resolves it from `/event-contracts/context`
> (`program_type`) or, failing that, from the `/exchange-accounts` risk drawdown
> signature + capital; set it manually with `--skip-lookup --mode <...>` if
> neither resolves it (e.g. the $10k Starter-vs-Fast overlap).

> ℹ️ The rules page briefly listed Standard $100K ($649) and Fast $50K ($499);
> as of 2026-07-13 those tiers are gone again and the page matches the backend
> catalog's 6 SKUs. `bind`'s fallback inference still tolerates those tiers if
> an account is ever issued at them (thresholds are per-*track*, not per-tier).

## Markets

- **Crypto trading:** initial pairs **BTCUSDT, ETHUSDT, SOLUSDT** (account-level
  leverage only; no per-pair leverage).
- **Prediction / event contracts:** BTCUSDT, ETHUSDT (see
  `event-contracts.md`).
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

Starter = **2**, Fast = **3**, Standard = **3 per phase** (published §03
"固定 每阶段 3"). A profitable day is a UTC calendar day with positive realized
PnL.

> ⚠️ **Code vs published:** the backend snapshot counted Standard's days with
> scope `total` (3 cumulative, not per-phase). The published page says per
> phase — plan for per-phase (the stricter reading) until the backend confirms.

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

See `references/risk-rules.md` §Payout for the full detail. Summary:

- **Profit share** (funded-account profit → platform balance). First eligibility:
  **14 days after the Fund Account is activated**; then once every **14 days**.
  Review target **1–3 business days**. Trader split **70%** (Starter) / **80%**
  (Standard, Fast; up to 90% when healthy). Payout coins **USDC / USDT**.
  - Minimum request: **$50** (Starter) / **$100** (Standard, Fast).
  - **Single-cycle cap: ~5% of account size** (first cycle up to **3%**).
  - Must satisfy **all** of: **KYC completed**; not in daily/max-loss breach; **no
    open crypto positions**; **no unsettled/disputed** event contracts; account
    not under review; request ≥ minimum and ≤ the cycle cap.
- **Wallet withdrawal** (platform balance → chain): minimum **$100** for
  everyone, **1%** fee, withdrawal days **8 / 18 / 28**, networks **ARB / POL /
  BSC**, coins **USDT / USDC**. Mainnet withdrawal is not yet live (testnet
  default; mainnet token contracts are placeholders).

> ⚠️ **Code vs published rules:** the code snapshot (`rules-authoritative.md`)
> did not yet enforce KYC or the 5%/3% cycle cap in the funds path; the public
> rules page (2026-06-24) lists both as requirements. Follow the published rules
> — treat KYC and the cycle cap as real payout gates.

## The three iron laws

| Law | How it is enforced |
|---|---|
| 🚫 **Drawdown = out** | Cumulative drawdown: propdesk real-time + backend backstop. Daily drawdown: propdesk only (two-strike: alert then breach). |
| 🚫 **No one-shot clear** | Event contracts need 6 settled before they count; profit target is cumulative, no single trade clears it. |
| 🚫 **Must earn on enough days** | Profitable-days check at pass and at payout (Starter 2 / Standard 3 / Fast 3). |

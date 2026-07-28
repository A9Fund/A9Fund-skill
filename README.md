# A9Fund Trading Skill

An AI-agent skill for trading on the **A9Fund** prop-trading platform. Works with
Claude Code and other agents that support the Claude skill format. With it
installed you can give natural-language instructions:

> "Buy 0.001 BTC with a stop at 75000"
> "Show my positions and risk status"
> "Buy an UP event contract on BTC for 1 hour, 50 USDT"
> "Close all positions"

and the agent calls the right A9Fund APIs on your behalf — **the API key never
passes through the chat**.

## Install in three steps

The A9Fund account detail page (`/app/agent-api`) generates the exact snippets,
prefilled with your account id:

1. **Install the skill.** Download it from the account detail page and unpack
   into `~/.claude/skills/` (macOS/Linux) or `%USERPROFILE%\.claude\skills\`
   (Windows). In this repo it already lives at
   `.claude/skills/a9fund-skill/`.
2. **Write credentials locally.** Paste the STEP 2 terminal snippet. It writes
   `~/.a9fund/accounts/<account_id>.json` (API key + URLs) on your machine only.
3. **Bind the skill.** Tell the agent *"Initialize account, account_id: xxxxx"*.
   The agent runs `python3 scripts/config.py bind --account-id xxxxx`.

Same `bind` command switches accounts later.

## What's inside

| Component | Purpose |
|---|---|
| `SKILL.md` | Skill entry point — workflow + rules the agent reads |
| `VERSION` | Build stamp (`YYYY-MM-DD.N`) |
| `scripts/` | Python 3.9+ CLIs wrapping the A9Fund HTTP API (zero deps) |
| `references/` | HTTP/WS API, data types, challenge + risk rules, event contracts |

### Scripts

| Script | Purpose |
|---|---|
| `config.py` | Binding: `show`, `list-accounts`, `bind`, `migrate`, `bootstrap` |
| `place_order.py` | MARKET / LIMIT orders, optional attached TP/SL (optional `--reasoning`) |
| `conditional_order.py` | Standalone conditional (trigger) orders: `create` / `list` / `history` / `cancel` |
| `close_position.py` | Close positions via market reduce-only |
| `cancel_order.py` | Cancel single or all regular orders |
| `query.py` | `positions`, `balance`, `open-orders`, `condition-orders`, `history-orders`, `trades`, `pnl-closed`, `leverage`, `accounts` |
| `markets.py` | Public market data: board, search, kline, orderbook, trades, contract, metadata |
| `set_leverage.py` | Adjust leverage (phase cap: challenge 10X / fund 5X) |
| `event_contracts.py` | Prediction market: `context` / `catalog` / `quote` / `order` / `list` / `detail` |
| `risk_status.py` | Risk snapshot: equity + cumulative-loss vs per-track red lines + reminders |
| `auth_check.py` | Validate the key, list authorized accounts |
| `api.py` | Generic HTTP fallback for any endpoint |

## Key rules for the agent

Real-time risk (drawdown, leverage, position/stake caps) is enforced
server-side. Per track:

- **Cumulative loss:** Starter 8%, Standard 8%, Fast 6% (Standard/Fast
  live-verified 2026-07-15 across 4 accounts; always confirm against the
  account's OWN live `max_drawdown_pct` — see `references/risk-rules.md`).
  Reaching this line force-closes and freezes the account on both phases —
  no waiver.
- **Daily loss:** Starter 4%, Standard 5% for accounts purchased after the
  catalog updated / 4% for older ones (risk params are locked in at purchase,
  don't change retroactively), Fast 4%. Enforced differently by phase:
  challenge phase is log-only (never freezes on this alone); fund phase is a
  rolling 7-day two-strike (1st hit = warning, 2nd = force-close).
- **Leverage:** challenge 10X / fund 5X account-level cap (the one that binds
  in practice); a real per-symbol cap also exists (100X BTC/ETH, 50X others),
  combined by taking the minimum of all applicable caps.
- **Rate limit:** 5 orders/sec per account.
- **Profitable days to pass:** Starter 3, Standard 3 per phase, Fast 3.
- **Event contracts:** count toward passing only after 6 settled; any
  open/disputed contract blocks pass + payout.
- **Inactivity:** suspended after 30 days without a real fill.

Full detail in [references/risk-rules.md](references/risk-rules.md) and
[references/challenge-rules.md](references/challenge-rules.md).

## Privacy model

- **The API key never reaches the AI.** The STEP 2 snippet writes it to a local
  file; scripts read it from disk in a subprocess. The chat context only sees the
  account id.
- **Server URLs are pinned in the credential file** — switch environments by
  re-pasting STEP 2, no code edit.
- **Sandboxable.** Deny direct reads of `~/.a9fund/accounts/**` in
  `.claude/settings.json` to keep the agent from ever ingesting the key bytes.

## Notes & caveats

Built around the A9Fund API surface (account detail page `/app/agent-api`)
and A9Fund's published rules: Starter/Standard/Fast tracks and their
thresholds; optional (not required) reasoning on orders; the dedicated
`/conditional-orders` resource; and the Event Contracts feature.

**Verified end-to-end against a test API environment** — every script and
endpoint was live-tested, which surfaced and fixed several real issues:

- The gateway is behind **Cloudflare Browser Integrity Check**, which 403-blocked
  the default urllib User-Agent (`error 1010`). Fixed on the Cloudflare side (a
  configuration rule skips BIC for the API hosts); the client also sends a
  self-identifying `a9fund-skill/<version>` UA (override via `A9FUND_USER_AGENT`).
- `/exchange-accounts` carries **no `program_id`**; `bind` infers the track from
  the risk drawdown signature + capital, and `risk_status` prefers the account's
  own live risk thresholds.
- `createOrder` attaches TP/SL via **flat fields** (`tp_trigger_price` etc.),
  while `/conditional-orders` uses the **`open_tp_param`/`open_sl_param` objects**
  — the docs page's table was misleading; both are now correct.
- Live API uses the `{code,msg,data}` envelope (the bare examples were
  illustrative).

Event-contract `quote`/`order` bodies were confirmed live; `api.py` and `--extra`
remain as escape hatches for any field the backend later changes.

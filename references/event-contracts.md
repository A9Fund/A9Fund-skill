# Event Contracts (prediction market)

A9Fund-only feature (the reference propdesk skill does not have it). A binary
contract: pick a **direction** (UP / DOWN) on a **symbol** over a fixed
**duration**; on a win you receive a fixed **80% payout**, otherwise you lose the
**premium** (stake).

## Rules

Per the published rules (qa.a9fund.com/rules, §09) — these are real limits, and
the `/event-contracts/context` endpoint returns the account's concrete bounds at
runtime (verified live):

| Rule | Value |
|---|---|
| Symbols | `BTCUSDT`, `ETHUSDT` |
| Direction | `UP`, `DOWN` |
| Duration | `10m`, `30m`, `1h`, `1d` |
| Odds band | **0.2 – 0.8** |
| Stake per contract | **0.5% – 2% of account equity** (live: `min_premium` = 10 USDT; `max_single_premium` = 2% of equity) |
| Max concurrent open | **3** (`max_open_count`) |
| Same underlying | **at most 1 open** per symbol / strongly-correlated event |
| **Trading ↔ prediction exclusivity** | A trading position and prediction exposure on the **same crypto must not stack** — holding a BTC-USDT position blocks a BTCUSDT prediction, and vice versa (FAQ: "同 crypto 的交易仓位与 prediction exposure 不得互相叠加") |
| Payout on win | fixed **80%** (`payout_rate` 0.8); loss forfeits the premium |

Before placing an order, call `context` / `quote` — `quote` returns
`can_place_order` and `blockers`, and `context.event_contract` gives
`available_premium`, `max_single_premium`, `open_count`, `event_risk_available`.
Respect those live numbers rather than hardcoding.

> ⚠️ **Agent pitfall — same-asset exclusivity.** Before buying a prediction,
> check `query.py positions`: if the account already holds a trading position on
> that crypto (e.g. BTC-USDT), do NOT place a BTCUSDT prediction — and don't
> open a trading position on a crypto that has an open prediction. The
> `same_asset_conflict` flag this produces blocks pass/payout until resolved.

**Activation (assessment interaction):**
- Event-contract profit counts toward passing the challenge **only after 6
  settled contracts** (`EVENT_CONTRACT_ACTIVATION_SETTLED_COUNT = 6`; WIN/LOSS
  count as settled). Before activation, event profit does not count toward the
  pass target.
- Settled **losses** always reduce account equity (and count toward the loss
  limits); settled **wins** add to equity.
- Any **open or disputed** contract blocks both challenge pass and payout until
  it settles — note this gate is *stricter* than the "3 open" cap: **any** open
  contract blocks pass/payout.

> Enforcement note: the A9Fund backend directly enforces the activation-6 gate,
> the input whitelist, and the pass/payout blockers; the quantitative bounds
> (odds / stake / max-open / same-symbol) are applied at the quote/propdesk
> layer and surfaced through `context`/`quote`. Either way they are real — an
> out-of-band order is rejected.

## Flow

```
1. context   GET  /event-contracts/context?account_id=<id>    -> account play context
2. catalog   GET  /event-contracts/catalog?account_id=<id>    -> available contracts
3. quote     POST /event-contracts/quote                      -> price preview (may return a quote_id)
4. order     POST /event-contracts/orders                     -> submit
5. list      GET  /event-contracts/orders?account_id=<id>&status=all&page=1&page_size=20
6. detail    GET  /event-contracts/orders/{order_id}?account_id=<id>
```

> These endpoints scope by **`account_id`** (not `exchange_account_id`).

## Script usage

```bash
python3 scripts/event_contracts.py context
python3 scripts/event_contracts.py catalog
python3 scripts/event_contracts.py quote  --symbol BTCUSDT --direction UP   --duration 1h --premium 50
python3 scripts/event_contracts.py order  --symbol BTCUSDT --direction UP   --duration 1h --premium 50 [--quote-id <id>]
python3 scripts/event_contracts.py list   [--status all] [--page 1] [--page-size 20]
python3 scripts/event_contracts.py detail --order-id <id>
```

## Request-body caveat

The exact field names for `quote` / `order` bodies are not published on the API
docs page. `event_contracts.py` assembles `{account_id, symbol, direction,
duration, premium[, quote_id]}`, which matches the documented inputs. If the
backend expects different names, pass extra/override fields:

```bash
# merge extra fields into the body
python3 scripts/event_contracts.py order --symbol BTCUSDT --direction UP --duration 1h --premium 50 \
  --extra '{"stake":"50","idempotency_key":"ec-001"}'

# or bypass entirely with the generic caller
python3 scripts/api.py POST /event-contracts/orders --json '{"account_id":"<id>","symbol":"BTCUSDT",...}'
```

Confirm the live `catalog` / `quote` responses to learn the precise contract ids
and body shape before placing real orders.

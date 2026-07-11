# HTTP API reference (A9Fund)

> Base URL: the public trading REST prefix shown on the A9Fund account detail
> page (`/app/agent-api`), stored as `base_url_http` in
> `~/.a9fund/accounts/<id>.json`. This file is the agent quick-ref + curl
> fallback; the scripts in `../scripts/` wrap the same endpoints.

## Common

### Authentication

Every Private endpoint (everything except `/markets/*`) requires:

```
Authorization: Bearer <api_key>
```

The API key (`af_...`) comes from the account detail page and is written into
the credential file by the STEP 2 terminal snippet. To extract for curl:

```bash
KEY=$(python3 -c 'import json,os,glob; f=sorted(glob.glob(os.path.expanduser("~/.a9fund/accounts/*.json")))[0]; d=json.load(open(f)); print(d.get("api_key") or d.get("token"))')
ACCT=$(python3 -c 'import json,os,glob; f=sorted(glob.glob(os.path.expanduser("~/.a9fund/accounts/*.json")))[0]; print(json.load(open(f))["exchange_account_id"])')
BASE=$(python3 -c 'import json,os,glob; f=sorted(glob.glob(os.path.expanduser("~/.a9fund/accounts/*.json")))[0]; print(json.load(open(f))["base_url_http"])')
```

### User-Agent

The scripts send a self-identifying `User-Agent` (`a9fund-skill/<version>`, via
`_common.py`; override with the `A9FUND_USER_AGENT` env var) rather than the
anonymous urllib default. The API domains (`qa-api` / `api.a9fund.com`) sit
behind Cloudflare with a configuration rule that skips Browser Integrity Check,
so any UA is accepted — but a descriptive UA is good practice and future-proofs
against WAFs that flag the `Python-urllib` signature.

### Response envelope

The live API returns the **enveloped** shape `{"code": 0, "msg": "ok", "data":
{...}}` (the bare bodies shown on the docs page are illustrative). Errors return
`{"code": <biz>, "msg": "..."}` (some edge/auth errors use `{"detail": "..."}`).
The scripts tolerate all of these — they unwrap `data` when present and read
`msg`/`detail` on failure.

### Error codes

| HTTP | Code | Meaning |
|---|---|---|
| 400 | 10001 | Invalid or missing parameters |
| 401 | 10002 | Authentication failed (key invalid or expired) |
| 403 | 10003 | Permission denied (cannot access this account) |
| 404 | 10004 | Resource not found |
| 409 | 10006 | Resource already exists (idempotency conflict) |
| 400 | 10007 | Precondition failed (insufficient balance / frozen account) |
| 429 | 10008 | Too many requests (max 5 orders/sec per account) |
| 500 | 10005 | Internal server error |

Auth error `detail` strings you may see: `missing or invalid authorization
header`, `invalid or expired token`, `access denied for this exchange account`.

---

## Trading (Private)

### POST /createOrder — regular MARKET / LIMIT

```bash
curl -X POST $BASE/createOrder \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "exchange_account_id": "'$ACCT'",
    "client_order_id": "agent-'$(date +%s%3N)'",
    "symbol": "BTC-USDT",
    "side": "BUY",
    "size": "0.01",
    "order_type": "MARKET"
  }'
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `exchange_account_id` | string | ✓ | The account id from the account detail page |
| `client_order_id` | string | ✓ | Idempotency key; keep it stable when retrying the same order |
| `symbol` | string | ✓ | e.g. `BTC-USDT`, `ETH-USDT` |
| `side` | string | ✓ | `BUY` / `SELL` |
| `size` | string | ✓ | Contract quantity as a string, e.g. `"0.01"` |
| `order_type` | string | ✓ | `MARKET` / `LIMIT` |
| `price` | string | LIMIT | Required for `LIMIT` (must be > 0) |
| `time_in_force` | string | — | `GTC` / `FOK` / `IOC` / `POST_ONLY` (LIMIT defaults GTC) |
| `reduce_only` | bool | — | `true` = reduce-only |
| `is_open_tpsl_order` | bool | — | `true` to attach TP/SL to this entry |
| `is_set_open_tp` / `is_set_open_sl` | bool | tpsl | Required `true` for whichever leg is attached |
| `tp_trigger_price` / `tp_trigger_price_type` | string | tpsl | Take-profit trigger (`MARK` / `MARKET` / `INDEX`) |
| `sl_trigger_price` / `sl_trigger_price_type` | string | tpsl | Stop-loss trigger |
| `reasoning` | string | — | **Optional** on A9Fund. ≤ 4096 bytes UTF-8 if provided |

> ⚠️ **`createOrder` uses FLAT TP/SL fields** (`tp_trigger_price` etc.), verified
> against the live API — NOT the `open_tp_param`/`open_sl_param` objects. (The
> objects are used by the separate `/conditional-orders` resource below.)
> Sending only `is_open_tpsl_order` returns `10001 "requires at least one of
> is_set_open_tp/is_set_open_sl"`; sending the flags without prices returns
> `10001 "tp_trigger_price is required when is_set_open_tp=true"`.

Open with attached TP/SL (OCO pair):

```bash
curl -X POST $BASE/createOrder \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "exchange_account_id": "'$ACCT'",
    "client_order_id": "agent-'$(date +%s%3N)'",
    "symbol": "BTC-USDT", "side": "BUY", "size": "0.001", "order_type": "MARKET",
    "is_open_tpsl_order": true,
    "is_set_open_tp": true, "tp_trigger_price": "80000", "tp_trigger_price_type": "MARK",
    "is_set_open_sl": true, "sl_trigger_price": "75000", "sl_trigger_price_type": "MARK"
  }'
```

Response: `{"code":0,"msg":"ok","data":{"order_id":"1234567890","status":"OPEN"}}`.
The entry's embedded `take_profit[]` / `stop_loss[]` arrays (in `openOrders`)
carry the leg `order_id`s; cancelling the entry cascade-cancels them.

### POST /cancelOrder — single (regular order)

```bash
curl -X POST $BASE/cancelOrder \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"exchange_account_id":"'$ACCT'","exchange_order_id":"1234567890","symbol":"BTC-USDT","trace_id":"cancel-001"}'
```

> ⚠️ Despite the field name, put the A9Fund **`order_id`** (from the create
> response or `/openOrders`) into `exchange_order_id`. On the paper venue the
> real `exchange_order_id` is usually `""`, so `order_id` is the id you cancel by.
> (`cancel_order.py --order-id` takes that `order_id`.)

### POST /cancelOrders — batch by symbol

```bash
curl -X POST $BASE/cancelOrders \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"exchange_account_id":"'$ACCT'","symbol":"BTC-USDT"}'
```

### POST /setLeverage

```bash
curl -X POST $BASE/setLeverage \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"exchange_account_id":"'$ACCT'","symbol":"BTC-USDT","leverage":5,"margin_mode":"CROSS"}'
```

> Caps: challenge phase 10X / fund phase 5X. propdesk rejects an over-cap order.

### Conditional (trigger) orders — dedicated resource

Standalone stop / take-profit entry orders live under `/conditional-orders`
(distinct from attached TP/SL and from the `/conditionOrders` query view).

```bash
# Create
curl -X POST $BASE/conditional-orders \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "exchange_account_id": "'$ACCT'",
    "symbol": "ETH-USDT", "side": "BUY", "size": "1",
    "trigger_price": "1582.77", "trigger_price_type": "MARKET",
    "trigger_direction": "GTE", "trigger_order_type": "LIMIT", "order_price": "1583",
    "reduce_only": false, "trace_id": "cond-001",
    "is_open_tpsl_order": true,
    "open_tp_param": { "trigger_price": "1700", "trigger_price_type": "MARKET" },
    "open_sl_param": { "trigger_price": "1500", "trigger_price_type": "MARKET" }
  }'

curl "$BASE/conditional-orders?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"          # list active
curl "$BASE/conditional-orders/history?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"  # history
curl -X DELETE "$BASE/conditional-orders/<id>?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"  # cancel one
```

- `trigger_direction`: `GTE` fires when price rises to/above the trigger; `LTE`
  when it falls to/below.
- After a conditional order triggers, the resulting regular order is linked via
  `triggered_order_id`.

> **Two similarly-named views — don't confuse them:**
> - `GET /conditional-orders` (dashed) = **active** standalone conditional
>   orders only (UNTRIGGERED). `/conditional-orders/history` for the rest.
>   Driven by `conditional_order.py list` / `history`.
> - `GET /conditionOrders` (camelCase) = **mixed** view: TP/SL legs + trigger
>   orders **including** history (TRIGGERED / CANCELED). Driven by
>   `query.py condition-orders`.

---

## Queries (Private)

```bash
curl "$BASE/positions?exchange_account_id=$ACCT&symbol=BTC-USDT" -H "Authorization: Bearer $KEY"
curl "$BASE/portfolio/balances?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"
curl "$BASE/openOrders?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"     # regular orders; entry rows embed take_profit[]/stop_loss[]
curl "$BASE/conditionOrders?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY" # MIXED: TP/SL + trigger orders incl. history
curl "$BASE/historyOrders?exchange_account_id=$ACCT&page=1&limit=20" -H "Authorization: Bearer $KEY"
curl "$BASE/trades?exchange_account_id=$ACCT&page=1&limit=20" -H "Authorization: Bearer $KEY"
curl "$BASE/pnl/closed?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"
curl "$BASE/getLeverage?exchange_account_id=$ACCT" -H "Authorization: Bearer $KEY"
curl "$BASE/exchange-accounts" -H "Authorization: Bearer $KEY"   # account list + per-account risk sub-object
```

Common query params: `exchange_account_id` (required on private query
endpoints), `symbol` (optional filter), `page` / `limit` (pagination).

See `data-types.md` for balance / position / order / risk field definitions.

---

## Market data (Public, no auth)

```bash
curl "$BASE/markets/board"
curl "$BASE/markets/search?keyword=BTC"
# Resolve the active venue first, then pass it as exchange=
EXCH=$(curl -s "$BASE/market/metadata" | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("data") or d).get("active_exchange"))')
curl "$BASE/markets/kline?exchange=$EXCH&symbol=BTC-USDT&interval=1m&limit=100"
curl "$BASE/markets/orderbook?exchange=$EXCH&symbol=BTC-USDT"
curl "$BASE/markets/trades?exchange=$EXCH&symbol=BTC-USDT"
curl "$BASE/markets/contracts/$EXCH/BTC-USDT/summary"
curl "$BASE/market/metadata"
```

> ⚠️ The kline param is **`interval`**, NOT `timeframe` (the public WebSocket
> `ohlcv` topic uses `timeframe`). Valid intervals:
> `1m / 3m / 5m / 15m / 30m / 1h / 2h / 4h / 6h / 8h / 12h / 1d / 3d / 1w / 1M`.
> `exchange` is optional; the server maps a stale name to the active hub and
> always returns the active name in the response.

---

## Event Contracts (Private)

See `event-contracts.md` for the full flow and rules. Endpoints:

```bash
curl "$BASE/event-contracts/context?account_id=$ACCT" -H "Authorization: Bearer $KEY"
curl "$BASE/event-contracts/catalog?account_id=$ACCT" -H "Authorization: Bearer $KEY"
curl -X POST $BASE/event-contracts/quote  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{...}'
curl -X POST $BASE/event-contracts/orders -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{...}'
curl "$BASE/event-contracts/orders?account_id=$ACCT&status=all&page=1&page_size=20" -H "Authorization: Bearer $KEY"
curl "$BASE/event-contracts/orders/<order_id>?account_id=$ACCT" -H "Authorization: Bearer $KEY"
```

> Event-contract endpoints scope by **`account_id`** (not `exchange_account_id`).

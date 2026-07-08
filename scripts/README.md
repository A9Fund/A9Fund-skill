# A9Fund Trading Skill — Scripts

Python 3.9+. No third-party dependencies (stdlib `urllib` only).

## Storage layout

- `~/.a9fund/accounts/<exchange_account_id>.json` — credentials only:
  ```json
  {
    "api_key": "af_...",
    "exchange_account_id": "2043740741521514496",
    "base_url_http": "https://<A9FUND_HOST>/api/v1",
    "base_url_ws_private": "wss://<A9FUND_HOST>/realtime_private",
    "base_url_ws_public": "wss://<A9FUND_HOST>/realtime_public"
  }
  ```
  Written by the STEP 2 terminal snippet (one file per account). The legacy key
  name `token` is also accepted in place of `api_key`.

- `<skill-root>/state.json` — per-skill runtime state:
  ```json
  {
    "active_account_id": "2043740741521514496",
    "mode": "standard-25k",
    "phase": "challenge",
    "initial_balance": 25000,
    "active_exchange": "binance"
  }
  ```
  Written by `config.py bind`.

One skill install = one bound account. Install twice to run two in parallel.

## First-time setup (keeps the API key out of the agent)

1. On the A9Fund account detail page (`/app/agent-api`), paste the STEP 2
   terminal snippet into your terminal. It writes
   `~/.a9fund/accounts/<account_id>.json`.
2. Ask your AI agent: *"Initialize account, account_id: <id>"*. The agent runs:
   ```bash
   python3 config.py bind --account-id <id>
   ```
   which reads mode/phase/baseline from `/exchange-accounts` and writes
   `state.json`. Same command switches accounts later.

Legacy (key passes through the agent): `python3 config.py bootstrap --api-key af_...`.

## Command cheatsheet

| Purpose | Command |
|---|---|
| Show current binding | `python3 config.py show` |
| List available accounts | `python3 config.py list-accounts` |
| Bind / switch account | `python3 config.py bind --account-id <id>` |
| Manual bind | `python3 config.py bind --account-id <id> --skip-lookup --mode standard-25k --phase challenge --initial-balance 25000` |
| Validate key | `python3 auth_check.py` |
| Place MARKET/LIMIT | `python3 place_order.py --symbol BTC-USDT --side BUY --order-type LIMIT --size 0.1 --price 60000` |
| Open with attached TP/SL | `python3 place_order.py --symbol BTC-USDT --side BUY --order-type MARKET --size 0.001 --tp-price 80000 --sl-price 75000` |
| Standalone conditional | `python3 conditional_order.py create --symbol ETH-USDT --side BUY --size 1 --trigger-price 1582.77 --trigger-direction GTE --trigger-order-type LIMIT --order-price 1583` |
| List conditional orders | `python3 conditional_order.py list` |
| Cancel conditional order | `python3 conditional_order.py cancel --id <id>` |
| Close position | `python3 close_position.py --symbol BTC-USDT` / `--all` |
| Cancel one regular order | `python3 cancel_order.py --order-id 123 --symbol BTC-USDT` |
| Cancel all (by symbol) | `python3 cancel_order.py --all --symbol BTC-USDT` |
| Set leverage | `python3 set_leverage.py --symbol BTC-USDT --leverage 5` |
| Positions | `python3 query.py positions [--symbol ...]` |
| Balance | `python3 query.py balance` |
| Open orders | `python3 query.py open-orders` |
| Condition orders | `python3 query.py condition-orders` |
| History orders | `python3 query.py history-orders [--symbol ...] [--page 1] [--limit 20]` |
| Trades | `python3 query.py trades` |
| Closed PnL | `python3 query.py pnl-closed` |
| Leverage config | `python3 query.py leverage` |
| Accounts + risk | `python3 query.py accounts` |
| Market board | `python3 markets.py board` |
| Metadata (active_exchange) | `python3 markets.py metadata` |
| Kline | `python3 markets.py kline --symbol BTC-USDT --interval 1m --limit 100` |
| Orderbook | `python3 markets.py orderbook --symbol BTC-USDT` |
| Event contract catalog | `python3 event_contracts.py catalog` |
| Event contract quote | `python3 event_contracts.py quote --symbol BTCUSDT --direction UP --duration 1h --premium 50` |
| Event contract order | `python3 event_contracts.py order --symbol BTCUSDT --direction UP --duration 1h --premium 50` |
| Event contract list | `python3 event_contracts.py list` |
| Risk snapshot | `python3 risk_status.py` |
| Generic fallback | `python3 api.py GET /xxx [--query "a=1"]` or `POST /xxx --json '{...}'` |

`markets.py` `--exchange` is optional — it defaults to `active_exchange` from
`/market/metadata`. Event-contract endpoints scope by `account_id` (not
`exchange_account_id`); `api.py --inject-account --account-key account_id` injects it.

## Failure fallback

1. Generic caller: `python3 api.py <METHOD> <PATH>`.
2. curl from `../references/api-http.md`. The key lives in
   `~/.a9fund/accounts/<id>.json`.

## Conventions

- Output: success → JSON to stdout; failure → stderr + non-zero exit.
- Money fields are strings; timestamps are int64 microseconds.
- Response envelope tolerated both enveloped (`{code,msg,data}`) and bare
  (`{...}` / `{"detail":...}`).
- HTTP errors map to friendly hints (401 → key invalid, 403 → permission,
  429 → rate limit).

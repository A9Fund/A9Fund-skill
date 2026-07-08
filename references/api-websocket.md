# WebSocket reference (A9Fund)

> WebSocket is out of scope for the MVP scripts (the skill ships no WS client —
> Python stdlib has none and the skill avoids third-party deps). For most
> workflows (orders, balance, positions, klines) the HTTP endpoints in
> `api-http.md` are enough. If you need live push streams, hand-roll from this
> doc. The private gateway URLs come from the account detail page and are stored
> as `base_url_ws_private` / `base_url_ws_public` in the credential file.

## Private WS (orders / positions / balance / trades)

**URL:** `wss://<private-gateway>/realtime_private[?user_mark=agent]`

### Flow

```
1. Open the connection
2. Send login (with the API key)
3. Receive login success
4. Subscribe to topics
5. Receive snapshot, then live events
6. Heartbeat both ways
```

```javascript
const ws = new WebSocket("wss://<private-gateway>/realtime_private?user_mark=agent");

ws.onopen = () => {
  ws.send(JSON.stringify({ type: "login", args: ["af_xxxxxxxxxxxxxxxx"] })); // API key
};

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "login" && msg.msg === "success") {
    ws.send(JSON.stringify({ type: "subscribe", args: ["order", "position", "balance", "trade"] }));
  }
  if (msg.type === "snapshot") console.log("snapshot:", msg.topic, msg.data);
  if (msg.type === "event")    console.log("event:", msg.event_type, msg.data);
};

setInterval(() => ws.send(JSON.stringify({ type: "ping" })), 20000); // keepalive
```

### Topics

| Topic | Event types | Notes |
|---|---|---|
| `order` | `order_created` / `order_filled` / `order_canceled` | Order status updates |
| `position` | `position_opened` / `position_closed` / `position_updated` | Position changes |
| `balance` | `balance_updated` | Balance changes |
| `trade` | `trade_created` | Fill events |

A snapshot is auto-pushed after a successful subscribe. Heartbeat: client sends
`{"type":"ping"}` every 15–20s; server replies `{"type":"pong"}`.

## Public WS (market data)

**URL:** `wss://<public-gateway>/realtime_public` (no auth)

```json
{"action":"subscribe","exchange":"binance","topic":"ohlcv","symbol":"BTC-USDT","timeframe":"1m"}
```

| Topic | Required parameters |
|---|---|
| ticker | exchange (symbol optional) |
| orderbook | exchange + symbol |
| trades | exchange + symbol |
| ohlcv | exchange + symbol + **timeframe** (1m / 5m / 1h / 1d) + optional limit |

> The public `ohlcv` topic uses **`timeframe`**, while the HTTP `/markets/kline`
> endpoint uses **`interval`** — don't conflate them. Use the `active_exchange`
> from `GET /market/metadata` for the `exchange` value; the server tolerates a
> stale name and echoes the active one back.

## Tooling notes

- **Preferred:** if the user has `wscat` (`npm i -g wscat`) or `websocat`, drive
  it with the JSON frames above.
- **Only if the user opts in:** `pip install websockets` per session. Do not
  assume it is present.

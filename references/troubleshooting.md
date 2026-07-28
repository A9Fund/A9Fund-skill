# Troubleshooting: real incidents and their fixes

## Stray LIMIT order left open after adding TP/SL to an existing position

**Reported symptom:** the skill opened an order; the user then asked to add
take-profit/stop-loss; the skill created a conditional order for it; after the
position was later sold, a leftover LIMIT BUY order was still sitting open.

**Root cause:** `place_order.py --tp-price/--sl-price` only attaches TP/SL to
a **new** entry order at creation time. For an already-open position, the
only mechanism is a standalone conditional order (`/conditional-orders`). The
backend only force-sets `reduce_only=true` when `trigger_order_type` is
`STOP_*` or `TAKE_PROFIT_*` — **a plain `LIMIT`/`MARKET` `trigger_order_type`
is always treated as a standard conditional ENTRY order** (`reduce_only`
stays whatever the caller passed, `false` by default) and is never
auto-corrected. If an agent free-hands `conditional_order.py create` to
"protect" a position using `--trigger-order-type LIMIT` (e.g. meaning "exit
at this limit price") instead of the correct `TAKE_PROFIT_MARKET` /
`STOP_MARKET` classification, the resulting order is never recognized as
reduce-only TP/SL by the backend — it is a genuine entry-type LIMIT order
that can sit in the book on the wrong side indefinitely, exactly matching the
reported symptom.

**Investigation:** the A9Fund web trading terminal has a dedicated "Position
TP/SL" dialog. Watching its actual network requests confirmed **there is no
separate "attach to position" API** — it hits the exact same
`/conditional-orders` endpoint this skill already wraps, just with
hardcoded-safe parameters: `side` = the position's closing side, `size` =
full position quantity, `trigger_order_type` always
`TAKE_PROFIT_MARKET`/`STOP_MARKET` (never `LIMIT`), `reduce_only` always
`true`, and existing legs for that position always cancelled before creating
new ones. A9Fund's own API confirms there is no merged position-TP/SL
endpoint: setting both legs on an existing position means two separate
`POST /conditional-orders` calls — exactly what the web dialog (and now this
skill) does.

Also confirmed: sending `is_position_tpsl: true` on `createOrder` is
**explicitly rejected by the API** (not currently supported). Don't be misled
by that field name into thinking there's a simpler "attach to position"
mechanism than there is.

**Fix:** added `conditional_order.py set-position-tpsl --symbol <sym>
[--tp-price X] [--sl-price Y]`, reproducing the web dialog's exact behavior.
**This is now the only sanctioned way to add or change TP/SL on an
already-open position** — see SKILL.md's TP/SL mental model.

**A second bug found while building the fix:** cancelling *all* of a
position's existing TP/SL legs before creating new ones (matching the web
dialog's raw behavior) but only recreating the explicitly-passed price
silently dropped the OTHER leg when only one of `--tp-price`/`--sl-price` was
given. Fixed: the subcommand reads existing legs *before* cancelling and
re-creates any leg the caller didn't touch (or explicitly clears with
`--clear-tp`/`--clear-sl`). Live-verified: create TP+SL → update SL only (TP
preserved) → `--clear-tp` (TP actually removed).

## Standalone TP/SL legs are not OCO-paired with each other

If you set a standalone TP and a standalone SL as two separate conditional
orders (which is the *only* way to set TP/SL on an already-open position —
see above), and one of them **triggers** (fires because the price hit it,
closing the position), **the other one is not automatically cancelled**. It
keeps resting and could later misfire — e.g. against a brand new, unrelated
position opened on the same symbol afterward.

(This is different from *attached* TP/SL set at entry time via
`place_order.py --tp-price/--sl-price`, which **is** a true OCO pair — only
the standalone/`set-position-tpsl` path lacks this.)

**Mitigation added:** `close_position.py` now cancels any remaining active
reduce_only conditional orders on a symbol (matching the position's closing
side) immediately after closing it via a direct MARKET order — a safety net
for the case where a stale sibling leg was left resting for any reason. Pass
`--keep-tpsl` to skip this.

**What live testing actually showed (be precise about this, don't overclaim):**
in a real test — set TP+SL via `set-position-tpsl`, then close the position
with `close_position.py`'s own MARKET order (not by letting either leg
trigger) — the sibling legs were **already gone** by the time the cleanup
step queried for them (`cancelled_stale_tpsl: []`, and a follow-up
`conditional_order.py list` showed zero active orders). This suggests the
backend has its own housekeeping that invalidates reduce-only conditional
orders once the position they'd reduce goes flat, at least for a **direct
external close** — separately from the specific no-OCO gap described above
for the **one-leg-triggers** case, which this particular test didn't
reproduce. This skill's cleanup step in `close_position.py` was NOT observed
to be load-bearing in this test; keep it as a defensive, no-op-if-unnecessary
safety net.

## Client-side retry safety: always reuse `client_order_id`

Attached TP/SL is created *after* the entry order is already accepted, so if
that TP/SL creation step fails, **the entry order may already exist** even
though the overall call returned an error. `(exchange_account_id,
client_order_id)` is the idempotency key — a retry with the *same*
`client_order_id` safely returns the original order instead of creating a
duplicate.

**Implication for the agent:** if a `place_order.py` call errors out (network
timeout, an attach-TP/SL failure after the entry was accepted, etc.), do
**not** just call it again — that generates a **new** auto client_order_id
(`agent-{ms}-{uuid}`) and risks placing a genuine duplicate entry. Instead,
either (a) check `query.py open-orders` / `history-orders` for whether the
entry already exists before retrying, or (b) retry with the exact same
`--client-order-id` explicitly passed the first time.

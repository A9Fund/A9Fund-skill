# Troubleshooting: real incidents and their fixes

## Stray LIMIT order left open after adding TP/SL to an existing position

**Reported symptom:** the skill opened an order; the user then asked to add
take-profit/stop-loss; the skill created a conditional order for it; after the
position was later sold, a leftover LIMIT BUY order was still sitting open.

**Root cause:** `place_order.py --tp-price/--sl-price` only attaches TP/SL to a
**new** entry order at creation time. It has no way to retroactively attach to
a position that's already open. The only mechanism for that is a standalone
order via `/conditional-orders` (`conditional_order.py create`) — but that
subcommand takes `--side`, `--size`, and `--reduce-only` as free parameters. If
an agent free-hands it to "protect" an existing position without getting all
three exactly right (side = the CLOSING side, opposite the position; size =
the full position quantity; `reduce_only = true`), the resulting order can end
up on the **wrong side** or **not reduce-only**. If it triggers (or the
position is separately closed by other means) while that order is still
resting, it can execute as a plain directional order rather than a close — a
BUY-side conditional with a LIMIT trigger type, for example, surfaces exactly
as "a leftover LIMIT BUY order" once the market has moved away from its price.

**Investigation:** the A9Fund web terminal has a dedicated "Position TP/SL"
dialog (`frontend-v2/src/app/app/terminal/position-tpsl-modal.tsx` +
`terminal-tpsl.ts`, `src/lib/api-trading.ts`). Reverse-engineering its actual
network calls showed **there is no separate "attach to position" API** — it
calls the exact same `/conditional-orders` endpoint this skill already uses,
just with hardcoded-safe parameters:
- `side`: always the position's closing side (SELL for LONG, BUY for SHORT).
- `size`: always the position's full quantity.
- `trigger_order_type`: always `take_profit_market` / `stop_market` (never
  `limit`).
- `reduce_only`: always `true`.
- Before creating new legs, it **cancels every existing TP/SL conditional
  order for that position first** — so re-opening the dialog and resubmitting
  never stacks duplicate legs.
- The dialog also **pre-fills both TP and SL fields from any existing legs**,
  so "I only want to change the stop-loss" naturally resubmits the unchanged
  take-profit value too, rather than dropping it.

There is no dedicated field like `is_position_tpsl` in what A9Fund's own
`/app/agent-api` docs page publishes (only `is_open_tpsl_order` for
attach-on-entry is documented there) — despite that name existing in the
internal `CreateOrderBody` type (`src/lib/api-trading.ts`), it isn't what the
position-TP/SL feature actually uses in practice, per the modal's real
network calls. Don't be misled by that field name into thinking there's a
simpler mechanism than there is.

**Fix:** added `conditional_order.py set-position-tpsl --symbol <sym>
[--tp-price X] [--sl-price Y]`, which reproduces the web dialog's exact
behavior: reads the current position, derives side/size automatically, cancels
prior legs for that symbol, and creates fresh TAKE_PROFIT_MARKET /
STOP_MARKET / reduce_only=true legs. **This is now the only sanctioned way to
add or change TP/SL on an already-open position** — see SKILL.md's TP/SL
mental model.

**A second bug found while building the fix:** an initial version of
`set-position-tpsl` cancelled *all* of the position's existing TP/SL legs
before creating new ones (matching the web dialog's raw behavior), but did
**not** pre-fill the untouched side the way the dialog's UI does — so calling
it with only `--sl-price` (intending to leave TP alone) silently dropped the
existing TP leg with no new one created. Fixed: the subcommand now reads
existing legs *before* cancelling, and re-creates any leg the caller didn't
explicitly touch (or explicitly clear with `--clear-tp` / `--clear-sl`) with
its prior trigger price unchanged. Live-verified on a real BTC-USDT LONG
position (fast-25k fund account, 2026-07-16): create TP+SL → update SL only
(confirmed TP preserved at its original price) → `--clear-tp` (confirmed TP
actually removed, not recreated).

**Takeaway for anyone extending this skill:** whenever a workflow needs to
target "the position", not "an order", check whether the A9Fund web app has an
equivalent dedicated UI first, and read its actual network calls rather than
assuming a field name in a type definition is the real mechanism — this
platform's docs page has repeatedly proven incomplete (see
`A9Fund-API-issues.md`), but the web app's own runtime behavior is ground
truth.

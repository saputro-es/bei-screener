# Locked Screener Blueprint

## 1. Data layers

### Daily market/flow layer
Stored in `stock_daily`:
- trade date
- ticker/company
- OHLC
- volume/value/frequency
- Foreign Buy / Foreign Sell

### Intraday orderbook layer
Stored in `orderbook_snapshot`:
- snapshot date/time
- ticker
- Bid/Offer price and volume, levels 1–5

The two layers are intentionally separate because one ticker can have many orderbook snapshots during one trading day while daily OHLC/flow has one row per trading date.

## 2. Accumulation horizons

The engine calculates:

`3D → 5D → 10D → 20D → 60D → 100D → 200D`

For every horizon it stores:
- available days
- net buy amount
- Net Buy %

The 3D threshold remains the primary candidate gate (>65% by default). All longer horizons remain part of the scoring and regime classification so a fresh accumulation spike is not confused with persistent accumulation.

## 3. Technical confirmation

- SMA20 / SMA50 / SMA200
- RSI14
- Volume / Volume MA20 ratio
- ATR14

## 4. Orderbook confirmation

Latest orderbook per ticker is summarized into:
- Best Bid / Best Offer
- spread and spread %
- 5-level Bid depth
- 5-level Offer depth
- Bid pressure %
- orderbook imbalance %
- orderbook signal
- orderbook score

Orderbook is a confirmation layer. It cannot override a weak long-horizon structure by itself.

## 5. Signal classes

The engine combines accumulation, technicals, volume, and orderbook into a transparent score and returns:

- `✅ LANJUT RALLY`
- `⚠️ KONSOLIDASI / KONFIRMASI`
- `❌ BERISIKO`

Accumulation quality separately distinguishes healthy cross-horizon accumulation from a new/expensive spike.

## 6. Risk outputs

For candidates the engine provides an indicative one-week target range and ATR-based stop-loss reference. These are rule-based estimates, not guarantees.

## 7. Data sufficiency

- 3D requires at least 3 daily rows.
- 20D technical/flow context is stronger with ≥20 rows.
- 60D/100D/200D are only marked active when the corresponding number of daily observations exists.
- Full blueprint quality requires ≥200 trading days plus current orderbook snapshots.

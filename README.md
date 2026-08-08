# BEI Screener V4

Database-backed Indonesian stock screener for daily BEI Excel data, built around the locked accumulation + technical + orderbook blueprint.

## Blueprint

The engine evaluates **seven accumulation horizons**:

**3D → 5D → 10D → 20D → 60D → 100D → 200D**

3D remains the primary candidate gate (>65% by default), while the longer horizons are used to measure whether the accumulation is recent, persistent, healthy, or potentially a short-lived spike. A stock with only 3D strength is treated differently from a stock with consistent strength through 60D/100D/200D.

Technical confirmation includes:

- SMA20, SMA50, SMA200
- RSI14
- volume ratio versus 20-day average
- ATR14
- rule-based one-week target and stop-loss reference

## Orderbook is a first-class signal

Orderbook snapshots are stored separately in SQLite so multiple intraday snapshots do not collide with the daily OHLC/foreign-flow table. The engine summarizes the latest snapshot per stock using:

- Best Bid / Best Offer
- spread and spread %
- Bid depth and Offer depth across up to 5 levels
- Bid pressure %
- orderbook imbalance %
- orderbook signal and score

Orderbook pressure is an additional confirmation, not a substitute for price/flow history.

## Data storage

- Daily market data: `database/bei_screener.db` → `stock_daily`
- Orderbook snapshots: `database/bei_screener.db` → `orderbook_snapshot`
- Daily rows are upserted by `(trade_date, stock_code)`.
- Orderbook rows are upserted by `(snapshot_date, snapshot_time, stock_code)`.
- Local SQLite/database files are ignored by Git.

## Recommended history

For the full blueprint, upload **at least 200 trading days** per stock. Fewer days are accepted, but the UI clearly reports how many days are available for each horizon.

Daily data should ideally include:

- `Kode Saham`
- `Tanggal Perdagangan Terakhir`
- `Penutupan`
- `Tertinggi`, `Terendah`, `Open Price`
- `Volume`
- `Foreign Buy`, `Foreign Sell`

Orderbook should ideally contain timestamp, ticker, and Bid/Offer price + volume for levels 1–5. The normalizer accepts common Indonesian/English column variants.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Testing

```bash
pytest -q
```

GitHub Actions runs the test suite on pushes and pull requests.

## Important

This is a rule-based research screener, not a guarantee of future price movement. Orderbook snapshots are point-in-time data and can change rapidly. Target/stop-loss outputs are indicative risk references.

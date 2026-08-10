import pandas as pd

from modules.analysis import accumulation_horizons
from modules.database import normalize_dataframe


def _bei_row(date: str, buy: float = 700, sell: float = 300) -> dict:
    return {
        "Kode Saham": "TEST",
        "Nama Perusahaan": "Test Company",
        "Tanggal Perdagangan Terakhir": date,
        "Penutupan": 100,
        "Volume": 1000,
        "Foreign Buy": buy,
        "Foreign Sell": sell,
        "Offer": 101,
        "Offer Volume": 800,
        "Bid": 99,
        "Bid Volume": 900,
    }


def test_real_bei_offer_volume_maps_to_ask_volume_1():
    data = normalize_dataframe(pd.DataFrame([_bei_row("31/07/2026")]))
    assert data.loc[0, "ask_price_1"] == 101
    assert data.loc[0, "ask_volume_1"] == 800
    assert data.loc[0, "bid_price_1"] == 99
    assert data.loc[0, "bid_volume_1"] == 900


def test_indonesian_bei_month_abbreviation_is_parsed():
    data = normalize_dataframe(pd.DataFrame([_bei_row("03 Agt 2026")]))
    assert data.loc[0, "trade_date"] == "2026-08-03"


def test_three_day_net_buy_is_not_exposed_before_three_complete_days():
    two_days = pd.DataFrame([
        _bei_row("30/07/2026", 700, 300),
        _bei_row("31/07/2026", 600, 400),
    ])
    result = accumulation_horizons(normalize_dataframe(two_days))
    row = result.iloc[0]
    assert row["days_available_3d"] == 2
    assert pd.isna(row["net_buy_3d"])
    assert pd.isna(row["net_buy_pct_3d"])


def test_three_day_net_buy_appears_only_after_three_complete_days():
    three_days = pd.DataFrame([
        _bei_row("29/07/2026", 700, 300),
        _bei_row("30/07/2026", 600, 400),
        _bei_row("31/07/2026", 800, 200),
    ])
    result = accumulation_horizons(normalize_dataframe(three_days))
    row = result.iloc[0]
    assert row["days_available_3d"] == 3
    assert row["net_buy_3d"] == 1200
    assert row["net_buy_pct_3d"] == 70

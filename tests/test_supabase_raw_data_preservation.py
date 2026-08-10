from __future__

import json

import pandas as pd

from modules.supabase_persistence import _daily_payload


def test_daily_payload_preserves_all_original_excel_fields_in_raw_data():
    frame = pd.DataFrame([{"Kode Saham":"SMDM","Sebelumnya":570,"Tanggal Perdagangan Terakhir":"2026-07-20","First Trade":570,"Penutupan":565,"Selisih":-5,"Index Individual":0.001,"Listed Shares":1000000,"Tradeble Shares":900000,"Weight For Index":0.0001,"Non Regular Volume":0,"Non Regular Value":0,"Non Regular Frequency":0}])
    raw = _daily_payload([frame])[0]["raw_data"]
    assert raw["Kode Saham"] == "SMDM"
    assert raw["Sebelumnya"] == 570
    assert raw["First Trade"] == 570
    assert raw["Selisih"] == -5
    assert raw["Index Individual"] == 0.001
    assert raw["Listed Shares"] == 1000000
    assert raw["Tradeble Shares"] == 900000
    assert raw["Weight For Index"] == 0.0001
    assert raw["Non Regular Volume"] == 0
    assert raw["Non Regular Value"] == 0
    assert raw["Non Regular Frequency"] == 0


def test_daily_payload_raw_data_is_json_serializable():
    frame = pd.DataFrame([{ "Kode Saham":"AAA", "Tanggal Perdagangan Terakhir":pd.Timestamp("2026-07-20"), "Penutupan":100 }])
    json.dumps(_daily_payload([frame])[0], ensure_ascii=False)

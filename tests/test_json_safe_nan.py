from __future__ import annotations

import json
import math

import numpy as np

from modules.supabase_persistence import _json_safe


def test_json_safe_converts_non_finite_floats_to_null():
    value = {
        "nan": float("nan"),
        "pos_inf": float("inf"),
        "neg_inf": float("-inf"),
        "nested": [np.float64("nan"), {"x": np.float64("inf")}],
    }
    safe = _json_safe(value)
    assert safe == {
        "nan": None,
        "pos_inf": None,
        "neg_inf": None,
        "nested": [None, {"x": None}],
    }
    json.dumps(safe, allow_nan=False)

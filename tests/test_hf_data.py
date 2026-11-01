import os

import pandas as pd

from meme import backtest as bt
from meme.hf_data import convert


def test_convert_roundtrip(tmp_path):
    src = tmp_path / "hf"
    os.makedirs(src / "data"); os.makedirs(src / "events")
    ev = pd.DataFrame({"slot": [10, 50, 99], "idx": [1, 2, 3], "kind": ["create", "complete", "create"],
                       "ts": [1000, 1500, 9000], "a": ["M1", "M1", "LATE"], "b": ["DEV", None, "X"],
                       "c": [None] * 3, "d": [None] * 3, "e": [None] * 3, "f": [None] * 3})
    ev.to_parquet(src / "events" / "e.parquet")
    rows = []
    vsol, vtok = 30e9, 1.073e15
    for k in range(20):
        sol = 1e8
        tok = vtok - vsol * vtok / (vsol + sol)
        vsol, vtok = vsol + sol, vtok - tok
        rows.append([1000 + k * 5, 10 + k, 1 if k == 0 else 5, "curve", False, "M1", "DEV" if k == 0 else f"U{k}",
                     "buy", int(sol), int(tok), vsol, vtok])
    rows.append([1001, 11, 9, "curve", True, "M1", "F", "buy", None, None, None, None])     # failed: dropped
    rows.append([1002, 12, 9, "pumpswap", False, "M1", "P", "buy", 1, 1, 1.0, 1.0])       # pumpswap: dropped
    t = pd.DataFrame(rows, columns=["ts", "slot", "idx", "venue", "failed", "mint", "wallet", "side", "sol_lamports",
                                    "token_amount", "r1", "r2"])
    t.to_parquet(src / "data" / "t.parquet")
    convert(str(src), str(tmp_path / "out"))
    cr, mig, tr = bt.load(str(tmp_path / "out"))
    assert list(cr.mint) == ["M1"] and abs(cr.sol.iloc[0] - 0.1) < 1e-9   # LATE coin dropped (incomplete hour)
    assert len(tr) == 20 and mig.loc["M1"] == 1_500_000
    tr2, coins = bt.prepare(cr, mig, tr)
    assert abs(tr2.vsol.iloc[0] - 30.1) < 1e-6 and tr2.mig_ts.iloc[0] == 1500

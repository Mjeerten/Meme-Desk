import gzip
import os

import numpy as np
import pandas as pd

from meme import backtest as bt
from meme.record import LAUNCH_FIELDS, TRADE_FIELDS


def test_curve_round_trip_loses_only_fees():
    tok = bt.buy_tokens(30.0, 1.073e9, 0.2)
    back = bt.sell_sol(30.0 + 0.2 * (1 - bt.FEE), 1.073e9 - tok, tok)
    assert 0.2 * (1 - bt.FEE) ** 2 * 0.999 < back < 0.2 * (1 - bt.FEE) ** 2 * 1.001


def fake_recording(folder, n_coins=60, seed=1):
    rng = np.random.default_rng(seed)
    L, T = [], []
    slot = 1000
    for c in range(n_coins):
        mint, dev = f"M{c}", f"D{c % 7}"
        t0 = 1_793_500_000 + c * 60
        L.append([t0 * 1000, "create", mint, dev, 0.5, 1e7, 28, "pump", 0, "S", "N"])
        vsol, vtok = 30.0, 1.073e9
        pump = c % 3 == 0   # every 3rd coin runs up, the rest fade
        for i in range(80):
            t = t0 + i * 10
            buy = rng.random() < (0.75 if pump else 0.4)
            user = f"U{rng.integers(0, 40)}" if i else dev
            if buy:
                sol = rng.uniform(0.1, 1.0)
                tok = vtok - vsol * vtok / (vsol + sol)
                vsol, vtok = vsol + sol, vtok - tok
            else:
                tok = rng.uniform(1e6, 2e7)
                sol = vsol - vsol * vtok / (vtok + tok)
                vsol, vtok = vsol - sol, vtok + tok
            slot += 1
            T.append([t * 1000, slot, f"s{slot}", t, mint, user, int(buy), sol, tok, vsol, vtok])
    os.makedirs(folder, exist_ok=True)
    for name, rows, cols in (("launches", L, LAUNCH_FIELDS), ("trades", T, TRADE_FIELDS)):
        with gzip.open(os.path.join(folder, f"x-a-{name}.csv.gz"), "wt") as f:
            pd.DataFrame(rows, columns=cols[:len(rows[0])]).to_csv(f, index=False)


def test_prepare_and_simulate(tmp_path):
    fake_recording(tmp_path)
    cr, mig, tr = bt.load(str(tmp_path))
    tr, coins = bt.prepare(cr, mig, tr)
    assert len(coins) == 60 and tr.age.min() == 0 and tr.dev_sold.dtype == bool
    assert tr.newb30.max() >= 1 and (tr.top_share >= 0).all()
    starts = tr.groupby("mint").cumcount()
    first_idx = (tr.index.to_series() - starts).groupby(tr.mint).first()
    cbm = {m: (bt.Coin(df), first_idx[m]) for m, df in tr.groupby("mint")}
    res = bt.run_rule(tr, cbm, bt.sig_baseline(tr, {"at": 5}), {"time": 300})
    assert len(res) == 60
    # pumping coins (every 3rd) should beat fading ones in a buy-and-hold test
    res["pump"] = res.mint.str[1:].astype(int) % 3 == 0
    assert res[res.pump].ret.mean() > res[~res.pump].ret.mean()
    tp = bt.run_rule(tr, cbm, bt.sig_baseline(tr, {"at": 5}), {"tp": 1.3, "stop": 0.2, "time": 600})
    assert set(tp.why) <= {"tp", "stop", "time", "end"}

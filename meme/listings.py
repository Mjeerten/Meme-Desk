"""Round 3b: trade new Binance USDT-M perpetual listings (all coins, memes shown apart), daily candles.

Trade: enter at the close of listing day `e` (0 = the first day's close), side short or long, hold H days, stop when
the price moves `stop` against us (filled at the stop, or the open if it gaps past it), funding paid / received daily
(short receives positive funding). Cost 0.2% round trip (taker 0.05% a side + slippage). One trade per listing.
Listings from 2020 on; train = listed before 2024, holdout = 2024+. %/yr = sum of trade % x 5% of capital per trade.

python -m meme.listings --out results
"""
from __future__ import annotations

import argparse
import itertools
import os
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from meme import binance as bn

COST = 0.002
SIZE = 0.05
MEME = {"DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BOME", "MEME", "PEOPLE", "TURBO", "NEIRO", "NEIROETH", "PNUT",
        "ACT", "TRUMP", "DOGS", "BABYDOGE", "PENGU", "SATS", "CHEEMS", "MUBARAK", "BROCCOLI714", "BROCCOLIF3B", "TST",
        "BANANAS31", "MEW", "POPCAT", "BRETT", "MOODENG", "GOAT", "SPX", "FARTCOIN", "PUMP", "MYRO", "RATS", "LUNC",
        "CHILLGUY", "PONKE", "SLERF", "HIPPO", "CAT", "WHY", "MOG", "DEGEN", "BOME", "PIPPIN", "PEIPEI", "KOMA", "SUN",
        "BAN", "LADYS", "AIDOGE", "1000X", "WIF", "SHIB", "MELANIA", "VINE", "JELLYJELLY", "ZEREBRO", "AI16Z", "GRIFFAIN",
        "USELESS", "TOSHI", "SKYAI", "DOOD", "BOBO", "HMSTR", "CATI", "NOT", "BABY"}


def base(sym):
    b = re.sub(r"USDT$", "", sym)
    return re.sub(r"^(1000000|100000|10000|1000|1M)", "", b)


def load_one(sym):
    ms = bn.months("um", sym, "1d")
    if not ms or ms[0] < "2020-01":
        return None
    first = ms[:4]
    k = bn.klines("um", sym, "1d", first)
    if len(k) < 10:
        return None
    f = bn.funding(sym, first)
    fd = f.groupby(f.index.normalize()).sum() if len(f) else pd.Series(dtype=float)
    k["fund"] = fd.reindex(k.index.normalize()).fillna(0.0).to_numpy()
    return sym, k


def trade(k, e, side, hold, stop):
    if len(k) <= e + 1:
        return None
    o, h, l, c, fu = (k[x].to_numpy() for x in ("open", "high", "low", "close", "fund"))
    px = c[e]
    sp = px * (1 + stop) if side < 0 else px * (1 - stop) if stop else None
    fund, end, x = 0.0, min(e + hold, len(k) - 1), None
    for j in range(e + 1, end + 1):
        fund += -side * fu[j]                        # long pays positive funding, short receives it
        if sp is not None and ((side < 0 and h[j] >= sp) or (side > 0 and l[j] <= sp)):
            x = max(sp, o[j]) if side < 0 else min(sp, o[j])
            break
    if x is None:
        x = c[end]
    return side * (x / px - 1) + fund - COST


def main(out):
    os.makedirs(out, exist_ok=True)
    syms = [s for s in bn.symbols("um") if s.endswith("USDT") and "_" not in s]
    print(len(syms), "USDT perps in the bucket", flush=True)
    with ThreadPoolExecutor(12) as ex:
        data = dict(x for x in ex.map(load_one, syms) if x)
    meta = pd.DataFrame([(s, k.index[0], base(s) in MEME, k.close.iloc[min(29, len(k) - 1)] / k.close.iloc[0] - 1)
                         for s, k in data.items()], columns=["sym", "listed", "meme", "ret30"])
    print(f"{len(meta)} listings since 2020 ({meta.meme.sum()} memes); median 30-day move after the first close "
          f"{meta.ret30.median():+.1%} (memes {meta[meta.meme].ret30.median():+.1%}), share down "
          f"{(meta.ret30 < 0).mean():.0%}", flush=True)
    meta["yr"] = meta.listed.dt.year
    print(meta.groupby("yr").agg(n=("sym", "size"), memes=("meme", "sum"), med30=("ret30", "median")).round(3).to_string())
    rows = []
    for e, side, hold, stop in itertools.product((0, 1, 2, 6), (-1, 1), (7, 14, 30, 60), (None, 0.3, 0.5, 1.0)):
        r = meta.assign(r=[trade(data[s], e, side, hold, stop) for s in meta.sym]).dropna(subset=["r"])
        for grp, sub in (("all", r), ("memes", r[r.meme])):
            dv, ho = sub[sub.listed < "2024-01-01"], sub[sub.listed >= "2024-01-01"]
            yrs_d, yrs_h = 4.0, max((r.listed.max() - pd.Timestamp("2024-01-01", tz="UTC")).days / 365, 0.1)
            rows.append(dict(grp=grp, entry_day=e, side="short" if side < 0 else "long", hold=hold, stop=stop,
                             n_dev=len(dv), n_hold=len(ho),
                             dev_avg=round(dv.r.mean() * 100, 2), hold_avg=round(ho.r.mean() * 100, 2),
                             dev_med=round(dv.r.median() * 100, 2), hold_med=round(ho.r.median() * 100, 2),
                             hold_win=round((ho.r > 0).mean(), 2), worst=round(sub.r.min() * 100, 1),
                             dev_yr=round(dv.r.sum() * SIZE / yrs_d * 100, 1), hold_yr=round(ho.r.sum() * SIZE / yrs_h * 100, 1),
                             years=" ".join(f"{y}:{v * 100:+.0f}" for y, v in sub.groupby(sub.listed.dt.year).r.mean().items())))
    g = pd.DataFrame(rows)
    g.to_csv(f"{out}/round3b_listings.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 80):
        for grp in ("all", "memes"):
            s = g[g.grp == grp]
            print(f"\n{grp}: both periods > 0: {((s.dev_avg > 0) & (s.hold_avg > 0)).mean():.0%} of {len(s)}")
            print(s.groupby(["side", "hold"])[["dev_avg", "hold_avg"]].median().to_string())
            print("TOP 10 BY 2020-23 AVG (n_dev >= 30):\n" +
                  s[s.n_dev >= (30 if grp == "all" else 5)].sort_values("dev_avg", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    main(ap.parse_args().out)

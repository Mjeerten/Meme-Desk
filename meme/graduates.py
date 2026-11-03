"""Round 4: pump.fun coins after they graduate (migrate to the PumpSwap pool): buy-and-hold rules and liquidity providing.

Coins: every migration in our recordings (PumpPortal feed). Price after migration: GeckoTerminal free API, 5-minute
candles in USD (up to ~83 h after migration; 2 calls per coin, 30 calls/min limit). Coins GeckoTerminal has no data
for are counted (if they are mostly dead coins, results would look too good: shown in the log).

A) Buy rules: buy at the close of the first candle >= `delay` after migration, sell after `hold` hours, or at a stop
   (`stop` below entry) / target (`tp` x entry), checked on 5-minute highs and lows (stop first if both in one candle).
   Filter: none, or only if the price at entry is above / below the migration price (momentum / dip).
   Cost per side: fee + impact, 1.5% (0.5% shown as the optimistic case). Train = first 60% of coins by migration time.
B) LP: put money in the pool at the same moment for `hold` hours (constant product, no other LPs moving the pool):
   value change = impermanent loss 2*sqrt(r)/(1+r)-1 on top of holding half/half, plus fees = lp_fee * volume * our
   share; pool size from the migration reserves (~206.9 M tokens) * price, scaled by sqrt(price change).
   Entry/exit: swap half the money, 1.5% each way on that half. lp_fee 0.20% and 0.05% (check PumpSwap's current split).

python -m meme.graduates data --max 1500 --out results
"""
from __future__ import annotations

import argparse
import pickle
import glob
import itertools
import os
import time

import numpy as np
import pandas as pd
import requests

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
POOL_TOKENS = 206.9e6
_s = requests.Session()
_s.headers["Accept"] = "application/json;version=20230302"


def get(url, **params):
    for i in range(6):
        time.sleep(2.1)
        r = _s.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(15 * (i + 1))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    return None


def migrations(folder):
    parts = [pd.read_csv(p, usecols=lambda c: c in ("t_ms", "type", "mint", "name", "symbol"), low_memory=False)
             for p in glob.glob(os.path.join(folder, "**", "*-launches.csv.gz"), recursive=True)]
    la = pd.concat(parts, ignore_index=True)
    cr = la[la.type == "create"].sort_values("t_ms").drop_duplicates("mint").set_index("mint")
    mg = la[la.type == "migrate"].sort_values("t_ms").drop_duplicates("mint").set_index("mint")
    mg["created"] = cr.t_ms.reindex(mg.index)
    mg["name"] = cr.name.reindex(mg.index) if "name" in cr else ""
    mg["speed_min"] = (mg.t_ms - mg.created) / 60000
    print(f"{len(cr)} launches, {len(mg)} migrations ({mg.created.notna().sum()} launched while recording)", flush=True)
    return mg


def candles(mint):
    j = get(f"{GT}/tokens/{mint}/pools")
    if not j or not j.get("data"):
        return None
    pools = sorted(j["data"], key=lambda p: float(p["attributes"].get("reserve_in_usd") or 0), reverse=True)
    pool = pools[0]["attributes"]["address"]
    j = get(f"{GT}/pools/{pool}/ohlcv/minute", aggregate=5, limit=1000, currency="usd", token=mint)
    rows = (j or {}).get("data", {}).get("attributes", {}).get("ohlcv_list") or []
    if not rows:
        return None
    d = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"]).sort_values("ts")
    return d.drop_duplicates("ts").reset_index(drop=True)


def buy(d, t_mig, delay, hold, stop, tp, filt, cost):
    ts, o, h, l, c = d["ts"], d["o"], d["h"], d["l"], d["c"]
    i = np.searchsorted(ts, t_mig + delay * 60)
    if i >= len(ts) or ts[i] - t_mig > delay * 60 + 3600:
        return None
    p0, e = c[0], c[i]
    if (filt == "up" and e <= p0) or (filt == "down" and e >= p0):
        return None
    end = ts[i] + hold * 3600
    x = None
    k = np.searchsorted(ts, end, side="right") - 1
    for j in range(i + 1, k + 1):
        if stop and l[j] <= e * (1 - stop):
            x = min(e * (1 - stop), o[j])
            break
        if tp and h[j] >= e * tp:
            x = max(e * tp, o[j])
            break
    if x is None:
        x = c[k]                                   # last trade before the end (no trade = price unchanged)
    return (x / e) * (1 - cost) ** 2 - 1


def lp(d, t_mig, delay, hold, lp_fee, cost=0.015):
    ts, c, v = d["ts"], d["c"], d["v"]
    i = np.searchsorted(ts, t_mig + delay * 60)
    if i >= len(ts):
        return None
    p_first, e = c[0], c[i]
    k = np.searchsorted(ts, ts[i] + hold * 3600, side="right") - 1
    r = c[k] / e
    tvl = 2 * POOL_TOKENS * p_first * np.sqrt(c[i + 1:k + 1] / p_first)   # USD pool size after each candle
    fees = (lp_fee * v[i + 1:k + 1] / np.clip(tvl, 1, None)).sum()          # per USD deposited
    hold_half = 0.5 + 0.5 * r                                          # value of just holding half/half
    il = 2 * np.sqrt(r) / (1 + r)
    return hold_half * il - 1 + fees - cost                             # 'cost': swap half in and out


def summary(r):
    r = r.dropna()
    if not len(r):
        return dict(n=0)
    return dict(n=len(r), avg=round(r.mean() * 100, 1), med=round(r.median() * 100, 1), win=round((r > 0).mean(), 2),
                best=round(r.max() * 100, 0), worst=round(r.min() * 100, 0))


def fetch(folder, mx, out, shard=0, of=1):
    """Download candles for this shard's coins; saved every 25 coins so a cancelled job keeps what it got."""
    os.makedirs(out, exist_ok=True)
    mg = migrations(folder)
    now = time.time()
    mg = mg[mg.t_ms / 1000 < now - 3 * 3600].sort_values("t_ms").tail(mx).iloc[shard::of]
    print(f"shard {shard}/{of}: {len(mg)} coins", flush=True)
    data, miss, path = {}, 0, f"{out}/candles-{shard}.pkl"
    for n, (mint, row) in enumerate(mg.iterrows()):
        try:
            d = candles(mint)
        except Exception as e:
            print("error", mint, repr(e)[:120], flush=True)
            d = None
        if d is not None:
            d = d[d.ts >= row.t_ms / 1000 - 300]
        if d is None or not len(d):
            miss += 1
        else:
            data[mint] = dict(t_ms=float(row.t_ms), **{k: d[k].to_numpy(float) for k in d})
        if n % 25 == 24 or n == len(mg) - 1:
            with open(path, "wb") as f:
                pickle.dump(data, f)
        if n % 100 == 99:
            print(f"{n + 1} coins fetched, {miss} without data", flush=True)
    print(f"shard {shard}: {len(data)} coins with candles, {miss} without", flush=True)


def main(cache, out):
    os.makedirs(out, exist_ok=True)
    data = {}
    for p in glob.glob(os.path.join(cache, "**", "candles-*.pkl"), recursive=True):
        with open(p, "rb") as f:
            data.update(pickle.load(f))
    mg = pd.DataFrame({"t_ms": {m: d.pop("t_ms") for m, d in data.items()}})
    print(f"{len(data)} graduated coins with candles", flush=True)
    life = pd.DataFrame({m: dict(x24=d["c"][d["ts"] <= mg.t_ms[m] / 1000 + 86400][-1] / d["c"][0],
                                 peak=d["h"].max() / d["c"][0]) for m, d in data.items()}).T
    print("price 24 h after migration vs at migration: median x{:.2f}, share up {:.0%}, share below 0.2x {:.0%}; "
          "median peak x{:.2f}".format(life.x24.median(), (life.x24 > 1).mean(), (life.x24 < 0.2).mean(),
                                       life.peak.median()), flush=True)
    cut = mg.t_ms.quantile(0.6)
    rows = []
    for delay, hold, stop, tp, filt in itertools.product((0, 5, 30, 120), (1, 6, 24, 72), (None, 0.3, 0.5),
                                                         (None, 2.0, 3.0), (None, "up", "down")):
        for cost in (0.015, 0.005):
            r = pd.Series({m: buy(d, mg.t_ms[m] / 1000, delay, hold, stop, tp, filt, cost) for m, d in data.items()},
                          dtype=float)
            tr, ho = r[mg.t_ms.reindex(r.index) < cut], r[mg.t_ms.reindex(r.index) >= cut]
            rows.append(dict(kind="buy", delay=delay, hold=hold, stop=stop, tp=tp, filt=filt, cost=cost,
                             **{f"tr_{k}": v for k, v in summary(tr).items()},
                             **{f"ho_{k}": v for k, v in summary(ho).items()}))
    for delay, hold, fee in itertools.product((0, 30, 120), (1, 6, 24, 72), (0.002, 0.0005)):
        r = pd.Series({m: lp(d, mg.t_ms[m] / 1000, delay, hold, fee) for m, d in data.items()}, dtype=float)
        tr, ho = r[mg.t_ms.reindex(r.index) < cut], r[mg.t_ms.reindex(r.index) >= cut]
        rows.append(dict(kind="lp", delay=delay, hold=hold, lp_fee=fee, **{f"tr_{k}": v for k, v in summary(tr).items()},
                         **{f"ho_{k}": v for k, v in summary(ho).items()}))
    g = pd.DataFrame(rows)
    g.to_csv(f"{out}/round4_graduates.csv", index=False)
    cols = [c for c in g.columns if c not in ("kind",)]
    with pd.option_context("display.width", 260, "display.max_columns", 40):
        b = g[(g.kind == "buy") & (g.cost == 0.015)]
        print(f"\nBUY RULES (1.5% a side): {len(b)}; train avg > 0 {(b.tr_avg > 0).mean():.0%}, both > 0 "
              f"{((b.tr_avg > 0) & (b.ho_avg > 0)).mean():.0%}")
        print("plain buy at migration, no stop/target:\n" + b[(b.delay == 0) & b.stop.isna() & b.tp.isna() & b.filt.isna()][cols].to_string(index=False))
        print("TOP 10 ON TRAIN (n >= 30):\n" + b[b.tr_n >= 30].sort_values("tr_avg", ascending=False).head(10)[cols].to_string(index=False))
        b5 = g[(g.kind == "buy") & (g.cost == 0.005)]
        print(f"optimistic 0.5% a side: both > 0 {((b5.tr_avg > 0) & (b5.ho_avg > 0)).mean():.0%}; best train:\n"
              + b5[b5.tr_n >= 30].sort_values("tr_avg", ascending=False).head(5)[cols].to_string(index=False))
        print("\nLIQUIDITY PROVIDING:\n" + g[g.kind == "lp"][["delay", "hold", "lp_fee", "tr_n", "tr_avg", "tr_med", "tr_win",
                                                              "ho_n", "ho_avg", "ho_med", "ho_win"]].to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="recordings (fetch) or downloaded candle files (analyse)")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--max", type=int, default=1500)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    if a.fetch:
        fetch(a.folder, a.max, a.out, a.shard, a.of)
    else:
        main(a.folder, a.out)

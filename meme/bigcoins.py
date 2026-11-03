"""Round 3a: the big memecoins on an exchange (Binance spot history; Bitvavo costs), daily candles.

Coins: every Binance USDT meme listing in MEMES (dead ones too: MEME, BOME, TURBO, NEIRO, PNUT, ACT ...), each from
its own listing day. Hindsight risk: the list was made in 2026 (Binance rarely delists a meme, so it is close to
'every meme Binance listed'). Basket = equal weight over the coins listed that day.
Strategies (signal on the daily close, position from that close, cost COST per unit traded = Bitvavo taker 0.25%):
  hold      always in
  sma N     in while close > N-day average
  donch E/X in on a close above the E-day high, out on a close below the X-day low
  rot k/L   every 7 days hold the k coins with the best L-day return (abs: only if that return > 0)
  dip t/x   in when RSI(2) < t, out when RSI(2) > x or after 5 days (trend: only above the 100-day average)
  + 'btc' filter: only while BTC is above its 50-day average.
Judge: 2019-2023 (train) vs 2024+ (holdout), %/yr compounded, worst drop, Sharpe; BTC and DOGE hold as reference.

python -m meme.bigcoins --out results
"""
from __future__ import annotations

import argparse
import itertools
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from meme import binance as bn

MEMES = ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BOME", "MEME", "PEOPLE", "TURBO", "NEIRO", "PNUT", "ACT",
         "TRUMP", "DOGS", "1MBABYDOGE", "PENGU", "1000SATS", "1000CHEEMS", "MUBARAK", "BROCCOLI714", "TST",
         "BANANAS31", "MEW", "POPCAT", "BRETT", "MOODENG", "GOAT", "SPX", "FARTCOIN", "PUMP", "WLFI"]
COST = 0.0025
SPLIT = "2024-01-01"


def load():
    def one(c):
        k = bn.klines("spot", c + "USDT", "1d")
        return c, k.close if len(k) else None
    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(one, MEMES + ["BTC"]))
    px = pd.DataFrame({c: s for c, s in got.items() if s is not None})
    px.index = px.index.normalize()
    px = px[px.index >= "2019-01-01"]
    print("coins found:", ", ".join(f"{c} ({px[c].first_valid_index():%Y-%m})" for c in px if c != "BTC"), flush=True)
    return px


def rsi(c, n=2):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def positions(px, kind, a=None, b=None, flag=False):
    """Target weight per coin per day (decided on that day's close)."""
    c = px.drop(columns="BTC")
    if kind == "hold":
        w = c.notna().astype(float)
    elif kind == "sma":
        w = (c > c.rolling(a, min_periods=a).mean()).astype(float)
    elif kind == "donch":
        hi, lo = c.rolling(a).max().shift(1), c.rolling(b).min().shift(1)
        sig = pd.DataFrame(np.where(c > hi, 1.0, np.where(c < lo, 0.0, np.nan)), index=c.index, columns=c.columns)
        w = sig.ffill().fillna(0.0)
    elif kind == "dip":
        r = c.apply(rsi)
        trend = c > c.rolling(100, min_periods=100).mean() if flag else c.notna()
        w = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        for col in c:
            inn, age, out = False, 0, []
            for x, ok in zip(r[col].to_numpy(), trend[col].to_numpy()):
                if inn:
                    age += 1
                    if x > b or age >= 5:
                        inn = False
                elif x < a and ok:
                    inn, age = True, 0
                out.append(1.0 if inn else 0.0)
            w[col] = out
    elif kind == "rot":
        ret = c / c.shift(b) - 1
        w = pd.DataFrame(0.0, index=c.index, columns=c.columns)
        cur = pd.Series(0.0, index=c.columns)
        for i, t in enumerate(c.index):
            if i % 7 == 0:
                r = ret.loc[t].dropna()
                if flag:
                    r = r[r > 0]
                top = r.nlargest(a).index
                cur = pd.Series(0.0, index=c.columns)
                cur[top] = 1.0 / a
            w.loc[t] = cur
        return w                                          # already portfolio weights
    else:
        raise ValueError(kind)
    n = c.notna().sum(axis=1).replace(0, np.nan)          # equal weight over listed coins
    return w.where(c.notna(), 0.0).div(n, axis=0).fillna(0.0)


def equity(px, w, btc_filter=False):
    c = px.drop(columns="BTC")
    if btc_filter:
        ok = (px.BTC > px.BTC.rolling(50).mean()).astype(float)
        w = w.mul(ok, axis=0)
    r = c.pct_change(fill_method=None).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    turn = w.diff().abs().sum(axis=1).fillna(w.abs().sum(axis=1))
    return (held * r).sum(axis=1) - COST * turn


def stats(d: pd.Series) -> dict:
    out = {}
    for name, s in (("dev", d[(d.index >= "2019-01-01") & (d.index < SPLIT)]), ("hold", d[d.index >= SPLIT])):
        s = s[s.index >= s.ne(0).idxmax()] if s.ne(0).any() else s
        if len(s) < 30:
            out.update({f"{name}_yr": np.nan, f"{name}_dd": np.nan, f"{name}_sh": np.nan})
            continue
        eq = (1 + s).cumprod()
        yrs = len(s) / 365
        out[f"{name}_yr"] = round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1)
        out[f"{name}_dd"] = round((eq / eq.cummax() - 1).min() * 100, 1)
        out[f"{name}_sh"] = round(s.mean() / s.std() * np.sqrt(365), 2) if s.std() > 0 else np.nan
    y = (1 + d).groupby(d.index.year).prod() - 1
    out["years"] = " ".join(f"{k}:{v * 100:+.0f}" for k, v in y.items())
    return out


def grid():
    yield ("hold", None, None, False)
    for n in (10, 20, 50, 100, 200):
        yield ("sma", n, None, False)
    for e, x in ((20, 10), (55, 20), (10, 5)):
        yield ("donch", e, x, False)
    for k, l, ab in itertools.product((1, 3, 5), (7, 14, 30, 60), (False, True)):
        yield ("rot", k, l, ab)
    for t, x, tr in itertools.product((5, 10, 20), (50, 70), (False, True)):
        yield ("dip", t, x, tr)


def main(out):
    os.makedirs(out, exist_ok=True)
    px = load()
    rows = []
    for kind, a, b, flag in grid():
        w = positions(px, kind, a, b, flag)
        for bf in (False, True):
            rows.append(dict(kind=kind, a=a, b=b, flag=flag, btc=bf, **stats(equity(px, w, bf))))
    g = pd.DataFrame(rows)
    for ref in ("BTC", "DOGE"):
        r = px[ref].pct_change(fill_method=None).fillna(0.0)
        g = pd.concat([g, pd.DataFrame([dict(kind=f"{ref} hold", **stats(r))])])
    g.to_csv(f"{out}/round3a_bigcoins.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 90):
        print(f"\n{len(g)} settings; dev>0 {(g.dev_yr > 0).mean():.0%}, both>0 {((g.dev_yr > 0) & (g.hold_yr > 0)).mean():.0%}")
        print("REFERENCES + PLAIN HOLD:\n" + g[g.kind.str.contains("hold")].to_string(index=False))
        print("BY KIND (median):\n" + g.groupby(["kind", "btc"])[["dev_yr", "hold_yr", "dev_sh", "hold_sh", "dev_dd", "hold_dd"]]
              .median().to_string())
        print("TOP 12 BY 2019-23 SHARPE:\n" + g.sort_values("dev_sh", ascending=False).head(12).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    main(ap.parse_args().out)

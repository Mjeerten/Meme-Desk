"""Funding-rate carry backtest: hold coin spot + short the perpetual (same size), collect funding every 8 h.

Price moves cancel (long spot, short perp); the income is the funding rate the perp longs pay the shorts.
Data: Binance USD-M funding history (data.binance.vision, free), 2020 -> now, as a proxy for any venue
(in the Netherlands retail perps: One Trading BTC/EUR, ETH/EUR).
Costs: COST per switch (enter or exit) = spot taker + perp taker fee, both legs; basis noise ignored.
Rules tested: always on; on only when the trailing mean of the last N funding payments > THR (off below EXIT);
rotation = hold whichever coin has the highest trailing funding (if above THR).
Tune on 2020-2023, holdout 2024+ (same rule as the day desk). Returns are %/yr on the position size (notional);
the capital needed is about 1.3-2x that (spot + perp margin), shown as 'on capital (1.5x)'.

python -m carry.funding
"""
from __future__ import annotations

import io
import itertools
import os
import sys
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import requests

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{y}-{m:02d}.zip"
COST = 0.0015          # per switch, both legs (spot 0.10% + perp 0.05% taker); a round trip costs 0.30%
CAPITAL_MULT = 1.5
SPLIT = "2024-01-01"


def fetch(sym: str, cache="carry_data") -> pd.Series:
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"{sym}.csv")
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
        return s
    rows = []
    today = date.today()
    for y in range(2019, today.year + 1):
        for m in range(1, 13):
            if (y, m) >= (today.year, today.month):
                break
            r = requests.get(BASE.format(s=sym, y=y, m=m), timeout=60)
            if r.status_code != 200:
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(z.open(z.namelist()[0]))
            if "calc_time" not in df.columns:  # very old files have no header
                df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=["calc_time", "funding_interval_hours", "last_funding_rate"])
            rows.append(df)
    df = pd.concat(rows)
    df["t"] = pd.to_datetime(df.calc_time, unit="ms")
    s = df.set_index("t").last_funding_rate.astype(float).sort_index()
    s = s[~s.index.duplicated()]
    s.to_csv(path)
    return s


def run_rule(f: pd.DataFrame, n: int | None, thr: float, exit_thr: float, rotate: bool, coin: str | None):
    """f: funding payments (rows = time, cols = coins). Decision uses payments up to and including the previous one."""
    if rotate:
        trail = f.rolling(n, min_periods=n).mean().shift(1)
        best_val = trail.max(axis=1)
        best = trail.fillna(-1.0).idxmax(axis=1).where(best_val.notna())
        held, pos, pnl, switches = None, [], [], 0
        for t, row in f.iterrows():
            b, v = best.get(t), best_val.get(t)
            want = held
            if held is None and pd.notna(v) and v > thr:
                want = b
            elif held is not None:
                hv = trail.at[t, held] if pd.notna(trail.at[t, held]) else -1
                if hv < exit_thr:
                    want = b if (pd.notna(v) and v > thr) else None
                elif pd.notna(v) and b != held and v > hv + 2 * COST / max(n, 1):
                    want = b
            cost = 0.0
            if want != held:
                cost = COST * ((held is not None) + (want is not None))
                switches += 1
            held = want
            r = (row[held] if held is not None and pd.notna(row[held]) else 0.0) - cost
            pnl.append(r)
            pos.append(held is not None)
        return pd.Series(pnl, index=f.index), np.mean(pos), switches
    x = f[coin].dropna()
    if n is None:
        on = pd.Series(True, index=x.index)
    else:
        trail = x.rolling(n, min_periods=n).mean().shift(1)
        state, out = False, []
        for v in trail:
            if not state and pd.notna(v) and v > thr:
                state = True
            elif state and pd.notna(v) and v < exit_thr:
                state = False
            out.append(state)
        on = pd.Series(out, index=x.index)
    sw = on.astype(int).diff().abs().fillna(on.iloc[0]).astype(int)
    pnl = np.where(on, x.to_numpy(), 0.0) - sw.to_numpy() * COST
    if on.iloc[-1]:
        pnl[-1] -= COST  # close at the end
    return pd.Series(pnl, index=x.index), on.mean(), int(sw.sum())


def stats(p: pd.Series) -> dict:
    if len(p) < 10:
        return {"pct_yr": np.nan, "worst_month": np.nan, "neg_months": np.nan}
    years = (p.index[-1] - p.index[0]).days / 365.25
    m = p.resample("ME").sum()
    return {"pct_yr": p.sum() / max(years, 1e-9) * 100, "worst_month": m.min() * 100, "neg_months": (m < 0).mean()}


def main():
    f = pd.concat({s: fetch(s) for s in COINS}, axis=1)
    f.index = f.index.floor("h")
    f = f.groupby(level=0).last().sort_index()
    print("data:", {c: f[c].first_valid_index().date().isoformat() for c in COINS}, "to", f.index[-1].date())
    yr = f.groupby(f.index.year)
    print("\nAverage funding per year, %/yr if always collected (3 payments a day):")
    print((yr.mean() * 3 * 365 * 100).round(1).to_string())
    rules = [("always", None, 0, 0)]
    for n, thr in itertools.product([3, 9, 21, 63], [0.0, 0.00005, 0.0001, 0.0002]):
        for ex in sorted({0.0, thr / 2}):
            rules.append((f"N{n} in>{thr*100:.3f}% out<{ex*100:.4f}%", n, thr, ex))
    rows = []
    for coin in COINS + ["ROTATE"]:
        for name, n, thr, ex in rules:
            if coin == "ROTATE" and n is None:
                continue
            p, frac, sw = run_rule(f, n, thr, ex, coin == "ROTATE", None if coin == "ROTATE" else coin)
            tr, ho = p[p.index < SPLIT], p[p.index >= SPLIT]
            a, b = stats(tr), stats(ho)
            rows.append({"coin": coin, "rule": name, "time_in": round(frac, 2), "switches": sw,
                         "train_%yr": round(a["pct_yr"], 1), "hold_%yr": round(b["pct_yr"], 1),
                         "hold_on_capital_%yr": round(b["pct_yr"] / CAPITAL_MULT, 1),
                         "hold_worst_month_%": round(b["worst_month"], 2), "hold_neg_months": round(b["neg_months"], 2)})
    res = pd.DataFrame(rows)
    os.makedirs("results", exist_ok=True)
    res.to_csv("results/funding.csv", index=False)
    pd.set_option("display.width", 250)
    print("\nAlways on, per coin (train 2020-2023 / holdout 2024+):")
    print(res[res.rule == "always"].to_string(index=False))
    print("\nBest rule per coin chosen on TRAIN, then its HOLDOUT:")
    best = res.dropna(subset=["train_%yr"]).sort_values("train_%yr", ascending=False).groupby("coin").head(1)
    print(best.to_string(index=False))
    print("\nTop 10 on train overall:")
    print(res.sort_values("train_%yr", ascending=False).head(10).to_string(index=False))
    last12 = f[f.index >= f.index[-1] - pd.Timedelta(days=365)]
    print("\nLast 12 months, average funding %/yr if always collected:", (last12.mean() * 3 * 365 * 100).round(1).to_dict())
    print(f"\nCosts: {COST*100:.2f}% per switch (round trip {2*COST*100:.2f}%). Returns on position size; on capital "
          f"divide by ~{CAPITAL_MULT}. Compare with a EUR savings rate (~2%/yr) - the carry has exchange risk on top.")


if __name__ == "__main__":
    main()

"""Backtest scan -> check -> buy -> sell strategies on recorded pump.fun data (meme/record.py output).

Simulation, per trade:
- Price comes from the curve itself: every recorded trade carries the virtual reserves after it (vsol, vtok), and a
  buy/sell of ours is filled on the constant-product curve at the reserves current at signal time + LATENCY.
- Costs: pump.fun fee FEE on each side, NET_FEE SOL per transaction (base + priority), token-account rent assumed
  reclaimed. Size SIZE SOL per trade.
- A coin that migrates (leaves the curve) while we hold is sold at the last curve price minus MIGRATE_HAIRCUT.
- Only the first WINDOW_MIN minutes of each coin are used (what a sniping strategy trades).
- Split: coins ordered by launch time, first TRAIN share to tune, the rest is the holdout (looked at once).

python -m meme.backtest data/            (all strategy families, grid search on train, holdout report)
"""
from __future__ import annotations

import glob
import itertools
import os
import sys

import numpy as np
import pandas as pd

FEE = 0.0125            # pump.fun fee per side
NET_FEE = 0.0001        # SOL per transaction (base + priority)
SIZE = 0.2              # SOL per trade
LATENCY = 2             # seconds from signal to fill (buy and sell)
MIGRATE_HAIRCUT = 0.05  # sold 5% below the last curve price if the coin migrates while held
WINDOW_MIN = 60
TRAIN = 0.6
SUPPLY = 1e9


# ----------------------------------------------------------------------------------------------- loading
def load(folder: str):
    lp = sorted(glob.glob(os.path.join(folder, "**", "*-launches.csv.gz"), recursive=True))
    tp = sorted(glob.glob(os.path.join(folder, "**", "*-trades.csv.gz"), recursive=True))
    la = pd.concat([pd.read_csv(p, low_memory=False) for p in lp], ignore_index=True)
    tr = pd.concat([pd.read_csv(p, low_memory=False) for p in tp], ignore_index=True)
    cr = la[la.type == "create"].sort_values("t_ms").drop_duplicates("mint")
    mig = la[la.type == "migrate"].sort_values("t_ms").drop_duplicates("mint").set_index("mint").t_ms
    tr = tr.drop_duplicates(["slot", "sig", "mint", "user", "buy", "sol", "tokens"])
    tr = tr[tr.mint.isin(cr.mint)]
    return cr, mig, tr


def prepare(cr: pd.DataFrame, mig: pd.Series, tr: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-trade feature table for coins launched while recording, first WINDOW_MIN minutes of each coin."""
    coins = cr[["t_ms", "mint", "creator", "sol", "mayhem"]].rename(columns={"sol": "dev_buy", "t_ms": "create_ms"})
    tr = tr.merge(coins, on="mint")
    tr = tr.sort_values(["mint", "slot", "recv_ms"]).reset_index(drop=True)
    t0 = tr.groupby("mint").ts.transform("min").clip(upper=tr.create_ms // 1000)
    tr["age"] = tr.ts - t0
    tr = tr[tr.age <= WINDOW_MIN * 60].reset_index(drop=True)
    tr["price"] = tr.vsol / tr.vtok
    tr["mcap"] = tr.price * SUPPLY
    g = tr.groupby("mint", sort=False)
    tr["ath"] = g.mcap.cummax()
    tr["dd"] = 1 - tr.mcap / tr.ath
    tr["mult0"] = tr.mcap / g.mcap.transform("first")
    is_dev = tr.user == tr.creator
    tr["dev_sold"] = (is_dev & (tr.buy == 0)).groupby(tr.mint).cummax().astype(bool)
    first_buy = (tr.buy == 1) & ~tr.duplicated(["mint", "user", "buy"])
    tr["uniq_buyers"] = first_buy.astype(int).groupby(tr.mint).cumsum()
    # rolling 30 s / 60 s windows (time-based, per coin)
    tr["t"] = pd.to_datetime(tr.ts, unit="s")
    tr["bsol"] = np.where(tr.buy == 1, tr.sol, 0.0)
    tr["ssol"] = np.where(tr.buy == 0, tr.sol, 0.0)
    tr["newb"] = first_buy.astype(float)
    for w in (30, 60):
        r = tr.set_index("t").groupby("mint", sort=False)[["bsol", "ssol", "newb"]].rolling(f"{w}s").sum()
        r = r.reset_index(level=0, drop=True)
        tr[f"bsol{w}"] = r.bsol.values
        tr[f"ssol{w}"] = r.ssol.values
        tr[f"newb{w}"] = r.newb.values
    # biggest single wallet's cumulative buys as share of supply (concentration proxy)
    cum_user = tr.assign(tb=np.where(tr.buy == 1, tr.tokens, -tr.tokens)).groupby(["mint", "user"]).tb.cumsum()
    tr["top_share"] = cum_user.clip(lower=0).groupby(tr.mint).cummax() / SUPPLY
    # migration time (s) per coin, NaN if not within recording
    tr["mig_ts"] = tr.mint.map(mig / 1000)
    # creator reputation: earlier launches by the same creator in the data, and how many migrated
    cr = cr.sort_values("t_ms").copy()
    cr["migrated"] = cr.mint.isin(mig.index).astype(int)
    cr["prev_launches"] = cr.groupby("creator").cumcount()
    cr["prev_migrated"] = cr.groupby("creator").migrated.cumsum() - cr.migrated
    tr = tr.merge(cr[["mint", "prev_launches", "prev_migrated"]], on="mint", how="left")
    tr = tr.sort_values(["mint", "slot", "recv_ms"]).reset_index(drop=True)
    coins = cr[cr.mint.isin(tr.mint)].reset_index(drop=True)
    return tr, coins


# ----------------------------------------------------------------------------------------------- execution
def buy_tokens(vsol, vtok, sol_in):
    k = vsol * vtok
    return vtok - k / (vsol + sol_in * (1 - FEE))


def sell_sol(vsol, vtok, tokens):
    k = vsol * vtok
    return (vsol - k / (vtok + tokens)) * (1 - FEE)


class Coin:
    """Arrays of one coin's trades, for fast exit simulation."""
    __slots__ = ("ts", "vsol", "vtok", "buy", "user", "creator", "mig_ts", "n")

    def __init__(self, df):
        self.ts = df.ts.to_numpy()
        self.vsol = df.vsol.to_numpy()
        self.vtok = df.vtok.to_numpy()
        self.buy = df.buy.to_numpy()
        self.user = df.user.to_numpy()
        self.creator = df.creator.iloc[0]
        m = df.mig_ts.iloc[0]
        self.mig_ts = None if pd.isna(m) else float(m)
        self.n = len(df)

    def state_at(self, t):
        """Index of the last trade at or before time t (reserves current at t)."""
        return max(int(np.searchsorted(self.ts, t, side="right")) - 1, 0)


def simulate(coin: Coin, i_sig: int, ex: dict, follow_wallet: str | None = None) -> dict | None:
    """Enter after trade i_sig (+latency), exit by the rules in ex. Returns the trade result in SOL."""
    lat = ex.get("latency", LATENCY)
    t_fill = coin.ts[i_sig] + lat
    j = coin.state_at(t_fill)
    if coin.mig_ts is not None and t_fill >= coin.mig_ts:
        return None  # already off the curve
    tokens = buy_tokens(coin.vsol[j], coin.vtok[j], SIZE)
    if tokens <= 0:
        return None
    cost = SIZE + NET_FEE
    # value of the whole position at every later trade's reserves
    vs, vt, ts = coin.vsol[j + 1:], coin.vtok[j + 1:], coin.ts[j + 1:]
    if len(ts) == 0:
        val = np.array([sell_sol(coin.vsol[j], coin.vtok[j], tokens)])
        ts = np.array([t_fill])
    else:
        val = sell_sol(vs, vt, tokens)
    rel = val / SIZE
    hold = ts - t_fill
    n = len(rel)
    cand = [n - 1]  # end of data window
    why = ["end"]

    def first(mask):
        idx = np.flatnonzero(mask)
        return int(idx[0]) if len(idx) else None

    if ex.get("time"):
        k = first(hold >= ex["time"]); cand.append(k); why.append("time")
    if ex.get("stop"):
        k = first(rel <= 1 - ex["stop"]); cand.append(k); why.append("stop")
    if ex.get("tp") and not ex.get("tp_frac"):
        k = first(rel >= ex["tp"]); cand.append(k); why.append("tp")
    if ex.get("trail"):
        peak = np.maximum.accumulate(rel)
        arm = ex.get("trail_arm", 1.0)
        k = first((peak >= arm) & (rel <= peak * (1 - ex["trail"]))); cand.append(k); why.append("trail")
    if ex.get("dev_exit"):
        later_users, later_buy = coin.user[j + 1:], coin.buy[j + 1:]
        k = first((later_users == coin.creator) & (later_buy == 0)) if len(later_users) else None
        cand.append(k); why.append("dev")
    if follow_wallet is not None:
        later_users, later_buy = coin.user[j + 1:], coin.buy[j + 1:]
        k = first((later_users == follow_wallet) & (later_buy == 0)) if len(later_users) else None
        cand.append(k); why.append("wallet")
    if coin.mig_ts is not None:
        k = first(ts >= coin.mig_ts - lat); cand.append(k); why.append("migrate")
    best = min((c, w) for c, w in zip(cand, why) if c is not None)
    k, reason = best

    def exit_value(k_idx, frac):
        # decision at trade k_idx, executed at reserves current latency seconds later
        t_exit = ts[k_idx] + lat
        if coin.mig_ts is not None and t_exit >= coin.mig_ts:
            last = coin.state_at(coin.mig_ts - 1e-6)
            return sell_sol(coin.vsol[last], coin.vtok[last], tokens * frac) * (1 - MIGRATE_HAIRCUT)
        m = coin.state_at(t_exit)
        m = max(m, j)
        return sell_sol(coin.vsol[m], coin.vtok[m], tokens * frac)

    proceeds = 0.0
    if ex.get("tp_frac") and ex.get("tp"):
        kp = first(rel[:k + 1] >= ex["tp"])
        if kp is not None:  # partial take profit, rest follows the other rules
            proceeds += exit_value(kp, ex["tp_frac"]) - NET_FEE
            proceeds += exit_value(k, 1 - ex["tp_frac"]) - NET_FEE
        else:
            proceeds += exit_value(k, 1.0) - NET_FEE
    else:
        proceeds += exit_value(k, 1.0) - NET_FEE
    return {"pnl": proceeds - cost, "ret": (proceeds - cost) / cost, "why": reason, "hold": float(hold[k])}


# ----------------------------------------------------------------------------------------------- strategies
def first_signal(tr: pd.DataFrame, mask: np.ndarray) -> pd.Series:
    """Row index of the first trade per coin where mask is true (tr is sorted by coin, then time)."""
    rows = np.flatnonzero(mask)
    mints = tr.mint.to_numpy()[rows]
    _, first = np.unique(mints, return_index=True)
    return pd.Series(rows[first], index=mints[first])


def base_safety(tr, p):
    ok = np.ones(len(tr), bool)
    if p.get("dev_hold"):
        ok &= ~tr.dev_sold.to_numpy()
    if p.get("max_top") is not None:
        ok &= tr.top_share.to_numpy() <= p["max_top"]
    if p.get("no_mayhem"):
        ok &= tr.mayhem.fillna(0).to_numpy() == 0
    if p.get("max_dev_buy") is not None:
        ok &= tr.dev_buy.fillna(0).to_numpy() <= p["max_dev_buy"]
    if p.get("creator_clean"):
        ok &= (tr.prev_launches.fillna(0).to_numpy() == 0) | (tr.prev_migrated.fillna(0).to_numpy() > 0)
    return ok


def sig_baseline(tr, p):
    return (tr.age.to_numpy() >= p["at"])


def sig_momentum(tr, p):
    a = tr.age.to_numpy()
    w = p["w"]
    m = (a >= p["age_min"]) & (a <= p["age_max"])
    m &= tr[f"newb{w}"].to_numpy() >= p["min_newb"]
    m &= tr[f"bsol{w}"].to_numpy() >= p["flow"] * np.maximum(tr[f"ssol{w}"].to_numpy(), 1e-9)
    m &= tr.mcap.to_numpy() <= p["max_mcap"]
    return m


def sig_progress(tr, p):
    a = tr.age.to_numpy()
    return (tr.mcap.to_numpy() >= p["mcap_in"]) & (a <= p["max_age"]) & \
        (tr.uniq_buyers.to_numpy() >= p["min_buyers"])


def sig_dip(tr, p):
    a = tr.age.to_numpy()
    return (a <= p["max_age"]) & (tr.ath.to_numpy() >= p["pump"] * tr.mcap.groupby(tr.mint).transform("first").to_numpy()) \
        & (tr.dd.to_numpy() >= p["dd_lo"]) & (tr.dd.to_numpy() <= p["dd_hi"]) \
        & (tr.bsol30.to_numpy() > tr.ssol30.to_numpy())


def sig_flip(tr, p):
    return tr.age.to_numpy() >= p["at"]


FAMILIES = {
    "baseline": (sig_baseline, {"at": [5]}, [{"time": 600}]),
    "fast_flip": (sig_flip, {"at": [0, 2, 5]}, [{"time": t} for t in (5, 15, 30, 60)]),
    "momentum": (sig_momentum,
                 {"w": [30, 60], "age_min": [30, 60], "age_max": [300, 600], "min_newb": [5, 10, 20],
                  "flow": [1.5, 3], "max_mcap": [60, 120]},
                 None),
    "progress": (sig_progress, {"mcap_in": [60, 100, 150, 250], "max_age": [600, 1800], "min_buyers": [20, 50]}, None),
    "dip": (sig_dip, {"max_age": [900], "pump": [3, 5], "dd_lo": [0.3, 0.45], "dd_hi": [0.6]}, None),
}

EXITS = [dict(e) for e in [
    {"time": 600}, {"time": 1800},
    {"tp": 2, "stop": 0.3, "time": 1200}, {"tp": 3, "stop": 0.4, "time": 1800}, {"tp": 5, "stop": 0.5, "time": 1800},
    {"tp": 2, "tp_frac": 0.5, "trail": 0.3, "trail_arm": 1.0, "time": 1800},
    {"trail": 0.25, "trail_arm": 1.2, "stop": 0.3, "time": 1800},
    {"tp": 2, "tp_frac": 0.5, "trail": 0.3, "dev_exit": True, "time": 1200},
]]

SAFETY = [{}, {"dev_hold": True}, {"dev_hold": True, "max_top": 0.1, "no_mayhem": True},
          {"dev_hold": True, "max_top": 0.1, "creator_clean": True, "max_dev_buy": 1.0}]


def grid(space):
    keys = list(space)
    for vals in itertools.product(*(space[k] for k in keys)):
        yield dict(zip(keys, vals))


def run_rule(tr, coins_by_mint, entry_mask, ex, mints=None):
    idx = first_signal(tr, entry_mask)
    out = []
    for mint, i in idx.items():
        if mints is not None and mint not in mints:
            continue
        c = coins_by_mint[mint]
        start = c[1]
        r = simulate(c[0], int(i - start), ex)
        if r:
            r["mint"] = mint
            out.append(r)
    return pd.DataFrame(out)


def summary(res: pd.DataFrame) -> dict:
    if res is None or len(res) == 0:
        return {"n": 0, "pnl": 0.0, "mean": 0.0, "win": 0.0, "lo": 0.0, "hi": 0.0}
    p = res.pnl.to_numpy()
    rng = np.random.default_rng(0)
    boots = rng.choice(p, (1000, len(p))).sum(1)
    return {"n": len(p), "pnl": p.sum(), "mean": res.ret.mean(), "win": (p > 0).mean(),
            "lo": np.percentile(boots, 2.5), "hi": np.percentile(boots, 97.5)}


def copy_wallets(tr, train_mints, min_coins=5, top=50):
    """Wallets with the best realized curve PnL on training coins (round trips valued at last price)."""
    t = tr[tr.mint.isin(train_mints)]
    flow = t.assign(s=np.where(t.buy == 1, -t.sol, t.sol), q=np.where(t.buy == 1, t.tokens, -t.tokens))
    g = flow.groupby(["user", "mint"]).agg(s=("s", "sum"), q=("q", "sum"))
    last_price = t.groupby("mint").price.last()
    g["val"] = g.s + g.q.clip(lower=0) * last_price.reindex(g.index.get_level_values(1)).to_numpy()
    w = g.groupby(level=0).agg(pnl=("val", "sum"), coins=("val", "size"))
    w = w[(w.coins >= min_coins) & (w.pnl > 0)].sort_values("pnl", ascending=False)
    return list(w.index[:top])


def main(folder="data"):
    cr, mig, tr = load(folder)
    tr, coins = prepare(cr, mig, tr)
    order = coins.sort_values("t_ms").mint.tolist()
    cut = int(len(order) * TRAIN)
    train, hold = set(order[:cut]), set(order[cut:])
    span_h = (coins.t_ms.max() - coins.t_ms.min()) / 3.6e6
    print(f"{len(coins):,} coins over {span_h:.0f} h, {len(tr):,} trades in their first {WINDOW_MIN} min; "
          f"train {len(train):,} coins, holdout {len(hold):,}; size {SIZE} SOL, fee {FEE:.2%}/side, latency {LATENCY}s")
    starts = tr.groupby("mint").cumcount()
    first_idx = (tr.index.to_series() - starts).groupby(tr.mint).first()
    coins_by_mint = {m: (Coin(df), first_idx[m]) for m, df in tr.groupby("mint")}

    rows = []
    for fam, (sig, space, fam_exits) in FAMILIES.items():
        exits = fam_exits or EXITS
        safeties = [{}] if fam in ("baseline", "fast_flip") else SAFETY
        for p in grid(space):
            raw = sig(tr, p)
            for s in safeties:
                mask = raw & base_safety(tr, s)
                for ex in exits:
                    r_tr = run_rule(tr, coins_by_mint, mask, ex, train)
                    st = summary(r_tr)
                    rows.append({"family": fam, "params": p, "safety": s, "exit": ex, **{f"tr_{k}": v for k, v in st.items()}})
        print(f"{fam}: {len(rows)} combinations so far", flush=True)

    # copy trading: follow the best training wallets' buys in the holdout
    for top, maxage in itertools.product([20, 50, 200], [60, 300, 1800]):
        wallets = set(copy_wallets(tr, train, top=top))
        mask = tr.user.isin(wallets).to_numpy() & (tr.buy.to_numpy() == 1) & (tr.age.to_numpy() <= maxage)
        for ex in EXITS:
            st = summary(run_rule(tr, coins_by_mint, mask, ex, train))
            rows.append({"family": "copy", "params": {"top": top, "max_age": maxage}, "safety": {}, "exit": ex,
                         **{f"tr_{k}": v for k, v in st.items()}})

    res = pd.DataFrame(rows)
    res = res[res.tr_n >= 30].sort_values("tr_pnl", ascending=False)
    print("\nBest per family on TRAIN (min 30 trades), then the same rule on the HOLDOUT:")
    report = []
    for fam, g in res.groupby("family", sort=False):
        for _, b in g.head(3).iterrows():
            if fam == "copy":
                wallets = set(copy_wallets(tr, train, top=b.params["top"]))
                mask = tr.user.isin(wallets).to_numpy() & (tr.buy.to_numpy() == 1) & (tr.age.to_numpy() <= b.params["max_age"])
            else:
                mask = FAMILIES[fam][0](tr, b.params) & base_safety(tr, b.safety)
            ho = summary(run_rule(tr, coins_by_mint, mask, b.exit, hold))
            report.append({"family": fam, "params": b.params, "safety": b.safety, "exit": b.exit,
                           "train_n": b.tr_n, "train_pnl": round(b.tr_pnl, 3), "train_mean": round(b.tr_mean, 3),
                           "hold_n": ho["n"], "hold_pnl": round(ho["pnl"], 3), "hold_mean": round(ho["mean"], 3),
                           "hold_win": round(ho["win"], 2), "hold_ci": (round(ho["lo"], 2), round(ho["hi"], 2))})
    rep = pd.DataFrame(report)
    with pd.option_context("display.max_colwidth", 80, "display.width", 250):
        print(rep.to_string(index=False))
    os.makedirs("results", exist_ok=True)
    res.to_csv("results/train_grid.csv", index=False)
    rep.to_csv("results/holdout.csv", index=False)
    print(f"\n{len(res)} combinations with 30+ train trades; positive on train: {(res.tr_pnl > 0).sum()}; "
          f"pnl in SOL per {SIZE} SOL trade")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")

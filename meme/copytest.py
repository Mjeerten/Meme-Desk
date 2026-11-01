"""Copy trading, tested properly: do profitable pump.fun wallets keep making money, and can we copy them in time?

1. Wallet results per coin (first hour of each coin): SOL out - SOL in + tokens still held at the last price.
2. Persistence: rank wallets on the training coins, then look at the SAME wallets on the later (holdout) coins.
   That is the best a copier could ever get (perfect copy, no delay, no fees on our side).
3. "Copyable" wallets only: enough coins, mostly winning, not bots (median hold >= 30 s), not coin creators.
4. Copy simulation on the holdout: buy when a followed wallet buys (one entry per coin), after 0 / 1 / 2 / 5 s,
   sell when that wallet sells (same delay) or after 30 min; curve-exact fills, fees, 0.2 SOL.

python -m meme.copytest data/
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from meme import backtest as bt


def wallet_coin_table(tr: pd.DataFrame) -> pd.DataFrame:
    last_price = tr.groupby("mint").price.last()
    t = tr.assign(s=np.where(tr.buy == 1, -tr.sol, tr.sol), q=np.where(tr.buy == 1, tr.tokens, -tr.tokens))
    first_buy = t[t.buy == 1].groupby(["user", "mint"]).ts.min()
    first_sell = t[t.buy == 0].groupby(["user", "mint"]).ts.min()
    g = t.groupby(["user", "mint"]).agg(s=("s", "sum"), q=("q", "sum"), n=("s", "size"), creator=("creator", "first"))
    g["spent"] = t[t.buy == 1].groupby(["user", "mint"]).sol.sum().reindex(g.index).fillna(0.0)
    g["pnl"] = g.s + g.q.clip(lower=0) * last_price.reindex(g.index.get_level_values(1)).to_numpy()
    g["hold"] = (first_sell.reindex(g.index) - first_buy.reindex(g.index))
    g["is_creator"] = g.index.get_level_values(0) == g.creator
    return g[g.spent > 0].drop(columns=["creator"])


def wallet_stats(wc: pd.DataFrame) -> pd.DataFrame:
    return wc.groupby(level=0).agg(coins=("pnl", "size"), pnl=("pnl", "sum"), spent=("spent", "sum"),
                                   win=("pnl", lambda x: (x > 0).mean()), hold=("hold", "median"),
                                   creator=("is_creator", "any"))


def main(folder="data"):
    cr, mig, tr = bt.load(folder)
    tr, coins = bt.prepare(cr, mig, tr)
    order = coins.sort_values("t_ms").mint.tolist()
    cut = int(len(order) * bt.TRAIN)
    train, hold = set(order[:cut]), set(order[cut:])
    wc = wallet_coin_table(tr)
    mints = wc.index.get_level_values(1)
    w_tr = wallet_stats(wc[mints.isin(train)])
    w_ho = wallet_stats(wc[mints.isin(hold)])
    print(f"{len(coins):,} coins, {len(wc):,} wallet-coin pairs, wallets: {len(w_tr):,} on train coins, "
          f"{len(w_ho):,} on holdout coins, {len(w_tr.index.intersection(w_ho.index)):,} on both")
    allw = pd.concat([w_tr.add_prefix("tr_"), w_ho.add_prefix("ho_")], axis=1)
    print(f"\nAll wallets on the holdout: {w_ho.pnl.sum():+,.0f} SOL total, {(w_ho.pnl > 0).mean():.0%} of wallets "
          f"in profit (on the curve, first hour, before their own fees beyond pump.fun's)")

    print("\n== Persistence: wallets ranked on TRAIN coins, their result on HOLDOUT coins (perfect copy, no delay) ==")
    rows = []
    for min_coins in (5, 10, 20):
        both = allw[(allw.tr_coins >= min_coins) & (allw.ho_coins >= 3)].sort_values("tr_pnl", ascending=False)
        rho = both.tr_pnl.rank().corr(both.ho_pnl.rank()) if len(both) > 10 else np.nan
        for top in (10, 50, 200, 1000):
            s = both.head(top)
            if len(s) == 0:
                continue
            rows.append({"min_train_coins": min_coins, "top": top, "wallets": len(s),
                         "train_SOL": round(s.tr_pnl.sum(), 1), "holdout_SOL": round(s.ho_pnl.sum(), 1),
                         "holdout_per_coin": round(s.ho_pnl.sum() / s.ho_coins.sum(), 4),
                         "holdout_wallets_in_profit": f"{(s.ho_pnl > 0).mean():.0%}", "rank_corr_all": round(rho, 2)})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n== Who are the top wallets? (top 50 by train profit, 10+ train coins) ==")
    top50 = allw[allw.tr_coins >= 10].sort_values("tr_pnl", ascending=False).head(50)
    print(f"median coins {top50.tr_coins.median():.0f}, median hold {top50.tr_hold.median():.0f} s, "
          f"held < 30 s: {(top50.tr_hold < 30).mean():.0%}, coin creators: {top50.tr_creator.mean():.0%}, "
          f"win rate {top50.tr_win.median():.0%}")

    print("\n== Copy simulation on HOLDOUT coins (0.2 SOL, fees, curve fills; exit when the wallet sells or 30 min) ==")
    starts = tr.groupby("mint").cumcount()
    first_idx = (tr.index.to_series() - starts).groupby(tr.mint).first()
    coin_obj = {m: (bt.Coin(df), first_idx[m]) for m, df in tr.groupby("mint") if m in hold}
    sims = []
    filters = {
        "top 50 by profit": lambda w: w[w.coins >= 10].sort_values("pnl", ascending=False).head(50),
        "copyable: 10+ coins, win>=50%, hold>=30s, not creator, top 50": lambda w: w[
            (w.coins >= 10) & (w.win >= 0.5) & (w.hold >= 30) & ~w.creator].sort_values("pnl", ascending=False).head(50),
        "copyable, top 200": lambda w: w[(w.coins >= 10) & (w.win >= 0.5) & (w.hold >= 30) & ~w.creator]
            .sort_values("pnl", ascending=False).head(200),
        "most consistent: 20+ coins, win>=60%, hold>=60s": lambda w: w[
            (w.coins >= 20) & (w.win >= 0.6) & (w.hold >= 60) & ~w.creator].sort_values("pnl", ascending=False).head(100),
    }
    ho_tr = tr[tr.mint.isin(hold)]
    for name, f in filters.items():
        wallets = set(f(w_tr).index)
        if not wallets:
            print(name, ": no wallets")
            continue
        sig = ho_tr[ho_tr.user.isin(wallets) & (ho_tr.buy == 1) & (ho_tr.age <= 1800)]
        sig = sig.groupby("mint").head(1)
        for lat in (0, 1, 2, 5):
            res = []
            for i, row in sig.iterrows():
                c, start = coin_obj[row.mint]
                r = bt.simulate(c, int(i - start), {"time": 1800, "latency": lat}, follow_wallet=row.user)
                if r:
                    res.append(r)
            st = bt.summary(pd.DataFrame(res))
            sims.append({"wallets": name, "followed": len(wallets), "delay_s": lat, "trades": st["n"],
                         "SOL": round(st["pnl"], 2), "per_trade": f"{st['mean']:+.1%}", "win": f"{st['win']:.0%}",
                         "95%_range": (round(st["lo"], 1), round(st["hi"], 1))})
    with pd.option_context("display.width", 250, "display.max_colwidth", 70):
        print(pd.DataFrame(sims).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")

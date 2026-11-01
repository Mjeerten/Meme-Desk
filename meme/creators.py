"""What do pump.fun coin creators make? (creator wallet only, first hour of each coin)

Per coin: SOL the creator's own wallet put in (dev buy + later buys) and took out (sells), plus tokens still held
valued at the last curve price (shown apart: those can rarely be sold at that price). Creation costs ~0.02 SOL
(not in the data); pump.fun's creator fee share on volume is NOT included (estimated separately from volume).
Bundled side wallets of the same creator are invisible here, so insider profits are understated.

python -m meme.creators data/
"""
import sys

import numpy as np
import pandas as pd

from meme import backtest as bt

CREATOR_FEE = 0.003   # assumed creator share of curve volume (check pump.fun's current rate)


def main(folder="data"):
    cr, mig, tr = bt.load(folder)
    tr, coins = bt.prepare(cr, mig, tr)
    d = tr[tr.user == tr.creator]
    g = d.groupby("mint").apply(lambda x: pd.Series({
        "sol_in": x.loc[x.buy == 1, "sol"].sum(), "sol_out": x.loc[x.buy == 0, "sol"].sum(),
        "tok_left": x.loc[x.buy == 1, "tokens"].sum() - x.loc[x.buy == 0, "tokens"].sum()}), include_groups=False)
    g = g.reindex(coins.mint).fillna(0.0)
    last_price = tr.groupby("mint").price.last().reindex(g.index)
    vol = tr.groupby("mint").sol.sum().reindex(g.index).fillna(0.0)
    g["realized"] = g.sol_out - g.sol_in - 0.02
    g["unrealized"] = g.tok_left.clip(lower=0) * last_price
    g["fees_est"] = vol * CREATOR_FEE
    g["migrated"] = g.index.isin(mig.index)
    n = len(g)
    print(f"{n:,} coins; migrated (curve completed) {g.migrated.mean():.2%}")
    for name, s in [("realized (sold - bought - 0.02 creation)", g.realized),
                    ("realized + est. creator fees", g.realized + g.fees_est),
                    ("realized + fees + unsold tokens at last price", g.realized + g.fees_est + g.unrealized)]:
        print(f"\n{name}: total {s.sum():+,.1f} SOL, mean {s.mean():+.3f}, median {s.median():+.3f} SOL per coin, "
              f"in profit {(s > 0).mean():.0%}")
        print("  percentiles (SOL):", {p: round(float(np.percentile(s, p)), 3) for p in (10, 25, 50, 75, 90, 99)})
    honest = g[g.sol_out == 0]
    print(f"\nCreators who never sold in the first hour: {len(honest):,} ({len(honest)/n:.0%}); "
          f"their est. fee income median {honest.fees_est.median():.4f} SOL, mean {honest.fees_est.mean():.4f}")
    print(f"Coins with volume > 10 SOL in their first hour: {(vol > 10).mean():.1%}; > 100 SOL: {(vol > 100).mean():.1%}")
    big = g[g.sol_in >= 1]
    print(f"Creators who put in >= 1 SOL: {len(big):,}, realized+fees mean {(big.realized + big.fees_est).mean():+.3f} SOL, "
          f"in profit {((big.realized + big.fees_est) > 0).mean():.0%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")

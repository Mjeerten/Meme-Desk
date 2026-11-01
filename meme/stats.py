"""Quick summary of recorded files. python -m meme.stats data/"""
import glob
import sys

import pandas as pd


def main(folder):
    L = [pd.read_csv(p, low_memory=False) for p in sorted(glob.glob(f"{folder}/**/*-launches.csv.gz", recursive=True))]
    T = [pd.read_csv(p, low_memory=False) for p in sorted(glob.glob(f"{folder}/**/*-trades.csv.gz", recursive=True))]
    if L:
        la = pd.concat(L).drop_duplicates(["type", "mint"])
        cr = la[la.type == "create"]
        h = max((cr.t_ms.max() - cr.t_ms.min()) / 3.6e6, 1e-9)
        mig = la[la.type == "migrate"].mint.isin(cr.mint).sum()
        print(f"launches {len(cr)} ({len(cr) / h:,.0f}/h), mayhem {cr.mayhem.mean():.0%}, "
              f"migrated within the run {mig} ({mig / max(len(cr), 1):.2%})")
    if T:
        raw = sum(len(t) for t in T)
        tr = pd.concat(T).drop_duplicates(["slot", "sig", "mint", "user", "sol", "tokens"])
        h = max((tr.recv_ms.max() - tr.recv_ms.min()) / 3.6e6, 1e-9)   # receive clock (always set)
        print(f"trades {len(tr):,} unique of {raw:,} rows ({len(tr) / h / 60:,.0f}/min), coins traded {tr.mint.nunique():,}")
        lag = tr.recv_ms / 1000 - pd.to_numeric(tr.ts, errors="coerce")
        print(f"on-chain time check: {lag.between(-5, 120).mean():.0%} of trades have ts within -5..120 s of receipt "
              f"(median lag {lag.median():.1f} s; far off = decoding offset wrong)")
        if L:
            new = tr[tr.mint.isin(cr.mint)]
            per = new.groupby("mint").size().reindex(cr.mint, fill_value=0)
            print(f"trades on coins launched in the run: {len(new):,}; per coin median {per.median():.0f}, "
                  f"90th {per.quantile(.9):.0f}, max {per.max()}; coins with no trade {(per == 0).mean():.0%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")

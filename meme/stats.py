"""Quick summary of recorded files. python -m meme.stats data/*.csv.gz"""
import sys

import pandas as pd


def main(paths):
    df = pd.concat([pd.read_csv(p, dtype={"extra": str, "slot_id": str}, low_memory=False) for p in paths],
                   ignore_index=True)
    c = df.type.value_counts()
    cr = df[df.type == "create"]
    hours = max((cr.t_ms.max() - cr.t_ms.min()) / 3.6e6, 1e-9) if len(cr) else 1
    print(f"{len(paths)} files, {hours:.1f} h of launches, {len(df):,} rows")
    print(c.to_string())
    print(f"launches per hour {len(cr) / hours:,.0f}")
    f = df[df.type == "fetched"]
    if len(f):
        n = pd.to_numeric(f.tokens, errors="coerce")
        print(f"fetched {len(f)} of {len(cr)} coins; trades per coin median {n.median():.0f}, 90th {n.quantile(.9):.0f},"
              f" max {n.max():.0f}, zero-trade coins {(n == 0).mean():.0%}, truncated {(f.extra == 'truncated').sum()}")
    mig = df[df.type == "migrate"].mint.isin(cr.mint).sum()
    if len(cr):
        print(f"migrated within the run: {mig} of {len(cr)} = {mig / len(cr):.2%}")


if __name__ == "__main__":
    main(sys.argv[1:])

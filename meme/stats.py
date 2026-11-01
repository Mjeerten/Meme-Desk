"""Quick summary of recorded files: launches, trades, how many coins migrated, data per hour.

python -m meme.stats data/*.csv.gz
"""
import sys

import pandas as pd


def main(paths):
    df = pd.concat([pd.read_csv(p, dtype={"extra": str}) for p in paths], ignore_index=True)
    hours = (df.t_ms.max() - df.t_ms.min()) / 3.6e6 or 1
    c = df.type.value_counts()
    launches = c.get("create", 0)
    print(f"{len(paths)} files, {hours:.1f} h, {len(df):,} events")
    print(c.to_string())
    print(f"launches per hour {launches / hours:,.0f}, trades per hour {(c.get('buy', 0) + c.get('sell', 0)) / hours:,.0f}")
    if launches:
        made = df[df.type == "migrate"].mint.isin(df[df.type == "create"].mint).sum()
        print(f"migrated (left the bonding curve): {made} of {launches} launches = {made / launches:.2%}")
        per = df[df.type.isin(["buy", "sell"])].groupby("mint").size()
        print("trades per token in the watch window: median", int(per.median()) if len(per) else 0,
              "| 90th pct", int(per.quantile(0.9)) if len(per) else 0, "| max", int(per.max()) if len(per) else 0)


if __name__ == "__main__":
    main(sys.argv[1:])

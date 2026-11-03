"""Convert the free pumpdata.fun Hugging Face sample (one full UTC day of pump.fun trades, 2026-10-15) into the
recorder's format, so meme/backtest.py runs on it unchanged.

Source: huggingface.co/datasets/pumpdatafun/pump-fun-trades-sample (CC BY 4.0). Only landed bonding-curve trades are
used (venue = curve, failed = false, r1 > 0); curve r1 = virtual SOL reserve (lamports), r2 = virtual token reserve
(base units, 6 decimals), after the trade. Coins: the day's `create` events; a coin's curve ends at its `complete`
(or `migrate`) event. Coins created in the last WINDOW minutes of the day are dropped (incomplete first hour).
Ordering inside a slot: recv_ms holds the transaction's index in the block (idx).

python -m meme.hf_data <hf folder> <out folder>
"""
import glob
import os
import sys

import pandas as pd
import pyarrow.parquet as pq

from meme.record import LAUNCH_FIELDS, TRADE_FIELDS

WINDOW = 60
COLS = ["ts", "slot", "idx", "venue", "failed", "mint", "wallet", "side", "sol_lamports", "token_amount", "r1", "r2"]


def convert(src: str, out: str):
    ev = pd.concat([pd.read_parquet(p) for p in glob.glob(os.path.join(src, "events", "*.parquet"))])
    print("event kinds:", ev.kind.value_counts().to_dict())
    cr = ev[ev.kind == "create"].copy()
    end_day = ev.ts.max()
    cr = cr[cr.ts <= end_day - WINDOW * 60]
    trades = []
    for p in sorted(glob.glob(os.path.join(src, "data", "*.parquet"))):
        t = pq.read_table(p, columns=COLS,
                          filters=[("venue", "=", "curve"), ("failed", "=", False)]).to_pandas()
        trades.append(t[t.r1 > 0])
        print(p, len(trades[-1]), "curve trades", flush=True)
    tr = pd.concat(trades, ignore_index=True)
    # create events: a = mint, b = creator; dev buy = creator's buys in the create transaction
    cr = cr.rename(columns={"a": "mint", "b": "creator"})
    cr = cr[cr.mint.isin(tr.mint)] if len(cr) else cr
    first_tx = tr.merge(cr[["mint", "creator", "slot", "idx"]], on=["mint", "slot", "idx"])
    dev = first_tx[(first_tx.wallet == first_tx.creator) & (first_tx.side == "buy")].groupby("mint").sol_lamports.sum() / 1e9
    launches = pd.DataFrame({"t_ms": cr.ts.astype("int64") * 1000, "type": "create", "mint": cr.mint,
                             "creator": cr.creator, "sol": cr.mint.map(dev).fillna(0.0), "tokens": "",
                             "mcap_sol": "", "pool": "pump", "mayhem": 0, "symbol": "", "name": ""})
    done = ev[ev.kind.isin(["complete", "migrate"])].sort_values("ts").drop_duplicates("a")
    mig = pd.DataFrame({"t_ms": done.ts.astype("int64") * 1000, "type": "migrate", "mint": done.a, "creator": "",
                        "sol": "", "tokens": "", "mcap_sol": "", "pool": done.kind, "mayhem": "", "symbol": "",
                        "name": ""})
    tr = tr[tr.mint.isin(launches.mint)]
    trades_out = pd.DataFrame({"recv_ms": tr.idx, "slot": tr.slot, "sig": tr.slot.astype(str) + "-" + tr.idx.astype(str),
                               "ts": tr.ts, "mint": tr.mint, "user": tr.wallet, "buy": (tr.side == "buy").astype(int),
                               "sol": tr.sol_lamports / 1e9, "tokens": tr.token_amount / 1e6,
                               "vsol": tr.r1 / 1e9, "vtok": tr.r2 / 1e6})
    os.makedirs(out, exist_ok=True)
    pd.concat([launches, mig]).reindex(columns=LAUNCH_FIELDS).to_csv(os.path.join(out, "hf-20261015-x-launches.csv.gz"), index=False)
    trades_out.reindex(columns=TRADE_FIELDS).to_csv(os.path.join(out, "hf-20261015-x-trades.csv.gz"), index=False)
    print(f"{len(launches):,} coins, {len(mig):,} completions/migrations, {len(trades_out):,} curve trades on them")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])

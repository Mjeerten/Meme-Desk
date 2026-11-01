"""Record every pump.fun launch and its trades from PumpPortal's free data feed.

Scan / check / buy / sell backtests need the full picture, rugs included, so the recorder subscribes to every new
token and keeps its trades for WATCH_MIN minutes after launch (the window a sniping strategy trades in). Migrations
(token leaves the bonding curve for PumpSwap) are recorded too, so we know which coins "made it".

Output: data/YYYYMMDD-HHMM.csv.gz, one row per event, receive time in ms UTC:
  t_ms,type,mint,trader,sol,tokens,vsol,vtok,mcap_sol,extra
  type = create | buy | sell | migrate; extra = symbol|name|initial buy on create rows.

Run:  python -m meme.record --minutes 345
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json
import os
import time
from datetime import datetime, timezone

URL = "wss://pumpportal.fun/api/data"
WATCH_MIN = 60          # keep a token's trades this long after launch
FIELDS = ["t_ms", "type", "mint", "trader", "sol", "tokens", "vsol", "vtok", "mcap_sol", "extra"]


def to_row(msg: dict, now_ms: int) -> list | None:
    """Turn one PumpPortal message into a CSV row (None for acks / unknown messages)."""
    kind = msg.get("txType")
    if kind is None and msg.get("mint") and "message" not in msg:
        kind = "migrate"  # migration events may come without a txType
    if kind not in ("create", "buy", "sell", "migrate"):
        return None
    extra = ""
    if kind == "create":
        name = str(msg.get("name", "")).replace("|", "/").replace("\n", " ")[:40]
        sym = str(msg.get("symbol", "")).replace("|", "/").replace("\n", " ")[:20]
        extra = f"{sym}|{name}|{msg.get('initialBuy', '')}"

    def num(k):
        v = msg.get(k)
        return "" if v is None else (f"{v:.9g}" if isinstance(v, float) else v)

    return [now_ms, kind, msg.get("mint", ""), msg.get("traderPublicKey", ""), num("solAmount"),
            num("tokenAmount") if kind != "create" else num("initialBuy"),
            num("vSolInBondingCurve"), num("vTokensInBondingCurve"), num("marketCapSol"), extra]


class Recorder:
    def __init__(self, path: str, watch_min: int = WATCH_MIN):
        self.path = path
        self.watch_ms = watch_min * 60_000
        self.active: dict[str, int] = {}      # mint -> launch time (ms)
        self.counts: dict[str, int] = {}
        self.shapes: set = set()              # message shapes already printed (to check the feed format)
        self.f = gzip.open(path, "wt", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(FIELDS)

    def handle(self, msg: dict, now_ms: int) -> str | None:
        """Write the message; return a mint to subscribe to when it is a new launch."""
        shape = (msg.get("txType"), tuple(sorted(msg)), str(msg.get("message", msg.get("errors", "")))[:60])
        if shape not in self.shapes and len(self.shapes) < 40:
            self.shapes.add(shape)
            print("sample:", json.dumps(msg)[:600], flush=True)
        row = to_row(msg, now_ms)
        if row is None:
            return None
        self.w.writerow(row)
        self.counts[row[1]] = self.counts.get(row[1], 0) + 1
        if row[1] == "create" and row[2]:
            self.active[row[2]] = now_ms
            return row[2]
        return None

    def expired(self, now_ms: int) -> list[str]:
        old = [m for m, t in self.active.items() if now_ms - t > self.watch_ms]
        for m in old:
            del self.active[m]
        return old

    def close(self):
        self.f.close()


async def run(minutes: float, out_dir: str = "data", watch_min: int = WATCH_MIN):
    import websockets

    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rec = Recorder(os.path.join(out_dir, f"{stamp}.csv.gz"), watch_min)
    end = time.time() + minutes * 60
    backoff = 2
    last_log = time.time()
    try:
        while time.time() < end:
            try:
                async with websockets.connect(URL, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    if rec.active:  # reconnect: pick the watched tokens back up
                        keys = list(rec.active)
                        for i in range(0, len(keys), 500):
                            await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": keys[i:i + 500]}))
                    backoff = 2
                    last_sweep = time.time()
                    while time.time() < end:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=60)
                        except asyncio.TimeoutError:
                            print("no data for 60 s, reconnecting", flush=True)
                            break
                        now_ms = int(time.time() * 1000)
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        new = rec.handle(msg, now_ms)
                        if new:
                            await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [new]}))
                        if time.time() - last_sweep > 30:
                            old = rec.expired(now_ms)
                            for i in range(0, len(old), 500):
                                await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": old[i:i + 500]}))
                            last_sweep = time.time()
                        if time.time() - last_log > 600:
                            print(datetime.now(timezone.utc).strftime("%H:%M"), rec.counts,
                                  "watching", len(rec.active), flush=True)
                            rec.f.flush()
                            last_log = time.time()
            except Exception as e:  # network drop, server close: back off and reconnect
                print("connection error:", repr(e), "- retry in", backoff, "s", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        rec.close()
        print("done", rec.path, rec.counts, flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=345)
    p.add_argument("--out", default="data")
    p.add_argument("--watch", type=int, default=WATCH_MIN)
    a = p.parse_args()
    asyncio.run(run(a.minutes, a.out, a.watch))


if __name__ == "__main__":
    main()

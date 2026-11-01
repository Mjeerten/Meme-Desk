"""Record pump.fun launches (PumpPortal free feed) and each coin's first-hour trades (pump.fun trade API, free).

Every launch is seen on the PumpPortal websocket (free: creations + migrations). WATCH_MIN minutes after a launch,
the coin's trades are fetched from swap-api.pump.fun (free, ~20 requests/min per IP, 100 trades per page), so the
file holds the whole first hour of every coin, rugs included. To stay inside the rate limit the work is split over
SHARDS parallel runners (each takes the mints whose hash % SHARDS == SHARD); a shard that falls behind skips coins
(type=skipped), which keeps the sample unbiased.

Output: data/YYYYMMDD-HHMM-sK.csv.gz, one row per event:
  t_ms,type,mint,trader,sol,tokens,price_sol,slot_id,program,extra
  type = create | buy | sell | migrate | fetched | skipped
  create: t_ms = receive time, sol = dev's initial buy (SOL), tokens = initial buy (tokens),
          price_sol = market cap in SOL, extra = symbol|name|mayhem
  buy/sell: t_ms = trade timestamp (ms) from the pump.fun API.
  fetched: tokens = number of trades returned, extra = truncated if more than MAX_PAGES pages.

Run:  python -m meme.record --minutes 280 --shard 0 --shards 4
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone

WS_URL = "wss://pumpportal.fun/api/data"
TRADES_URL = "https://swap-api.pump.fun/v2/coins/{mint}/trades"
WATCH_MIN = 60          # fetch a coin's trades this long after launch
MAX_PAGES = 40          # 4,000 trades; more is marked truncated
REQ_PER_MIN = 18        # stay under pump.fun's ~20/min
MAX_BACKLOG_MIN = 45    # a coin waiting longer than this past its due time is skipped
FIELDS = ["t_ms", "type", "mint", "trader", "sol", "tokens", "price_sol", "slot_id", "program", "extra"]


def shard_of(mint: str, shards: int) -> int:
    return int(hashlib.md5(mint.encode()).hexdigest(), 16) % shards


def ts_ms(v):
    """pump.fun timestamps: accept seconds, ms or ISO strings."""
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        return int(v * 1000) if v < 1e11 else int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return str(v)


def create_row(msg: dict, now_ms: int) -> list | None:
    kind = msg.get("txType")
    if kind is None and msg.get("mint") and "message" not in msg:
        kind = "migrate"
    if kind == "migrate":
        return [now_ms, "migrate", msg.get("mint", ""), "", "", "", "", "", msg.get("pool", ""), ""]
    if kind != "create":
        return None

    def clean(s, n):
        return str(s or "").replace("|", "/").replace("\n", " ")[:n]

    extra = f"{clean(msg.get('symbol'), 20)}|{clean(msg.get('name'), 40)}|{int(bool(msg.get('is_mayhem_mode')))}"
    return [now_ms, "create", msg.get("mint", ""), msg.get("traderPublicKey", ""), msg.get("solAmount", ""),
            msg.get("initialBuy", ""), msg.get("marketCapSol", ""), "", msg.get("pool", ""), extra]


def trade_rows(mint: str, trades: list[dict]) -> list[list]:
    rows = []
    for t in trades:
        kind = str(t.get("type", "")).lower()
        if kind not in ("buy", "sell"):
            continue
        rows.append([ts_ms(t.get("timestamp")), kind, mint, t.get("userAddress", ""), t.get("amountSol", ""),
                     t.get("baseAmount", ""), t.get("fillPriceSol") or t.get("priceSol", ""),
                     t.get("slotIndexId", ""), t.get("program", ""), ""])
    rows.sort(key=lambda r: (r[0] if isinstance(r[0], int) else 0, str(r[7])))
    return rows


class Limiter:
    def __init__(self, per_min: int):
        self.gap = 60.0 / per_min
        self.next = 0.0

    async def wait(self):
        now = time.monotonic()
        if now < self.next:
            await asyncio.sleep(self.next - now)
        self.next = max(now, self.next) + self.gap


async def fetch_trades(http, limiter: Limiter, mint: str, log) -> tuple[list[dict], bool]:
    """All trades of a coin, up to MAX_PAGES pages. Returns (trades, truncated)."""
    out, cursor = [], None
    for _ in range(MAX_PAGES):
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        data = None
        for attempt in range(6):
            await limiter.wait()
            try:
                r = await http.get(TRADES_URL.format(mint=mint), params=params)
                if r.status_code == 429 or r.status_code >= 500:
                    log(f"http {r.status_code}, backing off")
                    await asyncio.sleep(min(60, 2 ** attempt) * (0.5 + random.random()))
                    continue
                if r.status_code != 200:
                    log(f"http {r.status_code} for {mint}: {r.text[:200]}")
                    return out, False
                data = r.json()
                break
            except Exception as e:  # timeouts, bad json
                log(f"fetch error {e!r}")
                await asyncio.sleep(min(60, 2 ** attempt))
        if data is None:
            return out, False
        if isinstance(data, list):
            items, pag = data, {}
        else:
            items = data.get("trades") or data.get("data") or data.get("items") or []
            pag = data.get("pagination") or {}
        out.extend(items)
        cursor = pag.get("nextCursor")
        if not pag.get("hasMore") or not cursor:
            return out, False
    return out, True


class Recorder:
    def __init__(self, path: str, shard: int = 0, shards: int = 1, watch_min: int = WATCH_MIN):
        self.shard, self.shards, self.watch_ms = shard, shards, watch_min * 60_000
        self.due: list[tuple[int, str]] = []   # (due ms, mint), in launch order
        self.counts: dict[str, int] = {}
        self.seen_shapes: set = set()
        self.path = path
        self.f = gzip.open(path, "wt", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(FIELDS)

    def write(self, row):
        self.w.writerow(row)
        self.counts[row[1]] = self.counts.get(row[1], 0) + 1

    def on_message(self, msg: dict, now_ms: int):
        shape = (msg.get("txType"), str(msg.get("message", msg.get("errors", "")))[:60])
        if shape not in self.seen_shapes and len(self.seen_shapes) < 20:
            self.seen_shapes.add(shape)
            print("sample:", json.dumps(msg)[:500], flush=True)
        row = create_row(msg, now_ms)
        if row is None or shard_of(row[2], self.shards) != self.shard:
            return
        self.write(row)
        if row[1] == "create":
            self.due.append((now_ms + self.watch_ms, row[2]))

    def close(self):
        self.f.close()


async def listen(rec: Recorder, end: float):
    import websockets
    backoff = 2
    while time.time() < end:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                backoff = 2
                while time.time() < end:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60)
                    except asyncio.TimeoutError:
                        print("no data for 60 s, reconnecting", flush=True)
                        break
                    try:
                        rec.on_message(json.loads(raw), int(time.time() * 1000))
                    except ValueError:
                        pass
        except Exception as e:
            print("websocket error:", repr(e), "- retry in", backoff, "s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def fetcher(rec: Recorder, end: float, fetch_until: float):
    import httpx
    limiter = Limiter(REQ_PER_MIN)
    n_log = [0]

    def log(s):
        n_log[0] += 1
        if n_log[0] <= 30 or n_log[0] % 100 == 0:
            print(s, flush=True)

    first = True
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as http:
        while time.time() < fetch_until:
            now_ms = int(time.time() * 1000)
            if not rec.due or rec.due[0][0] > now_ms:
                if time.time() >= end and not rec.due:
                    return
                await asyncio.sleep(2)
                continue
            due, mint = rec.due.pop(0)
            if now_ms - due > MAX_BACKLOG_MIN * 60_000:
                rec.write([now_ms, "skipped", mint, "", "", "", "", "", "", "backlog"])
                continue
            trades, truncated = await fetch_trades(http, limiter, mint, log)
            if first and trades:
                print("trade sample:", json.dumps(trades[0])[:500], flush=True)
                first = False
            for row in trade_rows(mint, trades):
                rec.write(row)
            rec.write([now_ms, "fetched", mint, "", "", len(trades), "", "", "", "truncated" if truncated else ""])


async def run(minutes: float, shard: int, shards: int, out_dir: str = "data", watch_min: int = WATCH_MIN):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rec = Recorder(os.path.join(out_dir, f"{stamp}-s{shard}.csv.gz"), shard, shards, watch_min)
    end = time.time() + minutes * 60                 # stop listening for launches
    fetch_until = end + (watch_min + 2) * 60         # keep fetching the last launches' first hour
    print(f"shard {shard}/{shards}, listen {minutes} min, fetch until +{watch_min + 2} min", flush=True)

    async def progress():
        while True:
            await asyncio.sleep(600)
            print(datetime.now(timezone.utc).strftime("%H:%M"), rec.counts, "queue", len(rec.due), flush=True)
            rec.f.flush()

    work = [asyncio.create_task(listen(rec, end)), asyncio.create_task(fetcher(rec, end, fetch_until))]
    prog = asyncio.create_task(progress())
    try:
        await asyncio.gather(*work)
    finally:
        prog.cancel()
        left = len(rec.due)
        for _, mint in rec.due:
            rec.write([int(time.time() * 1000), "skipped", mint, "", "", "", "", "", "", "run ended"])
        rec.close()
        print("done", rec.path, rec.counts, "unfetched at end", left, flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=280)
    p.add_argument("--shard", type=int, default=0)
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--out", default="data")
    p.add_argument("--watch", type=int, default=WATCH_MIN)
    a = p.parse_args()
    asyncio.run(run(a.minutes, a.shard, a.shards, a.out, a.watch))


if __name__ == "__main__":
    main()

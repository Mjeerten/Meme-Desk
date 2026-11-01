"""Record pump.fun launches and every bonding-curve trade, from free sources only.

- Launches + migrations: PumpPortal websocket (free part: subscribeNewToken, subscribeMigration).
- Trades: free public Solana RPC, logsSubscribe on the pump.fun program; each TradeEvent is decoded from the
  'Program data:' log line (coin, SOL, tokens, buy/sell, wallet, curve reserves after the trade).
  The public RPC drops the connection every 10-30 s (~8% downtime), so the workflow runs two copies on different
  runners; the backtest merges them and drops duplicates (same slot + signature prefix).
  (pump.fun's own trade API is behind Cloudflare and blocks GitHub runners; PumpPortal trade streams need a
  funded key.)

Output, per run: data/YYYYMMDD-HHMM-<copy>-launches.csv.gz and -trades.csv.gz
  launches: t_ms,type,mint,creator,sol,tokens,mcap_sol,pool,mayhem,symbol,name   (type = create | migrate)
  trades:   recv_ms,slot,sig,ts,mint,user,buy,sol,tokens,vsol,vtok
            (ts = on-chain unix seconds; sol/tokens of the trade; vsol/vtok = virtual curve reserves after it,
             so price = vsol / vtok SOL per token)

Run:  python -m meme.record --minutes 340 --copy a
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import gzip
import json
import os
import struct
import time
from datetime import datetime, timezone

PP_URL = "wss://pumpportal.fun/api/data"
RPC_URL = "wss://api.mainnet-beta.solana.com"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TRADE_DISC = bytes.fromhex("bddb7fd34ee661ee")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
LAUNCH_FIELDS = ["t_ms", "type", "mint", "creator", "sol", "tokens", "mcap_sol", "pool", "mayhem", "symbol", "name"]
TRADE_FIELDS = ["recv_ms", "slot", "sig", "ts", "mint", "user", "buy", "sol", "tokens", "vsol", "vtok"]


def b58(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def decode_trade(data: bytes) -> dict | None:
    """pump.fun TradeEvent: disc(8) mint(32) sol u64 tokens u64 is_buy u8 user(32) ts i64 vsol u64 vtok u64 ..."""
    if len(data) < 129 or data[:8] != TRADE_DISC:
        return None
    mint = b58(data[8:40])
    sol, tok = struct.unpack_from("<QQ", data, 40)
    is_buy = data[56]
    user = b58(data[57:89])
    ts, vsol, vtok = struct.unpack_from("<qQQ", data, 89)
    return {"mint": mint, "sol": sol / 1e9, "tokens": tok / 1e6, "buy": int(bool(is_buy)), "user": user, "ts": ts,
            "vsol": vsol / 1e9, "vtok": vtok / 1e6}


def trades_from_logs(logs: list[str]) -> list[dict]:
    out = []
    for line in logs:
        if line.startswith("Program data: "):
            try:
                t = decode_trade(base64.b64decode(line[14:]))
            except ValueError:
                continue
            if t:
                out.append(t)
    return out


def launch_row(msg: dict, now_ms: int) -> list | None:
    kind = msg.get("txType")
    if kind is None and msg.get("mint") and "message" not in msg:
        kind = "migrate"
    if kind == "migrate":
        return [now_ms, "migrate", msg.get("mint", ""), "", "", "", "", msg.get("pool", ""), "", "", ""]
    if kind != "create":
        return None

    def clean(s, n):
        return str(s or "").replace("\n", " ")[:n]

    return [now_ms, "create", msg.get("mint", ""), msg.get("traderPublicKey", ""), msg.get("solAmount", ""),
            msg.get("initialBuy", ""), msg.get("marketCapSol", ""), msg.get("pool", ""),
            int(bool(msg.get("is_mayhem_mode"))), clean(msg.get("symbol"), 20), clean(msg.get("name"), 40)]


class Sink:
    def __init__(self, path: str, fields: list[str]):
        self.f = gzip.open(path, "wt", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(fields)
        self.n = 0

    def write(self, row):
        self.w.writerow(row)
        self.n += 1

    def close(self):
        self.f.close()


async def listen_launches(sink: Sink, end: float):
    import websockets
    backoff = 2
    while time.time() < end:
        try:
            async with websockets.connect(PP_URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                backoff = 2
                while time.time() < end:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(60, max(1, end - time.time())))
                    except asyncio.TimeoutError:
                        if time.time() < end:
                            print("launch feed quiet 60 s, reconnecting", flush=True)
                        break
                    try:
                        row = launch_row(json.loads(raw), int(time.time() * 1000))
                    except ValueError:
                        continue
                    if row:
                        sink.write(row)
        except Exception as e:
            print("launch feed error:", repr(e)[:200], "- retry in", backoff, "s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def listen_trades(sink: Sink, end: float, url: str, stats: dict):
    import websockets
    while time.time() < end:
        t_try = time.time()
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**23) as ws:
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                          "params": [{"mentions": [PUMP]}, {"commitment": "confirmed"}]}))
                await ws.recv()
                stats["down_s"] += time.time() - t_try
                while time.time() < end:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(30, max(1, end - time.time())))
                    except asyncio.TimeoutError:
                        break
                    now_ms = int(time.time() * 1000)
                    m = json.loads(raw)
                    res = m.get("params", {}).get("result", {})
                    v = res.get("value", {})
                    if not v or v.get("err"):
                        continue
                    slot = res.get("context", {}).get("slot", "")
                    sig = str(v.get("signature", ""))[:16]
                    for t in trades_from_logs(v.get("logs", [])):
                        sink.write([now_ms, slot, sig, t["ts"], t["mint"], t["user"], t["buy"], f"{t['sol']:.9g}",
                                    f"{t['tokens']:.9g}", f"{t['vsol']:.9g}", f"{t['vtok']:.9g}"])
        except Exception as e:
            stats["drops"] += 1
            if stats["drops"] <= 5 or stats["drops"] % 200 == 0:
                print(f"rpc drop {stats['drops']}: {e!r}"[:200], flush=True)
            t_d = time.time()
            await asyncio.sleep(1)
            stats["down_s"] += time.time() - t_d


async def run(minutes: float, copy: str, out_dir: str = "data", rpc_url: str = RPC_URL):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    launches = Sink(os.path.join(out_dir, f"{stamp}-{copy}-launches.csv.gz"), LAUNCH_FIELDS)
    trades = Sink(os.path.join(out_dir, f"{stamp}-{copy}-trades.csv.gz"), TRADE_FIELDS)
    stats = {"drops": 0, "down_s": 0.0}
    t0 = time.time()
    end = t0 + minutes * 60

    async def progress():
        while True:
            await asyncio.sleep(900)
            el = time.time() - t0
            print(f"{el / 60:.0f} min: {launches.n} launch rows, {trades.n} trades, {stats['drops']} rpc drops, "
                  f"down {stats['down_s'] / el:.0%}", flush=True)
            launches.f.flush()
            trades.f.flush()

    prog = asyncio.create_task(progress())
    try:
        await asyncio.gather(listen_launches(launches, end), listen_trades(trades, end, rpc_url, stats))
    finally:
        prog.cancel()
        launches.close()
        trades.close()
        el = max(time.time() - t0, 1)
        print(f"done: {launches.n} launch rows, {trades.n} trades ({trades.n / el * 60:.0f}/min), "
              f"{stats['drops']} rpc drops, down {stats['down_s'] / el:.0%}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=340)
    p.add_argument("--copy", default="a")
    p.add_argument("--out", default="data")
    p.add_argument("--rpc", default=RPC_URL)
    a = p.parse_args()
    asyncio.run(run(a.minutes, a.copy, a.out, a.rpc))


if __name__ == "__main__":
    main()

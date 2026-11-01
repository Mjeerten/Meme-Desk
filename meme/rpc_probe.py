"""Probe: can the free public Solana RPC stream pump.fun trades? (logsSubscribe on the pump.fun program)

Decodes pump.fun TradeEvent from 'Program data:' log lines: 8-byte discriminator, mint(32), sol_amount u64,
token_amount u64, is_buy u8, user(32), timestamp i64, virtual_sol u64, virtual_token u64.
python -m meme.rpc_probe --seconds 180 [--url wss://...]
"""
import argparse
import asyncio
import base64
import json
import struct
import time

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TRADE_DISC = bytes.fromhex("bddb7fd34ee661ee")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def decode_trade(data: bytes):
    if len(data) < 8 + 32 + 8 + 8 + 1 + 32 + 8 + 8 + 8 or data[:8] != TRADE_DISC:
        return None
    o = 8
    mint = b58(data[o:o + 32]); o += 32
    sol, tok = struct.unpack_from("<QQ", data, o); o += 16
    is_buy = data[o]; o += 1
    user = b58(data[o:o + 32]); o += 32
    ts, vsol, vtok = struct.unpack_from("<qQQ", data, o)
    return {"mint": mint, "sol": sol / 1e9, "tokens": tok / 1e6, "buy": bool(is_buy), "user": user, "ts": ts,
            "vsol": vsol / 1e9, "vtok": vtok / 1e6}


async def main(url, seconds):
    import websockets
    n_msg = n_trade = n_err = 0
    discs = {}
    t0 = time.time()
    async with websockets.connect(url, ping_interval=20, max_size=2**23) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                  "params": [{"mentions": [PUMP]}, {"commitment": "confirmed"}]}))
        print("subscribe reply:", (await ws.recv())[:300], flush=True)
        while time.time() - t0 < seconds:
            m = json.loads(await asyncio.wait_for(ws.recv(), 60))
            n_msg += 1
            v = m.get("params", {}).get("result", {}).get("value", {})
            if v.get("err"):
                n_err += 1
                continue
            for line in v.get("logs", []):
                if line.startswith("Program data: "):
                    try:
                        d = base64.b64decode(line[14:])
                    except Exception:
                        continue
                    discs[d[:8].hex()] = discs.get(d[:8].hex(), 0) + 1
                    t = decode_trade(d)
                    if t:
                        n_trade += 1
                        if n_trade <= 3:
                            print("trade:", t, flush=True)
    dt = time.time() - t0
    print(f"{dt:.0f}s: {n_msg} tx notifications ({n_err} failed tx), {n_trade} trades = {n_trade / dt * 60:.0f}/min")
    print("Program data discriminators:", sorted(discs.items(), key=lambda x: -x[1])[:8])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="wss://api.mainnet-beta.solana.com")
    p.add_argument("--seconds", type=int, default=180)
    a = p.parse_args()
    asyncio.run(main(a.url, a.seconds))

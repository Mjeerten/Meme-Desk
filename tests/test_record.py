import base64
import gzip
import struct

import pandas as pd

from meme.record import TRADE_DISC, Sink, b58, decode_trade, launch_row, trades_from_logs, TRADE_FIELDS


def event(buy=True):
    mint, user = bytes(range(32)), bytes([7] * 32)
    return (TRADE_DISC + mint + struct.pack("<QQ", 250_000_000, 3_500_000_000_000) + bytes([int(buy)]) + user
            + struct.pack("<qQQ", 1_793_546_661, 31_000_000_000, 1_038_000_000_000_000) + bytes(40))


def test_b58():
    assert b58(bytes(32)) == "1" * 32
    assert b58(bytes.fromhex("0001")) == "12"


def test_decode_trade():
    t = decode_trade(event(buy=False))
    assert t["sol"] == 0.25 and t["tokens"] == 3_500_000 and t["buy"] == 0
    assert t["ts"] == 1_793_546_661 and t["vsol"] == 31 and t["vtok"] == 1_038_000_000
    assert t["mint"] == b58(bytes(range(32)))
    assert decode_trade(b"\x00" * 200) is None


def test_trades_from_logs_skips_other_lines():
    logs = ["Program log: Instruction: Buy", "Program data: " + base64.b64encode(event()).decode(),
            "Program data: " + base64.b64encode(b"\x01" * 50).decode()]
    assert len(trades_from_logs(logs)) == 1


def test_launch_rows():
    assert launch_row({"message": "Successfully subscribed to token creation events."}, 1) is None
    assert launch_row({"signature": "x", "mint": "M2", "txType": "migrate", "pool": "pump-amm"}, 5)[1] == "migrate"
    r = launch_row({"mint": "M1", "traderPublicKey": "DEV", "txType": "create", "solAmount": 0.5,
                    "initialBuy": 1e6, "marketCapSol": 28.5, "symbol": "CAT", "name": "Cat\nCoin",
                    "is_mayhem_mode": True, "pool": "pump"}, 9)
    assert r[1] == "create" and r[3] == "DEV" and r[8] == 1 and r[10] == "Cat Coin"


def test_sink_roundtrip(tmp_path):
    s = Sink(str(tmp_path / "t.csv.gz"), TRADE_FIELDS)
    s.write([1, 2, "sig", 3, "M", "U", 1, 0.1, 5, 30, 1e9])
    s.close()
    df = pd.read_csv(gzip.open(tmp_path / "t.csv.gz", "rt"))
    assert list(df.columns) == TRADE_FIELDS and df.mint[0] == "M"

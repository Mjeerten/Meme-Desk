import gzip

import pandas as pd

from meme.record import Recorder, create_row, trade_rows, ts_ms

CREATE = {"signature": "s1", "mint": "M1", "traderPublicKey": "DEV", "txType": "create", "initialBuy": 1000.0,
          "solAmount": 0.5, "marketCapSol": 28.5, "name": "Cat|Coin", "symbol": "CAT", "is_mayhem_mode": True,
          "pool": "pump"}


def test_acks_skipped_and_migration():
    assert create_row({"message": "Successfully subscribed to token creation events."}, 1) is None
    assert create_row({"signature": "x", "mint": "M2", "txType": "migrate", "pool": "pump-amm"}, 5)[1] == "migrate"


def test_timestamps():
    assert ts_ms(1_700_000_000) == 1_700_000_000_000
    assert ts_ms(1_700_000_000_123) == 1_700_000_000_123
    assert ts_ms("2026-11-01T15:00:00Z") == 1_793_545_200_000


def test_trade_rows_sorted_and_filtered():
    trades = [{"type": "sell", "timestamp": 20, "userAddress": "B", "amountSol": 0.1, "baseAmount": 5,
               "priceSol": 2e-8, "slotIndexId": "2", "program": "pump"},
              {"type": "buy", "timestamp": 10, "userAddress": "A", "amountSol": 0.2, "baseAmount": 9,
               "fillPriceSol": 1e-8, "slotIndexId": "1", "program": "pump"},
              {"type": "create", "timestamp": 5}]
    rows = trade_rows("M1", trades)
    assert [r[1] for r in rows] == ["buy", "sell"] and rows[0][6] == 1e-8 and rows[0][0] == 10_000


def test_recorder_shard_and_queue(tmp_path):
    path = tmp_path / "x.csv.gz"
    r = Recorder(str(path), shard=0, shards=1, watch_min=1)
    r.on_message(CREATE, 1_000)
    assert r.due == [(61_000, "M1")]
    r.close()
    df = pd.read_csv(gzip.open(path, "rt"), dtype={"extra": str})
    assert df.type[0] == "create" and df.extra[0] == "CAT|Cat/Coin|1" and df.sol[0] == 0.5

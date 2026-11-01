import gzip

import pandas as pd

from meme.record import Recorder, to_row

CREATE = {"signature": "s1", "mint": "M1", "traderPublicKey": "DEV", "txType": "create", "initialBuy": 1000.0,
          "solAmount": 0.5, "vTokensInBondingCurve": 1.07e9, "vSolInBondingCurve": 30.5, "marketCapSol": 28.5,
          "name": "Cat|Coin", "symbol": "CAT", "uri": "x", "pool": "pump"}
BUY = {"signature": "s2", "mint": "M1", "traderPublicKey": "A", "txType": "buy", "tokenAmount": 5e6,
       "solAmount": 0.2, "newTokenBalance": 5e6, "vTokensInBondingCurve": 1.06e9, "vSolInBondingCurve": 30.7,
       "marketCapSol": 29.0, "pool": "pump"}


def test_ack_messages_are_skipped():
    assert to_row({"message": "Successfully subscribed to keys."}, 1) is None
    assert to_row({"errors": "x"}, 1) is None


def test_rows_and_watch_window(tmp_path):
    path = tmp_path / "x.csv.gz"
    r = Recorder(str(path), watch_min=1)
    assert r.handle(CREATE, 1_000) == "M1"
    assert r.handle(BUY, 2_000) is None
    r.handle({"signature": "s3", "mint": "M1", "pool": "pump-amm"}, 3_000)  # migration without txType
    assert r.expired(30_000) == []
    assert r.expired(62_000) == ["M1"]
    r.close()
    df = pd.read_csv(gzip.open(path, "rt"), dtype={"extra": str})
    assert list(df.type) == ["create", "buy", "migrate"]
    assert df.extra[0] == "CAT|Cat/Coin|1000.0"
    assert df.sol[1] == 0.2 and df.trader[1] == "A"

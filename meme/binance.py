"""Free Binance history from data.binance.vision (public S3 bucket; works from GitHub runners, not from Claude's container).

klines(market, symbol, interval) -> DataFrame indexed by UTC open time (open, high, low, close, volume, quote_vol)
funding(symbol) -> Series of funding rates (USDT-M perps)
symbols(market) -> every symbol in the bucket; months(market, symbol, interval) -> 'YYYY-MM' files available.
market = 'spot' or 'um' (USDT-M futures). Files are cached under CACHE.
"""
from __future__ import annotations

import io
import os
import re
import zipfile

import pandas as pd
import requests

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DATA = "https://data.binance.vision"
CACHE = os.environ.get("BINANCE_CACHE", "binance_cache")
KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_vol", "trades", "tb_base",
         "tb_quote", "ignore"]
_s = requests.Session()


def _root(market):
    return "data/spot" if market == "spot" else f"data/futures/{market}"


def s3_list(prefix: str, delimiter: str | None = "/"):
    """(sub-prefixes, keys) under a prefix, all pages."""
    pre, keys, marker = [], [], ""
    while True:
        p = {"prefix": prefix, "marker": marker}
        if delimiter:
            p["delimiter"] = delimiter
        x = _s.get(S3, params=p, timeout=60).text
        pre += re.findall(r"<Prefix>([^<]+)</Prefix>", x.split("</Name>", 1)[-1])[1:] if "<CommonPrefixes>" in x else []
        k = re.findall(r"<Key>([^<]+)</Key>", x)
        keys += k
        if "<IsTruncated>true</IsTruncated>" not in x:
            break
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", x)
        marker = nm.group(1) if nm else (k[-1] if k else (pre[-1] if pre else ""))
        if not marker:
            break
    return sorted(set(pre)), keys


def symbols(market="um"):
    pre, _ = s3_list(f"{_root(market)}/monthly/klines/")
    return [p.rstrip("/").split("/")[-1] for p in pre]


def months(market, sym, interval="1d"):
    _, keys = s3_list(f"{_root(market)}/monthly/klines/{sym}/{interval}/", None)
    return sorted(m.group(1) for k in keys if (m := re.search(r"-(\d{4}-\d{2})\.zip$", k)))


def _zip_csv(url, path):
    if os.path.exists(path):
        return path if os.path.getsize(path) else None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = _s.get(url, timeout=120)
    if r.status_code != 200:
        open(path, "w").close()
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with open(path, "wb") as f:
            f.write(z.read(z.namelist()[0]))
    return path


def _ms(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x)
    return pd.to_datetime(x.where(x < 1e14, x // 1000), unit="ms", utc=True)


def klines(market, sym, interval="1d", only: list[str] | None = None) -> pd.DataFrame:
    ms = only if only is not None else months(market, sym, interval)
    parts = []
    for m in ms:
        url = f"{DATA}/{_root(market)}/monthly/klines/{sym}/{interval}/{sym}-{interval}-{m}.zip"
        p = _zip_csv(url, f"{CACHE}/{market}/{sym}/{interval}-{m}.csv")
        if not p:
            continue
        d = pd.read_csv(p, header=None)
        if not str(d.iloc[0, 0]).isdigit():          # futures files have a header row
            d = d.iloc[1:]
        d = d.iloc[:, :12]
        d.columns = KCOLS
        parts.append(d)
    if not parts:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_vol"])
    d = pd.concat(parts)
    d.index = _ms(d.open_time)
    d = d[["open", "high", "low", "close", "volume", "quote_vol"]].astype(float)
    return d[~d.index.duplicated()].sort_index()


def funding(sym, only: list[str]) -> pd.Series:
    parts = []
    for m in only:
        url = f"{DATA}/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip"
        p = _zip_csv(url, f"{CACHE}/funding/{sym}/{m}.csv")
        if p:
            d = pd.read_csv(p)
            parts.append(pd.Series(d.iloc[:, -1].astype(float).to_numpy(), index=_ms(d.iloc[:, 0])))
    return pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)

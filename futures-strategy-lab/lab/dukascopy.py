"""Free 1-minute history from Dukascopy (CFD prices) as a long-history proxy
for the futures the lab trades:

    MNQ -> USATECHIDXUSD (Nasdaq 100)   MGC -> XAUUSD (gold)   CL/MCL -> LIGHTCMDUSD (WTI)

CFD prices are not futures prices (no basis, different volume), but intraday
structure is the same, which is what the strategies trade. Results on this data
are checked against the real futures data (Yahoo, last ~60 days).

File format: https://datafeed.dukascopy.com/datafeed/{NAME}/{YYYY}/{MM-1}/{DD}/BID_candles_min_1.bi5
— LZMA, 24-byte big-endian records (sec from 00:00 UTC, open, close, low, high as
int / 1000, volume float).
"""

from __future__ import annotations

import lzma
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .data import NY, resample

NAMES = {"MNQ": "USATECHIDXUSD", "MGC": "XAUUSD", "CL": "LIGHTCMDUSD", "MCL": "LIGHTCMDUSD"}
DIVISOR = 1000.0
URL = "https://datafeed.dukascopy.com/datafeed/{n}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"


def _day(name: str, day: pd.Timestamp, cache: Path) -> pd.DataFrame | None:
    f = cache / name / f"{day:%Y-%m-%d}.bi5"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        url = URL.format(n=name, y=day.year, m=day.month - 1, d=day.day)
        for attempt in range(6):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    f.write_bytes(r.read())
                break
            except Exception:  # noqa: BLE001 - retry on any network error (the feed rate-limits)
                time.sleep(2 ** attempt)
        else:
            return None
    raw = f.read_bytes()
    if not raw:
        return None
    b = lzma.decompress(raw)
    rec = np.frombuffer(b, dtype=">i4").reshape(-1, 6)
    vol = np.frombuffer(b, dtype=">f4").reshape(-1, 6)[:, 5]
    t = pd.to_datetime(day.value // 10**9 + rec[:, 0], unit="s", utc=True)
    df = pd.DataFrame({"open": rec[:, 1] / DIVISOR, "high": rec[:, 4] / DIVISOR, "low": rec[:, 3] / DIVISOR,
                       "close": rec[:, 2] / DIVISOR, "volume": vol.astype(float)}, index=t)
    # Dukascopy writes flat zero-volume minutes when the market is closed
    return df[df["volume"] > 0]


def load(symbol: str, start: str, end: str, cache: str | Path, tf: str = "15min", workers: int = 3) -> pd.DataFrame:
    """1-minute Dukascopy bars for [start, end) resampled to `tf`, New York time."""
    name = NAMES[symbol.upper()]
    cache = Path(cache)
    days = pd.date_range(start, end, freq="D", inclusive="left", tz="UTC")
    with ThreadPoolExecutor(workers) as ex:
        parts = [p for p in ex.map(lambda d: _day(name, d, cache), days) if p is not None and len(p)]
    df = pd.concat(parts).sort_index()
    df.index = df.index.tz_convert(NY)
    df.index.name = "time"
    return df if tf in ("1min", "1m") else resample(df, tf)

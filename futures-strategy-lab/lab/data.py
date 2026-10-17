"""Market data: instrument specs, CSV / yfinance loaders and a synthetic generator.

Every loader returns a DataFrame indexed by tz-aware America/New_York timestamps
with float columns open, high, low, close, volume, sorted and de-duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

NY = "America/New_York"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick: float          # minimum price increment
    point_value: float   # $ per 1.0 price point per contract
    contracts: int       # contracts traded per signal (the user's fixed size)
    commission: float    # $ per contract per side (broker + exchange, approx.)

    @property
    def tick_value(self) -> float:
        return self.tick * self.point_value

    def round_price(self, price: float) -> float:
        return round(round(price / self.tick) * self.tick, 10)


# The user's plan: always 2 MNQ or 1 MGC.
INSTRUMENTS: dict[str, Instrument] = {
    "MNQ": Instrument("MNQ", tick=0.25, point_value=2.0, contracts=2, commission=0.62),
    "MGC": Instrument("MGC", tick=0.10, point_value=10.0, contracts=1, commission=0.82),
    # crude oil (NYMEX): full and micro contract
    "MCL": Instrument("MCL", tick=0.01, point_value=100.0, contracts=1, commission=0.75),
    "CL": Instrument("CL", tick=0.01, point_value=1000.0, contracts=1, commission=2.25),
}


def get_instrument(symbol: str) -> Instrument:
    key = symbol.upper().replace("1!", "").replace("=F", "")
    for root, inst in INSTRUMENTS.items():
        if key.startswith(root):
            return inst
    raise ValueError(f"Unknown instrument {symbol!r}; supported: {', '.join(INSTRUMENTS)}")


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #

_ALIASES = {
    "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vol": "volume",
    "last": "close", "price": "close",
}


def _normalize(df: pd.DataFrame, tz: str | None) -> pd.DataFrame:
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("data index must be datetimes")
    if idx.tz is None:
        idx = idx.tz_localize(tz or NY, ambiguous="infer", nonexistent="shift_forward")
    df = df.copy()
    df.index = idx.tz_convert(NY)
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"missing column {col!r}; found {list(df.columns)}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    # Repair bars whose high/low don't contain open/close (bad exports happen).
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    df.index.name = "time"
    return df


def load_csv(path: str | Path, tz: str | None = None) -> pd.DataFrame:
    """Load OHLCV from common exports.

    Supported out of the box:
      * TradingView "Export chart data" (``time`` as unix seconds or ISO).
      * Generic ``datetime|date+time,open,high,low,close,volume`` CSVs.
      * NinjaTrader 8 exports ``yyyyMMdd HHmmss;open;high;low;close;volume``.
    ``tz`` is the timezone of naive timestamps (default New York). Unix
    timestamps are always UTC.
    """
    path = Path(path)
    if path.suffix == ".gz":
        import gzip
        with gzip.open(path, "rt", errors="ignore") as fh:
            text_head = fh.read(2000)
    else:
        text_head = path.read_text(errors="ignore")[:2000]
    first = text_head.splitlines()[0] if text_head else ""

    if ";" in first and "," not in first:
        raw = pd.read_csv(path, sep=";", header=None)
        if not str(raw.iloc[0, 0]).strip()[:1].isdigit():
            raw = raw.iloc[1:]
        raw = raw.iloc[:, :6]
        raw.columns = ["time", "open", "high", "low", "close", "volume"]
        raw.index = pd.to_datetime(raw["time"].astype(str), format="%Y%m%d %H%M%S")
        return _normalize(raw.drop(columns="time"), tz)

    raw = pd.read_csv(path)
    raw.columns = [_ALIASES.get(c.strip().lower(), c.strip().lower()) for c in raw.columns]
    cols = set(raw.columns)
    if "date" in cols and "time" in cols:
        stamp = pd.to_datetime(raw["date"].astype(str) + " " + raw["time"].astype(str))
    else:
        tcol = next((c for c in ("time", "datetime", "timestamp", "date", "date_time") if c in cols), None)
        if tcol is None:
            raise ValueError(f"no time column in {path}; columns: {list(raw.columns)}")
        series = raw[tcol]
        if pd.api.types.is_numeric_dtype(series):
            unit = "ms" if series.iloc[0] > 1e11 else "s"
            stamp = pd.to_datetime(series, unit=unit, utc=True)
        else:
            stamp = pd.to_datetime(series, utc=False, format="mixed")
    raw.index = pd.DatetimeIndex(stamp)
    return _normalize(raw, tz)


def load_yfinance(ticker: str, interval: str = "5m", period: str = "60d") -> pd.DataFrame:
    """Download from Yahoo Finance (free). Intraday history is short:
    1m ≈ 7 days, 5m/15m ≈ 60 days, 1h ≈ 730 days."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit("yfinance is not installed: pip install yfinance") from exc
    raw = yf.download(ticker, interval=interval, period=period, auto_adjust=False,
                      progress=False, prepost=True)
    if raw is None or raw.empty:
        raise SystemExit(f"yfinance returned no data for {ticker} {interval} {period}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [c.lower() for c in raw.columns]
    return _normalize(raw, "UTC")


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna(subset=["open"])


# --------------------------------------------------------------------------- #
# Synthetic data (for demos and tests only — not evidence of anything)
# --------------------------------------------------------------------------- #

def _intraday_vol_profile(minutes_of_day: np.ndarray) -> np.ndarray:
    """Relative volatility by New York clock time (U-shaped RTH, London bump)."""
    m = minutes_of_day
    prof = np.full(m.shape, 0.45)
    prof[(m >= 3 * 60) & (m < 6 * 60)] = 0.8           # London
    prof[(m >= 8 * 60 + 30) & (m < 9 * 60 + 30)] = 0.9  # data releases
    prof[(m >= 9 * 60 + 30) & (m < 11 * 60 + 30)] = 1.6  # NY AM
    prof[(m >= 11 * 60 + 30) & (m < 14 * 60)] = 0.8
    prof[(m >= 14 * 60) & (m < 16 * 60)] = 1.1
    return prof


def synthetic(symbol: str, days: int = 120, interval_min: int = 5, seed: int = 7,
              start: str = "2025-09-01", stop_runs: bool = True) -> pd.DataFrame:
    """Random-walk futures-like bars on the CME Globex clock (18:00–17:00 ET,
    Sun–Fri) with intraday volatility seasonality, volatility clustering and
    occasional stop-runs (spike through a recent extreme then snap back) so
    that sweep logic has something to find. Purely for demos and tests."""
    inst = get_instrument(symbol)
    rng = np.random.default_rng(seed)
    base = {"MNQ": 21000.0, "MGC": 3400.0}.get(inst.symbol, 70.0)
    daily_vol = {"MNQ": 0.013, "MGC": 0.010}.get(inst.symbol, 0.02)

    sessions = pd.bdate_range(start=start, periods=days, tz=NY)
    stamps = []
    for d in sessions:
        open_ = (d - pd.Timedelta(days=1)).replace(hour=18, minute=0)
        stamps.append(pd.date_range(open_, d.replace(hour=16, minute=55), freq=f"{interval_min}min"))
    idx = pd.DatetimeIndex(np.concatenate([s.values for s in stamps])).tz_localize("UTC").tz_convert(NY)

    n = len(idx)
    mod = (idx.hour * 60 + idx.minute).to_numpy()
    prof = _intraday_vol_profile(mod)
    bars_per_day = 23 * 60 / interval_min
    sigma_bar = daily_vol / np.sqrt(bars_per_day) / np.sqrt(np.mean(prof ** 2))

    # GARCH-ish volatility clustering
    vol = np.empty(n)
    v = 1.0
    shocks = rng.standard_normal(n)
    for i in range(n):
        v = 0.97 * v + 0.03 * (0.6 + 0.8 * shocks[i] ** 2)
        vol[i] = np.sqrt(v)

    # Bars are built from a continuous sub-bar path so wicks are real price
    # excursions (a bar's high/low is where price actually traded).
    # (fine Gaussian sub-steps: coarse/fat-tailed steps overshoot stops and
    # targets alike and would quietly tilt 2R odds above the fair 1/3)
    sub = 40
    step_sd = (sigma_bar * prof * vol / np.sqrt(sub))[:, None]
    steps = step_sd * rng.standard_normal((n, sub))
    path = base * np.exp(np.cumsum(steps.ravel())).reshape(n, sub)
    open_ = np.r_[base, path[:-1, -1]]
    close = path[:, -1].copy()
    high = np.maximum(path.max(axis=1), open_)
    low = np.minimum(path.min(axis=1), open_)

    # Stop runs: a quick excursion through the 20-bar extreme that reverses
    # inside the same bar (the wick), as on real liquidity grabs.
    look = 20
    for i in range(look, n if stop_runs else 0):
        if rng.random() < 0.012 * prof[i]:
            poke = sigma_bar * base * rng.uniform(0.3, 1.5)
            if rng.random() < 0.5:
                high[i] = max(high[i], high[i - look:i].max() + poke)
            else:
                low[i] = min(low[i], low[i - look:i].min() - poke)

    tick = inst.tick
    df = pd.DataFrame({
        "open": np.round(open_ / tick) * tick,
        "high": np.round(high / tick) * tick,
        "low": np.round(low / tick) * tick,
        "close": np.round(close / tick) * tick,
        "volume": np.round(1000 * prof * vol * rng.uniform(0.5, 1.5, n)),
    }, index=idx)
    return _normalize(df, None)

"""Precomputed per-bar features shared by every strategy.

All "known-at" rules are respected: a level only appears on a bar once the
information that defines it is complete (no look-ahead).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RTH_OPEN = 9 * 60 + 30
RTH_CLOSE = 16 * 60


def hm(text: str) -> int:
    """'09:30' -> minutes after midnight."""
    h, m = text.split(":")
    return int(h) * 60 + int(m)


@dataclass
class Features:
    df: pd.DataFrame
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    mod: np.ndarray          # minute of day, New York
    day: np.ndarray          # Globex trading-day id (int, increasing)
    atr: np.ndarray
    ema20: np.ndarray
    pdh: np.ndarray          # prior RTH day high/low
    pdl: np.ndarray
    onh: np.ndarray          # overnight (18:00-09:29) high/low, known from 09:30
    onl: np.ndarray
    asia_h: np.ndarray       # 20:00-23:59 ET, known from 00:00
    asia_l: np.ndarray
    london_h: np.ndarray     # 02:00-04:59 ET, known from 05:00
    london_l: np.ndarray
    or_h: np.ndarray         # 09:30-09:44 opening range, known from 09:45
    or_l: np.ndarray
    rth_open: np.ndarray     # today's 09:30 open
    rth_hi_sofar: np.ndarray  # RTH high/low up to and including this bar
    rth_lo_sofar: np.ndarray
    vwap: np.ndarray
    vwap_sd: np.ndarray
    pvah: np.ndarray         # prior RTH day value area high/low/POC
    pval: np.ndarray
    ppoc: np.ndarray
    interval_min: int

    @property
    def n(self) -> int:
        return len(self.c)


def atr(h, l, c, period=14):
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    out = np.empty_like(tr)
    out[0] = tr[0]
    a = 1.0 / period
    for i in range(1, len(tr)):
        out[i] = out[i - 1] + a * (tr[i] - out[i - 1])
    return out


def ema(x, period):
    out = np.empty_like(x)
    out[0] = x[0]
    a = 2.0 / (period + 1)
    for i in range(1, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def pivots(h, l, length):
    """Indices of confirmed swing highs / lows. A pivot at k is confirmed at
    bar k+length (strictly greater/less than neighbours on the left, >= on the
    right so equal highs still form a pool)."""
    n = len(h)
    ph, pl = [], []
    for k in range(length, n - length):
        left_h = h[k - length:k]
        right_h = h[k + 1:k + 1 + length]
        if h[k] > left_h.max() and h[k] >= right_h.max():
            ph.append(k)
        left_l = l[k - length:k]
        right_l = l[k + 1:k + 1 + length]
        if l[k] < left_l.min() and l[k] <= right_l.min():
            pl.append(k)
    return np.array(ph, dtype=int), np.array(pl, dtype=int)


def value_area(prices_lo, prices_hi, vols, step, pct=0.70):
    """Volume profile from OHLC bars: each bar's volume spread evenly across
    the price bins it touched. Returns (VAH, VAL, POC)."""
    lo = np.floor(prices_lo.min() / step) * step
    hi = np.ceil(prices_hi.max() / step) * step
    nb = int(round((hi - lo) / step)) + 1
    hist = np.zeros(nb)
    for a, b, vol in zip(prices_lo, prices_hi, vols):
        i0 = int((a - lo) // step)
        i1 = int((b - lo) // step)
        hist[i0:i1 + 1] += vol / (i1 - i0 + 1)
    poc = int(hist.argmax())
    total = hist.sum()
    lo_i = hi_i = poc
    acc = hist[poc]
    while acc < pct * total and (lo_i > 0 or hi_i < nb - 1):
        up = hist[hi_i + 1] if hi_i < nb - 1 else -1
        dn = hist[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1
            acc += up
        else:
            lo_i -= 1
            acc += dn
    return lo + hi_i * step, lo + lo_i * step, lo + poc * step


def build(df: pd.DataFrame, tick: float) -> Features:
    idx = df.index
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy(float)
    if not np.any(v > 0):
        v = np.ones_like(c)
    mod = (idx.hour * 60 + idx.minute).to_numpy()
    # Globex trading day: bars from 18:00 belong to the next calendar day.
    tday = (idx + pd.Timedelta(hours=6)).normalize()
    day_codes, day = np.unique(tday.asi8, return_inverse=True)
    n = len(c)
    interval = max(1, int(round(pd.Series(idx[1:min(n, 500)] - idx[:min(n, 500) - 1]).median().total_seconds() / 60))) if n > 1 else 5

    nan = lambda: np.full(n, np.nan)  # noqa: E731
    pdh, pdl, onh, onl = nan(), nan(), nan(), nan()
    asia_h, asia_l, lon_h, lon_l = nan(), nan(), nan(), nan()
    or_h, or_l, rth_open = nan(), nan(), nan()
    rhs, rls, vwap, vsd = nan(), nan(), nan(), nan()
    pvah, pval, ppoc = nan(), nan(), nan()

    rth = (mod >= RTH_OPEN) & (mod < RTH_CLOSE)
    step = tick * max(1, round(4 * (0.25 / tick))) if tick < 1 else tick
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], n]
    prev = None  # (high, low, vah, val, poc) of the previous RTH session
    for s, e in zip(starts, ends):
        m = mod[s:e]
        r = rth[s:e]
        on = ~r & ((m >= 18 * 60) | (m < RTH_OPEN))
        if prev is not None:
            pdh[s:e], pdl[s:e] = prev[0], prev[1]
            pvah[s:e], pval[s:e], ppoc[s:e] = prev[2], prev[3], prev[4]
        after_open = m >= RTH_OPEN
        if on.any():
            onh[s:e][after_open] = h[s:e][on].max()
            onl[s:e][after_open] = l[s:e][on].min()
        asia = (m >= 20 * 60)
        if asia.any():
            known = (m < 18 * 60)
            asia_h[s:e][known] = h[s:e][asia].max()
            asia_l[s:e][known] = l[s:e][asia].min()
        lon = (m >= 2 * 60) & (m < 5 * 60)
        if lon.any():
            known = (m >= 5 * 60) & (m < 18 * 60)
            lon_h[s:e][known] = h[s:e][lon].max()
            lon_l[s:e][known] = l[s:e][lon].min()
        orm = (m >= RTH_OPEN) & (m < RTH_OPEN + 15)
        if orm.any():
            known = (m >= RTH_OPEN + 15) & (m < 18 * 60)
            or_h[s:e][known] = h[s:e][orm].max()
            or_l[s:e][known] = l[s:e][orm].min()
        if r.any():
            ri = np.flatnonzero(r) + s
            rth_open[s:e][after_open & (m < 18 * 60)] = o[ri[0]]
            rhs[ri] = np.maximum.accumulate(h[ri])
            rls[ri] = np.minimum.accumulate(l[ri])
            tp = (h[ri] + l[ri] + c[ri]) / 3.0
            cv = np.cumsum(v[ri])
            cpv = np.cumsum(tp * v[ri])
            cp2v = np.cumsum(tp * tp * v[ri])
            vw = cpv / cv
            vwap[ri] = vw
            vsd[ri] = np.sqrt(np.maximum(cp2v / cv - vw * vw, 0.0))
            vah, val, poc = value_area(l[ri], h[ri], v[ri], step)
            prev = (h[ri].max(), l[ri].min(), vah, val, poc)

    return Features(df=df, o=o, h=h, l=l, c=c, v=v, mod=mod, day=day,
                    atr=atr(h, l, c), ema20=ema(c, 20), pdh=pdh, pdl=pdl, onh=onh, onl=onl,
                    asia_h=asia_h, asia_l=asia_l, london_h=lon_h, london_l=lon_l,
                    or_h=or_h, or_l=or_l, rth_open=rth_open, rth_hi_sofar=rhs, rth_lo_sofar=rls,
                    vwap=vwap, vwap_sd=vsd, pvah=pvah, pval=pval, ppoc=ppoc, interval_min=interval)

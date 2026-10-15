"""ICT research engine for 1-15 minute scalping on MNQ / MGC.

Builds every combination of

    family   × session window × context filter × entry mode × timeframe × symbol

backtests each with the user's plan (fixed R:R, 2 MNQ / 1 MGC, max trades per
day), and guards against false discoveries, because testing hundreds of
variants guarantees some will look great by luck:

  * In-sample / out-of-sample: the first 60 % of sessions pick, the last 40 %
    (never used for picking) must confirm.
  * Benjamini-Hochberg false-discovery control on the expectancy p-values.
  * A RANDOM-entry family runs through the identical pipeline. The share of
    random variants that "survive" is the false-positive yardstick.
  * Forward test: survivors are frozen into a watchlist with the date they
    were picked; later runs score them ONLY on bars that arrived afterwards.

Families (all mechanized; ICT vocabulary, our exact rules):
  fvg            every fair value gap, retrace entry
  first_fvg      first FVG of each clock hour (Silver Bullet style)
  ifvg           inverse FVG: a gap closed through, retested from the other side
  ob             order block: last opposite candle before a break of structure
  breaker        breaker block: an order block that failed, retested
  sweep_mss_fvg  liquidity sweep -> market structure shift -> FVG entry (2022 model)
  ote            sweep -> MSS -> optimal trade entry at the 62-79 % retracement
  judas          session-liquidity sweep (Asia/London/PD/overnight) -> MSS -> FVG
  cisd           change in state of delivery: close through the open of the
                 candle series that ran into a new 20-bar extreme
  bos_fvg        continuation: break of structure, then FVG in the BOS leg
  random         control: random direction, 1 ATR stop
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, engine, features
from .data import Instrument, get_instrument
from .engine import EngineConfig, Setup
from .features import Features, hm, pivots

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "store"
OUT = ROOT / "results" / "research"

FAMILIES = {
    "fvg": "Fair value gap retrace",
    "first_fvg": "First FVG of the hour (Silver Bullet style)",
    "ifvg": "Inverse FVG retest",
    "ob": "Order block retest after BOS",
    "breaker": "Breaker block retest",
    "sweep_mss_fvg": "Sweep → MSS → FVG (2022 model)",
    "ote": "Sweep → MSS → OTE 62-79 %",
    "judas": "Session sweep (Judas) → MSS → FVG",
    "cisd": "Change in state of delivery",
    "bos_fvg": "BOS continuation → FVG",
    "random": "Random entries (control)",
}
MARKET_FAMILIES = {"cisd"}

WINDOWS = {
    "asia": [("20:00", "24:00")],
    "london_kz": [("02:00", "05:00")],
    "ny_am_kz": [("08:30", "11:00")],
    "silver_bullet": [("10:00", "11:00")],
    "ny_pm": [("13:30", "15:30")],
    "all": [("20:00", "24:00"), ("00:00", "15:30")],
}
CONTEXTS = {
    "any": "No filter",
    "pd": "Premium/discount: longs below, shorts above the prior day's 50 %",
    "trend": "With the 1-hour trend (20-EMA slope)",
}
ENTRIES = {"ce": "Zone 50 % (CE / mean threshold)", "edge": "Zone near edge (first touch)"}
TIMEFRAMES = ["1m", "2m", "3m", "5m", "15m"]
YF = {"MNQ": "MNQ=F", "MGC": "MGC=F"}

P = dict(pivot_len=3, min_fvg_atr=0.15, buffer_ticks=2, expiry=20, mss_bars=20, fvg_after_mss=3,
         ob_lookback=10, zone_life=60, random_rate=0.02)


# --------------------------------------------------------------------------- #
# Data store: accumulate bars day after day (Yahoo keeps 1m ~30d, 2-15m ~60d)
# --------------------------------------------------------------------------- #

def _store_dir(sym, tf):
    return STORE / f"{sym}_{tf}"


def _store_read(sym, tf):
    """All monthly files of one symbol/timeframe, or None."""
    files = sorted(_store_dir(sym, tf).glob("*.csv.gz"))
    if not files:
        return None
    df = pd.concat([data.load_csv(f) for f in files])
    return df[~df.index.duplicated(keep="last")].sort_index()


def _store_write(sym, tf, df):
    """One gzip file per month, so a daily update only rewrites the current
    month (keeps git history small)."""
    d = _store_dir(sym, tf)
    d.mkdir(parents=True, exist_ok=True)
    for month, part in df.groupby(df.index.strftime("%Y-%m")):
        path = d / f"{month}.csv.gz"
        if path.exists() and len(data.load_csv(path)) == len(part):
            continue
        part.to_csv(path, compression={"method": "gzip", "mtime": 0}, date_format="%Y-%m-%dT%H:%M:%S%z")


def _download(sym, tf):
    import yfinance as yf

    ticker = YF[sym]
    if tf == "1m":
        end = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
        parts = []
        for k in range(4):  # 4 × 7 days; Yahoo serves ~30 days of 1m bars
            s, e = end - pd.Timedelta(days=7 * (k + 1)), end - pd.Timedelta(days=7 * k)
            d = yf.download(ticker, interval="1m", start=s, end=e, progress=False, prepost=True, auto_adjust=False)
            if d is not None and len(d):
                parts.append(d)
        raw = pd.concat(parts) if parts else None
    else:
        raw = yf.download(ticker, interval=tf, period="60d", progress=False, prepost=True, auto_adjust=False)
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [c.lower() for c in raw.columns]
    return data._normalize(raw, "UTC")


def update_store(symbols, timeframes, log=print) -> dict:
    """Download the latest bars and merge them into data/store. Returns
    {(sym, tf): DataFrame}. 3m is resampled from 1m."""
    STORE.mkdir(parents=True, exist_ok=True)
    out = {}
    for sym in symbols:
        for tf in timeframes:
            if tf == "3m":
                continue
            old = _store_read(sym, tf)
            try:
                new = _download(sym, tf)
            except Exception as exc:  # network hiccup: keep what we have
                log(f"  download {sym} {tf} failed: {exc}")
                new = None
            parts = [x for x in (old, new) if x is not None and len(x)]
            if not parts:
                continue
            df = pd.concat(parts)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            _store_write(sym, tf, df)
            out[(sym, tf)] = df
            log(f"  store {sym} {tf}: {len(df):,} bars {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}"
                f" (+{0 if old is None else len(df) - len(old):,} new)")
        if "3m" in timeframes and (sym, "1m") in out:
            out[(sym, "3m")] = data.resample(out[(sym, "1m")], "3min")
    return out


def load_store(symbols, timeframes) -> dict:
    out = {}
    for sym in symbols:
        for tf in timeframes:
            df = _store_read(sym, "1m" if tf == "3m" else tf)
            if df is not None:
                out[(sym, tf)] = data.resample(df, "3min") if tf == "3m" else df
    return out


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #

@dataclass
class Blocks:
    lsh: np.ndarray        # last confirmed swing high (value) as of bar i
    lsl: np.ndarray
    bull_fvg: dict          # bar -> (bot, top)
    bear_fvg: dict
    pd_mid: np.ndarray     # prior RTH day 50 %
    trend: np.ndarray      # +1 / -1 / 0 (1-hour 20 EMA slope)


def blocks(feat: Features, p=P) -> Blocks:
    h, l, a = feat.h, feat.l, feat.atr
    n = feat.n
    L = p["pivot_len"]
    ph, pl = pivots(h, l, L)
    lsh, lsl = np.full(n, np.nan), np.full(n, np.nan)
    ph_set, pl_set = set(ph.tolist()), set(pl.tolist())
    ch = cl = np.nan
    for i in range(n):
        if i - L in ph_set:
            ch = h[i - L]
        if i - L in pl_set:
            cl = l[i - L]
        lsh[i], lsl[i] = ch, cl
    bull, bear = {}, {}
    for i in range(2, n):
        if l[i] > h[i - 2] and l[i] - h[i - 2] >= p["min_fvg_atr"] * a[i]:
            bull[i] = (h[i - 2], l[i])
        elif h[i] < l[i - 2] and l[i - 2] - h[i] >= p["min_fvg_atr"] * a[i]:
            bear[i] = (h[i], l[i - 2])
    bph = max(1, 60 // max(1, feat.interval_min))
    e = features.ema(feat.c, 20 * bph)
    slope = np.zeros(n)
    slope[bph:] = e[bph:] - e[:-bph]
    return Blocks(lsh, lsl, bull, bear, (feat.pdh + feat.pdl) / 2.0, np.sign(slope))


def _zone_setup(i, side, bot, top, stop, mode, inst, p, note, invalidate=None):
    if mode == "ce":
        entry = inst.round_price((bot + top) / 2)
    else:  # near edge: the side price reaches first on the retrace
        entry = top if side > 0 else bot
    if invalidate is None:
        invalidate = bot if side > 0 else top
    return Setup(i, side, "limit", entry, stop, rr=p["rr"], expiry=p["expiry"], invalidate=invalidate, note=note)


def _pools(feat, b: Blocks, session_only: bool):
    """Per-bar candidate liquidity levels above (highs) and below (lows)."""
    lv_h = [feat.pdh, feat.onh, feat.asia_h, feat.london_h]
    lv_l = [feat.pdl, feat.onl, feat.asia_l, feat.london_l]
    if not session_only:
        lv_h.append(b.lsh)
        lv_l.append(b.lsl)
    return lv_h, lv_l


def fam_fvg(feat, b, inst, mode, p, first_only=False):
    h, l = feat.h, feat.l
    buf = p["buffer_ticks"] * inst.tick
    out, seen = [], set()
    hour = (feat.mod // 60)
    for i in sorted(set(b.bull_fvg) | set(b.bear_fvg)):
        key = (feat.day[i], hour[i])
        if first_only:
            if key in seen:
                continue
            seen.add(key)
        if i in b.bull_fvg:
            bot, top = b.bull_fvg[i]
            out.append(_zone_setup(i, 1, bot, top, min(l[i - 2:i + 1]) - buf, mode, inst, p, "FVG"))
        else:
            bot, top = b.bear_fvg[i]
            out.append(_zone_setup(i, -1, bot, top, max(h[i - 2:i + 1]) + buf, mode, inst, p, "FVG"))
    return out


def fam_ifvg(feat, b, inst, mode, p):
    h, l, c = feat.h, feat.l, feat.c
    buf = p["buffer_ticks"] * inst.tick
    active = []  # [side, bot, top, born]
    out = []
    for i in range(feat.n):
        keep = []
        for side, bot, top, born in active:
            if i - born > p["zone_life"]:
                continue
            if side < 0 and c[i] > top:      # bearish gap closed through -> bullish inversion
                out.append(_zone_setup(i, 1, bot, top, min(l[max(0, i - 5):i + 1]) - buf, mode, inst, p, "IFVG"))
            elif side > 0 and c[i] < bot:
                out.append(_zone_setup(i, -1, bot, top, max(h[max(0, i - 5):i + 1]) + buf, mode, inst, p, "IFVG"))
            else:
                keep.append([side, bot, top, born])
        active = keep
        if i in b.bull_fvg:
            active.append([1, *b.bull_fvg[i], i])
        if i in b.bear_fvg:
            active.append([-1, *b.bear_fvg[i], i])
    return out


def _bos_events(feat, b):
    """Bars where the close first breaks the last confirmed swing high/low."""
    c = feat.c
    ev = []
    last_up = last_dn = None
    for i in range(1, feat.n):
        sh, sl = b.lsh[i], b.lsl[i]
        if not math.isnan(sh) and c[i] > sh and sh != last_up:
            ev.append((i, 1))
            last_up = sh
        if not math.isnan(sl) and c[i] < sl and sl != last_dn:
            ev.append((i, -1))
            last_dn = sl
    return ev


def _order_blocks(feat, b, p):
    """(bar, side, ob_lo, ob_hi): last opposite-close candle before a BOS."""
    o, c, h, l = feat.o, feat.c, feat.h, feat.l
    obs = []
    for i, side in _bos_events(feat, b):
        for j in range(i - 1, max(0, i - p["ob_lookback"]) - 1, -1):
            if (side > 0 and c[j] < o[j]) or (side < 0 and c[j] > o[j]):
                obs.append((i, side, l[j], h[j]))
                break
    return obs


def fam_ob(feat, b, inst, mode, p):
    buf = p["buffer_ticks"] * inst.tick
    c = feat.c
    out = []
    for i, side, lo, hi in _order_blocks(feat, b, p):
        if (side > 0 and c[i] <= hi) or (side < 0 and c[i] >= lo):
            continue  # price still inside the block: no retest possible yet
        stop = lo - buf if side > 0 else hi + buf
        out.append(_zone_setup(i, side, lo, hi, stop, mode, inst, p, "OB"))
    return out


def fam_breaker(feat, b, inst, mode, p):
    buf = p["buffer_ticks"] * inst.tick
    c = feat.c
    obs = sorted(_order_blocks(feat, b, p))
    out, active, k = [], [], 0
    for i in range(feat.n):
        while k < len(obs) and obs[k][0] == i:
            active.append(obs[k])
            k += 1
        keep = []
        for born, side, lo, hi in active:
            if i == born:
                keep.append((born, side, lo, hi))
                continue
            if i - born > 3 * p["zone_life"]:
                continue
            if side > 0 and c[i] < lo:      # bullish OB failed -> bearish breaker
                out.append(_zone_setup(i, -1, lo, hi, hi + buf, mode, inst, p, "breaker", invalidate=hi))
            elif side < 0 and c[i] > hi:
                out.append(_zone_setup(i, 1, lo, hi, lo - buf, mode, inst, p, "breaker", invalidate=lo))
            else:
                keep.append((born, side, lo, hi))
        active = keep
    return out


def _sweep_mss(feat, b, p, session_only):
    """Yield (mss_bar, side, sweep_bar, extreme): a liquidity pool is run, then
    within `mss_bars` the close breaks the opposite swing (market structure
    shift). side = direction of the trade (-1 after a high is swept)."""
    h, l, c = feat.h, feat.l, feat.c
    lv_h, lv_l = _pools(feat, b, session_only)
    taken = set()
    st = {1: None, -1: None}
    for i in range(1, feat.n):
        for side in (1, -1):
            s = st[side]
            if s is None:
                continue
            if i - s["bar"] > p["mss_bars"]:
                st[side] = None
                continue
            if side < 0:
                s["x"] = max(s["x"], h[i])
                if c[i] < s["mss"]:
                    yield i, -1, s["bar"], s["x"]
                    st[side] = None
            else:
                s["x"] = min(s["x"], l[i])
                if c[i] > s["mss"]:
                    yield i, 1, s["bar"], s["x"]
                    st[side] = None
        for arr in lv_h:
            lvl = arr[i - 1]
            if not math.isnan(lvl) and h[i] > lvl and h[i - 1] <= lvl and (feat.day[i], round(lvl, 4)) not in taken:
                taken.add((feat.day[i], round(lvl, 4)))
                if not math.isnan(b.lsl[i]) and st[-1] is None:
                    st[-1] = {"bar": i, "x": h[i], "mss": b.lsl[i]}
        for arr in lv_l:
            lvl = arr[i - 1]
            if not math.isnan(lvl) and l[i] < lvl and l[i - 1] >= lvl and (feat.day[i], round(lvl, 4)) not in taken:
                taken.add((feat.day[i], round(lvl, 4)))
                if not math.isnan(b.lsh[i]) and st[1] is None:
                    st[1] = {"bar": i, "x": l[i], "mss": b.lsh[i]}


def fam_sweep_mss_fvg(feat, b, inst, mode, p, session_only=False):
    buf = p["buffer_ticks"] * inst.tick
    out = []
    for j, side, s, x in _sweep_mss(feat, b, p, session_only):
        gaps = b.bull_fvg if side > 0 else b.bear_fvg
        for k in range(j + p["fvg_after_mss"], s + 1, -1):  # most recent gap in the leg (or just after MSS)
            if k in gaps and k < feat.n:
                bot, top = gaps[k]
                stop = x - buf if side > 0 else x + buf
                out.append(_zone_setup(max(k, j), side, bot, top, stop, mode, inst, p,
                                       "judas" if session_only else "sweep-MSS-FVG"))
                break
    return out


def fam_ote(feat, b, inst, mode, p):
    h, l, c = feat.h, feat.l, feat.c
    buf = p["buffer_ticks"] * inst.tick
    fib = 0.705 if mode == "ce" else 0.62
    out = []
    for j, side, s, x in _sweep_mss(feat, b, p, False):
        if side < 0:
            lo = l[s:j + 1].min()
            entry = lo + fib * (x - lo)
            if c[j] < entry:
                out.append(Setup(j, -1, "limit", inst.round_price(entry), x + buf, rr=p["rr"],
                                 expiry=p["expiry"], note="OTE"))
        else:
            hi = h[s:j + 1].max()
            entry = hi - fib * (hi - x)
            if c[j] > entry:
                out.append(Setup(j, 1, "limit", inst.round_price(entry), x - buf, rr=p["rr"],
                                 expiry=p["expiry"], note="OTE"))
    return out


def fam_cisd(feat, b, inst, mode, p):
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    buf = p["buffer_ticks"] * inst.tick
    out = []
    for i in range(30, feat.n):
        # bearish CISD: up-close series ending at i-1 that printed a new 20-bar high
        k = i - 1
        while k > i - 10 and c[k] > o[k]:
            k -= 1
        if i - 1 - k >= 2:
            first = k + 1
            hi = h[first:i].max()
            if hi > h[first - 20:first].max() and c[i] < o[first]:
                out.append(Setup(i, -1, "market", 0.0, hi + buf, rr=p["rr"], expiry=1, note="CISD"))
                continue
        k = i - 1
        while k > i - 10 and c[k] < o[k]:
            k -= 1
        if i - 1 - k >= 2:
            first = k + 1
            lo = l[first:i].min()
            if lo < l[first - 20:first].min() and c[i] > o[first]:
                out.append(Setup(i, 1, "market", 0.0, lo - buf, rr=p["rr"], expiry=1, note="CISD"))
    return out


def fam_bos_fvg(feat, b, inst, mode, p):
    h, l = feat.h, feat.l
    buf = p["buffer_ticks"] * inst.tick
    out = []
    for i, side in _bos_events(feat, b):
        gaps = b.bull_fvg if side > 0 else b.bear_fvg
        for k in range(max(2, i - 3), min(feat.n, i + 4)):
            if k in gaps:
                bot, top = gaps[k]
                stop = (l[max(0, i - 10):k + 1].min() - buf) if side > 0 else (h[max(0, i - 10):k + 1].max() + buf)
                out.append(_zone_setup(max(k, i), side, bot, top, stop, mode, inst, p, "BOS-FVG"))
                break
    return out


def fam_random(feat, b, inst, mode, p):
    rng = np.random.default_rng(1 if mode == "ce" else 2)
    out = []
    for i in range(20, feat.n):
        if rng.random() < p["random_rate"]:
            side = 1 if rng.random() < 0.5 else -1
            out.append(Setup(i, side, "market", 0.0, feat.c[i] - side * feat.atr[i], rr=p["rr"], expiry=1,
                             note="random"))
    return out


FAMILY_FN = {
    "fvg": fam_fvg,
    "first_fvg": lambda f, b, i, m, p: fam_fvg(f, b, i, m, p, first_only=True),
    "ifvg": fam_ifvg,
    "ob": fam_ob,
    "breaker": fam_breaker,
    "sweep_mss_fvg": fam_sweep_mss_fvg,
    "ote": fam_ote,
    "judas": lambda f, b, i, m, p: fam_sweep_mss_fvg(f, b, i, m, p, session_only=True),
    "cisd": fam_cisd,
    "bos_fvg": fam_bos_fvg,
    "random": fam_random,
}


# --------------------------------------------------------------------------- #
# Filters, stats, run
# --------------------------------------------------------------------------- #

def _window_mask(feat, spans):
    m = np.zeros(feat.n, bool)
    for a, b_ in spans:
        m |= (feat.mod >= hm(a)) & (feat.mod < hm(b_))
    return m


def _ctx_ok(s: Setup, feat, b, ctx):
    if ctx == "any":
        return True
    if ctx == "pd":
        mid = b.pd_mid[s.bar]
        if math.isnan(mid):
            return False
        return feat.c[s.bar] < mid if s.side > 0 else feat.c[s.bar] > mid
    return b.trend[s.bar] * s.side > 0


def _pvalue(r):
    if len(r) < 3 or r.std(ddof=1) == 0:
        return 1.0
    z = r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))
    return 0.5 * math.erfc(z / math.sqrt(2))


def _stats(trades, cut_iso):
    r = np.array([t.r for t in trades])
    pnl = np.array([t.pnl for t in trades])
    is_mask = np.array([t.entry_time < cut_iso for t in trades], bool)
    def part(x):
        return (int(len(x)), float((x > 0).mean()) if len(x) else None, float(x.mean()) if len(x) else None)
    n_is, wr_is, ex_is = part(r[is_mask])
    n_oos, wr_oos, ex_oos = part(r[~is_mask])
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()) if len(eq) else 0.0
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    return {
        "trades": int(len(r)), "win_rate": float((r > 0).mean()) if len(r) else None,
        "expectancy_r": float(r.mean()) if len(r) else None,
        "profit_factor": float(min(gp / gl, 99.0)) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "net_pnl": float(pnl.sum()), "max_dd": dd, "p_value": _pvalue(r),
        "is_trades": n_is, "is_wr": wr_is, "is_exp": ex_is,
        "oos_trades": n_oos, "oos_wr": wr_oos, "oos_exp": ex_oos,
    }


def bh_qvalues(p: list[float]) -> list[float]:
    n = len(p)
    if not n:
        return []
    order = np.argsort(p)
    q = np.empty(n)
    prev = 1.0
    for rank in range(n, 0, -1):
        idx = order[rank - 1]
        prev = min(prev, p[idx] * n / rank)
        q[idx] = prev
    return q.tolist()


def strategy_id(r):
    return f"{r['family']}|{r['window']}|{r['context']}|{r['entry']}|{r['timeframe']}|{r['symbol']}"


def run(datasets: dict, cfg: EngineConfig, rr: float = 2.0, families=None, log=print,
        is_frac: float = 0.6, keep_trades: set | None = None):
    """Returns (rows, trades_by_id for ids in keep_trades)."""
    families = families or list(FAMILY_FN)
    p = {**P, "rr": rr}
    rows, kept = [], {}
    for (sym, tf), df in sorted(datasets.items()):
        inst = get_instrument(sym)
        feat = features.build(df, inst.tick)
        b = blocks(feat, p)
        days = np.unique(feat.day)
        cut_day = days[int(len(days) * is_frac)] if len(days) > 1 else days[0]
        cut_iso = feat.df.index[np.argmax(feat.day >= cut_day)].isoformat()
        wmask = {w: _window_mask(feat, spans) for w, spans in WINDOWS.items()}
        n_runs = 0
        for fam in families:
            modes = ["ce"] if fam in MARKET_FAMILIES else list(ENTRIES)
            for mode in modes:
                setups = FAMILY_FN[fam](feat, b, inst, mode, p)
                for w in WINDOWS:
                    in_w = [s for s in setups if wmask[w][s.bar]]
                    for ctx in CONTEXTS:
                        sel = [s for s in in_w if _ctx_ok(s, feat, b, ctx)]
                        trades = engine.run(feat, sel, inst, cfg) if sel else []
                        row = {"family": fam, "window": w, "context": ctx, "entry": mode, "timeframe": tf,
                               "symbol": sym, "rr": rr, "sessions": int(len(days)),
                               "data_start": feat.df.index[0].isoformat(), "data_end": feat.df.index[-1].isoformat(),
                               "cut": cut_iso, **_stats(trades, cut_iso)}
                        row["id"] = strategy_id(row)
                        rows.append(row)
                        if keep_trades and row["id"] in keep_trades:
                            kept[row["id"]] = trades
                        n_runs += 1
        log(f"  {sym} {tf:>3s}: {feat.n:,} bars, {len(days)} sessions, {n_runs} variants")
    return rows, kept


def judge(rows, min_trades=30, min_oos=10, q_max=0.10):
    """Attach q-values and survival flags. Real and random rows get BH
    separately so the random survival rate is a fair false-positive gauge."""
    for group in (lambda r: r["family"] != "random", lambda r: r["family"] == "random"):
        sub = [r for r in rows if group(r) and r["trades"] >= 20]
        for r, q in zip(sub, bh_qvalues([r["p_value"] for r in sub])):
            r["q_value"] = q
    for r in rows:
        r.setdefault("q_value", None)
        r["survivor"] = bool(
            r["trades"] >= min_trades and r["oos_trades"] >= min_oos
            and (r["is_exp"] or 0) > 0 and (r["oos_exp"] or 0) > 0
            and r["q_value"] is not None and r["q_value"] <= q_max)
        r["oos_confirmed"] = bool(r["trades"] >= min_trades and r["oos_trades"] >= min_oos
                                  and (r["is_exp"] or 0) > 0 and (r["oos_exp"] or 0) > 0)
    return rows


def summarize(rows):
    real = [r for r in rows if r["family"] != "random"]
    rnd = [r for r in rows if r["family"] == "random"]
    elig = lambda xs: [r for r in xs if r["trades"] >= 30]  # noqa: E731
    fam = {}
    for f in FAMILIES:
        xs = elig([r for r in rows if r["family"] == f])
        if not xs:
            continue
        ex = np.array([r["expectancy_r"] for r in xs])
        best = max(xs, key=lambda r: (r["oos_exp"] if r["oos_exp"] is not None else -9))
        fam[f] = {"label": FAMILIES[f], "variants": len(xs), "median_exp": float(np.median(ex)),
                  "share_positive": float((ex > 0).mean()),
                  "oos_confirmed": int(sum(r["oos_confirmed"] for r in xs)),
                  "survivors": int(sum(r["survivor"] for r in xs)),
                  "trades": int(sum(r["trades"] for r in xs)),
                  "win_rate": float(sum(r["win_rate"] * r["trades"] for r in xs) / sum(r["trades"] for r in xs)),
                  "best_id": best["id"]}
    heat = {}
    for r in elig(rows):
        k = f"{r['family']}|{r['timeframe']}"
        heat.setdefault(k, []).append(r["expectancy_r"])
    heat = {k: float(np.mean(v)) for k, v in heat.items()}
    rate = lambda xs, key: (sum(r[key] for r in elig(xs)) / len(elig(xs))) if elig(xs) else 0.0  # noqa: E731
    return {
        "variants": len(real), "eligible": len(elig(real)),
        "survivors": int(sum(r["survivor"] for r in real)),
        "oos_confirmed": int(sum(r["oos_confirmed"] for r in real)),
        "oos_confirmed_rate": rate(real, "oos_confirmed"),
        "random_variants": len(rnd), "random_eligible": len(elig(rnd)),
        "random_survivors": int(sum(r["survivor"] for r in rnd)),
        "random_oos_confirmed_rate": rate(rnd, "oos_confirmed"),
        "hit_60_wr": int(sum(1 for r in elig(real) if r["win_rate"] >= 0.60)),
        "families": fam, "heat": heat,
    }


# --------------------------------------------------------------------------- #
# Watchlist forward test
# --------------------------------------------------------------------------- #

def forward_update(rows, kept_trades, today: str, log=print):
    """Score watchlist strategies on bars that arrived AFTER they were picked,
    then add today's survivors (not already watched) to the watchlist."""
    OUT.mkdir(parents=True, exist_ok=True)
    wpath = OUT / "watchlist.json"
    watch = json.loads(wpath.read_text()) if wpath.exists() else []
    for w in watch:
        trades = [t for t in kept_trades.get(w["id"], []) if t.entry_time > w["picked_data_end"]]
        r = np.array([t.r for t in trades])
        w["forward"] = {"trades": int(len(r)), "win_rate": float((r > 0).mean()) if len(r) else None,
                        "expectancy_r": float(r.mean()) if len(r) else None,
                        "net_pnl": float(sum(t.pnl for t in trades)), "updated": today}
    watched = {w["id"] for w in watch}
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        if r["survivor"] and r["family"] != "random" and r["id"] not in watched:
            watch.append({"id": r["id"], "picked_on": today, "picked_data_end": r["data_end"],
                          "backtest": {k: r[k] for k in ("trades", "win_rate", "expectancy_r", "oos_exp", "q_value")},
                          "forward": {"trades": 0, "win_rate": None, "expectancy_r": None, "net_pnl": 0.0,
                                      "updated": today}})
            log(f"  + watchlist: {r['id']}")
    for w in watch:
        cur = by_id.get(w["id"])
        w["still_survivor"] = bool(cur and cur["survivor"])
    wpath.write_text(json.dumps(watch, indent=1))
    return watch


def append_history(summary, today):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "history.csv"
    line = (f"{today},{summary['variants']},{summary['eligible']},{summary['survivors']},"
            f"{summary['oos_confirmed']},{summary['oos_confirmed_rate']:.4f},"
            f"{summary['random_oos_confirmed_rate']:.4f},{summary['random_survivors']},{summary['hit_60_wr']}\n")
    if not path.exists():
        path.write_text("date,variants,eligible,survivors,oos_confirmed,oos_confirmed_rate,"
                        "random_oos_confirmed_rate,random_survivors,hit_60_wr\n")
    lines = [ln for ln in path.read_text().splitlines(True) if not ln.startswith(today + ",")]
    path.write_text("".join(lines) + line)
    return pd.read_csv(path).to_dict("records")


def export(rows, summary, watch, history, note, mode):
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "all_variants.csv", index=False)
    keys = ["id", "family", "window", "context", "entry", "timeframe", "symbol", "trades", "win_rate",
            "expectancy_r", "profit_factor", "net_pnl", "max_dd", "is_trades", "is_wr", "is_exp", "oos_trades",
            "oos_wr", "oos_exp", "p_value", "q_value", "survivor", "oos_confirmed"]
    rnd = lambda v: round(v, 4) if isinstance(v, float) and not math.isnan(v) else v  # noqa: E731
    slim = [{k: rnd(r[k]) for k in keys} for r in rows if r["trades"] >= 30]
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_mode": mode,
               "data_note": note, "families": FAMILIES, "windows": {k: v for k, v in WINDOWS.items()},
               "contexts": CONTEXTS, "entries": ENTRIES, "summary": summary, "rows": slim,
               "watchlist": watch, "history": history}
    (ROOT / "lab-research.js").write_text("// generated by `python lab.py research` — do not edit\n"
                                         "window.LAB_RESEARCH = " + json.dumps(payload, allow_nan=False,
                                                                                default=_nan_none) + ";\n")
    (OUT / "report.md").write_text(markdown(rows, summary, watch, note))


def _nan_none(o):
    if isinstance(o, float) and math.isnan(o):
        return None
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(type(o))


def markdown(rows, s, watch, note):
    pct = lambda x: "–" if x is None else f"{x:.0%}"  # noqa: E731
    rr = lambda x: "–" if x is None else f"{x:+.2f}R"  # noqa: E731
    out = ["# ICT research engine — scalping 1-15m", "", note, "",
           f"* Variants tested: **{s['variants']}** ({s['eligible']} with ≥30 trades)",
           f"* Out-of-sample confirmed (IS > 0 and OOS > 0): **{s['oos_confirmed']}** "
           f"= {s['oos_confirmed_rate']:.0%} of eligible — random control: {s['random_oos_confirmed_rate']:.0%}",
           f"* Survivors after false-discovery control (q ≤ 0.10): **{s['survivors']}** "
           f"(random control: {s['random_survivors']})",
           f"* Variants with ≥60 % win rate and ≥30 trades: **{s['hit_60_wr']}**", "",
           "If the real families confirm out-of-sample about as often as random entries do, "
           "the 'winners' are luck.", "",
           "## Families", "", "| Family | Variants | Median exp | % positive | Win rate | OOS-confirmed | Survivors |",
           "|---|---|---|---|---|---|---|"]
    for f, v in sorted(s["families"].items(), key=lambda kv: -kv[1]["median_exp"]):
        out.append(f"| {v['label']} | {v['variants']} | {v['median_exp']:+.3f}R | {v['share_positive']:.0%} | "
                   f"{v['win_rate']:.1%} | {v['oos_confirmed']} | {v['survivors']} |")
    top = sorted([r for r in rows if r["oos_confirmed"] and r["family"] != "random"],
                 key=lambda r: -(r["oos_exp"] or 0))[:25]
    out += ["", "## Top out-of-sample-confirmed variants", "",
            "| Variant | Trades | WR | Exp | IS exp | OOS n | OOS WR | OOS exp | q |", "|---|---|---|---|---|---|---|---|---|"]
    for r in top:
        out.append(f"| {r['id']} | {r['trades']} | {pct(r['win_rate'])} | {rr(r['expectancy_r'])} | {rr(r['is_exp'])} | "
                   f"{r['oos_trades']} | {pct(r['oos_wr'])} | {rr(r['oos_exp'])} | "
                   f"{'–' if r['q_value'] is None else format(r['q_value'], '.2f')} |")
    out += ["", "## Forward-test watchlist", ""]
    if not watch:
        out.append("Empty — no variant has survived the false-discovery control yet.")
    else:
        out += ["| Variant | Picked | Forward trades | Forward WR | Forward exp |", "|---|---|---|---|---|"]
        for w in watch:
            f = w["forward"]
            out.append(f"| {w['id']} | {w['picked_on']} | {f['trades']} | {pct(f['win_rate'])} | {rr(f['expectancy_r'])} |")
    return "\n".join(out) + "\n"

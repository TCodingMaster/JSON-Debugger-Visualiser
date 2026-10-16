"""profit / trend — higher-timeframe trend-following intraday (MNQ, MGC, MCL).

Idea: only trade in the direction of the higher-timeframe trend, enter on a
15m pullback, keep the loss small (structure stop) and let winners run
(wide fixed target, ATR chandelier or prior-bar trail), flat by 15:55 NY.

Everything is simulated on 1-minute bars (Dukascopy CFD proxies):
* signals are decided at the close of a completed 15m bar (data up to it);
* stop / limit orders work from the next minute, stop-first inside a minute
  (if a minute touches both stop and target / entry and stop, the worse
  outcome is assumed);
* trails are updated only at 15m bar closes and act from the next minute;
* 1 tick slippage (configurable) on stop entries, stop exits and EOD exits,
  limits and targets fill at their price; commission per side per contract.

Trend filters (known before the decision bar):
  d20   prior daily close (last bar before 16:00) above/below its 20-day EMA
  h50   last completed 1h bar close above EMA50(1h) and EMA50 rising over 5h
  both  d20 and h50 agree
Triggers on 15m (all require close on the trend side of the 15m EMA20):
  ema   bar touches EMA20 (low <= ema + 0.2 ATR) and closes beyond it -> stop entry at bar high
  pbb   pullback bar (lower high in an uptrend) -> stop entry at its high
  fvg   3-bar fair value gap in trend direction -> limit at gap edge
Exits: rr2 / rr3 fixed target, ch2 / ch3 chandelier (highest high since entry
- k * ATR15), pbt prior-15m-bar trail once +1R, all flat at 15:55.

Usage: PYTHONPATH=. python -m lab.prof_trend grid | check | final
"""

from __future__ import annotations

import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .features import atr as _atr, ema as _ema

P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
FILES = {"MNQ": "MNQ_1m.pkl", "MGC": "MGC_1m.pkl", "MCL": "CL_1m.pkl"}
OOS_START = pd.Timestamp("2026-04-01", tz="America/New_York")
OUT = Path(__file__).resolve().parent.parent / "results" / "profit"

# decision-time windows (time of the 15m bar close, NY)
WINDOWS = {
    "MNQ": {"am": (9 * 60 + 45, 12 * 60), "day": (9 * 60 + 45, 14 * 60), "eu": (3 * 60, 9 * 60)},
    "MGC": {"am": (8 * 60 + 30, 11 * 60 + 30), "day": (8 * 60 + 30, 13 * 60 + 30), "eu": (3 * 60, 8 * 60)},
    "MCL": {"am": (9 * 60, 11 * 60 + 30), "day": (9 * 60, 13 * 60 + 30), "eu": (3 * 60, 8 * 60 + 30)},
}
FLAT = 15 * 60 + 55


# --------------------------------------------------------------------------- #
# Market container
# --------------------------------------------------------------------------- #
@dataclass
class Market:
    sym: str
    inst: data.Instrument
    m1: pd.DataFrame
    t1: np.ndarray      # int64 ns timestamps of 1m bars
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    mod1: np.ndarray
    gday1: np.ndarray   # Globex day id per minute
    b15: pd.DataFrame
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    ema20: np.ndarray
    tclose: np.ndarray  # ns time at which each 15m bar is complete
    j_start: np.ndarray  # first 1m index at/after the bar close (= first tradable minute)
    end15: np.ndarray   # is minute j the last minute of a 15m bar -> bar index, else -1
    dtrend: np.ndarray  # per 15m bar: daily-EMA20 trend known at the bar (+1/-1/0)
    htrend: np.ndarray  # per 15m bar: 1h EMA50 trend known at the bar close


def _gday(idx):
    return ((idx + pd.Timedelta(hours=6)).normalize().tz_localize(None).asi8 // 86_400_000_000_000).astype(np.int64)


def build_market(sym: str, m1: pd.DataFrame | None = None) -> Market:
    inst = data.get_instrument(sym)
    if m1 is None:
        m1 = pd.read_pickle(P + FILES[sym])
    m1 = m1.copy()
    m1.index = m1.index.as_unit("ns")
    idx = m1.index
    t1 = idx.asi8
    mod1 = (idx.hour * 60 + idx.minute).to_numpy()
    gday1 = _gday(idx)
    b15 = data.resample(m1, "15min")
    o, h, l, c = (b15[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = _atr(h, l, c)
    e20 = _ema(c, 20)
    tclose = b15.index.asi8 + 15 * 60 * 10**9
    j_start = np.searchsorted(t1, tclose, side="left")
    end15 = np.full(len(t1), -1, dtype=np.int64)
    last_min = np.searchsorted(t1, tclose, side="left") - 1  # last minute inside bar k
    ok = last_min >= 0
    end15[last_min[ok]] = np.arange(len(b15))[ok]

    # daily trend: close of last minute before 16:00 per Globex day (only days with RTH data)
    rth = (mod1 >= 9 * 60 + 30) & (mod1 < 16 * 60)
    s = pd.Series(m1["close"].to_numpy()[rth], index=gday1[rth])
    dclose = s.groupby(level=0).last()
    # a day's close is only known after 16:00 of that day: usable from the next Globex day on
    dema = pd.Series(_ema(dclose.to_numpy(float), 20), index=dclose.index)
    dsig = np.sign(dclose - dema)
    gday15 = _gday(b15.index)
    # trend for a bar = signal of the most recent completed day strictly before its Globex day
    days = dsig.index.to_numpy()
    pos = np.searchsorted(days, gday15, side="left") - 1
    dtrend = np.where(pos >= 0, dsig.to_numpy()[np.clip(pos, 0, None)], 0).astype(int)
    dtrend[:0] = 0

    # 1h trend: last completed 1h bar at the 15m bar close
    b60 = data.resample(m1, "60min")
    c60 = b60["close"].to_numpy(float)
    e50 = _ema(c60, 50)
    slope = np.r_[np.zeros(5), e50[5:] - e50[:-5]]
    hs = np.where((c60 > e50) & (slope > 0), 1, np.where((c60 < e50) & (slope < 0), -1, 0))
    t60close = b60.index.asi8 + 60 * 60 * 10**9
    k60 = np.searchsorted(t60close, tclose, side="right") - 1
    htrend = np.where(k60 >= 0, hs[np.clip(k60, 0, None)], 0).astype(int)

    return Market(sym, inst, m1, t1, m1["open"].to_numpy(float), m1["high"].to_numpy(float),
                  m1["low"].to_numpy(float), m1["close"].to_numpy(float), mod1, gday1, b15, o, h, l, c,
                  a, e20, tclose, j_start, end15, dtrend, htrend)


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #
def signals(mk: Market, trend: str, trig: str, window: str) -> list[dict]:
    lo, hi = WINDOWS[mk.sym][window]
    o, h, l, c, a, e = mk.o, mk.h, mk.l, mk.c, mk.atr, mk.ema20
    tick = mk.inst.tick
    tc = pd.DatetimeIndex(mk.tclose, tz="UTC").tz_convert("America/New_York")
    dmod = (tc.hour * 60 + tc.minute).to_numpy()
    if trend == "d20":
        tr = mk.dtrend
    elif trend == "h50":
        tr = mk.htrend
    else:
        tr = np.where(mk.dtrend == mk.htrend, mk.dtrend, 0)
    out = []
    for k in range(25, len(c)):
        if not (lo <= dmod[k] <= hi):
            continue
        sd = tr[k]
        if sd == 0 or a[k] <= 0:
            continue
        if sd * (c[k] - e[k]) <= 0:
            continue
        s = None
        if trig == "ema":
            touch = (l[k] <= e[k] + 0.2 * a[k]) if sd > 0 else (h[k] >= e[k] - 0.2 * a[k])
            if touch:
                ent = h[k] + tick if sd > 0 else l[k] - tick
                stp = l[k] - 0.1 * a[k] if sd > 0 else h[k] + 0.1 * a[k]
                s = dict(type="stop", entry=ent, stop=stp, expiry=2, inval=None)
        elif trig == "pbb":
            pb = (h[k] < h[k - 1]) if sd > 0 else (l[k] > l[k - 1])
            if pb:
                ent = h[k] + tick if sd > 0 else l[k] - tick
                stp = (min(l[k], l[k - 1]) - 0.1 * a[k]) if sd > 0 else (max(h[k], h[k - 1]) + 0.1 * a[k])
                s = dict(type="stop", entry=ent, stop=stp, expiry=1, inval=None)
        elif trig == "fvg":
            gap = (l[k] - h[k - 2]) if sd > 0 else (l[k - 2] - h[k])
            if gap >= 0.15 * a[k]:
                ent = h[k - 2] if sd > 0 else l[k - 2]
                stp = (min(l[k - 2], l[k - 1]) - 0.1 * a[k]) if sd > 0 else (max(h[k - 2], h[k - 1]) + 0.1 * a[k])
                s = dict(type="limit", entry=ent, stop=stp, expiry=8, inval=stp)
        if s is None:
            continue
        risk = (s["entry"] - s["stop"]) * sd
        if risk < max(4 * tick, 0.2 * a[k]) or risk > 2.5 * a[k]:
            continue
        s.update(k=k, side=int(sd), atr=float(a[k]))
        out.append(s)
    return out


# --------------------------------------------------------------------------- #
# 1-minute simulator
# --------------------------------------------------------------------------- #
def simulate(mk: Market, sigs: list[dict], exit_: str, slip_ticks: int = 1, max_per_day: int = 1) -> list[dict]:
    O, H, L, C, mod1, gd = mk.O, mk.H, mk.L, mk.C, mk.mod1, mk.gday1
    tick = mk.inst.tick
    slip = slip_ticks * tick
    qty = mk.inst.contracts
    pv = mk.inst.point_value
    costs = 2 * mk.inst.commission * qty
    n1 = len(O)
    trades = []
    busy = -1
    day_n: dict[int, int] = {}
    for s in sigs:
        k, sd = s["k"], s["side"]
        j = int(mk.j_start[k])
        if j >= n1 or j <= busy:
            continue
        day = gd[j]
        if day_n.get(day, 0) >= max_per_day:
            continue
        if mod1[j] >= FLAT and mod1[j] < 18 * 60:
            continue
        jexp = int(mk.j_start[min(k + s["expiry"], len(mk.j_start) - 1)])
        ent, stp = s["entry"], s["stop"]
        # ---- work the entry order
        fill = None
        jj = j
        while jj < n1 and jj < jexp:
            if gd[jj] != day or (FLAT <= mod1[jj] < 18 * 60):
                break
            if s["type"] == "stop":
                if (O[jj] >= ent) if sd > 0 else (O[jj] <= ent):
                    fill = O[jj] + sd * slip
                elif (H[jj] >= ent) if sd > 0 else (L[jj] <= ent):
                    fill = ent + sd * slip
                elif (L[jj] <= stp) if sd > 0 else (H[jj] >= stp):
                    break  # stop level traded before the entry -> void
            else:
                if (L[jj] <= ent) if sd > 0 else (H[jj] >= ent):
                    fill = min(O[jj], ent) if sd > 0 else max(O[jj], ent)
            if fill is not None:
                break
            kb = mk.end15[jj]
            if s["inval"] is not None and kb >= 0 and ((C[jj] < s["inval"]) if sd > 0 else (C[jj] > s["inval"])):
                break
            jj += 1
        if fill is None:
            busy = jj
            continue
        risk = (fill - stp) * sd
        if risk <= 0:
            busy = jj
            continue
        j0 = jj
        day_n[day] = day_n.get(day, 0) + 1
        target = None
        if exit_.startswith("rr"):
            target = fill + sd * float(exit_[2:]) * risk
        stop = stp
        ext = fill  # most favourable completed-bar extreme since entry
        trail_on = False
        reason, px = None, None
        jj = j0
        first = True
        while True:
            if not first:
                if jj >= n1 or gd[jj] != day:
                    jj -= 1  # data gap / end of data: out at the last close of the day
                    px, reason = C[jj] - sd * slip, "eod"
                    break
                if FLAT <= mod1[jj] < 18 * 60:
                    px, reason = O[jj] - sd * slip, "eod"
                    break
                if (O[jj] <= stop) if sd > 0 else (O[jj] >= stop):
                    px, reason = O[jj] - sd * slip, "sl"
                    break
            # stop first inside the minute (on the fill minute too: conservative)
            if (L[jj] <= stop) if sd > 0 else (H[jj] >= stop):
                px, reason = stop - sd * slip, ("sl" if stop * sd <= stp * sd + 1e-12 else "trail")
                break
            if target is not None and ((H[jj] >= target) if sd > 0 else (L[jj] <= target)):
                if not first and ((O[jj] >= target) if sd > 0 else (O[jj] <= target)):
                    px = O[jj]
                else:
                    px = target
                reason = "tp"
                break
            kb = mk.end15[jj]
            if kb >= 0 and kb > k:
                # 15m bar kb completed: update trails (effective from next minute)
                if exit_.startswith("ch"):
                    m = float(exit_[2:])
                    ext = max(ext, mk.h[kb]) if sd > 0 else min(ext, mk.l[kb])
                    new = ext - sd * m * mk.atr[kb]
                    stop = max(stop, new) if sd > 0 else min(stop, new)
                elif exit_ == "pbt":
                    fav = (mk.h[kb] - fill) if sd > 0 else (fill - mk.l[kb])
                    if fav >= risk:
                        trail_on = True
                    if trail_on:
                        new = mk.l[kb] - tick if sd > 0 else mk.h[kb] + tick
                        stop = max(stop, new) if sd > 0 else min(stop, new)
            first = False
            jj += 1
        pts = (px - fill) * sd
        pnl = pts * pv * qty - costs
        trades.append(dict(sym=mk.sym, entry_time=pd.Timestamp(mk.t1[j0], tz="UTC").tz_convert("America/New_York"),
                           side=sd, entry=fill, stop=stp, exit=px, reason=reason,
                           r=pnl / (risk * pv * qty), pnl=pnl))
        busy = jj
    return trades


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def stats(tr: list[dict]) -> dict:
    if not tr:
        return dict(n=0, wr=0, exp=0, pf=0, net=0, dd=0, t=0)
    r = np.array([t["r"] for t in tr])
    p = np.array([t["pnl"] for t in tr])
    order = np.argsort([t["entry_time"].value for t in tr])
    eq = np.cumsum(p[order])
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]))
    gp, gl = p[p > 0].sum(), -p[p < 0].sum()
    sdv = r.std(ddof=1) if len(r) > 1 else 1
    return dict(n=len(r), wr=round(float((r > 0).mean()) * 100, 1), exp=round(float(r.mean()), 3),
                pf=round(float(gp / gl) if gl > 0 else 99, 2), net=round(float(p.sum())), dd=round(dd),
                t=round(float(r.mean() / sdv * np.sqrt(len(r))) if sdv > 0 else 0, 2))


def monthly(tr):
    m = {}
    for t in tr:
        key = t["entry_time"].strftime("%Y-%m")
        m[key] = m.get(key, 0) + t["r"]
    return {k: round(v, 2) for k, v in sorted(m.items())}


def split(tr):
    return [t for t in tr if t["entry_time"] < OOS_START], [t for t in tr if t["entry_time"] >= OOS_START]


def evaluate(tr):
    a, b = split(tr)
    mo = monthly(tr)
    return dict(full=stats(tr), IS=stats(a), OOS=stats(b), months=mo,
                pos=sum(v > 0 for v in mo.values()), nmonths=len(mo))


def fmt(s):
    return f"{s['n']:4d} tr WR {s['wr']:5.1f}% exp {s['exp']:+.3f}R PF {s['pf']:.2f} net ${s['net']:>7} DD ${s['dd']:>6} t {s['t']:+.2f}"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
TRENDS = ("d20", "h50", "both")
TRIGS = ("ema", "pbb", "fvg")
WINS = ("am", "day")
EXITS = ("rr2", "rr3", "ch2", "ch3", "pbt")


def grid(syms=("MNQ", "MGC", "MCL")):
    res = []
    for sym in syms:
        mk = build_market(sym)
        for trend, trig, win in itertools.product(TRENDS, TRIGS, WINS):
            sg = signals(mk, trend, trig, win)
            for ex in EXITS:
                ev = evaluate(simulate(mk, sg, ex))
                cfg = dict(sym=sym, trend=trend, trig=trig, win=win, exit=ex)
                res.append(dict(cfg=cfg, **ev))
                print(sym, trend, trig, win, ex, "| IS", fmt(ev["IS"]), "| OOS", fmt(ev["OOS"]), "|", ev["pos"], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trend_grid.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def truncation_check(sym="MNQ", cuts=(0.35, 0.6, 0.85)):
    full_m1 = pd.read_pickle(P + FILES[sym])
    full_m1.index = full_m1.index.as_unit("ns")
    mk = build_market(sym, full_m1)
    ok = True
    for cfg in itertools.product(TRENDS, TRIGS, ("day",)):
        full = signals(mk, *cfg)
        for frac in cuts:
            cut_t = mk.tclose[int(len(mk.tclose) * frac)]
            m1c = full_m1[full_m1.index.asi8 < cut_t]
            mkc = build_market(sym, m1c)
            part = signals(mkc, *cfg)
            kmax = len(mkc.c) - 2
            a = [(x["k"], x["side"], round(x["entry"], 6), round(x["stop"], 6)) for x in full if x["k"] < kmax]
            b = [(x["k"], x["side"], round(x["entry"], 6), round(x["stop"], 6)) for x in part if x["k"] < kmax]
            if a != b:
                ok = False
                print("MISMATCH", cfg, frac, len(a), len(b))
    print("truncation check", "OK" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        grid(tuple(sys.argv[2:]) or ("MNQ", "MGC", "MCL"))
    elif cmd == "check":
        truncation_check()

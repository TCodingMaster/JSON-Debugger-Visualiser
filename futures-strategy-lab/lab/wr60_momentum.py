"""wr60 / momentum: non-ICT trend & momentum families on MNQ (Dukascopy NQ proxy, 1 year).

Families (all decided on the CLOSE of bar i using data <= i; orders work from bar i+1):
  pb    - EMA pullback in an established trend: trend = close and EMA20 on the trend side of EMA50,
          EMA50 sloping over `slope_n` bars. Signal bar touches EMA20 (low <= ema20 + tol*ATR for longs)
          and closes back in trend direction (close > ema20, close > open). Entry: stop order 1 tick
          beyond the signal bar (expiry 2) or market. Stop: signal-bar extreme -/+ buf*ATR.
  odpb  - open-drive first pullback: drive = close at `drive_end` - 09:30 open; if |drive| >= k*ATR,
          wait for the first counter bar (close against the drive) and buy/sell a break of it (stop order).
          Stop beyond the pullback extreme. Once per day.
  orbr  - opening-range breakout + retest: first bar closing beyond the 09:30-09:45 OR -> resting limit
          at the OR edge (+ off*ATR into the breakout side), stop = edge -/+ sl_or*OR-width; expiry `exp`.
          Once per day.
  lonc  - London continuation: London direction = close at 05:00 vs open at 02:00 (|move| >= k*ATR).
          In NY (window) take the first EMA20-pullback signal (pb rules, no slope test) in that direction.
  ibb   - inside-bar breakout in trend (pb trend definition): bar i inside bar i-1 -> stop order beyond
          the inside bar, stop beyond the other side (or mother bar, `ib_stop`), expiry 2.

Optional bias filter `vw`: longs only above VWAP, shorts only below (RTH only).
Targets: fixed rr (0.75 - 1.5R). Engine: lab.engine, intrabar="path", flatten 15:55.

Protocol: IS = entry < 2026-04-01 (all choices), OOS = entry >= 2026-04-01 (reported untouched).

Run:  PYTHONPATH=. python -m lab.wr60_momentum [grid|best|check]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, engine, features
from .engine import EngineConfig, Setup
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "wr60"
DUKA = Path("/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/"
            "scratchpad/duka/MNQ_1m.pkl")
CUT = "2026-04-01"

DEFAULTS = dict(family="pb", win=("09:45", "15:00"), rr=1.0, buf=0.1, tol=0.0, slope_n=8, entry="stop",
                k=1.0, drive_end="10:00", off=0.0, sl_or=0.5, exp=8, ib_stop="inside", vw=0, side=0,
                max_trades=1)


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def generate(feat, inst, params=None):
    p = {**DEFAULTS, **(params or {})}
    o, h, l, c, a, mod, day = feat.o, feat.h, feat.l, feat.c, feat.atr, feat.mod, feat.day
    n = feat.n
    tick = inst.tick
    e20, e50 = ema(c, 20), ema(c, 50)
    w0, w1 = hm(p["win"][0]), hm(p["win"][1])
    inwin = (mod >= w0) & (mod < w1)
    rr, buf, fam = p["rr"], p["buf"], p["family"]
    sn = p["slope_n"]
    out: list[Setup] = []

    def bias_ok(i, side):
        if p["side"] and side != p["side"]:
            return False
        if p["vw"]:
            v = feat.vwap[i]
            if not np.isfinite(v):
                return False
            return (c[i] > v) if side > 0 else (c[i] < v)
        return True

    def trend(i):
        if i < sn + 50:
            return 0
        if c[i] > e50[i] and e20[i] > e50[i] and e50[i] > e50[i - sn]:
            return 1
        if c[i] < e50[i] and e20[i] < e50[i] and e50[i] < e50[i - sn]:
            return -1
        return 0

    def pb_signal(i, side):
        tol = p["tol"] * a[i]
        if side > 0:
            return l[i] <= e20[i] + tol and c[i] > e20[i] and c[i] > o[i]
        return h[i] >= e20[i] - tol and c[i] < e20[i] and c[i] < o[i]

    def emit(i, side, stop, entry_type, entry, expiry, note, invalidate=None):
        if not bias_ok(i, side):
            return
        out.append(Setup(bar=i, side=side, entry_type=entry_type, entry=inst.round_price(entry),
                         stop=inst.round_price(stop), rr=float(rr), expiry=expiry,
                         invalidate=invalidate, note=note))

    def pb_emit(i, side, note):
        if p["entry"] == "stop":
            ent = h[i] + tick if side > 0 else l[i] - tick
            emit(i, side, (l[i] - buf * a[i]) if side > 0 else (h[i] + buf * a[i]), "stop", ent, 2, note)
        else:
            emit(i, side, (l[i] - buf * a[i]) if side > 0 else (h[i] + buf * a[i]), "market", c[i], 1, note)

    if fam == "pb":
        for i in range(1, n):
            if not inwin[i]:
                continue
            t = trend(i)
            if t and pb_signal(i, t):
                pb_emit(i, t, "pb")

    elif fam == "ibb":
        for i in range(2, n):
            if not inwin[i]:
                continue
            t = trend(i)
            if not t or not (h[i] < h[i - 1] and l[i] > l[i - 1]):
                continue
            lo = l[i] if p["ib_stop"] == "inside" else l[i - 1]
            hi = h[i] if p["ib_stop"] == "inside" else h[i - 1]
            if t > 0:
                emit(i, 1, lo - buf * a[i], "stop", h[i] + tick, 2, "ibb")
            else:
                emit(i, -1, hi + buf * a[i], "stop", l[i] - tick, 2, "ibb")

    elif fam == "odpb":
        de = hm(p["drive_end"])
        dirn, done, ext = 0, False, None
        for i in range(1, n):
            if day[i] != day[i - 1]:
                dirn, done, ext = 0, False, None
            m = mod[i]
            if done or not np.isfinite(feat.rth_open[i]) or m < 9 * 60 + 30 or m >= w1:
                continue
            if m + feat.interval_min == de:      # bar closing exactly at drive_end
                d = c[i] - feat.rth_open[i]
                if abs(d) >= p["k"] * a[i]:
                    dirn = 1 if d > 0 else -1
                    ext = None
                else:
                    done = True
                continue
            if dirn == 0 or m + feat.interval_min <= de:
                continue
            counter = (c[i] < o[i]) if dirn > 0 else (c[i] > o[i])
            if counter:
                done = True
                if dirn > 0:
                    emit(i, 1, l[i] - buf * a[i], "stop", h[i] + tick, 3, "odpb")
                else:
                    emit(i, -1, h[i] + buf * a[i], "stop", l[i] - tick, 3, "odpb")

    elif fam == "orbr":
        done = False
        for i in range(1, n):
            if day[i] != day[i - 1]:
                done = False
            if done or not inwin[i] or not np.isfinite(feat.or_h[i]):
                continue
            orh, orl = feat.or_h[i], feat.or_l[i]
            w = orh - orl
            if w <= 0:
                continue
            if c[i] > orh:
                done = True
                ent = orh + p["off"] * a[i]
                if ent < c[i]:
                    emit(i, 1, ent - p["sl_or"] * w - buf * a[i], "limit", ent, p["exp"], "orbr")
            elif c[i] < orl:
                done = True
                ent = orl - p["off"] * a[i]
                if ent > c[i]:
                    emit(i, -1, ent + p["sl_or"] * w + buf * a[i], "limit", ent, p["exp"], "orbr")

    elif fam == "lonc":
        lo_open, ldir, done = np.nan, 0, False
        for i in range(1, n):
            if day[i] != day[i - 1]:
                lo_open, ldir, done = np.nan, 0, False
            m = mod[i]
            if m == 2 * 60:
                lo_open = o[i]
            if m + feat.interval_min == 5 * 60 and np.isfinite(lo_open):
                d = c[i] - lo_open
                ldir = (1 if d > 0 else -1) if abs(d) >= p["k"] * a[i] else 0
                continue
            if done or not ldir or not inwin[i] or i < 50:
                continue
            if pb_signal(i, ldir) and ((c[i] > e50[i]) if ldir > 0 else (c[i] < e50[i])):
                done = True
                pb_emit(i, ldir, "lonc")
    else:
        raise ValueError(fam)
    return out


# ------------------------------------------------------------- evaluation
def load(tf="15min"):
    m1 = pd.read_pickle(DUKA)
    df = data.resample(m1, tf)
    inst = data.get_instrument("MNQ")
    return features.build(df, inst.tick), inst


def stats(tr):
    if not tr:
        return dict(trades=0, wr=0.0, exp=0.0, pf=0.0, net=0.0, dd=0.0)
    pnl = np.array([t.pnl for t in tr])
    r = np.array([t.r for t in tr])
    eq = np.r_[0, np.cumsum(pnl)]
    gl = -pnl[pnl < 0].sum()
    return dict(trades=len(tr), wr=float((pnl > 0).mean()), exp=float(r.mean()),
                pf=float(pnl[pnl > 0].sum() / gl) if gl > 0 else 99.0,
                net=float(pnl.sum()), dd=float((np.maximum.accumulate(eq) - eq).max()))


def monthly(tr):
    m = {}
    for t in tr:
        m[t.entry_time[:7]] = m.get(t.entry_time[:7], 0.0) + t.r
    return {k: round(v, 2) for k, v in sorted(m.items())}


def evaluate(feat, inst, p):
    p = {**DEFAULTS, **p}
    st = generate(feat, inst, p)
    tr = engine.run(feat, st, inst, EngineConfig(flatten="15:55", max_trades_per_day=p["max_trades"],
                                                 intrabar="path"))
    a = [t for t in tr if t.entry_time < CUT]
    b = [t for t in tr if t.entry_time >= CUT]
    mo = monthly(tr)
    return dict(full=stats(tr), is_=stats(a), oos=stats(b), months=mo,
                pos_months=sum(v > 0 for v in mo.values()), n_months=len(mo)), tr


def fmt(s):
    return (f"n={s['trades']:3d} WR={s['wr']*100:4.1f}% exp={s['exp']:+.3f}R PF={s['pf']:.2f} "
            f"net=${s['net']:7.0f} dd=${s['dd']:6.0f}")


def grid_configs():
    """Pre-declared grid (~380 configs)."""
    cfgs = []
    rrs = (0.75, 1.0, 1.5)
    for tf in ("15min", "5min"):
        sl = 8 if tf == "15min" else 24
        for w in (("09:45", "15:00"), ("10:00", "12:00")):
            for ent in ("stop", "market"):
                for tol in (0.0, 0.2):
                    for vw in (0, 1):
                        for rr in rrs:
                            cfgs.append(dict(tf=tf, family="pb", win=w, entry=ent, tol=tol, vw=vw, rr=rr,
                                             slope_n=sl, max_trades=2 if w[0] == "09:45" else 1))
        for w in (("09:45", "15:00"), ("10:00", "12:00")):
            for ibs in ("inside", "mother"):
                for vw in (0, 1):
                    for rr in rrs:
                        cfgs.append(dict(tf=tf, family="ibb", win=w, ib_stop=ibs, vw=vw, rr=rr, slope_n=sl))
        for de in ("10:00", "10:15"):
            for k in (0.5, 1.0, 2.0):
                for buf in (0.1, 0.5):
                    for rr in rrs:
                        cfgs.append(dict(tf=tf, family="odpb", drive_end=de, k=k, buf=buf, rr=rr,
                                         win=("09:30", "12:00")))
        for off in (0.0, 0.25):
            for slo in (0.5, 1.0):
                for vw in (0, 1):
                    for rr in rrs:
                        cfgs.append(dict(tf=tf, family="orbr", off=off, sl_or=slo, vw=vw, rr=rr,
                                         win=("09:45", "12:00"), exp=8 if tf == "15min" else 24))
        for k in (0.5, 1.5):
            for w in (("09:30", "12:00"), ("05:00", "12:00")):
                for ent in ("stop", "market"):
                    for rr in rrs:
                        cfgs.append(dict(tf=tf, family="lonc", k=k, win=w, entry=ent, rr=rr))
    return cfgs


def is_score(e):
    s = e["is_"]
    if s["trades"] < 45 or s["pf"] < 1.1:
        return -9.0
    lb = s["wr"] - math.sqrt(s["wr"] * (1 - s["wr"]) / s["trades"])
    return lb + 0.5 * s["exp"]


def grid(log=print):
    cfgs = grid_configs()
    log(f"configs: {len(cfgs)}")
    feats, res = {}, []
    for j, cf in enumerate(cfgs):
        tf = cf["tf"]
        if tf not in feats:
            feats[tf] = load(tf)
        feat, inst = feats[tf]
        p = {k: v for k, v in cf.items() if k != "tf"}
        e, _ = evaluate(feat, inst, p)
        res.append(dict(cfg=cf, **e, score=is_score(e)))
        if j % 40 == 0:
            log(f"{j}/{len(cfgs)}")
    res.sort(key=lambda r: -r["score"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "momentum_grid.json").write_text(json.dumps(res, indent=1, default=str))
    for r in res[:25]:
        log(f"{r['score']:+.3f} {r['cfg']}\n   IS  {fmt(r['is_'])}\n   OOS {fmt(r['oos'])}  "
            f"months+ {r['pos_months']}/{r['n_months']}")
    return res


def truncation_check(tf="15min"):
    feat, inst = load(tf)
    df = feat.df
    k = len(df) * 2 // 3
    feat_k = features.build(df.iloc[:k], inst.tick)
    bad = 0
    for fam in ("pb", "ibb", "odpb", "orbr", "lonc"):
        full = [(s.bar, s.side, s.entry, s.stop) for s in generate(feat, inst, dict(family=fam)) if s.bar < k - 1]
        part = [(s.bar, s.side, s.entry, s.stop) for s in generate(feat_k, inst, dict(family=fam)) if s.bar < k - 1]
        ok = full == part
        bad += not ok
        print(f"truncation {fam}: {'OK' if ok else 'MISMATCH'} ({len(full)} setups)")
    return bad == 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        grid()
    elif cmd == "check":
        truncation_check()


if __name__ == "__main__":
    main()


# ------------------------------------------------------------- stage 2 (IS-only refinement)
def refine_configs():
    cfgs = []
    for w in (("10:00", "12:00"), ("09:45", "12:00"), ("10:00", "13:00"), ("10:00", "14:00")):
        for tol in (0.1, 0.2, 0.3):
            for buf in (0.1, 0.25):
                for sn in (4, 8, 16):
                    cfgs.append(dict(tf="15min", family="pb", win=w, entry="market", tol=tol, buf=buf,
                                     slope_n=sn, rr=0.75, max_trades=1))
    return cfgs


def refine(log=print):
    feat, inst = load("15min")
    res = []
    for cf in refine_configs():
        p = {k: v for k, v in cf.items() if k != "tf"}
        e, _ = evaluate(feat, inst, p)
        res.append(dict(cfg=cf, **e, score=is_score(e)))
    res.sort(key=lambda r: -r["score"])
    (OUT / "momentum_refine.json").write_text(json.dumps(res, indent=1, default=str))
    log(f"refine configs: {len(res)}")
    for r in res[:12]:
        log(f"{r['score']:+.3f} {r['cfg']}\n   IS  {fmt(r['is_'])}\n   OOS {fmt(r['oos'])}  "
            f"months+ {r['pos_months']}/{r['n_months']}")
    return res


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "refine":
    refine()

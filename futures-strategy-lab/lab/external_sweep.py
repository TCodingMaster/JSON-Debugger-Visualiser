"""External-liquidity sweep -> trend start (MSS + displacement) -> FVG of that leg (user's model).

The user's rules: look at all FVGs of the day and trade only the one that belongs to a NEW
trend that starts after price took EXTERNAL liquidity (PDH/PDL, session high/low, equal
highs/lows at the edge of the range). Never trade FVGs inside consolidation.

Short side (long mirrors), every step decided at a bar CLOSE, orders work from the next bar:
  1. External levels (all causal): PDH, Asia high (known 00:00), London high (known 05:00),
     overnight high (known 09:30) and equal highs: two confirmed pivot highs within
     `eq_tol` x ATR, nothing traded above them in between, and the pair is the highest
     high of the `ext_bars` bars before the first pivot (= range edge, not internal).
  2. Sweep: the first bar of the day (since the level became known) whose high trades
     above the level, inside `win`. One sweep per level per day.
  3. Trend start within `look` bars after the sweep:
       MSS          a close below the lowest low of the `mss_n` bars before the sweep bar,
       displacement a bearish bar in sweep..MSS with body >= `disp` x ATR,
       no chop      efficiency ratio of the closes from the sweep bar to the MSS bar
                    >= `er_min`, and ATR(14) / ATR(`atr_slow`) >= `atr_exp` (market moving).
  4. FVG of that leg: bearish gaps h[k] < l[k-2] with k-2 >= sweep bar, k <= MSS bar + `post`,
     size >= `mf` x ATR. `pick` = "first" (closest to the sweep) or "largest".
     Limit sell at the near edge (or CE), stop = sweep extreme + `buf` ticks, invalidate on
     a close above the sweep extreme, expiry `expiry` bars.
Max 1 trade per Globex day. Exit / stats: lab.daily_portfolio.simulate (half at 1R ->
BE -> runner 3R, time stop 8 bars, flat 15:55; 1 tick slippage, costs as data.py).

Protocol: IS = entry < 2026-04-01, OOS >= 2026-04-01; choices on IS only.
Run:  PYTHONPATH=. python -m lab.external_sweep trunc | grid | final
"""

from __future__ import annotations

import itertools
import json
import sys

import numpy as np

from . import data, features
from . import daily_levels as DL
from . import daily_portfolio as DP
from .engine import Setup
from .features import hm

DEF = dict(levels=("pd", "asia", "london", "on", "eq"), win=("02:00", "11:30"), look=8, mss_n=6, disp=0.8,
           er_min=0.0, atr_exp=0.0, atr_slow=96, mf=0.15, post=2, pick="first", entry="edge", buf=2,
           expiry=8, eq_tol=0.1, ext_bars=32, piv=3, trend=0)


def _eq_levels(feat, p):
    """Equal highs / lows -> per-bar arrays of the nearest live EQH above / EQL below (nan if none)."""
    h, l, a = feat.h, feat.l, feat.atr
    n, L = feat.n, p["piv"]
    ph, pl = features.pivots(h, l, L)
    eqh, eql = np.full(n, np.nan), np.full(n, np.nan)
    live_h, live_l = [], []          # [level, bar_known]
    ph_by_conf = {k + L: k for k in ph}
    pl_by_conf = {k + L: k for k in pl}
    piv_h, piv_l = [], []            # confirmed pivots so far (index)
    for i in range(n):
        if i in ph_by_conf:
            k = ph_by_conf[i]
            for q in reversed(piv_h[-6:]):
                if k - q > 96:
                    continue
                if abs(h[k] - h[q]) <= p["eq_tol"] * a[k] and h[q + 1:k].max(initial=-np.inf) <= max(h[k], h[q]):
                    lo = max(0, q - p["ext_bars"])
                    lvl = max(h[k], h[q])
                    if h[lo:q].max(initial=-np.inf) <= lvl:
                        live_h.append([lvl, i])
                    break
            piv_h.append(k)
        if i in pl_by_conf:
            k = pl_by_conf[i]
            for q in reversed(piv_l[-6:]):
                if k - q > 96:
                    continue
                if abs(l[k] - l[q]) <= p["eq_tol"] * a[k] and l[q + 1:k].min(initial=np.inf) >= min(l[k], l[q]):
                    lo = max(0, q - p["ext_bars"])
                    lvl = min(l[k], l[q])
                    if l[lo:q].min(initial=np.inf) >= lvl:
                        live_l.append([lvl, i])
                    break
            piv_l.append(k)
        # nearest live level (known before this bar) for the sweep check on bar i+1 onwards
        live_h = [x for x in live_h if x[1] >= i - 192]
        live_l = [x for x in live_l if x[1] >= i - 192]
        if live_h:
            eqh[i] = min(x[0] for x in live_h)
        if live_l:
            eql[i] = max(x[0] for x in live_l)
        live_h = [x for x in live_h if h[i] <= x[0] or x[1] == i]
        live_l = [x for x in live_l if l[i] >= x[0] or x[1] == i]
    return eqh, eql


def _levels(feat, p):
    hi, lo = [], []
    if "pd" in p["levels"]:
        hi.append(feat.pdh); lo.append(feat.pdl)
    if "asia" in p["levels"]:
        hi.append(feat.asia_h); lo.append(feat.asia_l)
    if "london" in p["levels"]:
        hi.append(feat.london_h); lo.append(feat.london_l)
    if "on" in p["levels"]:
        hi.append(feat.onh); lo.append(feat.onl)
    if "eq" in p["levels"]:
        eqh, eql = _eq_levels(feat, p)
        # the EQ level known at the close of bar i-1 is what bar i can sweep
        hi.append(np.r_[np.nan, eqh[:-1]]); lo.append(np.r_[np.nan, eql[:-1]])
    return hi, lo


def generate(feat, inst, p=None):
    p = {**DEF, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n = feat.n
    a_slow = features.atr(h, l, c, p["atr_slow"])
    w0, w1 = hm(p["win"][0]), hm(p["win"][1])
    hi_lv, lo_lv = _levels(feat, p)
    buf = p["buf"] * inst.tick
    tr_ema = features.ema(c, p["trend"]) if p["trend"] else None
    out = []
    used_day = set()
    # running extreme since each level became known (per level, reset each day / level change)
    run_hi = [np.nan] * len(hi_lv)
    run_lo = [np.nan] * len(lo_lv)
    prev_val_h = [np.nan] * len(hi_lv)
    prev_val_l = [np.nan] * len(lo_lv)
    taken_h = [False] * len(hi_lv)
    taken_l = [False] * len(lo_lv)
    pending = []    # (side, sweep_bar, level)
    for i in range(1, n):
        new_day = feat.day[i] != feat.day[i - 1]
        in_win = w0 <= feat.mod[i] < w1
        sweeps = []
        for side, lvls, run, prev, taken in ((-1, hi_lv, run_hi, prev_val_h, taken_h), (1, lo_lv, run_lo, prev_val_l, taken_l)):
            for j, arr in enumerate(lvls):
                v = arr[i]
                if new_day or not (v == prev[j]):
                    run[j], taken[j] = np.nan, False
                    prev[j] = v
                if np.isnan(v):
                    continue
                x = h[i] if side < 0 else l[i]
                crossed = (x > v) if side < 0 else (x < v)
                untouched = np.isnan(run[j]) or ((run[j] <= v) if side < 0 else (run[j] >= v))
                if crossed and untouched and not taken[j] and in_win:
                    sweeps.append((side, v))
                    taken[j] = True
                run[j] = x if np.isnan(run[j]) else (max(run[j], x) if side < 0 else min(run[j], x))
        for side, v in sweeps:
            pending.append((side, i, v))
        # evaluate pending sweeps: MSS + displacement + FVG
        keep = []
        for side, s, v in pending:
            if feat.day[i] != feat.day[s] or feat.day[i] in used_day:
                continue
            if i - s > p["look"] + p["post"]:
                continue
            seg = slice(s, i + 1)
            ext = h[seg].max() if side < 0 else l[seg].min()
            ref = l[max(0, s - p["mss_n"]):s].min() if side < 0 else h[max(0, s - p["mss_n"]):s].max()
            # MSS bar = first close beyond ref in (s, s+look]
            mss = None
            for j in range(s, min(i, s + p["look"]) + 1):
                if (c[j] < ref) if side < 0 else (c[j] > ref):
                    mss = j
                    break
            if mss is None:
                if i - s < p["look"]:
                    keep.append((side, s, v))
                continue
            body = side * (c[s:mss + 1] - o[s:mss + 1])
            if body.max() < p["disp"] * a[mss]:
                continue
            cc = c[s:mss + 1]
            er = abs(cc[-1] - cc[0]) / max(np.abs(np.diff(cc)).sum(), 1e-12) if len(cc) > 1 else 1.0
            if er < p["er_min"] or a[mss] < p["atr_exp"] * a_slow[mss]:
                continue
            if tr_ema is not None and side * (c[mss] - tr_ema[mss]) < 0:
                continue
            # FVGs of the leg known by bar i
            gaps = []
            for k in range(s + 2, min(i, mss + p["post"]) + 1):
                if side < 0 and h[k] < l[k - 2] and l[k - 2] - h[k] >= p["mf"] * a[k]:
                    gaps.append((k, h[k], l[k - 2]))
                if side > 0 and l[k] > h[k - 2] and l[k] - h[k - 2] >= p["mf"] * a[k]:
                    gaps.append((k, l[k], h[k - 2]))
            if not gaps:
                if i < mss + p["post"]:
                    keep.append((side, s, v))
                continue
            g = gaps[0] if p["pick"] == "first" else max(gaps, key=lambda z: abs(z[2] - z[1]))
            # emit once the MSS is in and the chosen gap exists; wait if more bars could add a larger gap
            if p["pick"] == "largest" and i < mss + p["post"]:
                keep.append((side, s, v))
                continue
            near, far = g[1], g[2]
            entry = near if p["entry"] == "edge" else (near + far) / 2
            stop = ext + buf if side < 0 else ext - buf
            # price must not already be through the entry (still a retrace to come)
            out.append(Setup(i, side, "limit", inst.round_price(entry), inst.round_price(stop), rr=3.0,
                             expiry=p["expiry"], invalidate=ext, note=f"ext sweep {v:.2f} -> MSS -> FVG"))
            used_day.add(feat.day[i])
        pending = keep
    return out


# ----------------------------------------------------------------- runs

def run(c, slip_ticks=1, intrabar="path", m1replay=False, shift=0):
    sym = c["sym"]
    feat = DL.feat_of(sym, c.get("tf", "15min"), shift)
    p = {k: v for k, v in c.items() if k not in ("sym", "tf")}
    ss = generate(feat, DP.inst_of(sym), p)
    tr = DP.simulate(feat, ss, DP.inst_of(sym), slip_ticks=slip_ticks, intrabar=intrabar,
                     m1df=DP.m1(sym) if m1replay else None, max_trades=1)
    for t in tr:
        t["sym"] = sym
    return tr


def key(c):
    return " ".join(f"{k}={'/'.join(v) if isinstance(v, tuple) and all(isinstance(z, str) for z in v) and k == 'levels' else v}"
                    for k, v in sorted(c.items()))


def truncation_check():
    for sym in ("MNQ", "MGC"):
        inst = DP.inst_of(sym)
        df = data.resample(DP.m1(sym), "15min")
        full = [(s.bar, s.side, s.entry, s.stop) for s in generate(features.build(df, inst.tick), inst, {})]
        for k in (7000, 15000, 23000):
            part = [(s.bar, s.side, s.entry, s.stop) for s in generate(features.build(df.iloc[:k], inst.tick), inst, {})]
            assert [x for x in full if x[0] < k - 1] == [x for x in part if x[0] < k - 1], (sym, k)
    print("truncation check OK")


GRID = dict(
    tf=["15min", "5min"],
    levels=[("pd", "asia", "london", "on", "eq"), ("pd", "asia", "london", "on")],
    win=[("02:00", "11:30"), ("02:00", "05:00"), ("08:30", "11:30")],
    disp=[0.5, 1.0],
    er_min=[0.0, 0.4],
    entry=["edge", "ce"],
)
BASE = dict(look=12, mss_n=4, post=4, expiry=12)


def grid(log=print):
    nd = DP.trading_days()
    rows = []
    for sym in ("MNQ", "MGC"):
        for vals in itertools.product(*GRID.values()):
            c = dict(BASE, **dict(zip(GRID, vals)), sym=sym)
            rep = DP.report_port(run(c), nd)
            rows.append(dict(cfg=c, **{k: rep[k] for k in ("full", "is_", "oos", "pos_months", "n_months")}))
            log(f"{sym} {key({k: v for k, v in c.items() if k != 'sym'}):110s} {DP.line(rep)}")
    DP.jdump(DP.OUT / "external_grid.json", rows)
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    {"trunc": truncation_check, "grid": grid}[cmd]()

"""Prop direction "concepts": NEW intraday concepts (not FVG/BOS, not sweep-reversal) as extra
legs next to FVG Pro Leto (MNQ London 02-05 + MGC COMEX 08:20-10:30) for prop-firm weekly payouts.

Concepts (all decided at a bar CLOSE; the order works from the NEXT bar; 1 trade per leg per Globex day):
  rbrk   range break: first FRESH close beyond a range (previous close inside, this close outside)
         ranges: or15 / or30 / ib60 = first 15/30/60 min of the market's session (MNQ 09:30, MGC 08:20,
                 MCL 09:00), signal window = W min after the range end;
                 asia  = 20:00-24:00 range (features.asia_h/l, known 00:00), window 02:00 + W (London open);
                 london = 02:00-05:00 range (features.london_h/l, known 05:00), window session open + W.
         entry "mkt" (next bar open, pays 1 tick) or "retest" (limit at the broken level, expiry 90 min,
         cancelled on a close back beyond the range mid); stop "mid" (range mid), "atr" (ref -/+ 1 ATR),
         "bar" (signal bar's opposite extreme -/+ 0.1 ATR).
  va80   80 % rule: the session opens outside the prior RTH value area (features.pvah/pval), then N
         consecutive closes back inside VA within W min of the open -> trade toward the other VA edge;
         market entry; stop "ext" (session extreme so far -/+ 0.1 ATR) or "atr" (1 ATR).
  vwr    VWAP-band reversion on balanced days: session-anchored VWAP +- k*sd (from session open);
         previous close outside the band, this close back inside, at least 60 min after the open,
         session range so far <= R * daily ATR (daily ATR = mean range of the 14 PRIOR sessions);
         market entry, stop = 3-bar extreme -/+ 0.1 ATR.
  gap    session-open gap vs the prior session's last close, |gap| in [g1, g2] * daily ATR, signal at the
         close of the first session bar: "fade" (gap still open at that close -> against the gap) or
         "go" (first bar closes in the gap direction -> with the gap); market entry, stop "ext" (first
         bar extreme -/+ 0.1 ATR) or "atr".
  fbm    first-bar momentum: first session bar with |body| >= b * ATR and close in its outer 30 %;
         entry "mkt" or "pb" (limit at the bar's midpoint, expiry 60 min, cancelled on a close beyond
         the bar's far end); stop "ext" (far end of the bar -/+ 0.1 ATR) or "atr".
  imom   intraday momentum: session open -> close of the bar ending at open+30 min; if |r| >= thr * daily
         ATR, enter at E (14:30 / 15:00, next bar open after the bar containing E-1min) in the sign of
         r, stop s * daily ATR, hold to 15:55 (no target).
Exits (decided on IS): "p13" = half at 1R -> BE -> runner 3R, time stop 120 min (Leto exit);
  "f1" = all at 1R, time stop 120 min; imom: "hold" (stop or 15:55). Flat 15:55 / new Globex day.
Execution: lab.daily_portfolio.simulate (limit/BE/stop logic, slip_ticks, intrabar, 1m replay);
  market entries are a marketable limit (ref + 1 ATR) filled at the next open, and pay slip_ticks
  extra per contract (applied to the trade's net $). 2 contracts per leg, data.py commissions.
  Risk check in the generator: risk >= 4 ticks and <= 3 ATR (with ref = signal close for market orders).

PRE-REGISTERED SELECTION RULE (written before any OOS number was looked at; IS = entry < 2026-04-01):
  For every config the IS stats are computed on the standard bars and on bars rebuilt with
  offsets 1..4 min (15m) / 1..2 min (5m) (lab.daily_levels.feat_of(sym, tf, shift)).
  IS-eligible:  IS trades at offset 0 >= 30 (~0.2/day),  IS exp > 0 at offset 0,
                IS WR >= 55 % at offset 0 and mean IS WR over the offsets >= 55 %,
                IS PF >= 1.15 at EVERY offset and median IS PF >= 1.30.
  Score = (min IS PF over offsets - 1) * sqrt(IS trades at offset 0).
  Candidate per (concept, market) = the best-scoring eligible config.
  Protocol gate (validation, not selection): IS PF >= 1.15 and OOS PF >= 1.15 at EVERY offset.
  Combination with Leto: the gated candidates in IS-score order, at most 3, skipping a candidate whose
  market AND signal window overlap an already chosen concept leg.  If none passes, the IS-best
  candidates are reported as "closest" with their exact numbers.

STAGE 2 (added after stage 1 failed: 12 IS-eligible configs, both per-concept picks failed the OOS
  bar-shift gate). Four more NEW families, same exits, same pre-registered IS rule, same gate; the
  final combination draws its candidates from stage 1 + stage 2 (best IS score per concept x market):
  ema_pb  EMA20 pullback in trend: EMA20 above EMA50 and EMA50 higher than 16 bars ago (long), the bar
          trades to within 0.3 ATR of EMA20, closes above EMA20 with a bullish body; window "am" =
          session open+15 .. +165 min or "pm" = 12:30-15:00; market entry, stop bar low - 0.1 ATR (mirror).
  vwap_pb trend-day VWAP pullback: the previous `m` minutes of closes all above the session VWAP, this
          bar's low within 0.1 ATR of VWAP (or below), close above VWAP, bullish body; open+60 .. 14:30;
          market entry, stop bar low - 0.1 ATR (mirror).
  box     consolidation breakout: the last K bars (K 4/6, all inside the session window open+30 .. 14:30)
          have a high-low box <= x * ATR (x 1.5/2.5); a close beyond the box -> market entry,
          stop box mid ("mid") or the far side of the box ("far").
  oncont  overnight continuation: move from the Globex 18:00 open to the session open, |r| >= thr *
          daily ATR (thr 0.25/0.5); the first session bar closes in the same direction -> market entry
          at the next open, stop first-bar extreme -/+ 0.1 ATR ("ext") or 1 ATR ("atr").
  Run: PYTHONPATH=. python -m lab.prop_concepts grid2   (-> results/prop/concepts_grid2.json)

Run:  PYTHONPATH=. python -m lab.prop_concepts trunc
      PYTHONPATH=. python -m lab.prop_concepts grid     (prints IS only; json keeps OOS)
      PYTHONPATH=. python -m lab.prop_concepts final
      PYTHONPATH=. python -m lab.prop_concepts real
      PYTHONPATH=. python -m lab.prop_concepts extra    (leg robustness, payout weeks, post-hoc info)
"""

from __future__ import annotations

import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features
from . import daily_portfolio as DP
from . import daily_levels as DL
from . import prop_legs as PL
from .engine import Setup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "prop"
CUT = DP.CUT
SESS = {"MNQ": (570, 960), "MGC": (500, 810), "MCL": (540, 870)}   # session open / close (min of day NY)
SYMS = ("MNQ", "MGC", "MCL")
TFS = ("15min", "5min")
TFMIN = {"15min": 15, "5min": 5}


def shifts_of(tf):
    return (0, 1, 2) if tf == "5min" else (0, 1, 2, 3, 4)


def exit_of(name, tf):
    tb = 120 // TFMIN[tf]
    if name == "p13":
        return dict(tp1=1.0, frac1=0.5, tp=3.0, be_tp1=True, tstop=tb)
    if name == "f1":
        return dict(tp1=None, tp=1.0, tstop=tb)
    if name == "hold":
        return dict(tp1=None, tp=99.0, tstop=0)
    raise KeyError(name)


# ----------------------------------------------------------------- per-day session structure (causal)

_S: dict = {}


def sess_of(feat, sym):
    k = (id(feat), sym)
    if k in _S and _S[k][0] is feat:      # keep a reference so the id cannot be reused
        return _S[k][1]
    t0, t1 = SESS[sym]
    o, h, l, c, v, mod, day = feat.o, feat.h, feat.l, feat.c, feat.v, feat.mod, feat.day
    n = feat.n
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], n]
    s_open = np.full(n, np.nan)       # session open, known from the first session bar on
    s_i0 = np.full(n, -1, int)        # index of the first session bar of the day
    pc = np.full(n, np.nan)           # prior session last close (whole day)
    datr = np.full(n, np.nan)         # mean range of the 14 prior sessions (whole day)
    vw, vsd = np.full(n, np.nan), np.full(n, np.nan)
    shi, slo = np.full(n, np.nan), np.full(n, np.nan)   # session high/low incl. this bar
    ranges, last_close = [], np.nan
    days = []
    for s, e in zip(starts, ends):
        m = mod[s:e]
        ins = np.flatnonzero((m >= t0) & (m < t1)) + s
        pc[s:e] = last_close
        if len(ranges) >= 5:
            datr[s:e] = float(np.mean(ranges[-14:]))
        if len(ins):
            i0 = ins[0]
            s_open[i0:e] = o[i0]
            s_i0[s:e] = i0
            tp = (h[ins] + l[ins] + c[ins]) / 3.0
            vv = np.maximum(v[ins], 1e-12)
            cv = np.cumsum(vv)
            w = np.cumsum(tp * vv) / cv
            vw[ins] = w
            vsd[ins] = np.sqrt(np.maximum(np.cumsum(tp * tp * vv) / cv - w * w, 0.0))
            shi[ins] = np.maximum.accumulate(h[ins])
            slo[ins] = np.minimum.accumulate(l[ins])
            ranges.append(float(h[ins].max() - l[ins].min()))
            last_close = float(c[ins[-1]])
        days.append((s, e, ins))
    out = dict(t0=t0, t1=t1, s_open=s_open, s_i0=s_i0, pc=pc, datr=datr, vw=vw, vsd=vsd, shi=shi, slo=slo, days=days)
    _S[k] = (feat, out)
    return out


# ----------------------------------------------------------------- signal generators

def _mk(feat, inst, i, side, ref, stop, mkt, entry=None, expiry=1, invalidate=None, note=""):
    """Build a Setup after the risk check (risk >= 4 ticks, <= 3 ATR). Market = marketable limit."""
    a = feat.atr[i]
    risk = (ref - stop) * side
    if not (a > 0) or risk < 4 * inst.tick or risk > 3.0 * a:
        return None
    if mkt:
        return Setup(bar=i, side=side, entry_type="market", entry=ref + side * 1.0 * a, stop=stop,
                     expiry=1, note="mkt")
    return Setup(bar=i, side=side, entry_type="limit", entry=entry, stop=stop, expiry=expiry,
                 invalidate=invalidate, note=note)


def _range_arrays(feat, S, c, tfm):
    """Per day: (range_hi, range_lo, first signal minute, last signal minute) or None."""
    rng = c["range"]
    out = []
    for s, e, ins in S["days"]:
        m = feat.mod[s:e]
        if rng in ("or15", "or30", "ib60"):
            L = {"or15": 15, "or30": 30, "ib60": 60}[rng]
            rb = ins[(feat.mod[ins] >= S["t0"]) & (feat.mod[ins] < S["t0"] + L)] if len(ins) else ins
            if not len(rb):
                out.append(None)
                continue
            hi, lo = feat.h[rb].max(), feat.l[rb].min()
            w0 = S["t0"] + L
        elif rng == "asia":
            j = np.flatnonzero((m >= 0) & (m < 18 * 60) & ~np.isnan(feat.asia_h[s:e]))
            if not len(j):
                out.append(None)
                continue
            hi, lo = feat.asia_h[s + j[0]], feat.asia_l[s + j[0]]
            w0 = 120
        elif rng == "london":
            j = np.flatnonzero(~np.isnan(feat.london_h[s:e]))
            if not len(j):
                out.append(None)
                continue
            hi, lo = feat.london_h[s + j[0]], feat.london_l[s + j[0]]
            w0 = S["t0"]
        else:
            raise KeyError(rng)
        out.append((hi, lo, w0, w0 + c["W"]))
    return out


def gen_rbrk(feat, inst, S, c):
    tfm = feat.interval_min
    o, h, l, cl, a, mod = feat.o, feat.h, feat.l, feat.c, feat.atr, feat.mod
    ss = []
    for (s, e, ins), r in zip(S["days"], _range_arrays(feat, S, c, tfm)):
        if r is None:
            continue
        hi, lo, w0, w1 = r
        mid = (hi + lo) / 2
        for i in range(max(s, 1), e):
            if not (w0 <= mod[i] < w1) or mod[i] >= 15 * 60 + 45:
                continue
            if feat.day[i - 1] != feat.day[i]:
                continue
            side = 1 if (cl[i] > hi and cl[i - 1] <= hi) else -1 if (cl[i] < lo and cl[i - 1] >= lo) else 0
            if not side:
                continue
            lvl = hi if side > 0 else lo
            mkt = c["entry"] == "mkt"
            ref = cl[i] if mkt else lvl
            if c["stop"] == "mid":
                stop = mid
            elif c["stop"] == "atr":
                stop = ref - side * 1.0 * a[i]
            else:
                stop = (l[i] if side > 0 else h[i]) - side * 0.1 * a[i]
            if (ref - stop) * side <= 0:
                break
            st = _mk(feat, inst, i, side, ref, stop, mkt, entry=lvl, expiry=max(1, 90 // tfm), invalidate=mid)
            if st is not None:
                ss.append(st)
            break   # first fresh break of the day only
    return ss


def gen_va80(feat, inst, S, c):
    tfm = feat.interval_min
    h, l, cl, a, mod = feat.h, feat.l, feat.c, feat.atr, feat.mod
    ss = []
    for s, e, ins in S["days"]:
        if not len(ins):
            continue
        i0 = ins[0]
        vah, val, so = feat.pvah[i0], feat.pval[i0], S["s_open"][i0]
        if np.isnan(vah) or np.isnan(val) or vah <= val:
            continue
        side = -1 if so > vah else 1 if so < val else 0
        if not side:
            continue
        run = 0
        for i in ins:
            if mod[i] >= S["t0"] + c["W"]:
                break
            inside = val < cl[i] < vah
            run = run + 1 if inside else 0
            if run >= c["N"]:
                if c["stop"] == "ext":
                    stop = (S["slo"][i] if side > 0 else S["shi"][i]) - side * 0.1 * a[i]
                else:
                    stop = cl[i] - side * 1.0 * a[i]
                st = _mk(feat, inst, i, side, cl[i], stop, True)
                if st is not None:
                    ss.append(st)
                break
    return ss


def gen_vwr(feat, inst, S, c):
    h, l, cl, a, mod = feat.h, feat.l, feat.c, feat.atr, feat.mod
    vw, sd, datr = S["vw"], S["vsd"], S["datr"]
    ss = []
    for s, e, ins in S["days"]:
        if len(ins) < 4:
            continue
        for j in range(1, len(ins)):
            i, ip = ins[j], ins[j - 1]
            if mod[i] < S["t0"] + 60 or mod[i] >= min(S["t1"], 15 * 60 + 30):
                continue
            if np.isnan(datr[i]) or sd[i] <= 0 or sd[ip] <= 0:
                continue
            if (S["shi"][i] - S["slo"][i]) > c["R"] * datr[i]:
                continue
            k = c["k"]
            up, dn = vw[i] + k * sd[i], vw[i] - k * sd[i]
            upp, dnp = vw[ip] + k * sd[ip], vw[ip] - k * sd[ip]
            side = 1 if (cl[ip] < dnp and cl[i] > dn) else -1 if (cl[ip] > upp and cl[i] < up) else 0
            if not side:
                continue
            lo3 = ins[max(0, j - 2):j + 1]
            stop = (l[lo3].min() if side > 0 else h[lo3].max()) - side * 0.1 * a[i]
            st = _mk(feat, inst, i, side, cl[i], stop, True)
            if st is not None:
                ss.append(st)
                break
    return ss


def gen_gap(feat, inst, S, c):
    o, h, l, cl, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    ss = []
    for s, e, ins in S["days"]:
        if not len(ins):
            continue
        i0 = ins[0]
        pc, d = S["pc"][i0], S["datr"][i0]
        if np.isnan(pc) or np.isnan(d) or d <= 0:
            continue
        g = o[i0] - pc
        if not (c["g1"] * d <= abs(g) <= c["g2"] * d):
            continue
        gs = 1 if g > 0 else -1
        if c["mode"] == "fade":
            if (l[i0] <= pc) if gs > 0 else (h[i0] >= pc):
                continue           # gap already filled in the first bar
            side = -gs
        else:
            if gs * (cl[i0] - o[i0]) <= 0:
                continue
            side = gs
        if c["stop"] == "ext":
            stop = (l[i0] if side > 0 else h[i0]) - side * 0.1 * a[i0]
        else:
            stop = cl[i0] - side * 1.0 * a[i0]
        st = _mk(feat, inst, i0, side, cl[i0], stop, True)
        if st is not None:
            ss.append(st)
    return ss


def gen_fbm(feat, inst, S, c):
    tfm = feat.interval_min
    o, h, l, cl, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    ss = []
    for s, e, ins in S["days"]:
        if not len(ins):
            continue
        i0 = ins[0]
        rg = h[i0] - l[i0]
        body = cl[i0] - o[i0]
        if rg <= 0 or not (a[i0] > 0) or abs(body) < c["b"] * a[i0]:
            continue
        side = 1 if body > 0 else -1
        loc = (cl[i0] - l[i0]) / rg if side > 0 else (h[i0] - cl[i0]) / rg
        if loc < 0.7:
            continue
        mid = (h[i0] + l[i0]) / 2
        far = l[i0] if side > 0 else h[i0]
        mkt = c["entry"] == "mkt"
        ref = cl[i0] if mkt else mid
        stop = far - side * 0.1 * a[i0] if c["stop"] == "ext" else ref - side * 1.0 * a[i0]
        st = _mk(feat, inst, i0, side, ref, stop, mkt, entry=mid, expiry=max(1, 60 // tfm), invalidate=far)
        if st is not None:
            ss.append(st)
    return ss


def gen_imom(feat, inst, S, c):
    tfm = feat.interval_min
    cl, mod = feat.c, feat.mod
    E = c["E"]
    ss = []
    for s, e, ins in S["days"]:
        if not len(ins):
            continue
        so, d = S["s_open"][ins[0]], S["datr"][ins[0]]
        if np.isnan(d) or d <= 0:
            continue
        first = ins[feat.mod[ins] < S["t0"] + 30]
        if not len(first):
            continue
        jb = first[-1]                      # last bar starting before open+30 -> its close ~ open+30
        r = cl[jb] - so
        if abs(r) < c["thr"] * d:
            continue
        side = 1 if r > 0 else -1
        for i in range(jb + 1, e):
            if mod[i] < E <= mod[i] + tfm:  # bar containing E - 1 min: enter at the next open
                stop = cl[i] - side * c["s"] * d
                if (cl[i] - stop) * side >= 4 * inst.tick:
                    ss.append(Setup(bar=i, side=side, entry_type="market", entry=cl[i] + side * feat.atr[i],
                                    stop=stop, expiry=1, note="mkt"))
                break
    return ss




def _ema_cache(feat):
    k = ("ema", id(feat))
    if k in _S and _S[k][0] is feat:
        return _S[k][1]
    e20, e50 = features.ema(feat.c, 20), features.ema(feat.c, 50)
    _S[k] = (feat, (e20, e50))
    return e20, e50


def gen_ema_pb(feat, inst, S, c):
    tfm = feat.interval_min
    o, h, l, cl, a, mod = feat.o, feat.h, feat.l, feat.c, feat.atr, feat.mod
    e20, e50 = _ema_cache(feat)
    w0, w1 = (S["t0"] + 15, S["t0"] + 165) if c["win"] == "am" else (750, 900)
    lb = 16
    ss = []
    for s, e, ins in S["days"]:
        for i in range(max(s, lb), e):
            if not (w0 <= mod[i] < w1):
                continue
            side = 0
            if e20[i] > e50[i] and e50[i] > e50[i - lb] and l[i] <= e20[i] + 0.3 * a[i] and cl[i] > e20[i] and cl[i] > o[i]:
                side = 1
            elif e20[i] < e50[i] and e50[i] < e50[i - lb] and h[i] >= e20[i] - 0.3 * a[i] and cl[i] < e20[i] and cl[i] < o[i]:
                side = -1
            if not side:
                continue
            stop = (l[i] if side > 0 else h[i]) - side * 0.1 * a[i]
            st = _mk(feat, inst, i, side, cl[i], stop, True)
            if st is not None:
                ss.append(st)
                break
    return ss


def gen_vwap_pb(feat, inst, S, c):
    tfm = feat.interval_min
    o, h, l, cl, a, mod = feat.o, feat.h, feat.l, feat.c, feat.atr, feat.mod
    vw = S["vw"]
    m = max(1, c["m"] // tfm)
    ss = []
    for s, e, ins in S["days"]:
        for j in range(m, len(ins)):
            i = ins[j]
            if mod[i] < S["t0"] + 60 or mod[i] >= 14 * 60 + 30:
                continue
            prev = ins[j - m:j]
            side = 0
            if (cl[prev] > vw[prev]).all() and l[i] <= vw[i] + 0.1 * a[i] and cl[i] > vw[i] and cl[i] > o[i]:
                side = 1
            elif (cl[prev] < vw[prev]).all() and h[i] >= vw[i] - 0.1 * a[i] and cl[i] < vw[i] and cl[i] < o[i]:
                side = -1
            if not side:
                continue
            stop = (l[i] if side > 0 else h[i]) - side * 0.1 * a[i]
            st = _mk(feat, inst, i, side, cl[i], stop, True)
            if st is not None:
                ss.append(st)
                break
    return ss


def gen_box(feat, inst, S, c):
    h, l, cl, a, mod = feat.h, feat.l, feat.c, feat.atr, feat.mod
    K = c["K"]
    ss = []
    for s, e, ins in S["days"]:
        done = False
        for j in range(K, len(ins)):
            i = ins[j]
            box = ins[j - K:j]
            if mod[box[0]] < S["t0"] + 30 or mod[i] >= 14 * 60 + 30:
                continue
            bh, bl = h[box].max(), l[box].min()
            if bh - bl > c["x"] * a[i]:
                continue
            side = 1 if cl[i] > bh else -1 if cl[i] < bl else 0
            if not side:
                continue
            stop = (bh + bl) / 2 if c["stop"] == "mid" else (bl if side > 0 else bh)
            st = _mk(feat, inst, i, side, cl[i], stop, True)
            if st is not None:
                ss.append(st)
            break
    return ss


def gen_oncont(feat, inst, S, c):
    o, h, l, cl, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    ss = []
    for s, e, ins in S["days"]:
        if not len(ins):
            continue
        i0 = ins[0]
        d = S["datr"][i0]
        if np.isnan(d) or d <= 0:
            continue
        r = o[i0] - o[s]
        if abs(r) < c["thr"] * d:
            continue
        side = 1 if r > 0 else -1
        if side * (cl[i0] - o[i0]) <= 0:
            continue
        stop = (l[i0] if side > 0 else h[i0]) - side * 0.1 * a[i0] if c["stop"] == "ext" else cl[i0] - side * a[i0]
        st = _mk(feat, inst, i0, side, cl[i0], stop, True)
        if st is not None:
            ss.append(st)
    return ss


GENS = dict(rbrk=gen_rbrk, va80=gen_va80, vwr=gen_vwr, gap=gen_gap, fbm=gen_fbm, imom=gen_imom,
            ema_pb=gen_ema_pb, vwap_pb=gen_vwap_pb, box=gen_box, oncont=gen_oncont)
STAGE2 = ("ema_pb", "vwap_pb", "box", "oncont")


def mkt_entry(c):
    return c["concept"] in ("va80", "vwr", "gap", "imom") + STAGE2 or c.get("entry") == "mkt"


def window_of(c):
    """Signal window (min of day) used for the overlap rule."""
    t0 = SESS[c["sym"]][0]
    k = c["concept"]
    if k == "rbrk":
        if c["range"] == "asia":
            return 120, 120 + c["W"]
        if c["range"] == "london":
            return t0, t0 + c["W"]
        L = {"or15": 15, "or30": 30, "ib60": 60}[c["range"]]
        return t0 + L, t0 + L + c["W"]
    if k == "va80":
        return t0, t0 + c["W"]
    if k == "vwr":
        return t0 + 60, SESS[c["sym"]][1]
    if k in ("gap", "fbm"):
        return t0, t0 + 120
    if k == "imom":
        return c["E"], 955
    if k == "ema_pb":
        return (t0 + 15, t0 + 165) if c["win"] == "am" else (750, 900)
    if k in ("vwap_pb", "box"):
        return t0 + 30, 870
    if k == "oncont":
        return t0, t0 + 120
    raise KeyError(k)


# ----------------------------------------------------------------- grid definition

def configs2():
    out = []
    for sym, tf in itertools.product(SYMS, TFS):
        base = dict(sym=sym, tf=tf)
        for win, ex in itertools.product(("am", "pm"), ("p13", "f1")):
            out.append(dict(base, concept="ema_pb", win=win, exit=ex))
        for m, ex in itertools.product((30, 60, 120), ("p13", "f1")):
            out.append(dict(base, concept="vwap_pb", m=m, exit=ex))
        for K, x, st, ex in itertools.product((4, 6), (1.5, 2.5), ("mid", "far"), ("p13", "f1")):
            out.append(dict(base, concept="box", K=K, x=x, stop=st, exit=ex))
        for thr, st, ex in itertools.product((0.25, 0.5), ("ext", "atr"), ("p13", "f1")):
            out.append(dict(base, concept="oncont", thr=thr, stop=st, exit=ex))
    return out


def configs():
    out = []
    for sym, tf in itertools.product(SYMS, TFS):
        base = dict(sym=sym, tf=tf)
        for rng, W, en, st, ex in itertools.product(("or15", "or30", "ib60", "asia", "london"), (60, 120, 180),
                                                    ("mkt", "retest"), ("mid", "atr", "bar"), ("p13", "f1")):
            if rng in ("asia", "london") and W == 60 or rng not in ("asia", "london") and W == 180:
                continue
            out.append(dict(base, concept="rbrk", range=rng, W=W, entry=en, stop=st, exit=ex))
        for N, W, st, ex in itertools.product((1, 2), (120, 240), ("ext", "atr"), ("p13", "f1")):
            out.append(dict(base, concept="va80", N=N, W=W, stop=st, exit=ex))
        for k, R, ex in itertools.product((1.5, 2.0), (0.7, 1.0, 99.0), ("p13", "f1")):
            out.append(dict(base, concept="vwr", k=k, R=R, exit=ex))
        for mode, g1, g2, st, ex in itertools.product(("fade", "go"), (0.1, 0.2), (0.6, 1.0), ("ext", "atr"),
                                                      ("p13", "f1")):
            out.append(dict(base, concept="gap", mode=mode, g1=g1, g2=g2, stop=st, exit=ex))
        for b, en, st, ex in itertools.product((0.5, 0.8, 1.2), ("mkt", "pb"), ("ext", "atr"), ("p13", "f1")):
            out.append(dict(base, concept="fbm", b=b, entry=en, stop=st, exit=ex))
        for thr, E, s in itertools.product((0.15, 0.25), (870, 900), (0.15, 0.25)):
            out.append(dict(base, concept="imom", thr=thr, E=E, s=s, exit="hold"))
    return out


def key(c):
    return "|".join(f"{k}={c[k]}" for k in ("concept", "sym", "tf") + tuple(sorted(set(c) - {"concept", "sym", "tf"})))


# ----------------------------------------------------------------- running a leg

def setups_for(feat, c):
    inst = DP.inst_of(c["sym"])
    return GENS[c["concept"]](feat, inst, sess_of(feat, c["sym"]), c)


def run_leg(c, shift=0, slip_ticks=1, intrabar="path", m1replay=False, feat=None):
    sym = c["sym"]
    inst = DP.inst_of(sym)
    feat = feat if feat is not None else DL.feat_of(sym, c["tf"], shift)
    ss = setups_for(feat, c)
    tr = DP.simulate(feat, ss, inst, mg=exit_of(c["exit"], c["tf"]), slip_ticks=slip_ticks, intrabar=intrabar,
                     min_risk_ticks=0, max_risk_atr=99.0, m1df=DP.m1(sym) if m1replay else None)
    if mkt_entry(c):
        extra = slip_ticks * inst.tick * inst.point_value * inst.contracts
        for t in tr:
            t["pnl"] -= extra
            t["r"] = t["pnl"] / (t["risk_pts"] * inst.point_value * inst.contracts)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = key(c), sym, pd.Timestamp(t["entry_time"])
    return tr


def _task(arg):
    sym, tf, shift, stage = arg
    rows = []
    for c in (configs() if stage == 1 else configs2()):
        if c["sym"] != sym or c["tf"] != tf:
            continue
        a, b = DP.split(run_leg(c, shift))
        rows.append(dict(key=key(c), cfg=c, shift=shift, is_=DP.stats(a), oos=DP.stats(b)))
    return rows


def grid(log=print, stage=1):
    tasks = [(s, tf, sh, stage) for s in SYMS for tf in TFS for sh in shifts_of(tf)]
    out = []
    with Pool(4) as pool:
        for rows in pool.imap_unordered(_task, tasks):
            out += rows
            log(f"{rows[0]['cfg']['sym']} {rows[0]['cfg']['tf']} shift {rows[0]['shift']}: {len(rows)} configs")
    PL.jdump(OUT / ("concepts_grid.json" if stage == 1 else "concepts_grid2.json"), out)
    # IS-only printout per concept x market (best IS PF at offset 0 with >= 30 trades)
    d = PL.by_config(out)
    for (k, sym) in itertools.product([g for g in GENS if (g in STAGE2) == (stage == 2)], SYMS):
        es = [e for e in d.values() if e["cfg"]["concept"] == k and e["cfg"]["sym"] == sym]
        es = [e for e in es if e["sh"][0]["is_"]["trades"] >= 30]
        if not es:
            log(f"{k:5s} {sym}: no config with >= 30 IS trades")
            continue
        b = max(es, key=lambda e: min(e["sh"][s]["is_"]["pf"] or 0 for s in e["sh"]))
        log(f"{k:5s} {sym}: best min-IS-PF {key(b['cfg'])}  IS0 {DP.fmt(b['sh'][0]['is_'])} "
            f"IS PF by shift {[round(b['sh'][s]['is_']['pf'] or 0, 2) for s in sorted(b['sh'])]}")
    return out


# ----------------------------------------------------------------- selection (IS only) + gate

def score(s):
    return (s["min_pf"] - 1.0) * np.sqrt(max(s["n0"], 0))


def eligible(e, s):
    s0 = e["sh"][0]["is_"]
    return (s["n0"] >= 30 and (s0["exp"] or 0) > 0 and s["wr0"] >= 0.55 and s["mean_wr"] >= 0.55
            and s["min_pf"] >= 1.15 and s["med_pf"] >= 1.30)


def select(rows):
    d = PL.by_config(rows)
    cands = []
    for k, e in d.items():
        s = PL.is_summary(e)
        if eligible(e, s):
            cands.append(dict(key=k, cfg=e["cfg"], s=s, score=float(score(s))))
    cands.sort(key=lambda x: -x["score"])
    best = {}
    for x in cands:
        g = (x["cfg"]["concept"], x["cfg"]["sym"])
        if g not in best:
            best[g] = x
    return cands, sorted(best.values(), key=lambda x: -x["score"])


def gate_of(e):
    per = {k: dict(is_pf=e["sh"][k]["is_"]["pf"] if e["sh"][k]["is_"]["trades"] else 0.0,
                   oos_pf=e["sh"][k]["oos"]["pf"] if e["sh"][k]["oos"]["trades"] else 0.0,
                   is_n=e["sh"][k]["is_"]["trades"], oos_n=e["sh"][k]["oos"]["trades"],
                   is_wr=e["sh"][k]["is_"]["wr"], oos_wr=e["sh"][k]["oos"]["wr"])
           for k in sorted(e["sh"])}
    return all(v["is_pf"] >= 1.15 and v["oos_pf"] >= 1.15 for v in per.values()), per


def overl(c1, c2):
    if c1["sym"] != c2["sym"]:
        return False
    a1, b1 = window_of(c1)
    a2, b2 = window_of(c2)
    return a1 < b2 and a2 < b1


def pick_combo(gated):
    chosen = []
    for x in gated:
        if any(overl(x["cfg"], y["cfg"]) for y in chosen):
            continue
        chosen.append(x)
        if len(chosen) == 3:
            break
    return chosen


# ----------------------------------------------------------------- portfolio

def leto_leg(c, shift=0, **kw):
    return PL.run_leg(c, shift if c["tf"] != "5min" else min(shift, 2), **kw)


def any_leg(c, shift=0, **kw):
    if "concept" in c:
        return run_leg(c, shift if c["tf"] != "5min" else min(shift, 2), **kw)
    return leto_leg(c, shift, **kw)


def portfolio(cfgs, shift=0, **kw):
    """Each leg max 1 trade / Globex day (inside its simulation); legs are independent (no cap)."""
    trs = [any_leg(c, shift, **kw) for c in cfgs]
    allt = sorted([t for tr in trs for t in tr], key=lambda t: t["ts"])
    return allt


def overlaps(tr):
    """Number of trades that open while another trade of the same market is still open."""
    by = {}
    for t in tr:
        by.setdefault(t["sym"], []).append((t["entry_time"], t["exit_time"]))
    n = 0
    for v in by.values():
        v.sort()
        for j in range(1, len(v)):
            if any(v[j][0] < x[1] for x in v[:j]):
                n += 1
    return n


def kname(c):
    return key(c) if "concept" in c else "LETO " + PL.key(c)


VARIANTS = PL.VARIANTS


def evaluate(name, cfgs, nd, log, out, real_shift=True):
    res = {}
    for tag, kw in VARIANTS:
        tr = portfolio(cfgs, **kw)
        rep = PL.full_report(tr, nd)
        rep["same_market_overlaps"] = overlaps(tr)
        res[tag] = rep
        log(f"{name:26s} {tag:12s} {PL.line(rep)}")
    for sh in (1, 2, 3, 4):
        rep = PL.full_report(portfolio(cfgs, shift=sh), nd)
        res[f"shift{sh}"] = rep
        log(f"{name:26s} shift {sh:<6d} {PL.line(rep)}")
    legs = {}
    for c in cfgs:
        legs[kname(c)] = PL.full_report(any_leg(c), nd)
        log(f"   leg {kname(c):60s} {PL.line(legs[kname(c)])}")
    res["legs"] = legs
    out["portfolios"][name] = res
    return res


def leg_robust(c, nd):
    r = {}
    for tag, kw in VARIANTS:
        r[tag] = PL.full_report(run_leg(c, **kw), nd)
    return r


def final(log=print):
    rows = json.loads((OUT / "concepts_grid.json").read_text())
    if (OUT / "concepts_grid2.json").exists():
        rows += json.loads((OUT / "concepts_grid2.json").read_text())
    nd = DP.trading_days()
    d = PL.by_config(rows)
    out = dict(trading_days=nd, n_configs=len(d), n_rows=len(rows), portfolios={})
    cands, per_group = select(rows)
    out["n_is_eligible"] = len(cands)
    out["eligible_by_concept"] = {k: sum(x["cfg"]["concept"] == k for x in cands) for k in GENS}
    log(f"{len(cands)} IS-eligible of {len(d)} configs; by concept {out['eligible_by_concept']}")
    out["candidates"] = []
    for x in per_group:
        ok, per = gate_of(d[x["key"]])
        x2 = dict(key=x["key"], cfg=x["cfg"], score=x["score"], is_summary=x["s"], passed=ok, per_shift=per)
        out["candidates"].append(x2)
        log(f"  {'PASS' if ok else 'fail'} score {x['score']:.2f} {x['key']}\n       " + " ".join(
            f"s{k}:{v['is_n']}/{v['oos_n']} {v['is_pf']:.2f}/{v['oos_pf']:.2f}" for k, v in per.items()))
    # family-level picture (IS-eligible configs that also pass the gate, all of them, for honesty)
    allpass = []
    for x in cands:
        ok, per = gate_of(d[x["key"]])
        if ok:
            allpass.append(x["key"])
    out["eligible_and_gate_pass_all_configs"] = allpass
    out["eligible_gate_pass_share"] = len(allpass) / max(1, len(cands))
    log(f"of all {len(cands)} IS-eligible configs {len(allpass)} also pass the gate")
    gated = [x for x in out["candidates"] if x["passed"]]
    combo = pick_combo(gated)
    out["combo"] = [x["key"] for x in combo]
    LETO = PL.LETO
    evaluate("Leto only", LETO, nd, log, out)
    if combo:
        for j in range(1, len(combo) + 1):
            cf = LETO + [x["cfg"] for x in combo[:j]]
            evaluate(f"Leto + {j} concept leg(s)", cf, nd, log, out)
        evaluate("concept legs only", [x["cfg"] for x in combo], nd, log, out)
        out["leg_robust"] = {x["key"]: leg_robust(x["cfg"], nd) for x in combo}
    else:
        closest = pick_combo(out["candidates"])
        out["closest"] = [x["key"] for x in closest]
        if closest:
            evaluate("Leto + closest (FAILED gate)", LETO + [x["cfg"] for x in closest], nd, log, out)
    PL.jdump(OUT / "concepts.json", out)
    return out


# ----------------------------------------------------------------- truncation check

def truncation_check(log=print):
    """Setups built on df[:k] equal the setups of the full df for bars < k-1 (offsets 0 and 2),
    for one representative config of every concept and market (and all exits share the generator)."""
    reps = {}
    only2 = len(sys.argv) > 2 and sys.argv[2] == "2"
    for c in (configs2() if only2 else configs() + configs2()):
        reps.setdefault((c["concept"], c["sym"], c["tf"]), []).append(c)
    n = 0
    for (k, sym, tf), cs in reps.items():
        for c in cs[:: max(1, len(cs) // 6)]:
            for sh in (0, 2):
                f_full = DL.feat_of(sym, tf, sh)
                full = [(s.bar, s.side, round(s.entry, 6), round(s.stop, 6), s.expiry) for s in setups_for(f_full, c)]
                df = f_full.df[["open", "high", "low", "close", "volume"]]
                for frac in (0.37, 0.71):
                    kk = int(len(df) * frac)
                    f = features.build(df.iloc[:kk], DP.inst_of(sym).tick)
                    part = [(s.bar, s.side, round(s.entry, 6), round(s.stop, 6), s.expiry) for s in setups_for(f, c)]
                    assert [x for x in full if x[0] < kk - 1] == [x for x in part if x[0] < kk - 1], (key(c), sh, kk)
                    n += 1
        log(f"truncation OK {k} {sym} {tf}")
    log(f"truncation check OK ({n} comparisons)")
    return n


# ----------------------------------------------------------------- real CME futures (MNQ, MGC)

def real_check(cfgs, log=print):
    from . import research
    st = research.load_store(["MNQ", "MGC"], ["5m"])
    res = {}
    for src in ("real", "proxy"):
        trs = []
        used = []
        for c in cfgs:
            real = st.get((c["sym"], "5m"))
            if real is None:
                continue
            lo, hi = real.index[0], real.index[-1]
            if src == "real":
                df = real if c["tf"] == "5min" else data.resample(real, c["tf"])
            else:
                d1 = DP.m1(c["sym"])
                df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], c["tf"])
            f = features.build(df, DP.inst_of(c["sym"]).tick)
            tr = any_leg_on(c, f)
            trs.append(tr)
            used.append(kname(c))
        pt = sorted([t for tr in trs for t in tr], key=lambda t: t["ts"])
        nd = len({PL.gday(x) for x in st[("MNQ", "5m")].index})
        per_leg = {u: DP.stats(t) for u, t in zip(used, trs)}
        res[src] = dict(stats=DP.stats(pt, nd), prop=PL.prop_metrics(pt, nd), days=nd, legs=used, per_leg=per_leg)
        log(f"real-window {src:6s} {DP.fmt(res[src]['stats'])} tpd {res[src]['stats']['tpd']:.2f} "
            f"windays/wk {res[src]['prop']['win_days_per_week']:.2f}")
        for u in used:
            log(f"     {u:60s} {DP.fmt(per_leg[u])}")
    return res


def any_leg_on(c, f):
    inst = DP.inst_of(c["sym"])
    if "concept" in c:
        return run_leg(c, feat=f)
    tr = DP.simulate(f, PL.setups(f, inst, c), inst)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = kname(c), c["sym"], pd.Timestamp(t["entry_time"])
    return tr


# ----------------------------------------------------------------- extra diagnostics (no selection)

def week_counts(tr, thr=150.0):
    """Weeks (Mon-Sun, by Globex day) with >= 3 / >= 5 winning days (day net >= thr)."""
    d = {}
    for t in tr:
        k = PL.gday(t["ts"]).tz_localize(None)
        d[k] = d.get(k, 0.0) + t["pnl"]
    s = pd.Series(d).sort_index()
    w = (s >= thr).groupby(s.index.to_period("W")).sum()
    cal = pd.date_range(s.index.min(), s.index.max(), freq="D").to_period("W").unique()
    return dict(weeks=len(cal), ge3=int((w >= 3).sum()), ge5=int((w >= 5).sum()), max_in_week=int(w.max()))


def legrob(log=print):
    o = json.loads((OUT / "concepts.json").read_text())
    nd = DP.trading_days()
    keys = o.get("combo") or o.get("closest") or []
    cands = {x["key"]: x["cfg"] for x in o["candidates"]}
    res = {"legs": {}, "weeks": {}}
    for k in keys:
        res["legs"][k] = {tag: PL.full_report(run_leg(cands[k], **kw), nd) for tag, kw in VARIANTS}
        for tag, r in res["legs"][k].items():
            log(f"{k[:60]:60s} {tag:12s} {PL.line(r)}")
    res["weeks"]["Leto"] = week_counts(portfolio(PL.LETO))
    res["weeks"]["Leto + closest"] = week_counts(portfolio(PL.LETO + [cands[k] for k in keys]))
    log(f"weeks: {res['weeks']}")
    # post-hoc information only (NOT selectable under the pre-registered rule): the IS-eligible
    # configs that happen to pass the OOS gate
    post = {}
    rows = json.loads((OUT / "concepts_grid.json").read_text())
    if (OUT / "concepts_grid2.json").exists():
        rows += json.loads((OUT / "concepts_grid2.json").read_text())
    d = PL.by_config(rows)
    for k in o["eligible_and_gate_pass_all_configs"]:
        c = d[k]["cfg"]
        post[k] = dict(leg=PL.full_report(run_leg(c), nd), with_leto=PL.full_report(portfolio(PL.LETO + [c]), nd))
        log(f"POST-HOC leg  {k}: {PL.line(post[k]['leg'])}")
        log(f"POST-HOC +Leto: {PL.line(post[k]['with_leto'])}")
    res["post_hoc_gate_passers"] = post
    PL.jdump(OUT / "concepts_extra.json", res)
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        grid()
    elif cmd == "grid2":
        grid(stage=2)
    elif cmd == "final":
        final()
    elif cmd == "trunc":
        truncation_check()
    elif cmd == "extra":
        legrob()
    elif cmd == "real":
        o = json.loads((OUT / "concepts.json").read_text())
        keys = o.get("combo") or o.get("closest") or []
        cf = [x["cfg"] for x in o["candidates"] if x["key"] in keys]
        r = {"leto": real_check(PL.LETO), "concepts": real_check(cf), "leto+concepts": real_check(PL.LETO + cf)}
        PL.jdump(OUT / "concepts_real.json", r)

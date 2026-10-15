"""SMC combination search: LuxAlgo-style structure + liquidity tools.

Python ports (from the public descriptions/open-source logic) of:
  * LuxAlgo "Smart Money Concepts": leg-based swing points (internal size 5,
    swing size 50), BOS / CHoCH on a close crossing the last swing level,
    order blocks (lowest/highest bar between the broken pivot and the
    break), FVGs with the auto threshold (middle candle's body % must exceed
    2 × its running average), premium/discount (equilibrium of the last
    swing high/low).
  * LuxAlgo "Liquidity Swings": pivot highs/lows (14/14) as liquidity, taken
    when price trades through.
  * LuxAlgo "Liquidity Sweeps" (Only Wicks): pivots 5/5, a sweep is a wick
    through the level with the close back on the other side.
  * BigBeluga "Liquidity Sweep Hunter" — APPROXIMATION (its exact code isn't
    reproduced here): pivots 10/10 with a wick sweep and close back inside.
  * Equal highs/lows (LuxAlgo EQH/EQL: two swings within 0.1 × ATR).

Template (long; shorts mirror):
  sell-side liquidity swept → within 30 bars an internal CHoCH (or any
  BOS/CHoCH) up → entry in the LuxAlgo FVG of that leg, or at its order
  block → stop beyond the sweep extreme (or 20 ticks beyond the FVG) → 2R.
"""

from __future__ import annotations

import math

import numpy as np

from .engine import Setup
from .features import Features

LIQ_SOURCES = {
    "lux_swings14": "LuxAlgo Liquidity Swings (14)",
    "lux_sweeps5": "LuxAlgo Liquidity Sweeps (5, wick)",
    "hunter10": "Sweep Hunter-style (10, wick) ~approx",
    "eqhl": "Equal highs/lows (LuxAlgo EQH/EQL)",
}
STRUCTURES = {"choch": "Internal CHoCH", "any": "Internal BOS or CHoCH"}
ENTRIES = {
    "fvg_limit": "Limit at LuxAlgo FVG edge",
    "fvg_respect": "Market after FVG respect candle, SL beyond sweep",
    "fvg_respect_sl20": "Market after FVG respect, SL 20 ticks beyond FVG",
    "ob_limit": "Limit at order block edge",
}
FILTERS = {"none": "No filter", "swing_trend": "With LuxAlgo swing trend (50)",
           "pd": "Premium/discount (longs below equilibrium)"}


# --------------------------------------------------------------------------- #
# LuxAlgo-style building blocks
# --------------------------------------------------------------------------- #

def leg_pivots(h, l, size):
    """LuxAlgo leg logic: newLegHigh = high[size] > highest(size) (the `size`
    bars after it), newLegLow likewise; a pivot is confirmed on the bar the
    leg flips. Returns list of (confirm_bar, pivot_bar, kind, level)."""
    n = len(h)
    leg = 0  # LuxAlgo: `var leg = 0` (bearish) on the first bar
    out = []
    for i in range(size, n):
        k = i - size
        new_high = h[k] > h[k + 1:i + 1].max()
        new_low = l[k] < l[k + 1:i + 1].min()
        new_leg = 0 if new_high else (1 if new_low else leg)
        if new_leg != leg:
            out.append((i, k, "H", h[k]) if new_leg == 0 else (i, k, "L", l[k]))
        leg = new_leg
    return out


def structure(c, piv, n):
    """BOS/CHoCH events from leg pivots: close crossing over the last pivot
    high (bullish) / under the last pivot low (bearish), each level once.
    Returns (events list[(bar, side, kind, pivot_bar)], bias array)."""
    by_bar = {}
    for cb, pb, kind, lv in piv:
        by_bar.setdefault(cb, []).append((pb, kind, lv))
    hi = lo = None  # [level, pivot_bar, crossed]
    bias = 0
    ev = []
    bias_arr = np.zeros(n)
    for i in range(1, n):
        for pb, kind, lv in by_bar.get(i, []):
            if kind == "H":
                hi = [lv, pb, False]
            else:
                lo = [lv, pb, False]
        if hi and not hi[2] and c[i] > hi[0] and c[i - 1] <= hi[0]:
            hi[2] = True
            ev.append((i, 1, "CHoCH" if bias == -1 else "BOS", hi[1]))
            bias = 1
        if lo and not lo[2] and c[i] < lo[0] and c[i - 1] >= lo[0]:
            lo[2] = True
            ev.append((i, -1, "CHoCH" if bias == 1 else "BOS", lo[1]))
            bias = -1
        bias_arr[i] = bias
    return ev, bias_arr


def lux_fvgs(o, h, l, c):
    """LuxAlgo FVG with the auto threshold. Returns dict bar -> (side, bot, top)."""
    n = len(c)
    delta = np.zeros(n)
    nz = o != 0
    delta[nz] = (c[nz] - o[nz]) / (o[nz] * 100)
    cum = np.cumsum(np.abs(delta))
    out = {}
    for i in range(2, n):
        thr = cum[i] / i * 2
        if l[i] > h[i - 2] and c[i - 1] > h[i - 2] and delta[i - 1] > thr:
            out[i] = (1, h[i - 2], l[i])
        elif h[i] < l[i - 2] and c[i - 1] < l[i - 2] and -delta[i - 1] > thr:
            out[i] = (-1, h[i], l[i - 2])
    return out


def liquidity_events(feat: Features, source: str, atr200):
    """Sweep events (bar, side_of_trade, extreme, level): side +1 = sell-side
    liquidity under a low was taken (a long setup)."""
    h, l, c = feat.h, feat.l, feat.c
    n = feat.n
    if source == "eqhl":
        piv = leg_pivots(h, l, 3)
        levels = []
        last = {"H": None, "L": None}
        for cb, pb, kind, lv in piv:
            prev = last[kind]
            if prev is not None and abs(lv - prev) < 0.1 * atr200[cb]:
                levels.append((cb, kind, max(lv, prev) if kind == "H" else min(lv, prev)))
            last[kind] = lv
        wick = False
    else:
        L = {"lux_swings14": 14, "lux_sweeps5": 5, "hunter10": 10}[source]
        levels = []
        for i in range(2 * L, n):
            k = i - L
            if h[k] == h[k - L:i + 1].max() and h[k] > h[k - L:k].max():
                levels.append((i, "H", h[k]))
            if l[k] == l[k - L:i + 1].min() and l[k] < l[k - L:k].min():
                levels.append((i, "L", l[k]))
        wick = source != "lux_swings14"
    by_bar = {}
    for cb, kind, lv in levels:
        by_bar.setdefault(cb, []).append((kind, lv))
    act_h, act_l = [], []
    ev = []
    for i in range(n):
        for kind, lv in by_bar.get(i, []):
            (act_h if kind == "H" else act_l).append([lv, i])
        if i == 0:
            continue
        act_h = [x for x in act_h if i - x[1] <= 600]
        act_l = [x for x in act_l if i - x[1] <= 600]
        taken_l = [x for x in act_l if x[1] < i and l[i] < x[0]]
        if taken_l:
            lv = min(x[0] for x in taken_l)
            act_l = [x for x in act_l if x not in taken_l]
            if not wick or c[i] > lv:
                ev.append((i, 1, l[i], lv))
        taken_h = [x for x in act_h if x[1] < i and h[i] > x[0]]
        if taken_h:
            lv = max(x[0] for x in taken_h)
            act_h = [x for x in act_h if x not in taken_h]
            if not wick or c[i] < lv:
                ev.append((i, -1, h[i], lv))
    return ev


class Context:
    """Everything shared by all combos on one dataset (computed once)."""

    def __init__(self, feat: Features):
        from .features import atr as _atr
        self.feat = feat
        o, h, l, c = feat.o, feat.h, feat.l, feat.c
        n = feat.n
        self.atr200 = _atr(h, l, c, 200)
        self.int_piv = leg_pivots(h, l, 5)
        self.int_ev, self.int_bias = structure(c, self.int_piv, n)
        sw_piv = leg_pivots(h, l, 50)
        _, self.sw_bias = structure(c, sw_piv, n)
        eq = np.full(n, np.nan)
        last_h = last_l = np.nan
        by = {}
        for cb, pb, kind, lv in sw_piv:
            by.setdefault(cb, []).append((kind, lv))
        for i in range(n):
            for kind, lv in by.get(i, []):
                if kind == "H":
                    last_h = lv
                else:
                    last_l = lv
            eq[i] = (last_h + last_l) / 2 if not (math.isnan(last_h) or math.isnan(last_l)) else np.nan
        self.eq = eq
        self.fvg = lux_fvgs(o, h, l, c)
        self.liq = {s: liquidity_events(feat, s, self.atr200) for s in LIQ_SOURCES}


def generate(ctx: Context, inst, liq: str, struct: str, entry: str, rr=2.0,
             sweep_window=30, fvg_after=3, expiry=20) -> list[Setup]:
    feat = ctx.feat
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    n = feat.n
    tick = inst.tick
    buf = 2 * tick
    sweeps = {}
    for b, side, ext, lv in ctx.liq[liq]:
        sweeps.setdefault(b, []).append((side, ext))
    breaks = {}
    for b, side, kind, pb in ctx.int_ev:
        if struct == "choch" and kind != "CHoCH":
            continue
        breaks.setdefault(b, []).append((side, pb))
    active = {1: None, -1: None}   # latest sweep per side: [bar, extreme]
    waiting = []                    # breaks waiting for an FVG: (bar, side, ext)
    armed = []                      # FVGs waiting for respect: dict
    out = []
    for i in range(1, n):
        for side, ext in sweeps.get(i, []):
            active[side] = [i, ext]
        for side in (1, -1):
            a = active[side]
            if a is not None:
                if i - a[0] > sweep_window:
                    active[side] = None
                else:
                    a[1] = min(a[1], l[i]) if side > 0 else max(a[1], h[i])
        new = []
        for side, pb in breaks.get(i, []):
            a = active[side]
            if a is None or a[0] >= i:
                continue
            new.append((side, a[0], a[1], pb))
            active[side] = None
        for side, sb, ext, pb in new:
            stop = ext - buf if side > 0 else ext + buf
            if entry == "ob_limit":
                seg = slice(max(pb, sb - 5), i)
                if seg.start >= seg.stop:
                    continue
                k = seg.start + (int(np.argmin(l[seg])) if side > 0 else int(np.argmax(h[seg])))
                bot, top = l[k], h[k]
                ent = top if side > 0 else bot
                st = min(stop, bot - buf) if side > 0 else max(stop, top + buf)
                if (c[i] - ent) * side > 0:
                    out.append(Setup(i, side, "limit", ent, st, rr=rr, expiry=expiry,
                                     invalidate=bot if side > 0 else top, note=f"OB {bot:.2f}-{top:.2f}"))
                continue
            got = None
            for k in range(i, sb, -1):
                g = ctx.fvg.get(k)
                if g and g[0] == side:
                    got = (k, g)
                    break
            if got:
                _handle_fvg(i, side, got[1][1], got[1][2], stop, entry, rr, expiry, tick, out, armed, c)
            else:
                waiting.append((i, side, stop))
        keep = []
        for wb, side, stop in waiting:
            if wb == i:
                keep.append((wb, side, stop))
                continue
            g = ctx.fvg.get(i)
            if g and g[0] == side:
                _handle_fvg(i, side, g[1], g[2], stop, entry, rr, expiry, tick, out, armed, c)
            elif i - wb < fvg_after:
                keep.append((wb, side, stop))
        waiting = keep
        keep = []
        for z in armed:
            if z["born"] == i:
                keep.append(z)
                continue
            side, bot, top = z["side"], z["bot"], z["top"]
            if i - z["born"] > expiry or (side > 0 and c[i] < bot) or (side < 0 and c[i] > top):
                continue
            touched = l[i] <= top if side > 0 else h[i] >= bot
            held = c[i] > top if side > 0 else c[i] < bot
            if touched and held:
                st = z["stop"] if entry == "fvg_respect" else (bot - 20 * tick if side > 0 else top + 20 * tick)
                out.append(Setup(i, side, "market", 0.0, st, rr=rr, expiry=1, note=f"FVG respect {bot:.2f}-{top:.2f}"))
                continue
            keep.append(z)
        armed = keep
    return out


def _handle_fvg(i, side, bot, top, stop, entry, rr, expiry, tick, out, armed, c):
    if entry == "fvg_limit":
        ent = top if side > 0 else bot
        if (c[i] - ent) * side > 0:
            out.append(Setup(i, side, "limit", ent, stop, rr=rr, expiry=expiry,
                             invalidate=bot if side > 0 else top, note=f"FVG {bot:.2f}-{top:.2f}"))
    else:
        armed.append(dict(side=side, bot=bot, top=top, born=i, stop=stop))


def filter_ok(ctx: Context, s: Setup, flt: str) -> bool:
    if flt == "none":
        return True
    if flt == "swing_trend":
        return ctx.sw_bias[s.bar] * s.side > 0
    eq = ctx.eq[s.bar]
    if math.isnan(eq):
        return False
    px = ctx.feat.c[s.bar] if s.entry_type == "market" else s.entry
    return px < eq if s.side > 0 else px > eq


# --------------------------------------------------------------------------- #
# Search over every combination, with the research engine's safeguards
# --------------------------------------------------------------------------- #

def search(datasets, cfg, log=print):
    from . import engine, features, research
    from .data import get_instrument

    rows = []
    for (sym, tf), df in sorted(datasets.items()):
        inst = get_instrument(sym)
        feat = features.build(df, inst.tick)
        ctx = Context(feat)
        days = np.unique(feat.day)
        cut_day = days[int(len(days) * 0.6)]
        cut = feat.df.index[np.argmax(feat.day >= cut_day)].isoformat()
        wmask = {w: research._window_mask(feat, spans) for w, spans in research.WINDOWS.items()}
        combos = [(lq, st, en) for lq in LIQ_SOURCES for st in STRUCTURES for en in ENTRIES]
        combos += [("random", "-", "seed1"), ("random", "-", "seed2")]
        b = research.blocks(feat, research.P)
        for lq, st, en in combos:
            if lq == "random":
                setups = research.fam_random(feat, b, inst, "ce" if en == "seed1" else "edge", {**research.P, "rr": 2.0})
            else:
                setups = generate(ctx, inst, lq, st, en)
            for w in research.WINDOWS:
                in_w = [s for s in setups if wmask[w][s.bar]]
                for flt in FILTERS:
                    sel = [s for s in in_w if filter_ok(ctx, s, flt)]
                    trades = engine.run(feat, sel, inst, cfg) if sel else []
                    row = {"family": "random" if lq == "random" else f"{lq}|{st}|{en}", "liq": lq, "structure": st,
                           "entry": en, "window": w, "context": flt, "timeframe": tf, "symbol": sym,
                           **research._stats(trades, cut)}
                    row["id"] = f"{row['family']}|{w}|{flt}|{tf}|{sym}"
                    rows.append(row)
        log(f"  {sym} {tf:>3s}: {feat.n:,} bars, {len(days)} sessions")
    research.judge(rows)
    return rows

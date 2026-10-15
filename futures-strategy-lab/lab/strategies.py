"""Mechanized versions of the strategy concepts in data/concepts.json.

Each strategy is `fn(feat, inst, p) -> list[Setup]`, where every Setup is
decided on the close of its bar using only information known at that time.
Every trade is planned at a fixed reward:risk of `p["rr"]` (2.0 by default,
per the user's plan). Parameters live in DEFAULTS and can be overridden from
the CLI with --param key=value.
"""

from __future__ import annotations

import math

import numpy as np

from .data import Instrument
from .engine import Setup
from .features import Features, hm, pivots

COMMON = {"rr": 2.0, "buffer_ticks": 2}


def _in_window(feat: Features, i: int, windows) -> bool:
    m = feat.mod[i]
    return any(hm(a) <= m < hm(b) for a, b in windows)


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


# --------------------------------------------------------------------------- #
# 1. Liquidity sweep + rejection block + FVG respected  (the user's playbook)
# --------------------------------------------------------------------------- #

def lsrb_fvg(feat: Features, inst: Instrument, p: dict) -> list[Setup]:
    """Liquidity pools = confirmed swing highs/lows, prior-day high/low and the
    overnight high/low. A sweep is a bar that trades through a pool and CLOSES
    back on the other side with a rejection wick (the rejection block). After
    the sweep, wait for a displacement FVG in the reversal direction; enter
    with a limit at the FVG's CE (50%). The FVG must be respected: a close
    through its far edge cancels the order. Stop beyond the sweep extreme."""
    h, l, o, c, a = feat.h, feat.l, feat.o, feat.c, feat.atr
    buf = p["buffer_ticks"] * inst.tick
    L = int(p["pivot_len"])
    ph, pl = pivots(h, l, L)
    ph_at = {k + L: k for k in ph}  # confirmation bar -> pivot bar
    pl_at = {k + L: k for k in pl}
    highs: list[list] = []  # [level, born_bar]
    lows: list[list] = []
    armed = {1: None, -1: None}  # side -> dict(extreme, bar, level)
    out: list[Setup] = []
    windows = p["windows"]

    for i in range(2, feat.n):
        if i in ph_at:
            highs.append([h[ph_at[i]], ph_at[i]])
        if i in pl_at:
            lows.append([l[pl_at[i]], pl_at[i]])
        if feat.mod[i] == hm("09:30") and p["use_session_levels"]:
            # prior-day levels already run overnight are no longer resting liquidity
            for lvl, fresh in ((feat.pdh[i], feat.pdh[i] > feat.onh[i]), (feat.onh[i], True)):
                if _ok(lvl) and fresh:
                    highs.append([lvl, i - 1])
            for lvl, fresh in ((feat.pdl[i], feat.pdl[i] < feat.onl[i]), (feat.onl[i], True)):
                if _ok(lvl) and fresh:
                    lows.append([lvl, i - 1])
        highs[:] = [x for x in highs if i - x[1] <= p["max_pool_age"]]
        lows[:] = [x for x in lows if i - x[1] <= p["max_pool_age"]]

        rng = h[i] - l[i]
        # --- sweeps (pools are consumed whenever traded through) ---
        taken_h = [x for x in highs if h[i] > x[0] and x[1] < i]
        if taken_h:
            highs[:] = [x for x in highs if x not in taken_h]
            lvl = max(x[0] for x in taken_h)
            wick = h[i] - max(o[i], c[i])
            if (c[i] < lvl and rng > 0 and wick >= p["wick_ratio"] * rng
                    and _in_window(feat, i, windows)):
                armed[-1] = dict(extreme=h[i], bar=i, level=lvl)
        taken_l = [x for x in lows if l[i] < x[0] and x[1] < i]
        if taken_l:
            lows[:] = [x for x in lows if x not in taken_l]
            lvl = min(x[0] for x in taken_l)
            wick = min(o[i], c[i]) - l[i]
            if (c[i] > lvl and rng > 0 and wick >= p["wick_ratio"] * rng
                    and _in_window(feat, i, windows)):
                armed[1] = dict(extreme=l[i], bar=i, level=lvl)

        # --- displacement FVG after an armed sweep ---
        for side in (1, -1):
            st = armed[side]
            if st is None or st["bar"] == i:
                continue
            if i - st["bar"] > p["fvg_window"] or not _in_window(feat, i, windows):
                armed[side] = None
                continue
            if (side < 0 and h[i] > st["extreme"]) or (side > 0 and l[i] < st["extreme"]):
                armed[side] = None  # sweep extreme taken out -> idea failed
                continue
            if i - 2 < st["bar"]:
                continue
            if side < 0 and h[i] < l[i - 2]:
                bot, top = h[i], l[i - 2]
            elif side > 0 and l[i] > h[i - 2]:
                bot, top = h[i - 2], l[i]
            else:
                continue
            if top - bot < p["min_fvg_atr"] * a[i]:
                continue
            body = abs(c[i - 1] - o[i - 1])
            if body < p["disp_atr"] * a[i]:
                continue
            if p["entry"] == "ce":
                entry = inst.round_price((top + bot) / 2)
            else:  # proximal edge
                entry = bot if side < 0 else top
            stop = st["extreme"] + buf if side < 0 else st["extreme"] - buf
            out.append(Setup(bar=i, side=side, entry_type="limit", entry=entry, stop=stop,
                             rr=p["rr"], expiry=p["order_expiry"],
                             invalidate=top if side < 0 else bot,
                             note=f"sweep {st['level']:.2f} -> FVG {bot:.2f}-{top:.2f}"))
            armed[side] = None
    return out


# --------------------------------------------------------------------------- #
# 2. Turtle Soup (Linda Raschke) — false break of a 20-bar extreme
# --------------------------------------------------------------------------- #

def turtle_soup(feat, inst, p):
    h, l, c = feat.h, feat.l, feat.c
    N, gap = int(p["lookback"]), int(p["min_age"])
    buf = p["buffer_ticks"] * inst.tick
    out = []
    for i in range(N + 1, feat.n):
        if not _in_window(feat, i, p["windows"]):
            continue
        win_l = l[i - N:i]
        k = int(np.argmin(win_l))
        prior_low = win_l[k]
        if l[i] < prior_low and (N - k) >= gap:
            # buy back above the old low; stop under today's new low
            out.append(Setup(i, 1, "stop", inst.round_price(prior_low + inst.tick), l[i] - buf,
                             rr=p["rr"], expiry=p["order_expiry"], note=f"20-bar low {prior_low:.2f} broken"))
            continue
        win_h = h[i - N:i]
        k = int(np.argmax(win_h))
        prior_high = win_h[k]
        if h[i] > prior_high and (N - k) >= gap:
            out.append(Setup(i, -1, "stop", inst.round_price(prior_high - inst.tick), h[i] + buf,
                             rr=p["rr"], expiry=p["order_expiry"], note=f"20-bar high {prior_high:.2f} broken"))
    return out


# --------------------------------------------------------------------------- #
# 3. "Oops" (Larry Williams) — RTH open outside yesterday's range, reclaim
# --------------------------------------------------------------------------- #

def oops_reclaim(feat, inst, p):
    c = feat.c
    buf = p["buffer_ticks"] * inst.tick
    out, fired = [], set()
    for i in range(1, feat.n):
        d = feat.day[i]
        if d in fired or not _in_window(feat, i, p["windows"]):
            continue
        ro, pdh, pdl = feat.rth_open[i], feat.pdh[i], feat.pdl[i]
        if not (_ok(ro) and _ok(pdh)):
            continue
        if ro < pdl and c[i] > pdl:
            out.append(Setup(i, 1, "market", 0.0, feat.rth_lo_sofar[i] - buf, rr=p["rr"], expiry=1,
                             note=f"opened below PDL {pdl:.2f}, reclaimed"))
            fired.add(d)
        elif ro > pdh and c[i] < pdh:
            out.append(Setup(i, -1, "market", 0.0, feat.rth_hi_sofar[i] + buf, rr=p["rr"], expiry=1,
                             note=f"opened above PDH {pdh:.2f}, lost it"))
            fired.add(d)
    return out


# --------------------------------------------------------------------------- #
# 4. Opening-range breakout failure (failed ORB, trap reversal)
# --------------------------------------------------------------------------- #

def orb_failure(feat, inst, p):
    h, l, c = feat.h, feat.l, feat.c
    buf = p["buffer_ticks"] * inst.tick
    out, fired = [], set()
    for i in range(1, feat.n):
        d = feat.day[i]
        if d in fired or not _in_window(feat, i, p["windows"]):
            continue
        orh, orl = feat.or_h[i], feat.or_l[i]
        if not _ok(orh):
            continue
        if h[i] > orh and c[i] < orh:
            out.append(Setup(i, -1, "market", 0.0, feat.rth_hi_sofar[i] + buf, rr=p["rr"], expiry=1,
                             note=f"failed break of OR high {orh:.2f}"))
            fired.add(d)
        elif l[i] < orl and c[i] > orl:
            out.append(Setup(i, 1, "market", 0.0, feat.rth_lo_sofar[i] - buf, rr=p["rr"], expiry=1,
                             note=f"failed break of OR low {orl:.2f}"))
            fired.add(d)
    return out


# --------------------------------------------------------------------------- #
# 5. Session-liquidity sweep & reclaim (Asia / London / overnight levels at NY)
# --------------------------------------------------------------------------- #

def session_sweep(feat, inst, p):
    h, l, o, c = feat.h, feat.l, feat.o, feat.c
    buf = p["buffer_ticks"] * inst.tick
    out = []
    used: set = set()
    for i in range(1, feat.n):
        if not _in_window(feat, i, p["windows"]):
            continue
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        d = feat.day[i]
        for name, lvl in (("asia_h", feat.asia_h[i]), ("london_h", feat.london_h[i]), ("onh", feat.onh[i])):
            if _ok(lvl) and (d, name) not in used and h[i] > lvl and c[i] < lvl \
                    and (h[i] - max(o[i], c[i])) >= p["wick_ratio"] * rng:
                used.add((d, name))
                out.append(Setup(i, -1, "market", 0.0, h[i] + buf, rr=p["rr"], expiry=1,
                                 note=f"swept {name} {lvl:.2f}"))
                break
        for name, lvl in (("asia_l", feat.asia_l[i]), ("london_l", feat.london_l[i]), ("onl", feat.onl[i])):
            if _ok(lvl) and (d, name) not in used and l[i] < lvl and c[i] > lvl \
                    and (min(o[i], c[i]) - l[i]) >= p["wick_ratio"] * rng:
                used.add((d, name))
                out.append(Setup(i, 1, "market", 0.0, l[i] - buf, rr=p["rr"], expiry=1,
                                 note=f"swept {name} {lvl:.2f}"))
                break
        # levels taken without a rejection are spent too
        for name, lvl in (("asia_h", feat.asia_h[i]), ("london_h", feat.london_h[i]), ("onh", feat.onh[i])):
            if _ok(lvl) and h[i] > lvl:
                used.add((d, name))
        for name, lvl in (("asia_l", feat.asia_l[i]), ("london_l", feat.london_l[i]), ("onl", feat.onl[i])):
            if _ok(lvl) and l[i] < lvl:
                used.add((d, name))
    return out


# --------------------------------------------------------------------------- #
# 6. Inventory Retracement Bar (Rob Hoffman) — trend continuation
# --------------------------------------------------------------------------- #

def irb_trend(feat, inst, p):
    h, l, o, c, e, a = feat.h, feat.l, feat.o, feat.c, feat.ema20, feat.atr
    out = []
    k = int(p["slope_bars"])
    for i in range(k + 1, feat.n):
        if not _in_window(feat, i, p["windows"]):
            continue
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        slope = (e[i] - e[i - k]) / (k * a[i])
        top_frac = (h[i] - max(o[i], c[i])) / rng
        bot_frac = (min(o[i], c[i]) - l[i]) / rng
        if slope >= p["min_slope"] and top_frac >= p["retrace"] and l[i] > e[i]:
            out.append(Setup(i, 1, "stop", h[i] + inst.tick, l[i] - inst.tick, rr=p["rr"],
                             expiry=p["order_expiry"], note="bull IRB"))
        elif slope <= -p["min_slope"] and bot_frac >= p["retrace"] and h[i] < e[i]:
            out.append(Setup(i, -1, "stop", l[i] - inst.tick, h[i] + inst.tick, rr=p["rr"],
                             expiry=p["order_expiry"], note="bear IRB"))
    return out


# --------------------------------------------------------------------------- #
# 7. Value-area rejection / 80% rule (Market Profile, J. Dalton)
# --------------------------------------------------------------------------- #

def va_rejection(feat, inst, p):
    c = feat.c
    buf = p["buffer_ticks"] * inst.tick
    need = max(1, int(round(p["hold_minutes"] / feat.interval_min)))
    out, fired = [], set()
    inside = 0
    for i in range(1, feat.n):
        d = feat.day[i]
        if feat.day[i] != feat.day[i - 1]:
            inside = 0
        vah, val, ro = feat.pvah[i], feat.pval[i], feat.rth_open[i]
        if not (_ok(vah) and _ok(ro)) or not _in_window(feat, i, p["windows"]) or d in fired:
            continue
        inside = inside + 1 if val < c[i] < vah else 0
        if inside >= need:
            if ro > vah:   # opened above value, accepted back inside -> short toward VAL
                out.append(Setup(i, -1, "market", 0.0, feat.rth_hi_sofar[i] + buf, rr=p["rr"], expiry=1,
                                 note=f"80% rule from above, VAH {vah:.2f}"))
                fired.add(d)
            elif ro < val:
                out.append(Setup(i, 1, "market", 0.0, feat.rth_lo_sofar[i] - buf, rr=p["rr"], expiry=1,
                                 note=f"80% rule from below, VAL {val:.2f}"))
                fired.add(d)
    return out


# --------------------------------------------------------------------------- #
# 8. VWAP band sweep (session low/high run beyond 2σ, close back inside)
# --------------------------------------------------------------------------- #

def vwap_band_sweep(feat, inst, p):
    h, l, c = feat.h, feat.l, feat.c
    buf = p["buffer_ticks"] * inst.tick
    k = p["band_sd"]
    out = []
    for i in range(1, feat.n):
        if not _in_window(feat, i, p["windows"]) or feat.day[i] != feat.day[i - 1]:
            continue
        vw, sd = feat.vwap[i], feat.vwap_sd[i]
        prev_lo, prev_hi = feat.rth_lo_sofar[i - 1], feat.rth_hi_sofar[i - 1]
        if not (_ok(vw) and _ok(prev_lo)) or sd <= 0:
            continue
        lower, upper = vw - k * sd, vw + k * sd
        if l[i] < prev_lo and l[i] < lower and c[i] > lower:
            out.append(Setup(i, 1, "market", 0.0, l[i] - buf, rr=p["rr"], expiry=1,
                             note=f"swept day low under -{k}σ VWAP"))
        elif h[i] > prev_hi and h[i] > upper and c[i] < upper:
            out.append(Setup(i, -1, "market", 0.0, h[i] + buf, rr=p["rr"], expiry=1,
                             note=f"swept day high over +{k}σ VWAP"))
    return out


# --------------------------------------------------------------------------- #
# 9. Al Brooks H2 / L2 — second-entry pullback in a trend
# --------------------------------------------------------------------------- #

def brooks_h2l2(feat, inst, p):
    h, l, o, c, e, a = feat.h, feat.l, feat.o, feat.c, feat.ema20, feat.atr
    out = []
    k = int(p["slope_bars"])
    state = {1: None, -1: None}  # side -> dict(count, extreme, touched)
    for i in range(k + 1, feat.n):
        if feat.day[i] != feat.day[i - 1]:
            state = {1: None, -1: None}
        up = e[i] > e[i - k] and c[i] > e[i]
        dn = e[i] < e[i - k] and c[i] < e[i]
        # --- bull side: pullback = lower high; Hn = high above prior bar's high
        s = state[1]
        if up or s is not None:
            if s is None and h[i] < h[i - 1]:
                s = state[1] = dict(count=0, top=max(h[i - 1], h[i]), touched=False)
            elif s is not None:
                s["touched"] |= l[i] <= e[i] + p["ema_touch_atr"] * a[i]
                if h[i] > s["top"] or c[i] < e[i] - a[i]:
                    state[1] = None  # new trend high or trend broken
                elif h[i] > h[i - 1]:
                    s["count"] += 1
                    strong = c[i] > o[i] and (c[i] - l[i]) >= 0.6 * (h[i] - l[i])
                    if s["count"] >= 2 and s["touched"] and strong and _in_window(feat, i, p["windows"]):
                        out.append(Setup(i, 1, "stop", h[i] + inst.tick, l[i] - inst.tick, rr=p["rr"],
                                         expiry=1, note="H2"))
                        state[1] = None
        s = state[-1]
        if dn or s is not None:
            if s is None and l[i] > l[i - 1]:
                s = state[-1] = dict(count=0, bot=min(l[i - 1], l[i]), touched=False)
            elif s is not None:
                s["touched"] |= h[i] >= e[i] - p["ema_touch_atr"] * a[i]
                if l[i] < s["bot"] or c[i] > e[i] + a[i]:
                    state[-1] = None
                elif l[i] < l[i - 1]:
                    s["count"] += 1
                    strong = c[i] < o[i] and (h[i] - c[i]) >= 0.6 * (h[i] - l[i])
                    if s["count"] >= 2 and s["touched"] and strong and _in_window(feat, i, p["windows"]):
                        out.append(Setup(i, -1, "stop", l[i] - inst.tick, h[i] + inst.tick, rr=p["rr"],
                                         expiry=1, note="L2"))
                        state[-1] = None
    return out


NY_AM = [("09:30", "11:30")]

REGISTRY = {
    "lsrb_fvg": (lsrb_fvg, dict(windows=NY_AM, pivot_len=3, max_pool_age=300, use_session_levels=True,
                                wick_ratio=0.40, fvg_window=10, min_fvg_atr=0.10, disp_atr=0.0,
                                entry="ce", order_expiry=20)),
    "turtle_soup": (turtle_soup, dict(windows=NY_AM, lookback=20, min_age=4, order_expiry=3)),
    "oops_reclaim": (oops_reclaim, dict(windows=[("09:30", "11:00")])),
    "orb_failure": (orb_failure, dict(windows=[("09:45", "11:30")])),
    "session_sweep": (session_sweep, dict(windows=NY_AM, wick_ratio=0.40)),
    "irb_trend": (irb_trend, dict(windows=[("09:45", "15:00")], slope_bars=5, min_slope=0.15,
                                  retrace=0.45, order_expiry=5)),
    "va_rejection": (va_rejection, dict(windows=[("09:30", "13:00")], hold_minutes=30)),
    "vwap_band_sweep": (vwap_band_sweep, dict(windows=[("10:00", "15:00")], band_sd=2.0)),
    "brooks_h2l2": (brooks_h2l2, dict(windows=[("09:45", "15:00")], slope_bars=5, ema_touch_atr=0.25)),
}


def params_for(sid: str, overrides: dict | None = None) -> dict:
    _, defaults = REGISTRY[sid]
    p = {**COMMON, **defaults}
    for k, v in (overrides or {}).items():
        if k in p:
            p[k] = v
    return p


def generate(sid: str, feat: Features, inst: Instrument, overrides: dict | None = None) -> list[Setup]:
    fn, _ = REGISTRY[sid]
    return fn(feat, inst, params_for(sid, overrides))

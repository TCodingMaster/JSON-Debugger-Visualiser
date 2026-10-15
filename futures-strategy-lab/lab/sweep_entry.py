"""Liquidity-sweep entry without FVG confirmation (separate strategy).

Liquidity pools: confirmed swing highs/lows (pivot_len bars each side) plus,
optionally, the prior RTH day high/low, overnight high/low and the Asia and
London session highs/lows. A pool is spent once price trades through it.

mode "limit"  — enter AS the sweep starts: a resting limit order sits on the
                pool nearest to price (sell at a high, buy at a low), renewed
                every bar. Stop = level ± stop_atr × ATR, target = rr × risk.
mode "close"  — enter after the sweep candle closes back on the other side of
                the level: market order on the next bar, stop beyond the wick.

Session windows (New York time), max trades per Globex day and the 15:55
flatten come from the shared engine.
"""

from __future__ import annotations

import math

import numpy as np

from . import engine, features
from .data import get_instrument
from .engine import EngineConfig, Setup
from .features import hm

DEFAULTS = dict(mode="limit", pivot_len=3, stop_atr=0.5, rr=1.5, max_dist_atr=1.5,
                session_levels=True, buffer_ticks=2,
                windows=(("20:00", "24:00"), ("02:00", "05:00")), flatten="15:55", max_trades=1)


def _ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def generate(feat, inst, p: dict | None = None) -> list[Setup]:
    p = {**DEFAULTS, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n, L = feat.n, int(p["pivot_len"])
    buf = p["buffer_ticks"] * inst.tick
    win = np.zeros(n, bool)
    for s_, e_ in p["windows"]:
        win |= (feat.mod >= hm(s_)) & (feat.mod < hm(e_))
    highs: list[float] = []
    lows: list[float] = []
    seen_lv: set = set()
    out = []
    for i in range(2 * L, n):
        k = i - L
        if h[k] > h[k - L:k].max() and h[k] >= h[k + 1:i + 1].max():
            highs.append(h[k])
        if l[k] < l[k - L:k].min() and l[k] <= l[k + 1:i + 1].min():
            lows.append(l[k])
        if p["session_levels"]:
            for lv, arr in ((feat.pdh[i], highs), (feat.onh[i], highs), (feat.asia_h[i], highs), (feat.london_h[i], highs),
                            (feat.pdl[i], lows), (feat.onl[i], lows), (feat.asia_l[i], lows), (feat.london_l[i], lows)):
                if _ok(lv) and (feat.day[i], round(lv, 6)) not in seen_lv:
                    seen_lv.add((feat.day[i], round(lv, 6)))
                    arr.append(lv)
        # pools taken on this bar are spent; remember which for the close-back mode
        taken_h = [x for x in highs if h[i] > x]
        taken_l = [x for x in lows if l[i] < x]
        highs[:] = [x for x in highs if x >= h[i]]
        lows[:] = [x for x in lows if x <= l[i]]
        if not win[i]:
            continue
        if p["mode"] == "close":
            if taken_h:
                lv = max(taken_h)
                if c[i] < lv:
                    out.append(Setup(i, -1, "market", 0.0, h[i] + buf, rr=p["rr"], expiry=1, note=f"swept high {lv:.2f}"))
                    continue
            if taken_l:
                lv = min(taken_l)
                if c[i] > lv:
                    out.append(Setup(i, 1, "market", 0.0, l[i] - buf, rr=p["rr"], expiry=1, note=f"swept low {lv:.2f}"))
            continue
        # limit mode: rest an order on the pool nearest to the close
        up = min((x for x in highs if x > c[i]), default=None)
        dn = max((x for x in lows if x < c[i]), default=None)
        cand = []
        if up is not None and up - c[i] <= p["max_dist_atr"] * a[i]:
            cand.append((up - c[i], -1, up))
        if dn is not None and c[i] - dn <= p["max_dist_atr"] * a[i]:
            cand.append((c[i] - dn, 1, dn))
        if not cand:
            continue
        _, side, lv = min(cand)
        stop = lv + p["stop_atr"] * a[i] + buf if side < 0 else lv - p["stop_atr"] * a[i] - buf
        out.append(Setup(i, side, "limit", inst.round_price(lv), inst.round_price(stop), rr=p["rr"], expiry=1,
                         note=f"limit at liquidity {lv:.2f}"))
    return out


def backtest(df, symbol, p: dict | None = None):
    p = {**DEFAULTS, **(p or {})}
    inst = get_instrument(symbol)
    feat = features.build(df, inst.tick)
    cfg = EngineConfig(flatten=p["flatten"], max_trades_per_day=p["max_trades"], intrabar="path")
    return feat, engine.run(feat, generate(feat, inst, p), inst, cfg)

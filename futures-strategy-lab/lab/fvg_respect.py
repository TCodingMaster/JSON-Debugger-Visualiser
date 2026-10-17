"""FVG Pro with the user's definition of a RESPECTED FVG (confirmation entry).

The FVG Pro setup (BOS + FVG, lab/fvg_pro.py) normally rests a limit order on
the FVG edge, so any touch fills. Here the gap must be *respected* first:

  * the first candle that trades back into the gap (low <= top for a bullish
    FVG) must close back above the gap top and be a rejection candle:
    a hammer (lower wick >= wick_frac x range) or a doji (body <= doji_frac x range);
  * then enter at the next bar's open (market);
  * a close below the gap bottom kills the setup; so does `first_touch_only`
    when the first touching candle is not a respect candle;
  * the setup expires after `expiry` bars.
Bearish setups mirror. Stop: "fvg" = beyond the far side of the gap,
"wick" = beyond the respect candle, "orig" = FVG Pro's swing stop.
"""

from __future__ import annotations

import numpy as np

from . import engine, features, fvg_pro
from .data import get_instrument
from .engine import EngineConfig, Setup

DEFAULTS = dict(wick_frac=0.5, doji_frac=0.25, first_touch_only=True, stop_mode="fvg", rr=2.0,
                buffer_ticks=2, expiry=20)


def respect_setups(feat, inst, base: list[Setup], p: dict) -> list[Setup]:
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    buf = p["buffer_ticks"] * inst.tick
    out = []
    for s in base:
        side = s.side
        edge, far = s.entry, s.invalidate            # long: edge = gap top, far = gap bottom
        for j in range(s.bar + 1, min(s.bar + 1 + p["expiry"], feat.n)):
            touched = l[j] <= edge if side > 0 else h[j] >= edge
            if not touched:
                if (c[j] < far) if side > 0 else (c[j] > far):
                    break
                continue
            rng = h[j] - l[j]
            body = abs(c[j] - o[j])
            wick = (min(o[j], c[j]) - l[j]) if side > 0 else (h[j] - max(o[j], c[j]))
            back = c[j] > edge if side > 0 else c[j] < edge
            shape = rng > 0 and (wick >= p["wick_frac"] * rng or body <= p["doji_frac"] * rng)
            if back and shape:
                if p["stop_mode"] == "fvg":
                    stop = far - buf if side > 0 else far + buf
                elif p["stop_mode"] == "wick":
                    stop = l[j] - buf if side > 0 else h[j] + buf
                else:
                    stop = s.stop
                out.append(Setup(j, side, "market", 0.0, inst.round_price(stop), rr=p["rr"], expiry=1,
                                 note=f"FVG respected ({'hammer' if wick >= p['wick_frac'] * rng else 'doji'})"))
                break
            if p["first_touch_only"] or ((c[j] < far) if side > 0 else (c[j] > far)):
                break
    out.sort(key=lambda s: s.bar)
    return out


def generate(feat, inst, fp: dict | None = None, p: dict | None = None) -> list[Setup]:
    fp = {**fvg_pro.DEFAULTS, **(fp or {})}
    p = {**DEFAULTS, **(p or {})}
    return respect_setups(feat, inst, fvg_pro.generate(feat, inst, fp), p)


def backtest(df, symbol, fp: dict | None = None, p: dict | None = None):
    fp = {**fvg_pro.DEFAULTS, **(fp or {})}
    inst = get_instrument(symbol)
    feat = features.build(df, inst.tick)
    cfg = EngineConfig(flatten=fp["flatten"], max_trades_per_day=fp["max_trades"], intrabar="path")
    return feat, engine.run(feat, generate(feat, inst, fp, p), inst, cfg)

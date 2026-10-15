"""sweepX — the user's written strategy (Google doc "sweepX"), mechanized.

CORE: market structure, HTF bias, liquidity sweep, MSS, displacement, FVG/IFVG.
FILTERS: PDH/PDL (A+), previous session high/low, session timing.
Timeframe 3-5 min for everything except the bias (1h / 4h).

Liquidity pools: confirmed swing highs/lows plus PDH/PDL, overnight, Asia and
London highs/lows. A pool is swept when a bar trades through it; the sweep
stays "live" for `sweep_age` bars. FVGs born from `pre` bars before the sweep
onward belong to that sweep.

Reversal (doc steps 1-6, shown for a swept HIGH -> short):
  1. HTF bias bearish (or bias filter off).
  2. A buy-side pool is swept (A+ if it is PDH).
  3. A bullish FVG exists (formed in the run into the sweep or after it).
  4. A displacement candle (body >= disp_atr x ATR) CLOSES below the FVG
     bottom -> the FVG becomes a bearish IFVG. A close back above the IFVG
     top later = "disrespected": that IFVG is dropped (wait for another).
  5. Optional MSS/CHoCH: since the sweep a candle closed below the last
     confirmed swing low that existed at the sweep.
  6. Respect + rejection candle: price trades back into the IFVG and the bar
     closes bearish below its bottom. Market entry on the next bar's open,
     stop `buffer_ticks` above the IFVG top, target rr x risk.

Continuation (swept LOW in a down move -> short; mirrored for longs):
  1. HTF bias bearish.  2. A sell-side pool is swept.
  3. A bearish FVG (formed in the leg or after the sweep).
  4. Price retraces into it (one or more candles) without closing above it.
  5. A displacement candle closes back below the FVG bottom, optionally
     with a BOS (close below the last confirmed swing low).
  6. One more candle closes without getting back into the FVG (the doc's
     "let one more candle close"), then market entry on the next bar's open,
     stop `buffer_ticks` above the FVG top.

"Trail when needed" is approximated with the engine's break-even option
(be_at_r). Session windows (New York time), max trades per Globex day and
the 15:55 flatten come from the shared engine.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import engine, features
from .data import get_instrument
from .engine import EngineConfig, Setup
from .features import hm

WINDOW_PRESETS = {
    "asia_london": (("20:00", "24:00"), ("02:00", "05:00")),
    "london_ny": (("02:00", "12:00"),),
    "ny_am": (("08:30", "12:00"),),
    "all": (("20:00", "24:00"), ("00:00", "15:30")),
}

DEFAULTS = dict(
    model="both",            # "reversal" | "continuation" | "both"
    bias="both",             # HTF bias: "1h" | "4h" | "both" (1h and 4h agree) | "off"
    bias_pivot=2,
    pivot_len=3,
    min_fvg_atr=0.10,
    disp_atr=0.5,            # displacement: body >= N x ATR
    need_mss=False,          # reversal: MSS/CHoCH since the sweep before entry
    need_bos=True,           # continuation: displacement candle closes beyond the last swing
    aplus_only=False,        # only PDH/PDL sweeps
    pre=10, sweep_age=30, zone_age=30,
    buffer_ticks=2, rr=1.5, be_at_r=0.0,
    windows="all", flatten="15:55", max_trades=2,
)


# --------------------------------------------------------------------------- #
# HTF bias from completed higher-timeframe bars only
# --------------------------------------------------------------------------- #

def htf_bias(feat, rule: str, pivot: int = 2) -> np.ndarray:
    """+1 / -1 / 0 per LTF bar: direction of the last break of structure on
    the `rule` timeframe (close beyond the last confirmed swing high/low),
    using only HTF bars that were complete when the LTF bar closed."""
    df = feat.df
    off = "2h" if rule == "4h" else "0h"   # 4h bars aligned to the 18:00 Globex open
    hdf = df.resample(rule, offset=off, label="left", closed="left").agg(
        {"high": "max", "low": "min", "close": "last"}).dropna()
    H, Lw, C = hdf["high"].to_numpy(), hdf["low"].to_numpy(), hdf["close"].to_numpy()
    m = len(hdf)
    bias_after = np.zeros(m)
    sh = sl = np.nan
    b = 0
    for j in range(m):
        k = j - pivot
        if k >= pivot:
            if H[k] > H[k - pivot:k].max() and H[k] >= H[k + 1:j + 1].max():
                sh = H[k]
            if Lw[k] < Lw[k - pivot:k].min() and Lw[k] <= Lw[k + 1:j + 1].min():
                sl = Lw[k]
        if not math.isnan(sh) and C[j] > sh:
            b, sh = 1, np.nan
        elif not math.isnan(sl) and C[j] < sl:
            b, sl = -1, np.nan
        bias_after[j] = b
    done = (hdf.index + pd.Timedelta(rule)).asi8
    ltf_close = (df.index + pd.Timedelta(minutes=feat.interval_min)).asi8
    j = np.searchsorted(done, ltf_close, side="right") - 1
    out = np.where(j >= 0, bias_after[np.clip(j, 0, None)], 0.0)
    return out


def bias_array(feat, p) -> np.ndarray:
    if p["bias"] == "off":
        return np.ones(feat.n) * np.nan
    if p["bias"] in ("1h", "4h"):
        return htf_bias(feat, p["bias"], p["bias_pivot"])
    b1, b4 = htf_bias(feat, "1h", p["bias_pivot"]), htf_bias(feat, "4h", p["bias_pivot"])
    return np.where(b1 == b4, b1, 0.0)


# --------------------------------------------------------------------------- #
# Signal generation
# --------------------------------------------------------------------------- #

def _ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def generate(feat, inst, p: dict | None = None) -> list[Setup]:
    p = {**DEFAULTS, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n, L = feat.n, int(p["pivot_len"])
    tick = inst.tick
    buf = p["buffer_ticks"] * tick
    windows = WINDOW_PRESETS[p["windows"]] if isinstance(p["windows"], str) else p["windows"]
    win = np.zeros(n, bool)
    for s_, e_ in windows:
        win |= (feat.mod >= hm(s_)) & (feat.mod < hm(e_))
    bias = bias_array(feat, p)
    use_rev = p["model"] in ("reversal", "both")
    use_con = p["model"] in ("continuation", "both")

    def allowed(side, i):
        return math.isnan(bias[i]) or bias[i] == side

    def disp(i):
        return abs(c[i] - o[i]) >= p["disp_atr"] * a[i]

    # pools: (level, is_aplus)
    highs: list[tuple] = []
    lows: list[tuple] = []
    seen: set = set()
    lsh = lsl = np.nan           # last confirmed swing high / low
    sweeps = []                  # dict(kind=+1 high swept / -1 low swept, bar, aplus, ref_swing)
    zones = {}                   # fvg key -> state dict
    out = []
    for i in range(2 * L, n):
        k = i - L
        if h[k] > h[k - L:k].max() and h[k] >= h[k + 1:i + 1].max():
            lsh = h[k]
            highs.append((h[k], False))
        if l[k] < l[k - L:k].min() and l[k] <= l[k + 1:i + 1].min():
            lsl = l[k]
            lows.append((l[k], False))
        for lv, arr, ap in ((feat.pdh[i], highs, True), (feat.onh[i], highs, False),
                            (feat.asia_h[i], highs, False), (feat.london_h[i], highs, False),
                            (feat.pdl[i], lows, True), (feat.onl[i], lows, False),
                            (feat.asia_l[i], lows, False), (feat.london_l[i], lows, False)):
            if _ok(lv) and (feat.day[i], round(lv, 6)) not in seen:
                seen.add((feat.day[i], round(lv, 6)))
                arr.append((lv, ap))
        # 2: sweeps on this bar
        took_h = [x for x in highs if h[i] > x[0]]
        took_l = [x for x in lows if l[i] < x[0]]
        highs[:] = [x for x in highs if x[0] >= h[i]]
        lows[:] = [x for x in lows if x[0] <= l[i]]
        if took_h and (not p["aplus_only"] or any(ap for _, ap in took_h)):
            sweeps.append(dict(kind=1, bar=i, aplus=any(ap for _, ap in took_h), ref=lsl))
        if took_l and (not p["aplus_only"] or any(ap for _, ap in took_l)):
            sweeps.append(dict(kind=-1, bar=i, aplus=any(ap for _, ap in took_l), ref=lsh))
        sweeps = [s for s in sweeps if i - s["bar"] <= p["sweep_age"]]

        # 3: new FVG at bar i, attached to the latest live sweep it can serve
        if i >= 2:
            if l[i] > h[i - 2] and l[i] - h[i - 2] >= p["min_fvg_atr"] * a[i]:
                fv = (1, h[i - 2], l[i])
            elif h[i] < l[i - 2] and l[i - 2] - h[i] >= p["min_fvg_atr"] * a[i]:
                fv = (-1, h[i], l[i - 2])
            else:
                fv = None
            if fv:
                zones[i] = dict(fside=fv[0], bot=fv[1], top=fv[2], born=i, state="fvg",
                                touched=False, trig=None, inv=None)

        # a zone serves the latest live sweep of the same direction (a swept HIGH
        # pairs with a bullish FVG, a swept LOW with a bearish FVG) if it was born
        # at most `pre` bars before that sweep. It then either inverts (reversal)
        # or is respected (continuation).
        for kz in list(zones):
            z = zones[kz]
            if i - z["born"] > p["zone_age"] + p["pre"] or z["state"] == "dead":
                del zones[kz]
                continue
            if kz == i:
                continue
            bot, top, fs = z["bot"], z["top"], z["fside"]
            s = next((s for s in reversed(sweeps) if s["kind"] == fs and z["born"] >= s["bar"] - p["pre"]), None)
            if z["state"] == "fvg":
                inverted = (fs > 0 and c[i] < bot) or (fs < 0 and c[i] > top)
                if inverted:
                    if use_rev and s is not None and disp(i):
                        z.update(state="ifvg", inv=i, sweep=s)
                    else:
                        z["state"] = "dead"
                    continue
            # continuation lives on FVGs in the direction of the sweep's leg:
            # swept LOW in a down leg -> bearish FVG (fs = -1 = s.kind)
            if z["state"] == "fvg":
                if not use_con or s is None:
                    continue
                side = fs                      # bearish FVG -> short, bullish FVG -> long
                if i > s["bar"]:
                    if (side < 0 and h[i] >= bot) or (side > 0 and l[i] <= top):
                        z["touched"] = True
                    if (side < 0 and c[i] > top) or (side > 0 and c[i] < bot):
                        z["state"] = "dead"
                        continue
                if z["trig"] is None and z["touched"] and i > s["bar"]:
                    brk = (side < 0 and c[i] < bot) or (side > 0 and c[i] > top)
                    bos = (not p["need_bos"]) or (side < 0 and _ok(lsl) and c[i] < lsl) or \
                        (side > 0 and _ok(lsh) and c[i] > lsh)
                    if brk and disp(i) and bos:
                        z["trig"] = i
                        continue
                if z["trig"] is not None and i == z["trig"] + 1:
                    stays = (side < 0 and c[i] < bot) or (side > 0 and c[i] > top)
                    if stays and win[i] and allowed(side, i):
                        stop = top + buf if side < 0 else bot - buf
                        out.append(Setup(i, side, "market", 0.0, stop, rr=p["rr"], expiry=1,
                                         note=f"continuation FVG {bot:.2f}-{top:.2f}"
                                              + (" A+" if s["aplus"] else "")))
                    z["state"] = "dead"
                continue
            # ---- reversal: respect of the IFVG + rejection candle
            if z["state"] == "ifvg" and i > z["inv"]:
                s = z["sweep"]
                side = -fs                     # bullish FVG inverted -> short
                if i - z["inv"] > p["zone_age"]:
                    z["state"] = "dead"
                    continue
                if (side < 0 and c[i] > top) or (side > 0 and c[i] < bot):
                    z["state"] = "dead"        # IFVG disrespected
                    continue
                retest = (side < 0 and h[i] >= bot) or (side > 0 and l[i] <= top)
                reject = (side < 0 and c[i] < bot and c[i] < o[i]) or (side > 0 and c[i] > top and c[i] > o[i])
                if retest and reject:
                    mss = True
                    if p["need_mss"]:
                        ref = s["ref"]
                        seg = c[s["bar"]:i + 1]
                        mss = _ok(ref) and ((side < 0 and seg.min() < ref) or (side > 0 and seg.max() > ref))
                    if mss and win[i] and allowed(side, i):
                        stop = top + buf if side < 0 else bot - buf
                        out.append(Setup(i, side, "market", 0.0, stop, rr=p["rr"], expiry=1,
                                         note=f"reversal IFVG {bot:.2f}-{top:.2f}" + (" A+" if s["aplus"] else "")))
                        z["state"] = "dead"
    return out


def backtest(df, symbol, p: dict | None = None):
    p = {**DEFAULTS, **(p or {})}
    inst = get_instrument(symbol)
    feat = features.build(df, inst.tick)
    cfg = EngineConfig(flatten=p["flatten"], max_trades_per_day=p["max_trades"], intrabar="path",
                       be_at_r=p["be_at_r"])
    return feat, engine.run(feat, generate(feat, inst, p), inst, cfg)

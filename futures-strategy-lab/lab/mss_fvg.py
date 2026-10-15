"""MSS + liquidity sweep + FVG respect — the user's own method, mechanized.

Rules (bullish; bearish mirrors):
  1. Structure from confirmed swings (pivot_len bars each side). Downtrend
     context: the last swing high is a LOWER HIGH (below the swing high before it).
  2. MSS: a candle CLOSES above that lower high.
  3. Liquidity sweep: the leg into the MSS (from the lower high to the MSS bar)
     traded below the last swing low that existed before the leg (sell-side
     liquidity taken). Optionally prior-day / overnight lows count as liquidity.
  4. FVG: a bullish gap formed in the MSS leg (after the sweep low, up to
     `fvg_after` bars after the MSS). The most recent one is used.
  5. Respect: a later candle trades into the FVG (low <= top) and closes back
     above it (close > top in "strict" mode; close >= bottom in "loose" mode).
     Entry at the next bar's open.
  6. Stop: `stop_ticks` ticks below the FVG bottom (the user's "20 pips").
     Alternative: below the sweep low. Target: 2R.
  7. The setup dies if a candle closes below the FVG before it is respected,
     or after `expiry` bars. Session windows in New York time, max trades per
     day, flat by 15:55 (shared engine).
"""

from __future__ import annotations

import math

import numpy as np

from . import engine, features
from .data import get_instrument
from .engine import EngineConfig, Setup
from .features import hm

DEFAULTS = dict(
    pivot_len=3, min_fvg_atr=0.10, fvg_after=3, respect="strict", stop_mode="fvg", stop_ticks=20,
    rr=2.0, expiry=20, use_session_liq=False,
    windows=(("20:00", "24:00"), ("00:00", "15:30")),
    flatten="15:55", max_trades=2,
)


def _swings(h, l, L):
    """Per bar: (last SH, its bar, previous SH, last SL, its bar, previous SL)
    from swings confirmed L bars after they print."""
    n = len(h)
    out = np.full((n, 6), np.nan)
    sh = sh_bar = psh = sl = sl_bar = psl = np.nan
    for i in range(2 * L, n):
        k = i - L
        if h[k] > h[k - L:k].max() and h[k] >= h[k + 1:i + 1].max():
            psh, sh, sh_bar = sh, h[k], k
        if l[k] < l[k - L:k].min() and l[k] <= l[k + 1:i + 1].min():
            psl, sl, sl_bar = sl, l[k], k
        out[i] = (sh, sh_bar, psh, sl, sl_bar, psl)
    return out


def generate(feat, inst, p: dict | None = None) -> list[Setup]:
    p = {**DEFAULTS, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n, L = feat.n, int(p["pivot_len"])
    tick = inst.tick
    sw = _swings(h, l, L)
    win = np.zeros(n, bool)
    for s_, e_ in p["windows"]:
        win |= (feat.mod >= hm(s_)) & (feat.mod < hm(e_))

    def gap(k, side):
        if k < 2:
            return None
        if side > 0 and l[k] > h[k - 2] and l[k] - h[k - 2] >= p["min_fvg_atr"] * a[k]:
            return h[k - 2], l[k]
        if side < 0 and h[k] < l[k - 2] and l[k - 2] - h[k] >= p["min_fvg_atr"] * a[k]:
            return h[k], l[k - 2]
        return None

    used = {1: None, -1: None}
    sl_hist = []  # (bar, value) of confirmed swing lows / highs, for the sweep reference
    sh_hist = []
    pending = []   # MSS waiting for its FVG: dict(side, mss, leg_lo_bar, extreme)
    armed = []     # FVGs waiting to be respected: dict(side, bot, top, born, extreme)
    out = []
    for i in range(2 * L + 1, n):
        sh, sh_bar, psh, sl, sl_bar, psl = sw[i]
        if not sh_hist or (not math.isnan(sh_bar) and sh_hist[-1][0] != sh_bar):
            if not math.isnan(sh):
                sh_hist.append((int(sh_bar), sh))
        if not sl_hist or (not math.isnan(sl_bar) and sl_hist[-1][0] != sl_bar):
            if not math.isnan(sl):
                sl_hist.append((int(sl_bar), sl))

        # 1-3: MSS with a liquidity sweep in the leg
        for side in (1, -1):
            if side > 0:
                ok = not math.isnan(psh) and sh < psh and c[i] > sh and used[1] != sh_bar
                if not ok:
                    continue
                used[1] = sh_bar
                leg = slice(int(sh_bar), i + 1)
                lo_bar = int(sh_bar) + int(np.argmin(l[leg]))
                ext = l[lo_bar]
                refs = [v for b, v in sl_hist if b < sh_bar]
                liq = refs[-1] if refs else np.nan
                if p["use_session_liq"]:
                    for lv in (feat.pdl[i], feat.onl[i], feat.asia_l[i], feat.london_l[i]):
                        if not math.isnan(lv) and lv > ext and (math.isnan(liq) or lv > liq):
                            liq = lv if l[int(sh_bar):lo_bar + 1].min() < lv else liq
                if math.isnan(liq) or not ext < liq:
                    continue
            else:
                ok = not math.isnan(psl) and sl > psl and c[i] < sl and used[-1] != sl_bar
                if not ok:
                    continue
                used[-1] = sl_bar
                leg = slice(int(sl_bar), i + 1)
                lo_bar = int(sl_bar) + int(np.argmax(h[leg]))
                ext = h[lo_bar]
                refs = [v for b, v in sh_hist if b < sl_bar]
                liq = refs[-1] if refs else np.nan
                if p["use_session_liq"]:
                    for lv in (feat.pdh[i], feat.onh[i], feat.asia_h[i], feat.london_h[i]):
                        if not math.isnan(lv) and lv < ext and (math.isnan(liq) or lv < liq):
                            liq = lv if h[int(sl_bar):lo_bar + 1].max() > lv else liq
                if math.isnan(liq) or not ext > liq:
                    continue
            # 4: most recent FVG in the MSS leg (already formed), else wait
            g = None
            for k in range(i, lo_bar + 1, -1):
                g = gap(k, side)
                if g:
                    armed.append(dict(side=side, bot=g[0], top=g[1], born=i, extreme=ext))
                    break
            if not g:
                pending.append(dict(side=side, mss=i, extreme=ext))

        keep = []
        for pd_ in pending:
            if pd_["mss"] == i:
                keep.append(pd_)
                continue
            g = gap(i, pd_["side"])
            if g:
                armed.append(dict(side=pd_["side"], bot=g[0], top=g[1], born=i, extreme=pd_["extreme"]))
            elif i - pd_["mss"] < p["fvg_after"]:
                keep.append(pd_)
        pending = keep

        # 5-7: respect -> market entry next bar
        keep = []
        for z in armed:
            if z["born"] == i:
                keep.append(z)
                continue
            side, bot, top = z["side"], z["bot"], z["top"]
            if i - z["born"] > p["expiry"]:
                continue
            if (side > 0 and c[i] < bot) or (side < 0 and c[i] > top):
                continue  # FVG not respected: closed through it
            touched = (l[i] <= top) if side > 0 else (h[i] >= bot)
            if p["respect"] == "strict":
                held = (c[i] > top) if side > 0 else (c[i] < bot)
            else:
                held = (c[i] >= bot) if side > 0 else (c[i] <= top)
            if touched and held:
                if win[i]:
                    if p["stop_mode"] == "fvg":
                        stop = bot - p["stop_ticks"] * tick if side > 0 else top + p["stop_ticks"] * tick
                    else:
                        stop = z["extreme"] - 2 * tick if side > 0 else z["extreme"] + 2 * tick
                    out.append(Setup(i, side, "market", 0.0, stop, rr=p["rr"], expiry=1,
                                     note=f"MSS+sweep, FVG {bot:.2f}-{top:.2f} respected"))
                continue  # one entry per FVG
            keep.append(z)
        armed = keep
    return out


def backtest(df, symbol, p: dict | None = None):
    p = {**DEFAULTS, **(p or {})}
    inst = get_instrument(symbol)
    feat = features.build(df, inst.tick)
    cfg = EngineConfig(flatten=p["flatten"], max_trades_per_day=p["max_trades"], intrabar="path")
    return feat, engine.run(feat, generate(feat, inst, p), inst, cfg)

"""Strategies on LuxAlgo "Liquidity Swings" zones.

Liquidity Swings [LuxAlgo] (CC BY-NC-SA 4.0, © LuxAlgo), re-implemented:
  * pivot high/low with `length` bars each side (known `length` bars later);
  * the zone of a pivot high runs from its high down to max(open, close) of
    that bar ("Wick Extremity") or to its low ("Full Range"); lows mirrored;
  * only the latest pivot-high zone and the latest pivot-low zone are live;
  * count = bars whose range overlaps the zone, counted with the indicator's
    `length`-bar lag; the zone is shown when count > filter;
  * "crossed" once a bar closes beyond the zone's outer level.

Entries (shown for the swing-high zone; the swing-low zone mirrors):
  sweep   — before the zone is crossed, a bar trades above the swing high and
            closes back below it (liquidity grab) -> short at the next open,
            stop above that bar's high.
  reject  — a bar trades into the zone without closing above the high and
            closes back below the zone bottom -> short, stop above the zone.
  retest  — after the zone was crossed (close above the high), price comes
            back to the high and closes above it -> long (old resistance holds
            as support), stop below the zone bottom.
Target rr × risk. Sessions, max trades per Globex day and the 15:55 flatten
come from the shared engine. One entry per zone.
"""

from __future__ import annotations

import numpy as np

from . import engine, features
from .data import get_instrument
from .engine import EngineConfig, Setup
from .features import hm

WINDOW_PRESETS = {
    "all": (("20:00", "24:00"), ("00:00", "15:30")),
    "asia_london": (("20:00", "24:00"), ("02:00", "05:00")),
    "london_ny": (("02:00", "12:00"),),
    "ny_am": (("08:30", "12:00"),),
}

DEFAULTS = dict(length=14, area="wick", min_count=0, mode="sweep", rr=2.0, buffer_ticks=2,
                ema_len=0, windows="all", flatten="15:55", max_trades=1)


# MNQ 15m preset (chosen on in-sample data, see results/liq_swings/REPORT.md)
PRESET_MNQ15 = dict(mode="retest", length=5, area="full", min_count=0, ema_len=0, windows="london_ny",
                    rr=2.0, max_trades=1)


def zones(feat, length=14, area="wick"):
    """Per bar: live (top, btm, count, crossed, id) for the swing-high zone and
    the swing-low zone, exactly as the indicator holds them after bar i."""
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    n, L = feat.n, length
    hz = np.full((n, 5), np.nan)
    lz = np.full((n, 5), np.nan)
    ph_top = ph_btm = pl_top = pl_btm = np.nan
    ph_cnt = pl_cnt = 0
    ph_x = pl_x = ph_id = pl_id = -1
    ph_cr = pl_cr = False
    for i in range(n):
        k = i - L
        is_ph = k - L >= 0 and h[k] > h[k - L:k].max() and h[k] >= h[k + 1:i + 1].max()
        is_pl = k - L >= 0 and l[k] < l[k - L:k].min() and l[k] <= l[k + 1:i + 1].min()
        # counts (indicator: reset on the pivot bar, else add the bar `length` back)
        if is_ph:
            ph_cnt = 0
        elif k >= 0 and not np.isnan(ph_top):
            ph_cnt += int(l[k] < ph_top and h[k] > ph_btm)
        if is_pl:
            pl_cnt = 0
        elif k >= 0 and not np.isnan(pl_top):
            pl_cnt += int(l[k] < pl_top and h[k] > pl_btm)
        if is_ph:
            ph_top = h[k]
            ph_btm = max(c[k], o[k]) if area == "wick" else l[k]
            ph_x, ph_id, ph_cr = k, k, False
        elif not np.isnan(ph_top):
            ph_cr = ph_cr or c[i] > ph_top
        if is_pl:
            pl_top = min(c[k], o[k]) if area == "wick" else h[k]
            pl_btm = l[k]
            pl_x, pl_id, pl_cr = k, k, False
        elif not np.isnan(pl_btm):
            pl_cr = pl_cr or c[i] < pl_btm
        hz[i] = (ph_top, ph_btm, ph_cnt, ph_cr, ph_id)
        lz[i] = (pl_top, pl_btm, pl_cnt, pl_cr, pl_id)
    return hz, lz


def generate(feat, inst, p: dict | None = None) -> list[Setup]:
    p = {**DEFAULTS, **(p or {})}
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    n = feat.n
    buf = p["buffer_ticks"] * inst.tick
    hz, lz = zones(feat, p["length"], p["area"])
    win = np.zeros(n, bool)
    wins = WINDOW_PRESETS[p["windows"]] if isinstance(p["windows"], str) else p["windows"]
    for s_, e_ in wins:
        win |= (feat.mod >= hm(s_)) & (feat.mod < hm(e_))
    trend = None
    if p["ema_len"]:
        e = features.ema(c, p["ema_len"])
        trend = np.zeros(n)
        trend[3:] = np.sign(e[3:] - e[:-3])
    used = set()
    out = []
    mode = p["mode"]
    for i in range(1, n):
        cands = []
        for z, d in ((hz, 1), (lz, -1)):        # d = +1 swing-high zone, -1 swing-low zone
            top, btm, cnt, cr, zid = z[i]
            if np.isnan(top) or cnt < p["min_count"] or (d, zid) in used or zid < 0:
                continue
            was_cr = bool(z[i - 1][3]) and z[i - 1][4] == zid
            lvl = top if d > 0 else btm          # outer liquidity level
            inner = btm if d > 0 else top
            if mode == "sweep" and not was_cr:
                if (d > 0 and h[i] > lvl and c[i] < lvl) or (d < 0 and l[i] < lvl and c[i] > lvl):
                    side = -d
                    stop = h[i] + buf if d > 0 else l[i] - buf
                    cands.append((side, stop, (d, zid), f"LS sweep {lvl:.2f} cnt {int(cnt)}"))
            elif mode == "reject" and not was_cr:
                into = (h[i] >= inner) if d > 0 else (l[i] <= inner)
                held = (c[i] < inner) if d > 0 else (c[i] > inner)
                inside_only = (h[i] <= lvl) if d > 0 else (l[i] >= lvl)
                if into and held and inside_only:
                    side = -d
                    stop = lvl + buf if d > 0 else lvl - buf
                    cands.append((side, stop, (d, zid), f"LS reject zone cnt {int(cnt)}"))
            elif mode == "retest" and was_cr:
                if (d > 0 and l[i] <= lvl and c[i] > lvl) or (d < 0 and h[i] >= lvl and c[i] < lvl):
                    side = d
                    stop = inner - buf if d > 0 else inner + buf
                    stop = min(stop, l[i] - buf) if d > 0 else max(stop, h[i] + buf)
                    cands.append((side, stop, (d, zid), f"LS break-retest {lvl:.2f}"))
        for side, stop, key, note in cands:
            used.add(key)
            if not win[i] or (trend is not None and trend[i] != side):
                continue
            out.append(Setup(i, side, "market", 0.0, inst.round_price(stop), rr=p["rr"], expiry=1, note=note))
    return out


def backtest(df, symbol, p: dict | None = None):
    p = {**DEFAULTS, **(p or {})}
    inst = get_instrument(symbol)
    feat = features.build(df, inst.tick)
    cfg = EngineConfig(flatten=p["flatten"], max_trades_per_day=p["max_trades"], intrabar="path")
    return feat, engine.run(feat, generate(feat, inst, p), inst, cfg)

"""wr60 / meanrev: non-ICT mean-reversion families on MNQ (Dukascopy NQ proxy, 1 year).

Families (all decided on the CLOSE of a bar, entry = market at next bar open):
  vwap  - VWAP sigma-band rejection: bar trades beyond vwap +/- k*sd and closes back inside.
  orf   - opening-range (09:30-09:45) failed breakout: price broke OR high/low after 09:45
          and a bar closes back inside the OR -> fade. Stop beyond the breakout extreme.
  lvl   - prior-day high/low and overnight high/low rejection: wick through the level,
          close back on the other side. First test of each level per day.
  rsi   - RSI(2) extreme + close outside Bollinger(20, 2) inside RTH.

Stops: beyond the signal extreme (orf: breakout extreme) + buf*ATR.
Targets: fixed rr (0.75 - 1.5R) or "mean" (VWAP; for rsi the BB mid) with rr clipped to [rr_min, 3].

Protocol: IS = entry < 2026-04-01 (all choices), OOS = entry >= 2026-04-01 (reported untouched).

Run:  PYTHONPATH=. python -m lab.wr60_meanrev [grid|best|check]
"""

from __future__ import annotations

import itertools
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

DEFAULTS = dict(family="vwap", k=2.0, win=("10:00", "15:00"), buf=0.1, rr=1.0, target="rr",
                rr_min=0.5, rsi_lo=10.0, side=0, max_trades=1)


# ------------------------------------------------------------- indicators
def rsi(c, n=2):
    d = np.diff(c, prepend=c[0])
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au, ad = np.zeros_like(c), np.zeros_like(c)
    a = 1.0 / n
    for i in range(1, len(c)):
        au[i] = au[i - 1] + a * (up[i] - au[i - 1])
        ad[i] = ad[i - 1] + a * (dn[i] - ad[i - 1])
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(ad > 0, au / ad, np.inf)
    return 100 - 100 / (1 + rs)


def boll(c, n=20, k=2.0):
    s = pd.Series(c)
    m = s.rolling(n, min_periods=n).mean().to_numpy()
    sd = s.rolling(n, min_periods=n).std(ddof=0).to_numpy()
    return m, m + k * sd, m - k * sd


# ------------------------------------------------------------- generator
def generate(feat, inst, params=None):
    p = {**DEFAULTS, **(params or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n = feat.n
    w0, w1 = hm(p["win"][0]), hm(p["win"][1])
    inwin = (feat.mod >= w0) & (feat.mod < w1)
    fam, buf, rr = p["family"], p["buf"], p["rr"]
    out: list[Setup] = []

    def add(i, side, stop, mean=None, note=""):
        if p["side"] and side != p["side"]:
            return
        r = rr
        if p["target"] == "mean":
            if mean is None or not np.isfinite(mean):
                return
            risk = (c[i] - stop) * side
            if risk <= 0:
                return
            r = (mean - c[i]) * side / risk
            if r < p["rr_min"]:
                return
            r = min(r, 3.0)
        out.append(Setup(bar=i, side=side, entry_type="market", entry=c[i], stop=inst.round_price(stop),
                         rr=float(r), expiry=1, note=note))

    if fam == "vwap":
        k = p["k"]
        for i in range(1, n):
            if not inwin[i] or not np.isfinite(feat.vwap[i]) or feat.vwap_sd[i] <= 0:
                continue
            up = feat.vwap[i] + k * feat.vwap_sd[i]
            dn = feat.vwap[i] - k * feat.vwap_sd[i]
            if h[i] >= up and c[i] < up:
                add(i, -1, h[i] + buf * a[i], feat.vwap[i], "vwap-short")
            elif l[i] <= dn and c[i] > dn:
                add(i, +1, l[i] - buf * a[i], feat.vwap[i], "vwap-long")

    elif fam == "orf":
        hi_ext = lo_ext = None   # breakout extremes since 09:45 of this day
        used_s = used_l = False
        for i in range(1, n):
            if feat.day[i] != feat.day[i - 1]:
                hi_ext = lo_ext = None
                used_s = used_l = False
            if not np.isfinite(feat.or_h[i]) or feat.mod[i] < hm("09:45") or feat.mod[i] >= hm("16:00"):
                continue
            orh, orl = feat.or_h[i], feat.or_l[i]
            if h[i] > orh:
                hi_ext = max(hi_ext or -np.inf, h[i])
            if l[i] < orl:
                lo_ext = min(lo_ext or np.inf, l[i])
            if not inwin[i]:
                continue
            if hi_ext is not None and not used_s and c[i] < orh and c[i] > orl:
                used_s = True
                add(i, -1, hi_ext + buf * a[i], feat.vwap[i], "orf-short")
            elif lo_ext is not None and not used_l and c[i] > orl and c[i] < orh:
                used_l = True
                add(i, +1, lo_ext - buf * a[i], feat.vwap[i], "orf-long")

    elif fam == "lvl":
        levels = p.get("levels", ("pd", "on"))
        used = set()
        for i in range(1, n):
            if feat.day[i] != feat.day[i - 1]:
                used = set()
            if not inwin[i]:
                continue
            cands = []
            if "pd" in levels:
                cands += [("pdh", feat.pdh[i], -1), ("pdl", feat.pdl[i], +1)]
            if "on" in levels:
                cands += [("onh", feat.onh[i], -1), ("onl", feat.onl[i], +1)]
            for name, L, side in cands:
                if not np.isfinite(L) or name in used:
                    continue
                if side < 0 and h[i] > L:
                    used.add(name)
                    if c[i] < L and o[i] < L + 0.0:
                        add(i, -1, h[i] + buf * a[i], feat.vwap[i], name)
                        break
                elif side > 0 and l[i] < L:
                    used.add(name)
                    if c[i] > L and o[i] > L:
                        add(i, +1, l[i] - buf * a[i], feat.vwap[i], name)
                        break

    elif fam == "rsi":
        r2 = rsi(c, 2)
        mid, bu, bl = boll(c, 20, p["k"])
        lo_th, hi_th = p["rsi_lo"], 100 - p["rsi_lo"]
        for i in range(1, n):
            if not inwin[i] or not np.isfinite(mid[i]):
                continue
            if r2[i] < lo_th and c[i] < bl[i]:
                add(i, +1, l[i] - buf * a[i], mid[i], "rsi-long")
            elif r2[i] > hi_th and c[i] > bu[i]:
                add(i, -1, h[i] + buf * a[i], mid[i], "rsi-short")
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
    return f"n={s['trades']:3d} WR={s['wr']*100:4.1f}% exp={s['exp']:+.3f}R PF={s['pf']:.2f} net=${s['net']:8.0f} dd=${s['dd']:6.0f}"


def grid_configs():
    """Modest, pre-declared grid (~360 configs)."""
    cfgs = []
    wins = [("09:45", "15:30"), ("10:00", "14:00")]
    for tf in ("15min", "5min"):
        for k in (1.5, 2.0, 2.5):
            for w in wins:
                for tgt, rr in (("rr", 0.75), ("rr", 1.0), ("rr", 1.5), ("mean", None)):
                    for buf in (0.1, 0.5):
                        cfgs.append(dict(tf=tf, family="vwap", k=k, win=w, target=tgt, rr=rr or 1.0, buf=buf))
        for w in (("09:45", "11:30"), ("09:45", "15:00")):
            for tgt, rr in (("rr", 0.75), ("rr", 1.0), ("rr", 1.5), ("mean", None)):
                for buf in (0.1, 0.5):
                    for mt in (1, 2):
                        cfgs.append(dict(tf=tf, family="orf", win=w, target=tgt, rr=rr or 1.0, buf=buf, max_trades=mt))
        for lv in (("pd",), ("on",), ("pd", "on")):
            for w in (("09:30", "15:30"), ("09:45", "12:00")):
                for tgt, rr in (("rr", 0.75), ("rr", 1.0), ("rr", 1.5), ("mean", None)):
                    for buf in (0.1, 0.5):
                        cfgs.append(dict(tf=tf, family="lvl", levels=lv, win=w, target=tgt, rr=rr or 1.0, buf=buf))
        for th in (5.0, 10.0):
            for k in (2.0, 2.5):
                for tgt, rr in (("rr", 0.75), ("rr", 1.0), ("rr", 1.5), ("mean", None)):
                    for buf in (0.1, 0.5):
                        cfgs.append(dict(tf=tf, family="rsi", rsi_lo=th, k=k, win=("10:00", "15:30"),
                                         target=tgt, rr=rr or 1.0, buf=buf))
    return cfgs


def is_score(e):
    s = e["is_"]
    if s["trades"] < 45 or s["pf"] < 1.1:
        return -9.0
    # want WR near 60% AND positive expectancy: Wilson-ish lower bound of WR plus expectancy
    lb = s["wr"] - math.sqrt(s["wr"] * (1 - s["wr"]) / s["trades"])
    return lb + 0.5 * s["exp"]


def grid(log=print):
    cfgs = grid_configs()
    log(f"configs: {len(cfgs)}")
    feats = {}
    res = []
    for j, c in enumerate(cfgs):
        tf = c["tf"]
        if tf not in feats:
            feats[tf] = load(tf)
        feat, inst = feats[tf]
        p = {k: v for k, v in c.items() if k != "tf"}
        e, _ = evaluate(feat, inst, p)
        res.append(dict(cfg=c, **e))
        if j % 25 == 0:
            log(f"{j} {c} IS {fmt(e['is_'])}")
    return res


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "grid"
    OUT.mkdir(parents=True, exist_ok=True)
    if mode == "grid":
        res = grid()
        for r in res:
            r["score"] = is_score(r)
        res.sort(key=lambda r: -r["score"])
        for r in res[:30]:
            print(r["cfg"], "\n   IS ", fmt(r["is_"]), "\n   OOS", fmt(r["oos"]), " pos", r["pos_months"], "/", r["n_months"])
        (OUT / "meanrev_grid.json").write_text(json.dumps(res, default=lambda x: x.item() if hasattr(x, "item") else list(x), indent=0))
    elif mode == "check":
        truncation_check()


def truncation_check():
    m1 = pd.read_pickle(DUKA)
    df = data.resample(m1, "15min")
    inst = data.get_instrument("MNQ")
    full = features.build(df, inst.tick)
    for fam in ("vwap", "orf", "lvl", "rsi"):
        p = dict(family=fam, target="mean", k=2.0)
        a = {(s.bar, s.side, s.stop, round(s.rr, 6)) for s in generate(full, inst, p)}
        for k in (9000, 17777, 24001):
            tr = features.build(df.iloc[:k], inst.tick)
            b = {(s.bar, s.side, s.stop, round(s.rr, 6)) for s in generate(tr, inst, p)}
            aa = {x for x in a if x[0] < k - 1}
            bb = {x for x in b if x[0] < k - 1}
            assert aa == bb, (fam, k, len(aa ^ bb))
        print("truncation ok", fam, len(a))


if __name__ == "__main__":
    main()

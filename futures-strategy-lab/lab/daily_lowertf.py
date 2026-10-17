"""Daily direction "lowertf": lower execution timeframe (5m / 10m) + higher-TF context.

Goal: ~1 trade per trading day (>= 0.8/day) with WR >= 58 % in IS and OOS.

Entry (one "component" = market x window x exec TF x context x min FVG x time stop):
  * the unchanged FVG Pro setup (lab/fvg_pro.generate: BOS + FVG, limit at the gap edge, stop beyond
    the BOS leg) on the 5m or 10m execution chart, max 1 trade per component per day,
  * "don't chase": skip when side*(close-entry)/ATR > 1.0 at the signal bar,
  * a context filter computed on COMPLETED higher-TF bars only (an HTF bar starting at T with length H is
    usable by an exec bar starting at s with length e only when T + H <= s + e):
      none     no filter
      bos15    side == direction of the last 15m break of structure (close beyond the last
               confirmed pivot-3 swing; the state flips at each break)
      bos60    same on 1h bars
      ema60    side == sign of the slope of a 20-period EMA on completed 1h bars (vs. 1 bar earlier)
      bos15+ema60  both
  * exit (fixed): half at 1R -> stop to BE -> runner 3R; time stop `ts` exec bars; flat 15:55 / new day.

Simulator: lab.daily_exits.simulate (TradingView path model, plus "worst" intrabar, 1m replay, slip ticks).
Daily rule of the portfolio: the first FILLED trade per market per Globex day (max 1 MNQ + 1 MGC).

Protocol: IS = entry < 2026-04-01, OOS = entry >= 2026-04-01; selection on IS only.

Run:  PYTHONPATH=. python -m lab.daily_lowertf grid     (component grid -> results/daily/lowertf_grid.json)
      PYTHONPATH=. python -m lab.daily_lowertf final    (IS selection, portfolio, robustness, shifts)
      PYTHONPATH=. python -m lab.daily_lowertf trunc    (truncation check of the new context code)
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import daily_exits as X
from . import daily_portfolio as D
from . import features, fvg_pro

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "daily"
CUT = D.CUT
EXIT = dict(tp1=1.0, frac1=0.5, tp=3.0, after=0.0)
EXITS = {  # "ex" field of a component (default p10 = the fixed partial exit)
    "p10": dict(tp1=1.0, frac1=0.5, tp=3.0, after=0.0),
    "p075": dict(tp1=0.75, frac1=0.5, tp=2.0, after=0.0),
    "p05": dict(tp1=0.5, frac1=0.5, tp=2.0, after=0.0),
    "p05x3": dict(tp1=0.5, frac1=2 / 3, tp=2.0, after=0.0),   # 3 contracts, 2 exit at 0.5R
}

WINDOWS = {
    "london": (("02:00", "05:00"),),
    "ny_am": (("08:30", "11:00"),),
    "comex": (("08:20", "10:30"),),
    "lon+nyam": (("02:00", "05:00"), ("08:30", "11:00")),
    "lon+comex": (("02:00", "05:00"), ("08:20", "10:30")),
}
MARKET_WINDOWS = {"MNQ": ("london", "ny_am"), "MGC": ("london", "comex")}
CTXS = ("none", "bos15", "bos60", "ema60", "bos15+ema60")

_C: dict = {}


# ----------------------------------------------------------------- bars

def bars(sym, tf, shift=0):
    """Resample the 1m data to `tf` minutes, bar starts shifted by `shift` minutes."""
    k = ("bars", sym, tf, shift)
    if k not in _C:
        m1 = D.m1(sym)
        out = m1.resample(f"{tf}min", label="left", closed="left", offset=f"{shift}min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        _C[k] = out.dropna(subset=["open"])
    return _C[k]


def feat(sym, tf, shift=0):
    k = ("feat", sym, tf, shift)
    if k not in _C:
        _C[k] = features.build(bars(sym, tf, shift), D.inst_of(sym).tick)
    return _C[k]


# ----------------------------------------------------------------- HTF context (causal)

def bos_state(f, L=3):
    """+1 / -1 = direction of the last close beyond the last confirmed swing (known at bar close)."""
    lsh, lsl = fvg_pro._confirmed_swings(f.h, f.l, L)
    st = np.zeros(f.n)
    cur = 0.0
    for i in range(f.n):
        if not math.isnan(lsh[i]) and f.c[i] > lsh[i]:
            cur = 1.0
        elif not math.isnan(lsl[i]) and f.c[i] < lsl[i]:
            cur = -1.0
        st[i] = cur
    return st


def ema_slope(f, period=20):
    e = features.ema(f.c, period)
    s = np.zeros(f.n)
    s[1:] = np.sign(e[1:] - e[:-1])
    return s


def map_htf(htf_df, htf_min, vals, exec_df, exec_min):
    """Value of the last HTF bar COMPLETED by the close of each exec bar (0 if none)."""
    htf_close = (htf_df.index + pd.Timedelta(minutes=htf_min)).asi8
    exec_close = (exec_df.index + pd.Timedelta(minutes=exec_min)).asi8
    j = np.searchsorted(htf_close, exec_close, side="right") - 1
    out = np.where(j >= 0, vals[np.clip(j, 0, None)], 0.0)
    return out


def fvg15_state(sym, shift, hold=8, mf=0.3):
    """Side of the latest 15m FVG Pro setup (any time of day, min FVG mf, chase 1.0) decided at a completed
    15m bar within the last `hold` 15m bars; 0 otherwise."""
    fh = feat(sym, 15, shift % 15)
    p = dict(windows=(("00:00", "24:00"),), min_fvg_atr=mf, entry="edge")
    st = np.zeros(fh.n)
    for s in fvg_pro.generate(fh, D.inst_of(sym), p):
        if fh.atr[s.bar] > 0 and s.side * (fh.c[s.bar] - s.entry) / fh.atr[s.bar] > 1.0:
            continue
        st[s.bar:s.bar + hold] = s.side
    return fh, st


def context(sym, tf, ctx, shift=0):
    k = ("ctx", sym, tf, ctx, shift)
    if k in _C:
        return _C[k]
    ex = bars(sym, tf, shift)
    if ctx == "none":
        v = np.ones(len(ex)) * 2  # sentinel: allow both sides
    else:
        parts = []
        for c in ctx.split("+"):
            if c == "fvg15":
                fh, raw = fvg15_state(sym, shift)
                parts.append(map_htf(fh.df, 15, raw, ex, tf))
                continue
            htf = 15 if c.endswith("15") else 60
            fh = feat(sym, htf, shift % htf)
            raw = bos_state(fh) if c.startswith("bos") else ema_slope(fh)
            parts.append(map_htf(fh.df, htf, raw, ex, tf))
        v = parts[0] if len(parts) == 1 else np.where(parts[0] == parts[1], parts[0], 0.0)
    _C[k] = v
    return v


# ----------------------------------------------------------------- components

def comp_key(c):
    return (f"{c['sym']}|{c['tf']}m|{c['win']}|{c['ctx']}|mf{c['mf']}|ts{c['ts']}|ch{c.get('chase', 1.0)}"
            + (f"|{c['ex']}" if c.get("ex", "p10") != "p10" else ""))


def setups(c, shift=0):
    f, inst = feat(c["sym"], c["tf"], shift), D.inst_of(c["sym"])
    p = dict(windows=WINDOWS[c["win"]], min_fvg_atr=c["mf"], max_trades=1, entry="edge")
    k = ("gen", c["sym"], c["tf"], c["win"], c["mf"], shift)
    if k not in _C:
        _C[k] = fvg_pro.generate(f, inst, p)
    ss = _C[k]
    ch = c.get("chase", 1.0)
    if ch:
        ss = [s for s in ss if not (f.atr[s.bar] > 0 and s.side * (f.c[s.bar] - s.entry) / f.atr[s.bar] > ch)]
    cx = context(c["sym"], c["tf"], c["ctx"], shift)
    return [s for s in ss if cx[s.bar] == 2 or cx[s.bar] * s.side > 0]


def run(c, shift=0, slip_ticks=1, intrabar="path", m1replay=False):
    f = feat(c["sym"], c["tf"], shift)
    mg = dict(EXITS[c.get("ex", "p10")], tstop=c["ts"])
    tr = X.simulate(f, setups(c, shift), X.inst_for(c["sym"], mg["frac1"]), mg, slip_ticks=slip_ticks, intrabar=intrabar,
                    m1df=D.m1(c["sym"]) if m1replay else None)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = comp_key(c), c["sym"], pd.Timestamp(t["entry_time"])
    return tr


def ndays():
    if "nd" not in _C:
        _C["nd"] = D.trading_days()
    return _C["nd"]


def summary(tr):
    n_all, n_is, n_oos = ndays()
    a, b = D.split(tr)
    mo = D.months(tr)
    return dict(full=D.stats(tr, n_all), is_=D.stats(a, n_is), oos=D.stats(b, n_oos), months=mo,
                pos_months=int(sum(v > 0 for v in mo.values())), n_months=len(mo),
                is_pos_months=int(sum(v > 0 for k, v in mo.items() if k < CUT[:7])))


def grid_comps():
    out = []
    for sym, wins in MARKET_WINDOWS.items():
        for win, tf, ctx, mf in itertools.product(wins, (5, 10), CTXS, (0.15, 0.3)):
            for ts in ((8, 24) if tf == 5 else (8, 12)):   # 8 bars, or ~2 h (as 8 bars of 15m)
                out.append(dict(sym=sym, tf=tf, win=win, ctx=ctx, mf=mf, ts=ts, chase=1.0))
    return out


def grid2_comps():
    """Stage 2: quicker partial exits, single-window and two-window components, ts ~2 h."""
    out = []
    wins = {"MNQ": ("london", "ny_am", "lon+nyam"), "MGC": ("london", "comex", "lon+comex")}
    for sym in ("MNQ", "MGC"):
        for win, tf, ctx, mf, ex in itertools.product(wins[sym], (5, 10), ("none", "bos15", "ema60", "bos15+ema60"),
                                                       (0.15, 0.3), ("p05", "p05x3")):
            out.append(dict(sym=sym, tf=tf, win=win, ctx=ctx, mf=mf, ts=24 if tf == 5 else 12, chase=1.0, ex=ex))
    return out


def grid2(log=print):
    rows = []
    for c in grid2_comps():
        r = summary(run(c))
        rows.append(dict(**c, key=comp_key(c), **{k: r[k] for k in ("full", "is_", "oos", "pos_months", "is_pos_months")}))
        log(f"{comp_key(c):50s} IS {fmt(r['is_'])} | OOS {fmt(r['oos'])}")
    D.jdump(OUT / "lowertf_grid2.json", rows)
    return rows


def grid3_comps():
    """Stage 3: context = a 15m FVG Pro setup (BOS + FVG) in the same direction in the last 2 h."""
    out = []
    for sym, wins in MARKET_WINDOWS.items():
        for win, tf, mf, ex in itertools.product(wins, (5, 10), (0.15, 0.3), ("p10", "p05")):
            out.append(dict(sym=sym, tf=tf, win=win, ctx="fvg15", mf=mf, ts=24 if tf == 5 else 12, chase=1.0, ex=ex))
    return out


def grid3(log=print):
    rows = []
    for c in grid3_comps():
        r = summary(run(c))
        rows.append(dict(**c, key=comp_key(c), **{k: r[k] for k in ("full", "is_", "oos", "pos_months", "is_pos_months")}))
        log(f"{comp_key(c):50s} IS {fmt(r['is_'])} | OOS {fmt(r['oos'])}")
    D.jdump(OUT / "lowertf_grid3.json", rows)
    return rows


def fmt(s):
    return D.fmt(s) + (f" {s['tpd']:.2f}/d" if s.get("tpd") is not None else "")


def grid(log=print):
    rows = []
    t0 = time.time()
    for c in grid_comps():
        tr = run(c)
        r = summary(tr)
        rows.append(dict(**c, key=comp_key(c), **{k: r[k] for k in ("full", "is_", "oos", "pos_months", "is_pos_months")}))
        log(f"{comp_key(c):42s} IS {fmt(r['is_'])} | OOS {fmt(r['oos'])}  [{time.time() - t0:.0f}s]")
    D.jdump(OUT / "lowertf_grid.json", rows)
    return rows


# ----------------------------------------------------------------- selection (IS only)

def load_rows(name):
    rows = json.loads((OUT / name).read_text())
    for r in rows:
        r["pos_months"], r["is_pos_months"] = int(r["pos_months"]), int(r["is_pos_months"])
    return rows


def is_score(r):
    """IS rule written down before looking at OOS: >= 30 IS trades, IS WR >= 60 %, IS PF >= 1.3,
    >= 5/7 IS months positive; rank by IS WR x min(PF, 3) x sqrt(IS trades/day)."""
    s = r["is_"]
    if s["trades"] < 30 or s["wr"] < 0.60 or s["pf"] < 1.3 or r["is_pos_months"] < 5:
        return None
    return s["wr"] * min(s["pf"], 3.0) * math.sqrt(s["tpd"])


def select(rows):
    best = {}
    for r in rows:
        sc = is_score(r)
        if sc is None:
            continue
        k = (r["sym"], r["win"])
        if k not in best or sc > best[k][0]:
            best[k] = (sc, r)
    return [v[1] for v in best.values()]


def strip(r):
    return {k: r[k] for k in ("sym", "tf", "win", "ctx", "mf", "ts", "chase", "ex") if k in r}


def portfolio(comps, shift=0, **kw):
    trs = [run(c, shift=shift, **kw) for c in comps]
    order = [comp_key(c) for c in comps]
    tr = D.combine(trs, rule="per_market", order=order)
    return tr, summary(tr)


def line(r):
    return (f"IS {fmt(r['is_'])} | OOS {fmt(r['oos'])} | year {fmt(r['full'])} | +m {r['pos_months']}/{r['n_months']}")


def passes(r):
    return (r["full"]["tpd"] >= 0.8 and r["is_"]["wr"] >= 0.58 and r["oos"]["wr"] >= 0.58
            and r["is_"]["pf"] >= 1.3 and r["oos"]["pf"] >= 1.3 and r["pos_months"] >= 10)


def final(log=print):
    rows = [r for f in ("lowertf_grid.json", "lowertf_grid2.json", "lowertf_grid3.json") for r in load_rows(f)]
    picks = sorted(select(rows), key=lambda r: (r["sym"], r["win"]))
    log(f"eligible components: {sum(is_score(r) is not None for r in rows)} / {len(rows)}")
    for r in picks:
        log(f"PICK {r['key']:42s} IS {fmt(r['is_'])} | OOS {fmt(r['oos'])}")
    comps = [strip(r) for r in picks]
    res = {"picks": comps}
    tr, rep = portfolio(comps)
    log("PORTFOLIO base   " + line(rep))
    res["base"] = rep
    res["monthly"] = rep["months"]
    res["passes_base"] = passes(rep)
    for name, kw in (("worst+2t", dict(intrabar="worst", slip_ticks=2)),
                     ("conservative+2t", dict(intrabar="conservative", slip_ticks=2)),
                     ("m1replay+2t", dict(m1replay=True, slip_ticks=2))):
        _, r2 = portfolio(comps, **kw)
        res[name] = r2
        log(f"PORTFOLIO {name:15s} " + line(r2) + f"  pass={passes(r2)}")
    for sh in (1, 2, 3, 4):
        _, r2 = portfolio(comps, shift=sh)
        res[f"shift{sh}"] = r2
        log(f"PORTFOLIO shift {sh}m       " + line(r2) + f"  pass={passes(r2)}")
    # neighbours, one change at a time per component
    neigh = []
    for i, c in enumerate(comps):
        for field, alts in (("mf", (0.15, 0.3)), ("ts", (8, 12, 16, 24)), ("ctx", CTXS), ("ex", tuple(EXITS)), ("tf", (5, 10)),
                            ("chase", (0.0, 1.0))):
            for v in alts:
                if v == c.get(field, "p10" if field == "ex" else None):
                    continue
                cc = [dict(x) for x in comps]
                cc[i][field] = v
                _, r2 = portfolio(cc)
                neigh.append(dict(comp=i, field=field, value=v, rep=r2))
                log(f"NEIGH {comp_key(c)} {field}={v}: " + line(r2))
    res["neighbours"] = neigh
    D.jdump(OUT / "lowertf_final.json", res)
    return res


def evaluate(comps, log=print, tag=""):
    """Full robustness for an explicit list of components."""
    out = {}
    _, rep = portfolio(comps)
    out["base"] = rep
    log(f"{tag} base " + line(rep) + f" pass={passes(rep)}")
    for name, kw in (("worst+2t", dict(intrabar="worst", slip_ticks=2)),
                     ("m1replay+2t", dict(m1replay=True, slip_ticks=2))):
        _, r2 = portfolio(comps, **kw)
        out[name] = r2
        log(f"{tag} {name} " + line(r2) + f" pass={passes(r2)}")
    for sh in (1, 2, 3, 4):
        _, r2 = portfolio(comps, shift=sh)
        out[f"shift{sh}"] = r2
        log(f"{tag} shift{sh} " + line(r2) + f" pass={passes(r2)}")
    return out


# ----------------------------------------------------------------- truncation check

def truncation_check():
    """Context + setups on the first k minutes of data must equal those on the full data (for bars < k-1)."""
    for sym, win, tf, ctx in (("MNQ", "london", 5, "bos15+ema60"), ("MGC", "comex", 10, "bos60"),
                              ("MNQ", "ny_am", 10, "ema60")):
        c = dict(sym=sym, tf=tf, win=win, ctx=ctx, mf=0.15, ts=8, chase=1.0)
        full = [(s.bar, s.side, s.entry, s.stop) for s in setups(c)]
        m1 = D.m1(sym)
        for frac in (0.3, 0.6, 0.85):
            cut = m1.index[int(len(m1) * frac)]
            saved = dict(_C)
            _C.clear()
            D._CACHE[("m1", sym)] = m1[m1.index < cut]
            part = [(s.bar, s.side, s.entry, s.stop) for s in setups(c)]
            k = len(bars(sym, tf))
            D._CACHE[("m1", sym)] = m1
            _C.clear()
            _C.update(saved)
            a = [x for x in full if x[0] < k - 2]
            b = [x for x in part if x[0] < k - 2]
            assert a == b, (sym, tf, ctx, frac, len(a), len(b))
    print("truncation check OK")
    return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        grid()
    elif cmd == "grid2":
        grid2()
    elif cmd == "grid3":
        grid3()
    elif cmd == "final":
        final()
    elif cmd == "trunc":
        truncation_check()

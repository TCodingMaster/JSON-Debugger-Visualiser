"""WR60 research, direction "exits": trade management on the FVG Pro family.

Entries are the unchanged FVG Pro setups (lab/fvg_pro.generate). Only the
exit side changes. Own bar-by-bar simulator (pending-order logic copied from
lab/engine.py) with a management config:

  tp        final target in R (fixed-target mode: the only target)
  tp1       first target in R (None = off); `frac1` of the size exits there
  be_tp1    after TP1 the stop moves to entry (from the next bar on)
  be_at     move stop to entry once price reaches +be_at R (0 = off; next bar on)
  tstop     time stop: exit at the next bar's open once the trade is N bars old (0 = off)

Execution: every bar is walked with the OHLC path (open -> nearer extreme ->
farther extreme -> close, TradingView's emulator). Stops / BE stops / market
exits pay 1 tick slippage; targets fill at price (or the open on a gap).
Costs: $0.62/side/contract, 2 contracts (partial = 1 contract each leg).
A win is a trade whose net $ (all legs, after costs) is > 0.

Protocol: IS = entry < 2026-04-01, OOS = entry >= 2026-04-01. Settings are
ranked on IS only.

Run:  python -m lab.wr60_exits            (grid + report)
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features, fvg_pro
from .data import get_instrument
from .engine import Setup
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "wr60"
M1 = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/MNQ_1m.pkl"
CUT = "2026-04-01"


def _path(o, h, l, c):
    return [o, l, h, c] if (o - l) <= (h - o) else [o, h, l, c]


def simulate(feat, setups: list[Setup], inst, mg: dict, flatten="15:55", max_trades=1,
             min_risk_ticks=4, max_risk_atr=3.0):
    tp = float(mg.get("tp", 2.0))
    tp1 = mg.get("tp1")
    frac1 = float(mg.get("frac1", 0.5))
    be_tp1 = bool(mg.get("be_tp1", True))
    be_at = float(mg.get("be_at", 0.0))
    tstop = int(mg.get("tstop", 0))

    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    idx = feat.df.index
    n = feat.n
    flat = hm(flatten)
    tick = inst.tick
    slip = tick
    qty = inst.contracts
    pv = inst.point_value
    costs = 2 * inst.commission * qty
    q1 = max(1, int(round(qty * frac1))) if tp1 else 0
    by_bar: dict[int, list[Setup]] = {}
    for s in setups:
        by_bar.setdefault(s.bar, []).append(s)

    def after_flat(i):
        return flat <= feat.mod[i] < 18 * 60

    trades = []
    pending = None
    pend_age = 0
    pos = None
    day_count: dict[int, int] = {}

    def finish(i, reason):
        nonlocal pos
        p = pos
        pnl = p["pts_qty"] * pv - costs
        risk_usd = p["risk"] * pv * qty
        trades.append(dict(entry_time=idx[p["i0"]].isoformat(), exit_time=idx[i].isoformat(),
                           side=p["side"], entry=p["entry"], stop=p["stop0"], risk_pts=p["risk"],
                           r=pnl / risk_usd, pnl=pnl, reason=reason, bars=i - p["i0"],
                           tp1_hit=p["tp1_done"]))
        pos = None

    def exit_qty(price, q):
        pos["pts_qty"] += (price - pos["entry"]) * pos["side"] * q
        pos["open_qty"] -= q

    def walk(i, pts, check_open):
        """Walk path points for the open position on bar i. Returns True when flat."""
        side = pos["side"]
        stop = pos["stop"]
        levels_t = []
        if pos["tp1_px"] is not None and not pos["tp1_done"]:
            levels_t.append(("tp1", pos["tp1_px"]))
        levels_t.append(("tp", pos["tp_px"]))
        if check_open:
            a = pts[0]
            if (a <= stop) if side > 0 else (a >= stop):
                exit_qty(a - side * slip, pos["open_qty"])
                finish(i, "be" if pos["be_done"] else "sl")
                return True
            for name, px in list(levels_t):
                if (a >= px) if side > 0 else (a <= px):
                    if name == "tp1":
                        exit_qty(a, q1)
                        pos["tp1_done"] = True
                        pos["be_pending"] |= be_tp1
                        levels_t.remove((name, px))
                    else:
                        exit_qty(a, pos["open_qty"])
                        finish(i, "tp")
                        return True
        for k in range(1, len(pts)):
            a, b = pts[k - 1], pts[k]
            lo, hi = min(a, b), max(a, b)
            hits = []
            if lo <= stop <= hi:
                hits.append((abs(stop - a), "stop", stop))
            for name, px in levels_t:
                if lo <= px <= hi:
                    hits.append((abs(px - a), name, px))
            hits.sort(key=lambda x: x[0])
            for _, name, px in hits:
                if name == "stop":
                    exit_qty(stop - side * slip, pos["open_qty"])
                    finish(i, "be" if pos["be_done"] else ("sl_after_tp1" if pos["tp1_done"] else "sl"))
                    return True
                if name == "tp1" and not pos["tp1_done"]:
                    exit_qty(px, q1)
                    pos["tp1_done"] = True
                    pos["be_pending"] |= be_tp1
                    levels_t = [x for x in levels_t if x[0] != "tp1"]
                elif name == "tp":
                    exit_qty(px, pos["open_qty"])
                    finish(i, "tp")
                    return True
            if be_at > 0 and not pos["be_done"]:
                trig = pos["entry"] + side * be_at * pos["risk"]
                if lo <= trig <= hi:
                    pos["be_pending"] = True
        return False

    for i in range(n):
        new_day = i > 0 and feat.day[i] != feat.day[i - 1]
        if pos is not None:
            side = pos["side"]
            if pos["be_pending"] and not pos["be_done"]:
                pos["stop"] = pos["entry"]
                pos["be_done"] = True
            if new_day or after_flat(i):
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "eod")
            elif pos["tstop_due"]:
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "time")
            else:
                walk(i, _path(o[i], h[i], l[i], c[i]), True)
            if pos is not None and tstop > 0 and i - pos["i0"] >= tstop:
                pos["tstop_due"] = True

        if pending is not None and pos is None:
            s = pending
            pend_age += 1
            if (new_day or after_flat(i) or pend_age > s.expiry
                    or day_count.get(feat.day[i], 0) >= max_trades):
                pending = None
            else:
                res = _fill(s, o[i], h[i], l[i], c[i], slip)
                if res is None:
                    if s.invalidate is not None and ((c[i] < s.invalidate) if s.side > 0 else (c[i] > s.invalidate)):
                        pending = None
                elif res[0] == "cancel":
                    pending = None
                else:
                    _, fill, rest = res
                    pending = None
                    risk = (fill - s.stop) * s.side
                    pos = dict(side=s.side, entry=fill, stop=s.stop, stop0=s.stop, risk=risk, i0=i,
                               tp_px=fill + s.side * tp * risk,
                               tp1_px=(fill + s.side * tp1 * risk) if tp1 else None,
                               tp1_done=False, be_pending=False, be_done=False, tstop_due=False,
                               open_qty=qty, pts_qty=0.0)
                    day_count[feat.day[i]] = day_count.get(feat.day[i], 0) + 1
                    walk(i, rest, False)
                    if pos is not None and tstop > 0 and i - pos["i0"] >= tstop:
                        pos["tstop_due"] = True

        if pos is None and i in by_bar:
            for s in by_bar.get(i, []):
                if day_count.get(feat.day[i], 0) >= max_trades or after_flat(i):
                    continue
                risk = (s.entry - s.stop) * s.side
                if risk < min_risk_ticks * tick or (feat.atr[i] > 0 and risk > max_risk_atr * feat.atr[i]):
                    continue
                pending, pend_age = s, 0
    if pos is not None:
        exit_qty(c[n - 1], pos["open_qty"])
        finish(n - 1, "eod")
    return trades


def _fill(s, o, h, l, c, slip):
    """Limit-order fill on one bar (same model as engine._resolve_fill_bar).
    Returns None, ("cancel",) or ("fill", price, remaining_path_points)."""
    side = s.side
    path = _path(o, h, l, c)
    if s.entry_type == "limit" and ((o <= s.entry) if side > 0 else (o >= s.entry)):
        if (o - s.stop) * side <= 0:
            return ("cancel",)
        return ("fill", o, path)
    for k in range(1, len(path)):
        a, b = path[k - 1], path[k]
        lo, hi = min(a, b), max(a, b)
        hits = []
        if lo <= s.entry <= hi:
            hits.append((abs(s.entry - a), "entry"))
        if lo <= s.stop <= hi:
            hits.append((abs(s.stop - a), "stop"))
        if hits:
            hits.sort()
            if hits[0][1] == "stop":
                return ("cancel",)
            return ("fill", s.entry, [s.entry] + path[k:])
    return None


# ----------------------------------------------------------------- stats

def stats(tr):
    if not tr:
        return dict(trades=0, wr=None, exp=None, pf=None, net=0.0, dd=0.0)
    pnl = np.array([t["pnl"] for t in tr])
    r = np.array([t["r"] for t in tr])
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    gl = -pnl[pnl < 0].sum()
    return dict(trades=len(tr), wr=float((pnl > 0).mean()), exp=float(r.mean()),
                pf=float(pnl[pnl > 0].sum() / gl) if gl > 0 else float("inf"),
                net=float(pnl.sum()), dd=dd)


def monthly(tr):
    m = {}
    for t in tr:
        k = t["entry_time"][:7]
        m[k] = m.get(k, 0.0) + t["r"]
    return dict(sorted(m.items()))


def split(tr):
    return [t for t in tr if t["entry_time"] < CUT], [t for t in tr if t["entry_time"] >= CUT]


def evaluate(feat, inst, setups, mg, max_trades):
    tr = simulate(feat, setups, inst, mg, max_trades=max_trades)
    a, b = split(tr)
    mo = monthly(tr)
    return dict(full=stats(tr), is_=stats(a), oos=stats(b), months=mo,
                pos_months=sum(v > 0 for v in mo.values()), n_months=len(mo),
                is_months=monthly(a)), tr


# ----------------------------------------------------------------- grid

EXITS = (
    [dict(name=f"fixed {x}R", tp=x) for x in (0.75, 1.0, 1.25, 1.5, 2.0)]
    + [dict(name=f"partial {a}/{b} BE", tp1=a, tp=b, be_tp1=True) for a, b in ((0.5, 1.5), (0.75, 1.5), (1.0, 2.0), (0.75, 2.0))]
    + [dict(name="partial 1/2 noBE", tp1=1.0, tp=2.0, be_tp1=False)]
    + [dict(name=f"BE@{be} tp {x}R", tp=x, be_at=be) for be in (0.5, 0.75) for x in (1.0, 1.5, 2.0)]
    + [dict(name=f"fixed {x}R ts{ts}", tp=x, tstop=ts) for x in (1.0, 1.5) for ts in (4, 8)]
    + [dict(name=f"partial 1/2 BE ts8", tp1=1.0, tp=2.0, be_tp1=True, tstop=8)]
)

ENTRIES = [dict(win=w, mf=mf, mt=mt) for w in ("london", "asia+london", "ny_am") for mf in (0.15, 0.3) for mt in (1, 2)]


def load(tf="15min"):
    m1 = pd.read_pickle(M1)
    return data.resample(m1, tf)


def grid(tf="15min", log=print):
    inst = get_instrument("MNQ")
    df = load(tf)
    feat = features.build(df, inst.tick)
    rows = []
    for e in ENTRIES:
        p = dict(windows=fvg_pro.WINDOW_PRESETS[e["win"]], min_fvg_atr=e["mf"], max_trades=e["mt"], entry="edge")
        setups = fvg_pro.generate(feat, inst, p)
        for mg in EXITS:
            res, _ = evaluate(feat, inst, setups, mg, e["mt"])
            rows.append(dict(tf=tf, **e, exit=mg["name"], mg=mg, **res))
    return rows


def fmt(s):
    if not s["trades"]:
        return "0 tr"
    return f"{s['trades']:3d} tr WR {s['wr']:.0%} {s['exp']:+.2f}R PF {s['pf']:.2f} ${s['net']:,.0f} DD ${s['dd']:,.0f}"


def truncation_check():
    """Entries come from fvg_pro.generate (unchanged); verify setups decided on
    bars < k-1 are identical on df[:k] vs full df."""
    inst = get_instrument("MNQ")
    df = load("15min")
    p = dict(windows=fvg_pro.WINDOW_PRESETS["asia+london"], min_fvg_atr=0.15)
    full = fvg_pro.generate(features.build(df, inst.tick), inst, p)
    for k in (5000, 12000, 20000):
        part = fvg_pro.generate(features.build(df.iloc[:k], inst.tick), inst, p)
        a = [(s.bar, s.side, s.entry, s.stop) for s in full if s.bar < k - 1]
        b = [(s.bar, s.side, s.entry, s.stop) for s in part if s.bar < k - 1]
        assert a == b, k
    return True


if __name__ == "__main__":
    tfs = sys.argv[1:] or ["15min"]
    allrows = []
    for tf in tfs:
        rows = grid(tf)
        allrows += rows
        for r in rows:
            print(f"{tf} {r['win']:11s} mf{r['mf']} mt{r['mt']} {r['exit']:22s} | IS {fmt(r['is_'])} | OOS {fmt(r['oos'])} | +m {r['pos_months']}/{r['n_months']}")
    OUT.mkdir(parents=True, exist_ok=True)
    slim = [{k: v for k, v in r.items() if k not in ("months", "is_months")} for r in allrows]
    (OUT / f"exits_grid_{'_'.join(tfs)}.json").write_text(json.dumps(slim, default=str))


# ----------------------------------------------------------------- stage 2: refinement around London partials

REFINE_EXITS = [dict(name=f"partial {a}/{b} BE" + (f" ts{ts}" if ts else ""), tp1=a, tp=b, be_tp1=True, tstop=ts)
                for a in (0.5, 0.75, 1.0) for b in (1.5, 2.0, 3.0) for ts in (0, 8)]


def refine(tfs=("10min", "15min", "30min")):
    inst = get_instrument("MNQ")
    rows = []
    for tf in tfs:
        feat = features.build(load(tf), inst.tick)
        for mf in (0.15, 0.3):
            p = dict(windows=fvg_pro.WINDOW_PRESETS["london"], min_fvg_atr=mf, max_trades=1, entry="edge")
            setups = fvg_pro.generate(feat, inst, p)
            for mg in REFINE_EXITS:
                res, _ = evaluate(feat, inst, setups, mg, 1)
                rows.append(dict(tf=tf, win="london", mf=mf, mt=1, exit=mg["name"], mg=mg, **res))
    return rows


# ----------------------------------------------------------------- chosen config

BEST_ENTRY = dict(windows=fvg_pro.WINDOW_PRESETS["london"], min_fvg_atr=0.3, max_trades=1, entry="edge")
BEST_EXIT = dict(name="partial 0.75/3.0 BE ts8", tp1=0.75, frac1=0.5, tp=3.0, be_tp1=True, tstop=8)


def best(tf="15min"):
    """Reproduce the chosen config (python -c 'from lab import wr60_exits as W; W.best()')."""
    inst = get_instrument("MNQ")
    feat = features.build(load(tf), inst.tick)
    res, tr = evaluate(feat, inst, fvg_pro.generate(feat, inst, BEST_ENTRY), BEST_EXIT, 1)
    for k in ("full", "is_", "oos"):
        print(k, fmt(res[k]))
    print({k: round(v, 2) for k, v in res["months"].items()}, f"+months {res['pos_months']}/{res['n_months']}")
    return res, tr

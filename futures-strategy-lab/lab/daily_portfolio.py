"""Daily direction "portfolio": ~1 trade per day from several FVG Pro rule sets.

Every component is the unchanged FVG Pro entry (lab/fvg_pro.generate: BOS +
FVG, limit at the gap edge) on one market / timeframe / session window, with

  * the "don't chase" filter: skip a setup when side*(close-entry)/ATR > chase
    at the signal bar (decided at that bar's close, order works from the next bar),
  * the partial exit: half at tp1 = 1R -> stop to break-even -> runner 3R,
    time stop 8 bars, flat 15:55 NY / new Globex day, max 1 trade per component per day.

Components are chosen on IS only (entry < 2026-04-01). Daily rule of the
portfolio: per Globex day take only the FIRST filled trade across all components
("first"), or at most one per market ("per_market"). Pending orders of the other
components are cancelled once one fills; no look-ahead: only a trade that
filled earlier can block a later one.

Simulator: copy of lab/wr60_exits.simulate with two extra knobs
  slip_ticks  (stop / BE / market exits pay this many ticks; default 1)
  intrabar    "path" (TradingView emulator) or "conservative" (adverse extreme
              always visited first, on the fill bar too -> stop before target)
and an optional 1-minute replay of every bar the position is open ("m1").

Run:  PYTHONPATH=. python -m lab.daily_portfolio scan      (component grid)
      PYTHONPATH=. python -m lab.daily_portfolio final     (selection + portfolio + robustness)
      PYTHONPATH=. python -m lab.daily_portfolio trunc     (truncation check of the chase filter)
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features, fvg_pro
from .data import get_instrument
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "daily"
P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
FILES = {"MNQ": "MNQ_1m.pkl", "MGC": "MGC_1m.pkl", "MCL": "CL_1m.pkl"}
CUT = "2026-04-01"
EXIT = dict(tp1=1.0, frac1=0.5, tp=3.0, be_tp1=True, tstop=8)

WINDOWS = {
    "asia": (("20:00", "24:00"),),
    "pre_lon": (("00:00", "02:00"),),
    "london": (("02:00", "05:00"),),
    "lon_late": (("05:00", "08:00"),),
    "ny_am": (("08:30", "11:00"),),
    "comex": (("08:20", "10:30"),),
    "nymex": (("09:00", "11:30"),),
    "ny_pm": (("13:00", "15:00"),),
}

_CACHE: dict = {}


def inst_of(sym):
    i = get_instrument(sym)
    return dataclasses.replace(i, contracts=2)  # 2 so the partial exit splits 1 + 1


def m1(sym):
    k = ("m1", sym)
    if k not in _CACHE:
        _CACHE[k] = pd.read_pickle(P + FILES[sym])
    return _CACHE[k]


def feat_of(sym, tf):
    k = ("feat", sym, tf)
    if k not in _CACHE:
        _CACHE[k] = features.build(data.resample(m1(sym), tf), inst_of(sym).tick)
    return _CACHE[k]


# ----------------------------------------------------------------- setups

def setups_of(sym, tf, win, mf, chase, trend=False):
    feat, inst = feat_of(sym, tf), inst_of(sym)
    p = dict(windows=WINDOWS[win], min_fvg_atr=mf, max_trades=1, entry="edge", trend_filter=bool(trend))
    ss = fvg_pro.generate(feat, inst, p)
    if chase:
        ss = [s for s in ss if not (feat.atr[s.bar] > 0 and s.side * (feat.c[s.bar] - s.entry) / feat.atr[s.bar] > chase)]
    return ss


# ----------------------------------------------------------------- simulator

def _path(o, h, l, c, side=0, mode="path"):
    if mode == "conservative" and side:
        return [o, l, h, c] if side > 0 else [o, h, l, c]
    return [o, l, h, c] if (o - l) <= (h - o) else [o, h, l, c]


def _fill(s, o, h, l, c, mode):
    side = s.side
    path = _path(o, h, l, c, side, mode)
    if (o <= s.entry) if side > 0 else (o >= s.entry):
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


def simulate(feat, setups, inst, mg=EXIT, flatten="15:55", max_trades=1, slip_ticks=1, intrabar="path",
             min_risk_ticks=4, max_risk_atr=3.0, m1df=None):
    """Same logic as lab.wr60_exits.simulate (+ slip_ticks, intrabar, m1 replay)."""
    tp, tp1 = float(mg["tp"]), mg.get("tp1")
    frac1, be_tp1, tstop = float(mg.get("frac1", .5)), bool(mg.get("be_tp1", True)), int(mg.get("tstop", 0))
    o, h, l, c = feat.o, feat.h, feat.l, feat.c
    idx = feat.df.index
    n = feat.n
    flat = hm(flatten)
    slip = slip_ticks * inst.tick
    qty, pv = inst.contracts, inst.point_value
    costs = 2 * inst.commission * qty
    q1 = max(1, int(round(qty * frac1))) if tp1 else 0
    step = pd.Timedelta(minutes=feat.interval_min)
    if m1df is not None:
        m1o, m1h, m1l, m1c = (m1df[k].to_numpy() for k in ("open", "high", "low", "close"))
        m1i = m1df.index
    by_bar = {}
    for s in setups:
        by_bar.setdefault(s.bar, []).append(s)

    def after_flat(i):
        return flat <= feat.mod[i] < 18 * 60

    def bar_paths(i, side):
        """Price path of bar i: OHLC model, or the 1-minute bars inside it."""
        if m1df is None:
            return [_path(o[i], h[i], l[i], c[i], side, intrabar)]
        a, b = m1i.searchsorted(idx[i]), m1i.searchsorted(idx[i] + step)
        if b <= a:
            return [_path(o[i], h[i], l[i], c[i], side, intrabar)]
        return [_path(m1o[j], m1h[j], m1l[j], m1c[j], side, intrabar) for j in range(a, b)]

    trades = []
    pending, pend_age, pos = None, 0, None
    day_count = {}

    def finish(i, reason):
        nonlocal pos
        p = pos
        pnl = p["pts_qty"] * pv - costs
        trades.append(dict(entry_time=idx[p["i0"]].isoformat(), exit_time=idx[i].isoformat(), side=p["side"],
                           entry=p["entry"], stop=p["stop0"], risk_pts=p["risk"],
                           r=pnl / (p["risk"] * pv * qty), pnl=pnl, reason=reason, bars=i - p["i0"],
                           day=int(feat.day[p["i0"]])))
        pos = None

    def exit_qty(price, q):
        pos["pts_qty"] += (price - pos["entry"]) * pos["side"] * q
        pos["open_qty"] -= q

    def walk(i, pts, check_open):
        side, stop = pos["side"], pos["stop"]
        lv = []
        if pos["tp1_px"] is not None and not pos["tp1_done"]:
            lv.append(("tp1", pos["tp1_px"]))
        lv.append(("tp", pos["tp_px"]))
        if check_open:
            a = pts[0]
            if (a <= stop) if side > 0 else (a >= stop):
                exit_qty(a - side * slip, pos["open_qty"])
                finish(i, "be" if pos["be_done"] else "sl")
                return True
            for name, px in list(lv):
                if (a >= px) if side > 0 else (a <= px):
                    if name == "tp1":
                        exit_qty(a, q1)
                        pos["tp1_done"] = True
                        pos["be_pending"] |= be_tp1
                        lv.remove((name, px))
                    else:
                        exit_qty(a, pos["open_qty"])
                        finish(i, "tp")
                        return True
        for k in range(1, len(pts)):
            a, b = pts[k - 1], pts[k]
            lo, hi = min(a, b), max(a, b)
            hits = []
            if lo <= stop <= hi:
                hits.append((abs(stop - a), 0, "stop", stop))
            for name, px in lv:
                if lo <= px <= hi:
                    hits.append((abs(px - a), 1, name, px))
            hits.sort()
            for _, _, name, px in hits:
                if name == "stop":
                    exit_qty(stop - side * slip, pos["open_qty"])
                    finish(i, "be" if pos["be_done"] else ("sl_after_tp1" if pos["tp1_done"] else "sl"))
                    return True
                if name == "tp1" and not pos["tp1_done"]:
                    exit_qty(px, q1)
                    pos["tp1_done"] = True
                    pos["be_pending"] |= be_tp1
                    lv = [x for x in lv if x[0] != "tp1"]
                elif name == "tp":
                    exit_qty(px, pos["open_qty"])
                    finish(i, "tp")
                    return True
        return False

    def walk_bar(i, first_check_open=True, skip_points=None):
        """Walk bar i (all sub-paths). BE moves only between 15m bars (as the reference sim)."""
        paths = bar_paths(i, pos["side"])
        for j, pts in enumerate(paths):
            if pos is None:
                return
            if walk(i, pts, first_check_open or j > 0):
                return

    for i in range(n):
        new_day = i > 0 and feat.day[i] != feat.day[i - 1]
        if pos is not None:
            side = pos["side"]
            if pos["be_pending"] and not pos["be_done"]:
                pos["stop"], pos["be_done"] = pos["entry"], True
            if new_day or after_flat(i):
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "eod")
            elif pos["tstop_due"]:
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "time")
            else:
                walk_bar(i)
            if pos is not None and tstop > 0 and i - pos["i0"] >= tstop:
                pos["tstop_due"] = True

        if pending is not None and pos is None:
            s = pending
            pend_age += 1
            if new_day or after_flat(i) or pend_age > s.expiry or day_count.get(feat.day[i], 0) >= max_trades:
                pending = None
            else:
                filled = False
                subs = bar_paths(i, s.side) if m1df is not None else None
                if subs is None:
                    res = _fill(s, o[i], h[i], l[i], c[i], intrabar)
                    rest_paths = None
                else:
                    res = None
                    for j, pts in enumerate(subs):
                        r_ = _fill(s, pts[0], max(pts), min(pts), pts[-1], intrabar)
                        if r_ is not None:
                            res = r_
                            rest_paths = subs[j + 1:]
                            break
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
                               tp_px=fill + s.side * tp * risk, tp1_px=(fill + s.side * tp1 * risk) if tp1 else None,
                               tp1_done=False, be_pending=False, be_done=False, tstop_due=False,
                               open_qty=qty, pts_qty=0.0)
                    day_count[feat.day[i]] = day_count.get(feat.day[i], 0) + 1
                    walk(i, rest, False)
                    if pos is not None and rest_paths:
                        for pts in rest_paths:
                            if pos is None or walk(i, pts, True):
                                break
                    if pos is not None and tstop > 0 and i - pos["i0"] >= tstop:
                        pos["tstop_due"] = True

        if pos is None and i in by_bar:
            for s in by_bar[i]:
                if day_count.get(feat.day[i], 0) >= max_trades or after_flat(i):
                    continue
                risk = (s.entry - s.stop) * s.side
                if risk < min_risk_ticks * inst.tick or (feat.atr[i] > 0 and risk > max_risk_atr * feat.atr[i]):
                    continue
                pending, pend_age = s, 0
    if pos is not None:
        exit_qty(c[n - 1], pos["open_qty"])
        finish(n - 1, "eod")
    return trades


# ----------------------------------------------------------------- stats

def stats(tr, ndays=None):
    if not tr:
        return dict(trades=0, wr=None, exp=None, pf=None, net=0.0, dd=0.0, tpd=0.0)
    pnl = np.array([t["pnl"] for t in tr])
    r = np.array([t["r"] for t in tr])
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    gl = -pnl[pnl < 0].sum()
    return dict(trades=len(tr), wr=float((pnl > 0).mean()), exp=float(r.mean()),
                pf=float(pnl[pnl > 0].sum() / gl) if gl > 0 else 99.0, net=float(pnl.sum()), dd=dd,
                tpd=len(tr) / ndays if ndays else None)


def split(tr):
    return [t for t in tr if t["entry_time"] < CUT], [t for t in tr if t["entry_time"] >= CUT]


def months(tr):
    m = {}
    for t in tr:
        m[t["entry_time"][:7]] = m.get(t["entry_time"][:7], 0.0) + t["pnl"]
    return dict(sorted(m.items()))


def trading_days():
    """Globex trading days in the data (MNQ calendar), split IS / OOS."""
    f = feat_of("MNQ", "15min")
    idx = f.df.index
    d = pd.Series(idx, index=f.day).groupby(level=0).first()
    first = d.dt.strftime("%Y-%m-%d").to_numpy()
    # a Globex day id belongs to IS if its first bar is before the cut
    n_is = int((first < CUT).sum())
    return len(first), n_is, len(first) - n_is


def fmt(s):
    if not s["trades"]:
        return "0 tr"
    return (f"{s['trades']:3d} tr WR {s['wr']:.1%} {s['exp']:+.3f}R PF {s['pf']:.2f} "
            f"${s['net']:>7,.0f} DD ${s['dd']:>6,.0f}")


# ----------------------------------------------------------------- components

MARKETS = {"MNQ": ["asia", "pre_lon", "london", "lon_late", "ny_am", "ny_pm"],
           "MGC": ["asia", "pre_lon", "london", "lon_late", "comex", "ny_pm"],
           "MCL": ["asia", "london", "lon_late", "nymex", "ny_pm"]}
MFS = (0.15, 0.3)
CHASES = (0.0, 1.0)


def comp_key(c):
    return f"{c['sym']}|{c['tf']}|{c['win']}|mf{c['mf']}|ch{c['chase']}" + ("|tr" if c.get("trend") else "")


def run_comp(c, slip_ticks=1, intrabar="path", m1replay=False):
    feat = feat_of(c["sym"], c["tf"])
    ss = setups_of(c["sym"], c["tf"], c["win"], c["mf"], c["chase"], c.get("trend", False))
    tr = simulate(feat, ss, inst_of(c["sym"]), slip_ticks=slip_ticks, intrabar=intrabar,
                  m1df=m1(c["sym"]) if m1replay else None)
    for t in tr:
        t["comp"] = comp_key(c)
        t["sym"] = c["sym"]
        t["ts"] = pd.Timestamp(t["entry_time"])
    return tr


def scan(tf="15min", trend=False, log=print):
    rows = []
    for sym, wins in MARKETS.items():
        for win, mf, ch in itertools.product(wins, MFS, CHASES):
            c = dict(sym=sym, tf=tf, win=win, mf=mf, chase=ch, trend=trend)
            tr = run_comp(c)
            a, b = split(tr)
            row = dict(**c, key=comp_key(c), is_=stats(a), oos=stats(b), full=stats(tr))
            rows.append(row)
            log(f"{row['key']:32s} IS {fmt(row['is_'])} | OOS {fmt(row['oos'])}")
    return rows


def eligible(row, min_n=20, min_wr=0.60, min_pf=1.3):
    s = row["is_"]
    return s["trades"] >= min_n and s["wr"] >= min_wr and s["pf"] >= min_pf


def select(rows, **kw):
    """IS-only: per (market, window) keep the eligible variant with the best IS PF
    (needs >= 20 IS trades, IS WR >= 60 %, IS PF >= 1.3)."""
    best = {}
    for r in rows:
        if not eligible(r, **kw):
            continue
        k = (r["sym"], r["win"])
        if k not in best or r["is_"]["pf"] > best[k]["is_"]["pf"]:
            best[k] = r
    return list(best.values())


# ----------------------------------------------------------------- portfolio

def combine(trades_by_comp, rule="first", order=None):
    """Per Globex day: 'first' = first filled trade of the day across everything;
    'per_market' = first filled trade per market. A later trade is only blocked by
    one that FILLED earlier (strictly earlier entry bar start); ties -> component order."""
    allt = [t for tr in trades_by_comp for t in tr]
    rank = {k: i for i, k in enumerate(order or [])}
    allt.sort(key=lambda t: (t["ts"], rank.get(t["comp"], 99)))
    taken, seen = [], set()
    for t in allt:
        dkey = pd.Timestamp(t["ts"] + pd.Timedelta(hours=6)).normalize()
        k = dkey if rule == "first" else (dkey, t["sym"])
        if k in seen:
            continue
        seen.add(k)
        taken.append(t)
    return taken


def report_port(tr, nd):
    n_all, n_is, n_oos = nd
    a, b = split(tr)
    mo = months(tr)
    return dict(full=stats(tr, n_all), is_=stats(a, n_is), oos=stats(b, n_oos), months=mo,
                pos_months=sum(v > 0 for v in mo.values()), n_months=len(mo))


def truncation_check():
    """Chase filter + generate on df[:k] must give the same setups (bar < k-1) as on the full df."""
    for sym, win in (("MNQ", "london"), ("MGC", "comex"), ("MCL", "nymex")):
        inst = inst_of(sym)
        df = data.resample(m1(sym), "15min")
        p = dict(windows=WINDOWS[win], min_fvg_atr=0.15)

        def gen(d):
            f = features.build(d, inst.tick)
            ss = fvg_pro.generate(f, inst, p)
            return [(s.bar, s.side, s.entry, s.stop) for s in ss
                    if not (f.atr[s.bar] > 0 and s.side * (f.c[s.bar] - s.entry) / f.atr[s.bar] > 1.0)]
        full = gen(df)
        for k in (6000, 15000, 22000):
            part = gen(df.iloc[:k])
            assert [x for x in full if x[0] < k - 1] == [x for x in part if x[0] < k - 1], (sym, k)
    print("truncation check OK")
    return True


def jdump(path, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=str))


# ----------------------------------------------------------------- final (selection on IS + robustness)

SCAN_FILES = ["5min", "10min", "15min", "30min", "10min_trend", "15min_trend"]


def load_scans():
    return [r for f in SCAN_FILES for r in json.loads((OUT / f"portfolio_scan_{f}.json").read_text())]


def cfg(r):
    return dict(sym=r["sym"], tf=r["tf"], win=r["win"], mf=r["mf"], chase=r["chase"], trend=r.get("trend", False))


def port(comps, rule="first", **kw):
    trs = [run_comp(c, **kw) for c in comps]
    return combine(trs, rule, [comp_key(c) for c in comps])


def line(rep):
    f, a, b = rep["full"], rep["is_"], rep["oos"]
    return (f"FULL {fmt(f)} tpd {f['tpd']:.2f} | IS {fmt(a)} tpd {a['tpd']:.2f} | OOS {fmt(b)} tpd {b['tpd']:.2f} "
            f"| +m {rep['pos_months']}/{rep['n_months']}")


def final(log=print):
    rows = load_scans()
    nd = trading_days()
    out = {"trading_days": nd, "configs_scanned": len(rows), "portfolios": {}}
    sel = sorted(select(rows), key=lambda r: -r["is_"]["pf"])
    comps = [cfg(r) for r in sel]
    out["selected"] = [dict(key=r["key"], is_=r["is_"], oos=r["oos"]) for r in sel]
    log("selected (IS WR>=60 %, PF>=1.3, n>=20, best IS PF per market+window):")
    for r in sel:
        log(f"  {r['key']:34s} IS {fmt(r['is_'])} | OOS {fmt(r['oos'])}")
    variants = {"A strict, first/day": (comps, "first"), "A strict, 1/market/day": (comps, "per_market")}
    comex = dict(sym="MGC", tf="15min", win="comex", mf=0.3, chase=0.0, trend=False)
    variants["B strict + MGC COMEX (prior pick), first/day"] = (comps + [comex], "first")
    variants["B strict + MGC COMEX (prior pick), 1/market/day"] = (comps + [comex], "per_market")
    for name, (cs, rule) in variants.items():
        res = {}
        for tag, kw in (("base", {}), ("conservative", dict(intrabar="conservative")), ("slip2", dict(slip_ticks=2)),
                        ("cons+slip2", dict(intrabar="conservative", slip_ticks=2)), ("m1 replay", dict(m1replay=True))):
            rep = report_port(port(cs, rule, **kw), nd)
            res[tag] = rep
            log(f"{name:48s} {tag:12s} {line(rep)}")
        out["portfolios"][name] = res
    # neighbours of the strict selection: each component's min_fvg / chase / timeframe moved one step
    log("neighbours (strict, first/day): one component changed at a time")
    neigh = []
    tfs = ["5min", "10min", "15min", "30min"]
    for i, c in enumerate(comps):
        alts = [dict(c, mf=0.45 if c["mf"] == 0.3 else 0.3), dict(c, mf=0.15 if c["mf"] == 0.3 else 0.3 if c["mf"] == 0.15 else 0.15),
                dict(c, chase=0.0 if c["chase"] else 1.0), dict(c, chase=0.75 if c["chase"] else 1.5)]
        k = tfs.index(c["tf"])
        alts += [dict(c, tf=tfs[j]) for j in (k - 1, k + 1) if 0 <= j < len(tfs)]
        for a in alts:
            cs = comps[:i] + [a] + comps[i + 1:]
            rep = report_port(port(cs, "first"), nd)
            neigh.append(dict(changed=comp_key(a), rep=rep))
            log(f"  {comp_key(a):34s} {line(rep)}")
    out["neighbours"] = neigh
    jdump(OUT / "portfolio_final.json", out)
    return out


def real_check(log=print):
    """Real CME futures (~70 days, 5m/15m bars): MNQ and MGC components only (no real MCL)."""
    from . import research
    st = research.load_store(["MNQ", "MGC"], ["15m", "5m"])
    rows = load_scans()
    comps = [cfg(r) for r in sorted(select(rows), key=lambda r: -r["is_"]["pf"])]
    comps_b = comps + [dict(sym="MGC", tf="15min", win="comex", mf=0.3, chase=0.0, trend=False)]
    saved = dict(_CACHE)
    res = {}
    try:
        for name, cs in (("A", comps), ("B", comps_b)):
            for tag, src in (("real", "real"), ("proxy same window", "proxy")):
                trs = []
                for c in cs:
                    if c["sym"] not in ("MNQ", "MGC"):
                        continue
                    real = st.get((c["sym"], "5m"))
                    if real is None:
                        continue
                    lo, hi = real.index[0], real.index[-1]
                    if src == "real":
                        df = real if c["tf"] == "5min" else data.resample(real, c["tf"])
                    else:
                        d1 = m1(c["sym"])
                        df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], c["tf"])
                    _CACHE[("feat", c["sym"], c["tf"])] = features.build(df, inst_of(c["sym"]).tick)
                    tr = simulate(_CACHE[("feat", c["sym"], c["tf"])],
                                  setups_of(c["sym"], c["tf"], c["win"], c["mf"], c["chase"], c.get("trend")),
                                  inst_of(c["sym"]))
                    for t in tr:
                        t["comp"], t["sym"], t["ts"] = comp_key(c), c["sym"], pd.Timestamp(t["entry_time"])
                    trs.append(tr)
                    _CACHE.pop(("feat", c["sym"], c["tf"]))
                pt = combine(trs, "first", [comp_key(c) for c in cs])
                s = stats(pt)
                res[f"{name} {tag}"] = dict(stats=s, start=str(lo), end=str(hi))
                log(f"{name} {tag:18s} {lo:%Y-%m-%d}..{hi:%Y-%m-%d} {fmt(s)}")
    finally:
        _CACHE.clear()
        _CACHE.update(saved)
    jdump(OUT / "portfolio_real.json", res)
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "trunc":
        truncation_check()
    elif cmd == "final":
        final()
    elif cmd == "real":
        real_check()
    elif cmd == "scan":
        tf = sys.argv[2] if len(sys.argv) > 2 else "15min"
        trend = len(sys.argv) > 3 and sys.argv[3] == "trend"
        rows = scan(tf, trend)
        jdump(OUT / f"portfolio_scan_{tf}{'_trend' if trend else ''}.json", rows)

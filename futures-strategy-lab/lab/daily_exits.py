"""Daily direction "exits": exit structures on the most frequent FVG Pro entries.

Goal: ~1 trade per trading day (>= 0.8/day) with WR >= 58 % in both halves.
Entries are unchanged (lab/daily_portfolio.setups_of = fvg_pro.generate + "don't chase"):

  MNQ 15m  Asia 20-24, London 02-05, NY AM 08:30-11 (NY time), chase 1.0 ATR, min FVG mf (0.15 / 0.3)
  MGC 15m  COMEX 08:20-10:30, min FVG 0.3, no chase filter (prior pick)

Daily rule: per Globex day the first FILLED trade per market (max 1 MNQ + 1 MGC = max 2/day),
causal (only an earlier fill blocks a later one): lab/daily_portfolio.combine(rule="per_market").

Exit grid (management only, all at bar resolution):
  tp1     first target in R (0.5 / 0.75 / 1.0), frac of the position exits there (1/2 -> 2 contracts,
          2/3 -> 3 contracts, so the split is exact)
  after   after TP1 the stop moves to entry + after*R from the next bar (0 = BE, -0.5)
  tp      runner target in R (2 / 3)
  tstop   time stop: everything left exits at the next bar's open once the trade is N bars old
  nft     "no follow-through": if after N bars the trade has never been +0.5R, exit at the next open
Costs $0.62/side/contract; stops / BE / market / time exits pay `slip_ticks` (1, robustness 2);
intrabar "path" (TradingView emulator), "conservative" (daily_portfolio's: adverse extreme first, also on the
fill bar -- which is actually favourable for a resting limit: after the fill it visits the far extreme) or
"worst" (adverse first on every bar AND on the fill bar the favourable extreme is assumed to come before the fill);
optional 1-minute replay of every bar (fill bar included).

Protocol: IS = entry < 2026-04-01, OOS = entry >= 2026-04-01; selection on IS only.

Run:  PYTHONPATH=. python -m lab.daily_exits grid      (grid -> results/daily/exits_grid.json)
      PYTHONPATH=. python -m lab.daily_exits final     (IS pick + robustness + neighbours)
      PYTHONPATH=. python -m lab.daily_exits real      (real CME futures, ~70 days)
      PYTHONPATH=. python -m lab.daily_exits trunc     (truncation check of the entries)
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features
from . import daily_portfolio as D
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "daily"
CUT = D.CUT


def comps_of(mf_nq, mf_gc=0.3):
    return ([dict(sym="MNQ", tf="15min", win=w, mf=mf_nq, chase=1.0) for w in ("asia", "london", "ny_am")]
            + [dict(sym="MGC", tf="15min", win="comex", mf=mf_gc, chase=0.0)])


def inst_for(sym, frac):
    return dataclasses.replace(D.inst_of(sym), contracts=3 if abs(frac - 2 / 3) < 1e-6 else 2)


# ----------------------------------------------------------------- simulator

def simulate(feat, setups, inst, mg, flatten="15:55", max_trades=1, slip_ticks=1, intrabar="path",
             min_risk_ticks=4, max_risk_atr=3.0, m1df=None):
    """lab.daily_portfolio.simulate + stop-after-TP1 offset and the no-follow-through exit.
    With after=0, nft=0 it reproduces daily_portfolio.simulate trade for trade (see selftest)."""
    tp, tp1 = float(mg["tp"]), mg.get("tp1")
    frac1 = float(mg.get("frac1", .5))
    after = mg.get("after", 0.0)          # None = stop stays at the original stop
    tstop = int(mg.get("tstop", 0))
    nft, nft_r = int(mg.get("nft", 0)), float(mg.get("nft_r", 0.5))
    worst = intrabar == "worst"
    if worst:
        intrabar = "conservative"
    path_ = D._path
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
        if m1df is None:
            return [path_(o[i], h[i], l[i], c[i], side, intrabar)]
        a, b = m1i.searchsorted(idx[i]), m1i.searchsorted(idx[i] + step)
        if b <= a:
            return [path_(o[i], h[i], l[i], c[i], side, intrabar)]
        return [path_(m1o[j], m1h[j], m1l[j], m1c[j], side, intrabar) for j in range(a, b)]

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
                           day=int(feat.day[p["i0"]]), tp1_hit=p["tp1_done"], qty=qty))
        pos = None

    def exit_qty(price, q):
        pos["pts_qty"] += (price - pos["entry"]) * pos["side"] * q
        pos["open_qty"] -= q

    def mfe_upd(x):
        pos["mfe"] = max(pos["mfe"], (x - pos["entry"]) * pos["side"] / pos["risk"])

    def tp1_fill(px):
        exit_qty(px, q1)
        pos["tp1_done"] = True
        if after is not None:
            pos["move_pending"] = True

    def walk(i, pts, check_open):
        side, stop = pos["side"], pos["stop"]
        lv = []
        if pos["tp1_px"] is not None and not pos["tp1_done"]:
            lv.append(("tp1", pos["tp1_px"]))
        lv.append(("tp", pos["tp_px"]))
        if check_open:
            a = pts[0]
            mfe_upd(a)
            if (a <= stop) if side > 0 else (a >= stop):
                exit_qty(a - side * slip, pos["open_qty"])
                finish(i, "be" if pos["moved"] else "sl")
                return True
            for name, px in list(lv):
                if (a >= px) if side > 0 else (a <= px):
                    if name == "tp1":
                        tp1_fill(a)
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
                    finish(i, "be" if pos["moved"] else ("sl_after_tp1" if pos["tp1_done"] else "sl"))
                    return True
                if name == "tp1" and not pos["tp1_done"]:
                    tp1_fill(px)
                    lv = [x for x in lv if x[0] != "tp1"]
                elif name == "tp":
                    exit_qty(px, pos["open_qty"])
                    finish(i, "tp")
                    return True
            mfe_upd(b)
        return False

    def walk_bar(i):
        for pts in bar_paths(i, pos["side"]):
            if pos is None or walk(i, pts, True):
                return

    def end_of_bar(i):
        if pos is None:
            return
        age = i - pos["i0"]
        if tstop > 0 and age >= tstop:
            pos["exit_due"] = "time"
        elif nft > 0 and age >= nft and not pos["tp1_done"] and pos["mfe"] < nft_r:
            pos["exit_due"] = "nft"

    for i in range(n):
        new_day = i > 0 and feat.day[i] != feat.day[i - 1]
        if pos is not None:
            side = pos["side"]
            if pos["move_pending"] and not pos["moved"]:
                pos["stop"] = pos["entry"] + side * after * pos["risk"]
                pos["moved"] = True
            if new_day or after_flat(i):
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "eod")
            elif pos["exit_due"]:
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, pos["exit_due"])
            else:
                walk_bar(i)
            end_of_bar(i)

        if pending is not None and pos is None:
            s = pending
            pend_age += 1
            if new_day or after_flat(i) or pend_age > s.expiry or day_count.get(feat.day[i], 0) >= max_trades:
                pending = None
            else:
                subs = bar_paths(i, s.side) if m1df is not None else None
                rest_paths = None
                if subs is None:
                    res = D._fill(s, o[i], h[i], l[i], c[i], intrabar)
                else:
                    res = None
                    for j, pts in enumerate(subs):
                        r_ = D._fill(s, pts[0], max(pts), min(pts), pts[-1], intrabar)
                        if r_ is not None:
                            res, rest_paths = r_, subs[j + 1:]
                            break
                if res is None:
                    if s.invalidate is not None and ((c[i] < s.invalidate) if s.side > 0 else (c[i] > s.invalidate)):
                        pending = None
                elif res[0] == "cancel":
                    pending = None
                else:
                    _, fill, rest = res
                    if worst and subs is None:
                        # worst case on the fill bar: the favourable extreme came BEFORE the fill
                        rest = [rest[0], l[i] if s.side > 0 else h[i], c[i]]
                    pending = None
                    risk = (fill - s.stop) * s.side
                    pos = dict(side=s.side, entry=fill, stop=s.stop, stop0=s.stop, risk=risk, i0=i,
                               tp_px=fill + s.side * tp * risk, tp1_px=(fill + s.side * tp1 * risk) if tp1 else None,
                               tp1_done=False, move_pending=False, moved=False, exit_due=None, mfe=0.0,
                               open_qty=qty, pts_qty=0.0)
                    day_count[feat.day[i]] = day_count.get(feat.day[i], 0) + 1
                    walk(i, rest, False)
                    if pos is not None and rest_paths:
                        for pts in rest_paths:
                            if pos is None or walk(i, pts, True):
                                break
                    end_of_bar(i)

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


# ----------------------------------------------------------------- portfolio

_SETUPS: dict = {}


def setups(c):
    k = D.comp_key(c)
    if k not in _SETUPS:
        _SETUPS[k] = D.setups_of(c["sym"], c["tf"], c["win"], c["mf"], c["chase"])
    return _SETUPS[k]


def run_comp(c, mg, **kw):
    m1r = kw.pop("m1replay", False)
    tr = simulate(D.feat_of(c["sym"], c["tf"]), setups(c), inst_for(c["sym"], mg.get("frac1", .5)), mg,
                  m1df=D.m1(c["sym"]) if m1r else None, **kw)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = D.comp_key(c), c["sym"], pd.Timestamp(t["entry_time"])
    return tr


def combine_cap(trs, order, cap=2):
    """Per Globex day at most `cap` trades in total (any market), never two open on the same market:
    a fill is skipped if an earlier taken trade on that market is still open. Causal: only earlier fills block."""
    rank = {k: i for i, k in enumerate(order)}
    allt = sorted((t for tr in trs for t in tr), key=lambda t: (t["ts"], rank.get(t["comp"], 99)))
    taken, cnt, open_until = [], {}, {}
    for t in allt:
        dkey = (t["ts"] + pd.Timedelta(hours=6)).normalize()
        if cnt.get(dkey, 0) >= cap:
            continue
        if t["sym"] in open_until and t["ts"] <= open_until[t["sym"]]:
            continue
        cnt[dkey] = cnt.get(dkey, 0) + 1
        open_until[t["sym"]] = pd.Timestamp(t["exit_time"])
        taken.append(t)
    return taken


def portfolio(comps, mg, rule="per_market", **kw):
    trs = [run_comp(c, mg, **dict(kw)) for c in comps]
    if rule == "cap2":
        return combine_cap(trs, [D.comp_key(c) for c in comps], 2)
    return D.combine(trs, rule, [D.comp_key(c) for c in comps])


def mstats(tr):
    """Monthly net $ split by IS months."""
    mo = D.months(tr)
    return mo, sum(v > 0 for v in mo.values()), sum(v > 0 for k, v in mo.items() if k < CUT[:7])


def report(tr, nd):
    r = D.report_port(tr, nd)
    r["pos_is_months"] = int(sum(v > 0 for k, v in r["months"].items() if k < CUT[:7]))
    r["pos_months"] = int(r["pos_months"])
    return r


# ----------------------------------------------------------------- grid

def exit_grid():
    out = []
    for tp1, frac, after, tp, ts, nft in itertools.product((0.5, 0.75, 1.0), (0.5, 2 / 3), (0.0, -0.5), (2.0, 3.0),
                                                           (4, 8, 12, 16), (0, 3)):
        out.append(dict(tp1=tp1, frac1=frac, after=after, tp=tp, tstop=ts, nft=nft))
    return out


def mg_name(mg):
    return (f"tp1 {mg['tp1']}R x{'2/3' if mg['frac1'] > .6 else '1/2'} -> stop {'BE' if mg['after'] == 0 else str(mg['after']) + 'R'}"
            f" runner {mg['tp']}R ts{mg['tstop']}" + (f" nft{mg['nft']}" if mg.get("nft") else ""))


def grid(log=print):
    nd = D.trading_days()
    rows = []
    for mf in (0.15, 0.3):
        comps = comps_of(mf)
        for mg in exit_grid():
            rep = report(portfolio(comps, mg), nd)
            rows.append(dict(mf=mf, mg=mg, name=mg_name(mg), **{k: rep[k] for k in ("full", "is_", "oos", "pos_months",
                                                                                     "n_months", "pos_is_months")}))
            log(f"mf{mf} {mg_name(mg):55s} {D.line(rep)}")
    D.jdump(OUT / "exits_grid.json", rows)
    return rows


# ----------------------------------------------------------------- selection (IS only)

def eligible(r, tpd_min=0.8):
    s = r["is_"]
    return s["tpd"] >= tpd_min and s["pf"] >= 1.3 and s["exp"] > 0 and int(r["pos_is_months"]) >= 5


def pick(rows, tpd_min=0.8):
    """Pre-declared IS rule: IS trades/day >= 0.8, IS PF >= 1.3, IS exp > 0, >= 5/7 IS months positive;
    then highest IS WR (ties: IS PF)."""
    el = [r for r in rows if eligible(r, tpd_min)]
    el.sort(key=lambda r: (-round(r["is_"]["wr"], 4), -r["is_"]["pf"]))
    return el


def neighbours(mg):
    vals = dict(tp1=(0.5, 0.75, 1.0), frac1=(0.5, 2 / 3), after=(0.0, -0.5), tp=(2.0, 3.0), tstop=(4, 6, 8, 10, 12, 16),
                nft=(0, 2, 3, 4, 5))
    out = []
    for k, vs in vals.items():
        j = min(range(len(vs)), key=lambda q: abs(vs[q] - mg[k]))
        for q in (j - 1, j + 1):
            if 0 <= q < len(vs):
                out.append((k, dict(mg, **{k: vs[q]})))
    return out


def _comps(mf):
    return comps_mix(*mf) if isinstance(mf, list) else comps_of(mf)


def _alt_mf(mf):
    if isinstance(mf, list):
        return [("mf_" + "ALN"[j], [x if q != j else (0.3 if x == 0.15 else 0.15) for q, x in enumerate(mf)]) for j in range(3)]
    return [("mf", 0.3 if mf == 0.15 else 0.15)]


def final(stage=1, log=print):
    rows = json.loads((OUT / ("exits_grid.json" if stage == 1 else "exits_grid2.json")).read_text())
    nd = D.trading_days()
    el = pick(rows, 0.8 if stage == 1 else 0.85)
    log(f"configs in grid: {len(rows)}, eligible on IS: {len(el)}")
    for r in el[:10]:
        log(f"  mf{r['mf']} {r['name']:55s} IS WR {r['is_']['wr']:.1%} PF {r['is_']['pf']:.2f} exp {r['is_']['exp']:+.3f} "
            f"tpd {r['is_']['tpd']:.2f} | OOS WR {r['oos']['wr']:.1%} PF {r['oos']['pf']:.2f}")
    out = dict(trading_days=nd, configs=len(rows), eligible=len(el), top=[{k: r[k] for k in ("mf", "name", "is_", "oos")}
                                                                          for r in el[:15]])
    if not el:
        D.jdump(OUT / ("exits_final.json" if stage == 1 else "exits_final2.json"), out)
        return out
    best = el[0]
    mg, comps = best["mg"], _comps(best["mf"])
    out["chosen"] = dict(mf=best["mf"], mg=mg, name=best["name"])
    res = {}
    for tag, kw in (("base", {}), ("conservative", dict(intrabar="conservative")), ("slip2", dict(slip_ticks=2)),
                    ("cons+slip2", dict(intrabar="conservative", slip_ticks=2)), ("worst", dict(intrabar="worst")),
                    ("worst+slip2", dict(intrabar="worst", slip_ticks=2)), ("m1 replay", dict(m1replay=True)),
                    ("m1 replay+slip2", dict(m1replay=True, slip_ticks=2))):
        tr = portfolio(comps, mg, **kw)
        rep = report(tr, nd)
        res[tag] = rep
        log(f"{tag:16s} {D.line(rep)}")
        if tag == "base":
            log("  months $: " + ", ".join(f"{k[2:]} {v:+.0f}" for k, v in rep["months"].items()))
            for sym in ("MNQ", "MGC"):
                for comp in sorted({t['comp'] for t in tr if t['sym'] == sym}):
                    sub = [t for t in tr if t["comp"] == comp]
                    a, b = D.split(sub)
                    log(f"  {comp:28s} IS {D.fmt(D.stats(a))} | OOS {D.fmt(D.stats(b))}")
            reasons = {}
            for t in tr:
                reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
            log(f"  exits: {reasons}; avg win {np.mean([t['r'] for t in tr if t['pnl'] > 0]):+.2f}R, "
                f"avg loss {np.mean([t['r'] for t in tr if t['pnl'] <= 0]):+.2f}R")
    out["robust"] = res
    log("neighbours (one exit parameter one step, plus other mf):")
    nb = []
    for k, m2 in neighbours(mg) + _alt_mf(best["mf"]):
        cs = _comps(m2) if k.startswith("mf") else comps
        m2 = mg if k.startswith("mf") else m2
        rep = report(portfolio(cs, m2), nd)
        nb.append(dict(changed=k, mg=m2, comps=[D.comp_key(c) for c in cs],
                       rep={q: rep[q] for q in ("full", "is_", "oos", "pos_months")}))
        log(f"  {k:6s} {mg_name(m2):55s} {D.line(rep)}")
    out["neighbours"] = nb
    # "first" rule (max 1/day total) for reference
    rep = report(portfolio(comps, mg, rule="first"), nd)
    out["first_per_day"] = rep
    log(f"first/day rule  {D.line(rep)}")
    D.jdump(OUT / ("exits_final.json" if stage == 1 else "exits_final2.json"), out)
    return out


def real(comps=None, mg=None, log=print):
    """Real CME MNQ/MGC 15m (from the 5m store), same window on the proxy for comparison.
    Default: the stage-3 pick."""
    from . import research
    if comps is None:
        comps = comps_mix(*S2_PICK["mf"]) + [dict(sym="MGC", tf="15min", win="asia", mf=0.3, chase=1.0)]
        mg = S2_PICK["mg"]
    st = research.load_store(["MNQ", "MGC"], ["15m", "5m"])
    out = {}
    saved = dict(D._CACHE)
    try:
        for src in ("real", "proxy"):
            trs = []
            for c in comps:
                real_df = st.get((c["sym"], "5m"))
                lo, hi = real_df.index[0], real_df.index[-1]
                if src == "real":
                    df = data.resample(real_df, "15min")
                else:
                    d1 = D.m1(c["sym"])
                    df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], "15min")
                inst = inst_for(c["sym"], mg["frac1"])
                f = features.build(df, inst.tick)
                D._CACHE[("feat", c["sym"], c["tf"])] = f
                ss = D.setups_of(c["sym"], c["tf"], c["win"], c["mf"], c["chase"])
                tr = simulate(f, ss, inst, mg)
                for t in tr:
                    t["comp"], t["sym"], t["ts"] = D.comp_key(c), c["sym"], pd.Timestamp(t["entry_time"])
                trs.append(tr)
                D._CACHE.pop(("feat", c["sym"], c["tf"]))
            pt = D.combine(trs, "per_market", [D.comp_key(c) for c in comps])
            days = len({(t["ts"] + pd.Timedelta(hours=6)).normalize() for t in pt})
            s = D.stats(pt)
            nd_ = len(np.unique(features.build(data.resample(st[("MNQ", "5m")], "15min"), 0.25).day))
            out[src] = dict(stats=s, start=str(lo), end=str(hi), days=nd_, by_comp={
                D.comp_key(c): D.stats([t for t in pt if t["comp"] == D.comp_key(c)]) for c in comps})
            log(f"{src:6s} {lo:%Y-%m-%d}..{hi:%Y-%m-%d} {D.fmt(s)} tpd {len(pt) / nd_:.2f} (days with a trade {days}/{nd_})")
            for k, v in out[src]["by_comp"].items():
                log(f"   {k:30s} {D.fmt(v)}")
    finally:
        D._CACHE.clear()
        D._CACHE.update(saved)
    D.jdump(OUT / "exits_real.json", out)
    return out


def selftest():
    """With after=0 (BE), nft=0 the simulator must equal daily_portfolio.simulate."""
    c = comps_of(0.15)[1]
    mg = dict(tp1=1.0, frac1=0.5, after=0.0, tp=3.0, tstop=8, nft=0)
    a = run_comp(c, mg)
    b = D.run_comp(c)
    assert [(x["entry_time"], round(x["pnl"], 6)) for x in a] == [(x["entry_time"], round(x["pnl"], 6)) for x in b]
    print("selftest OK", len(a))


# ----------------------------------------------------------------- stage 2: per-session min FVG (entry frequency)

def comps_mix(mfa, mfl, mfn, mf_gc=0.3):
    return ([dict(sym="MNQ", tf="15min", win=w, mf=m, chase=1.0) for w, m in (("asia", mfa), ("london", mfl), ("ny_am", mfn))]
            + [dict(sym="MGC", tf="15min", win="comex", mf=mf_gc, chase=0.0)])


def stage2_exits():
    return [dict(tp1=0.5, frac1=fr, after=0.0, tp=2.0, tstop=ts, nft=nf)
            for fr in (0.5, 2 / 3) for ts in (8, 12, 16) for nf in (0, 3)]


def grid2(log=print):
    nd = D.trading_days()
    rows = []
    for mfa, mfl, mfn in itertools.product((0.15, 0.3), repeat=3):
        for mg in stage2_exits():
            rep = report(portfolio(comps_mix(mfa, mfl, mfn), mg), nd)
            rows.append(dict(mf=[mfa, mfl, mfn], mg=mg, name=mg_name(mg),
                             **{k: rep[k] for k in ("full", "is_", "oos", "pos_months", "n_months", "pos_is_months")}))
            s = rep["is_"]
            log(f"A{mfa} L{mfl} N{mfn} {mg_name(mg):50s} IS {D.fmt(s)} tpd {s['tpd']:.2f} +m {rep['pos_is_months']}/7")
    D.jdump(OUT / "exits_grid2.json", rows)
    return rows



# ----------------------------------------------------------------- stage 3: one extra component for frequency

S2_PICK = dict(mf=[0.15, 0.3, 0.3], mg=dict(tp1=0.5, frac1=2 / 3, after=0.0, tp=2.0, tstop=8, nft=0))
EXTRA = [dict(sym=s, tf="15min", win=w, mf=0.3, chase=ch) for s, w in (("MNQ", "pre_lon"), ("MNQ", "lon_late"),
         ("MGC", "asia"), ("MGC", "london"), ("MGC", "lon_late"), ("MGC", "ny_pm"), ("MCL", "nymex"), ("MCL", "london"))
         for ch in (0.0, 1.0)]


def robust(comps, mg, nd, log=print, rule="per_market"):
    res = {}
    for tag, kw in (("base", {}), ("slip2", dict(slip_ticks=2)), ("conservative", dict(intrabar="conservative")),
                    ("worst", dict(intrabar="worst")), ("worst+slip2", dict(intrabar="worst", slip_ticks=2)),
                    ("m1 replay", dict(m1replay=True)), ("m1 replay+slip2", dict(m1replay=True, slip_ticks=2))):
        tr = portfolio(comps, mg, rule=rule, **kw)
        rep = report(tr, nd)
        res[tag] = rep
        log(f"{tag:16s} {D.line(rep)}")
        if tag == "base":
            log("  months $: " + ", ".join(f"{k[2:]} {v:+.0f}" for k, v in rep["months"].items()))
            for comp in [D.comp_key(c) for c in comps]:
                sub = [t for t in tr if t["comp"] == comp]
                a, b = D.split(sub)
                log(f"  {comp:30s} IS {D.fmt(D.stats(a))} | OOS {D.fmt(D.stats(b))}")
            reasons = {}
            for t in tr:
                reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
            per_day = {}
            for t in tr:
                k = (t["ts"] + pd.Timedelta(hours=6)).normalize()
                per_day[k] = per_day.get(k, 0) + 1
            log(f"  exits {reasons}; days with >=1 trade {len(per_day)}/{nd[0]}, max/day {max(per_day.values())}; "
                f"avg win {np.mean([t['r'] for t in tr if t['pnl'] > 0]):+.2f}R avg loss {np.mean([t['r'] for t in tr if t['pnl'] <= 0]):+.2f}R")
    return res


def stage3(log=print):
    nd = D.trading_days()
    base = comps_mix(*S2_PICK["mf"])
    mg = S2_PICK["mg"]
    rows = []
    for c in EXTRA:
        rep = report(portfolio(base + [c], mg), nd)
        rows.append(dict(extra=c, key=D.comp_key(c), **{k: rep[k] for k in ("full", "is_", "oos", "pos_months", "pos_is_months")}))
        log(f"+ {D.comp_key(c):30s} IS {D.fmt(rep['is_'])} tpd {rep['is_']['tpd']:.2f} +m {rep['pos_is_months']}/7")
    # IS-only rule: max 2 trades/day (MNQ or MGC additions only), IS WR >= 58 %, PF >= 1.3, tpd >= 0.9, >= 5/7 months
    el = [r for r in rows if r["extra"]["sym"] != "MCL" and r["is_"]["wr"] >= 0.58 and r["is_"]["pf"] >= 1.3
          and r["is_"]["tpd"] >= 0.9 and r["pos_is_months"] >= 5]
    el.sort(key=lambda r: -r["is_"]["pf"])
    out = dict(configs=len(rows), rows=rows)
    if el:
        pk = el[0]
        log(f"IS pick: + {pk['key']}")
        comps = base + [pk["extra"]]
        out["chosen"] = dict(comps=[D.comp_key(c) for c in comps], mg=mg)
        out["robust"] = robust(comps, mg, nd, log)
        nb = []
        log("neighbours:")
        alts = [("tp1", dict(mg, tp1=0.75)), ("frac", dict(mg, frac1=0.5)), ("after", dict(mg, after=-0.5)),
                ("tp", dict(mg, tp=3.0)), ("ts6", dict(mg, tstop=6)), ("ts12", dict(mg, tstop=12)),
                ("ts16", dict(mg, tstop=16)), ("nft3", dict(mg, nft=3))]
        for k, m2 in alts:
            rep = report(portfolio(comps, m2), nd)
            nb.append(dict(changed=k, rep={q: rep[q] for q in ("full", "is_", "oos", "pos_months")}))
            log(f"  {k:10s} {D.line(rep)}")
        e = pk["extra"]
        for k, c2 in (("extra mf0.15", dict(e, mf=0.15)), ("extra chase", dict(e, chase=1.0 if not e["chase"] else 0.0)),
                      ("extra 10min", dict(e, tf="10min")), ("extra 30min", dict(e, tf="30min"))):
            rep = report(portfolio(base + [c2], mg), nd)
            nb.append(dict(changed=k, rep={q: rep[q] for q in ("full", "is_", "oos", "pos_months")}))
            log(f"  {k:10s} {D.line(rep)}")
        out["neighbours"] = nb
    D.jdump(OUT / "exits_stage3.json", out)
    return out


def truncation_check():
    """The 5 chosen entry streams (generate + chase filter) on df[:k] equal the full-data ones for bars < k-1."""
    comps = comps_mix(*S2_PICK["mf"]) + [dict(sym="MGC", tf="15min", win="asia", mf=0.3, chase=1.0)]
    for c in comps:
        inst = D.inst_of(c["sym"])
        df = data.resample(D.m1(c["sym"]), c["tf"])

        def gen(d):
            f = features.build(d, inst.tick)
            from . import fvg_pro
            ss = fvg_pro.generate(f, inst, dict(windows=D.WINDOWS[c["win"]], min_fvg_atr=c["mf"], max_trades=1, entry="edge"))
            return [(s.bar, s.side, s.entry, s.stop) for s in ss if not (
                c["chase"] and f.atr[s.bar] > 0 and s.side * (f.c[s.bar] - s.entry) / f.atr[s.bar] > c["chase"])]
        full = gen(df)
        for k in (7000, 16000, 24000):
            part = gen(df.iloc[:k])
            assert [x for x in full if x[0] < k - 1] == [x for x in part if x[0] < k - 1], (D.comp_key(c), k)
    print("truncation check (5 chosen streams) OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        grid()
    elif cmd == "final":
        final(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif cmd == "stage3":
        stage3()
    elif cmd == "grid2":
        grid2()
    elif cmd == "real":
        real()
    elif cmd == "trunc":
        selftest()
        truncation_check()

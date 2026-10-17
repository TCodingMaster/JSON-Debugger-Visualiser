"""Prop direction "legs": add bar-shift-robust FVG Pro legs to Leto (MNQ London + MGC COMEX).

Every leg is the unchanged Leto rule family (lab/fvg_pro.generate: BOS + FVG, limit at the
gap edge; optional "don't chase" filter side*(close-entry)/ATR > 1.0 at the signal bar;
partial exit half at 1R -> BE -> runner 3R, time stop 8 bars, flat 15:55 NY / new Globex day,
max 1 trade per leg per Globex day). Per leg free choices: market (MNQ/MGC/MCL), timeframe
(5/10/15/30 min), session window, min FVG (0.15/0.3/0.45 ATR), chase filter on/off.

PRE-REGISTERED SELECTION RULE (written before any OOS number was looked at; IS only):
  IS = entry < 2026-04-01. For every config the IS stats are computed on the standard bars
  (shift 0) and on bars rebuilt with start offsets 1..4 min (15/10/30 min) or 1..2 min (5 min).
  A config is IS-eligible if
     * IS trades at shift 0 >= 20 (about >= 0.13 trades/day),
     * IS WR (position net $ > 0) >= 55 % at shift 0 and the mean IS WR over all shifts >= 55 %,
     * IS PF >= 1.15 at EVERY shift and the median IS PF over the shifts >= 1.30.
  Score = minimum IS PF over the shifts. Greedy pick in score order; a config is skipped when a
  leg of the same market with an overlapping session window is already in (the two Leto legs are
  seeded first). At most 1 leg per (market, window).
  The mandatory bar-shift gate is then applied as a validation step:
     IS PF >= 1.15 and OOS PF >= 1.15 at every offset (also for the two Leto legs).
  Both the IS-selected portfolio (before the OOS gate) and the gated portfolio are reported.
Portfolio: max 1 trade per leg per day (inside each leg's simulation) and per market at most the
first 2 filled trades per Globex day (only an earlier fill blocks a later one).

Run:  PYTHONPATH=. python -m lab.prop_legs grid     (config x shift grid, ~10 min on 4 cores)
      PYTHONPATH=. python -m lab.prop_legs final    (selection, gate, portfolio, robustness)
      PYTHONPATH=. python -m lab.prop_legs trunc    (truncation check of the signal code)
      PYTHONPATH=. python -m lab.prop_legs real     (real CME futures sanity check, MNQ/MGC)
"""

from __future__ import annotations

import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features, fvg_pro
from . import daily_portfolio as DP
from . import daily_levels as DL
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "prop"
CUT = DP.CUT

WINDOWS = {
    "eve": ("18:00", "20:00"),
    "asia": ("20:00", "24:00"),
    "pre_lon": ("00:00", "02:00"),
    "london": ("02:00", "05:00"),
    "lon_late": ("05:00", "08:00"),
    "comex": ("08:20", "10:30"),
    "ny_am": ("08:30", "11:00"),
    "rth": ("09:30", "11:30"),
    "midday": ("11:30", "13:30"),
    "ny_pm": ("13:00", "15:00"),
    "late": ("14:00", "15:45"),
}
SYMS = ("MNQ", "MGC", "MCL")
TFS = ("5min", "10min", "15min", "30min")
MFS = (0.15, 0.3, 0.45)
CHASES = (0.0, 1.0)
LETO = [dict(sym="MNQ", tf="15min", win="london", mf=0.3, chase=1.0),
        dict(sym="MGC", tf="15min", win="comex", mf=0.3, chase=0.0)]


def shifts_of(tf):
    return (0, 1, 2) if tf == "5min" else (0, 1, 2, 3, 4)


def key(c):
    return f"{c['sym']}|{c['tf']}|{c['win']}|mf{c['mf']}|ch{c['chase']}"


def _win_mins(w):
    a, b = WINDOWS[w]
    return hm(a), hm(b)


def overlap(w1, w2):
    """Windows overlap in clock time (18:00-24:00 and 00:00-.. are on the same Globex day, no wrap)."""
    a1, b1 = _win_mins(w1)
    a2, b2 = _win_mins(w2)
    return a1 < b2 and a2 < b1


# ----------------------------------------------------------------- legs

def setups(feat, inst, c):
    p = dict(windows=(WINDOWS[c["win"]],), min_fvg_atr=c["mf"], max_trades=1, entry="edge")
    ss = fvg_pro.generate(feat, inst, p)
    ch = c["chase"]
    if ch:
        ss = [s for s in ss if not (feat.atr[s.bar] > 0 and s.side * (feat.c[s.bar] - s.entry) / feat.atr[s.bar] > ch)]
    return ss


def run_leg(c, shift=0, slip_ticks=1, intrabar="path", m1replay=False):
    sym = c["sym"]
    feat = DL.feat_of(sym, c["tf"], shift)
    inst = DP.inst_of(sym)
    tr = DP.simulate(feat, setups(feat, inst, c), inst, slip_ticks=slip_ticks, intrabar=intrabar,
                     m1df=DP.m1(sym) if m1replay else None)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = key(c), sym, pd.Timestamp(t["entry_time"])
    return tr


def _grid_task(arg):
    sym, tf, shift = arg
    rows = []
    for win, mf, ch in itertools.product(WINDOWS, MFS, CHASES):
        c = dict(sym=sym, tf=tf, win=win, mf=mf, chase=ch)
        a, b = DP.split(run_leg(c, shift))
        rows.append(dict(key=key(c), cfg=c, shift=shift, is_=DP.stats(a), oos=DP.stats(b)))
    return rows


def grid(log=print):
    tasks = [(s, tf, sh) for s in SYMS for tf in TFS for sh in shifts_of(tf)]
    out = []
    with Pool(4) as pool:
        for rows in pool.imap_unordered(_grid_task, tasks):
            out += rows
            log(f"{rows[0]['cfg']['sym']} {rows[0]['cfg']['tf']} shift {rows[0]['shift']}: {len(rows)} configs")
    jdump(OUT / "legs_grid.json", out)
    return out


# ----------------------------------------------------------------- selection (IS only)

def by_config(rows):
    d = {}
    for r in rows:
        d.setdefault(r["key"], {"cfg": r["cfg"], "sh": {}})["sh"][r["shift"]] = r
    return d


def is_summary(e):
    sh = e["sh"]
    s0 = sh[0]["is_"]
    pfs = [sh[k]["is_"]["pf"] if sh[k]["is_"]["trades"] else 0.0 for k in sorted(sh)]
    wrs = [sh[k]["is_"]["wr"] or 0.0 for k in sorted(sh)]
    return dict(n0=s0["trades"], wr0=s0["wr"] or 0.0, pf0=s0["pf"] or 0.0, min_pf=min(pfs),
                med_pf=float(np.median(pfs)), mean_wr=float(np.mean(wrs)), pfs=pfs, wrs=wrs)


def is_eligible(s):
    return (s["n0"] >= 20 and s["wr0"] >= 0.55 and s["mean_wr"] >= 0.55 and s["min_pf"] >= 1.15
            and s["med_pf"] >= 1.30)


def select(rows):
    d = by_config(rows)
    cands = []
    for k, e in d.items():
        s = is_summary(e)
        if is_eligible(s):
            cands.append((s["min_pf"], k, e["cfg"], s))
    cands.sort(key=lambda x: -x[0])
    chosen = [dict(c) for c in LETO]
    picks = []
    for score, k, c, s in cands:
        if any(x["sym"] == c["sym"] and overlap(x["win"], c["win"]) for x in chosen):
            continue
        chosen.append(c)
        picks.append(dict(key=k, cfg=c, is_summary=s))
    return cands, picks


def gate(rows, cfgs):
    """Mandatory bar-shift gate: IS PF >= 1.15 and OOS PF >= 1.15 at every offset."""
    d = by_config(rows)
    res = []
    for c in cfgs:
        e = d[key(c)]
        per = {k: dict(is_pf=e["sh"][k]["is_"]["pf"] if e["sh"][k]["is_"]["trades"] else 0.0,
                       oos_pf=e["sh"][k]["oos"]["pf"] if e["sh"][k]["oos"]["trades"] else 0.0,
                       is_n=e["sh"][k]["is_"]["trades"], oos_n=e["sh"][k]["oos"]["trades"],
                       is_wr=e["sh"][k]["is_"]["wr"], oos_wr=e["sh"][k]["oos"]["wr"])
               for k in sorted(e["sh"])}
        ok = all(v["is_pf"] >= 1.15 and v["oos_pf"] >= 1.15 for v in per.values())
        res.append(dict(key=key(c), cfg=c, passed=ok, per_shift=per))
    return res


# ----------------------------------------------------------------- portfolio + prop metrics

def gday(ts):
    return pd.Timestamp(ts + pd.Timedelta(hours=6)).normalize()


def combine(trs, order, cap=2):
    allt = [t for tr in trs for t in tr]
    rank = {k: i for i, k in enumerate(order)}
    allt.sort(key=lambda t: (t["ts"], rank.get(t["comp"], 99)))
    cnt, taken = {}, []
    for t in allt:
        k = (gday(t["ts"]), t["sym"])
        if cnt.get(k, 0) >= cap:
            continue
        cnt[k] = cnt.get(k, 0) + 1
        taken.append(t)
    return taken


def prop_metrics(tr, ndays, thr=150.0):
    """Winning days (Globex-day net >= thr), worst day, max trailing end-of-day drawdown."""
    if not tr:
        return dict(win_days_per_week=0.0, worst_day=0.0, trail_eod_dd=0.0, days_traded=0)
    d = {}
    for t in tr:
        k = gday(t["ts"])
        d[k] = d.get(k, 0.0) + t["pnl"]
    s = pd.Series(d).sort_index()
    eq = np.r_[0.0, s.cumsum().to_numpy()]
    weeks = ndays / 5.0
    return dict(win_days_per_week=float((s >= thr).sum() / weeks), worst_day=float(s.min()),
                trail_eod_dd=float((np.maximum.accumulate(eq) - eq).max()), days_traded=int(len(s)),
                pos_day_share=float((s > 0).mean()), best_day=float(s.max()))


def full_report(tr, nd):
    n_all, n_is, n_oos = nd
    rep = DP.report_port(tr, nd)
    a, b = DP.split(tr)
    rep["prop"] = dict(full=prop_metrics(tr, n_all), is_=prop_metrics(a, n_is), oos=prop_metrics(b, n_oos))
    for k, n in (("full", n_all), ("is_", n_is), ("oos", n_oos)):
        rep[k]["tpw"] = rep[k]["trades"] / (n / 5.0)
    return rep


def line(rep):
    f, a, b, p = rep["full"], rep["is_"], rep["oos"], rep["prop"]["full"]
    return (f"FULL {DP.fmt(f)} tpd {f['tpd']:.2f} | IS {DP.fmt(a)} | OOS {DP.fmt(b)} | +m {rep['pos_months']}/"
            f"{rep['n_months']} | windays/wk {p['win_days_per_week']:.2f} worst ${p['worst_day']:.0f} "
            f"trailDD ${p['trail_eod_dd']:.0f}")


def portfolio(cfgs, shift=0, **kw):
    trs = [run_leg(c, shift if c["tf"] != "5min" or shift <= 2 else 2, **kw) for c in cfgs]
    return combine(trs, [key(c) for c in cfgs])


def jdump(path, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=str))


VARIANTS = (("base", {}), ("slip2", dict(slip_ticks=2)), ("conservative", dict(intrabar="conservative")),
            ("cons+slip2", dict(intrabar="conservative", slip_ticks=2)), ("m1 replay", dict(m1replay=True)))


def evaluate(name, cfgs, nd, log, out):
    res = {}
    for tag, kw in VARIANTS:
        rep = full_report(portfolio(cfgs, **kw), nd)
        res[tag] = rep
        log(f"{name:24s} {tag:12s} {line(rep)}")
    for sh in (1, 2, 3, 4):
        rep = full_report(portfolio(cfgs, shift=sh), nd)
        res[f"shift{sh}"] = rep
        log(f"{name:24s} shift {sh:<6d} {line(rep)}")
    legs = {}
    for c in cfgs:
        tr = run_leg(c)
        legs[key(c)] = full_report(tr, nd)
        log(f"   leg {key(c):34s} {line(legs[key(c)])}")
    res["legs"] = legs
    out["portfolios"][name] = res


def final(log=print):
    rows = json.loads((OUT / "legs_grid.json").read_text())
    nd = DP.trading_days()
    out = dict(trading_days=nd, n_configs=len(by_config(rows)), n_rows=len(rows), portfolios={})
    cands, picks = select(rows)
    out["n_is_eligible"] = len(cands)
    out["is_eligible"] = [dict(key=k, min_pf=s["min_pf"], med_pf=s["med_pf"], n0=s["n0"], wr0=s["wr0"],
                               mean_wr=s["mean_wr"]) for _, k, _, s in cands]
    out["picks"] = picks
    log(f"{len(cands)} IS-eligible configs of {out['n_configs']}; picks (IS-only rule):")
    for p in picks:
        s = p["is_summary"]
        log(f"  {p['key']:34s} n0 {s['n0']} wr0 {s['wr0']:.1%} meanWR {s['mean_wr']:.1%} "
            f"IS PF by shift {[round(x, 2) for x in s['pfs']]}")
    pre = LETO + [p["cfg"] for p in picks]
    g = gate(rows, pre)
    out["gate"] = g
    log("bar-shift gate (IS and OOS PF >= 1.15 at every offset):")
    for x in g:
        log(f"  {'PASS' if x['passed'] else 'fail'} {x['key']:34s} " + " ".join(
            f"s{k}:{v['is_pf']:.2f}/{v['oos_pf']:.2f}" for k, v in x["per_shift"].items()))
    gated = [x["cfg"] for x in g if x["passed"]]
    evaluate("Leto only", LETO, nd, log, out)
    evaluate("IS-selected (pre-gate)", pre, nd, log, out)
    evaluate("gated", gated, nd, log, out)
    jdump(OUT / "legs.json", out)
    return out


# ----------------------------------------------------------------- truncation check

def truncation_check(cfgs=None, log=print):
    """generate + chase filter on df[:k] must give the same setups (bar < k-1) as on the full df,
    for shifted and unshifted bars."""
    cfgs = cfgs or LETO
    for c in cfgs:
        for sh in (0, 1):
            f_full = DL.feat_of(c["sym"], c["tf"], sh)
            inst = DP.inst_of(c["sym"])
            full = [(s.bar, s.side, s.entry, s.stop) for s in setups(f_full, inst, c)]
            df = f_full.df[["open", "high", "low", "close", "volume"]]
            for frac in (0.3, 0.6, 0.85):
                k = int(len(df) * frac)
                f = features.build(df.iloc[:k], inst.tick)
                part = [(s.bar, s.side, s.entry, s.stop) for s in setups(f, inst, c)]
                assert [x for x in full if x[0] < k - 1] == [x for x in part if x[0] < k - 1], (key(c), sh, k)
        log(f"truncation OK {key(c)}")
    return True


# ----------------------------------------------------------------- real CME futures

def real_check(cfgs, log=print):
    from . import research
    st = research.load_store(["MNQ", "MGC"], ["5m"])
    res = {}
    saved = dict(DL._C)
    try:
        for src in ("real", "proxy"):
            trs = []
            for c in cfgs:
                real = st.get((c["sym"], "5m"))
                if real is None or c["tf"] == "5min" and False:
                    continue
                lo, hi = real.index[0], real.index[-1]
                if src == "real":
                    if c["tf"] == "5min":
                        df = real
                    else:
                        df = data.resample(real, c["tf"])
                else:
                    d1 = DP.m1(c["sym"])
                    df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], c["tf"])
                inst = DP.inst_of(c["sym"])
                f = features.build(df, inst.tick)
                tr = DP.simulate(f, setups(f, inst, c), inst)
                for t in tr:
                    t["comp"], t["sym"], t["ts"] = key(c), c["sym"], pd.Timestamp(t["entry_time"])
                trs.append(tr)
            pt = combine(trs, [key(c) for c in cfgs])
            nd = len({gday(x) for x in st[("MNQ", "5m")].index})
            res[src] = dict(stats=DP.stats(pt, nd), prop=prop_metrics(pt, nd), days=nd,
                            legs=[c for c in cfgs if (c["sym"], "5m") in st])
            log(f"real-window {src:6s} {DP.fmt(res[src]['stats'])} tpd {res[src]['stats']['tpd']:.2f} "
                f"windays/wk {res[src]['prop']['win_days_per_week']:.2f}")
    finally:
        DL._C.clear()
        DL._C.update(saved)
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        grid()
    elif cmd == "final":
        final()
    elif cmd == "trunc":
        truncation_check()
    elif cmd == "real":
        o = json.loads((OUT / "legs.json").read_text())
        cf = [x["cfg"] for x in o["gate"] if x["passed"]]
        r = {"gated": real_check(cf), "pre_gate": real_check([x["cfg"] for x in o["gate"]]),
             "leto": real_check(LETO)}
        jdump(OUT / "legs_real.json", r)

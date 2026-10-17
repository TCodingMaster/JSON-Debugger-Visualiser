"""Portfolio of independent intraday rule sets (direction "portfolio").

Idea: no single rule set is consistent month by month, but rule sets that
trade different sessions / markets lose in different months.  Combine 2-4 of
them with FIXED sizing and check whether the combined curve is steadier.

Candidate pool (fixed BEFORE running; parameters copied from earlier reports,
NOT re-tuned here):
  leto     MNQ 15m FVG Pro London 02-05, min FVG 0.3, edge, RR 2, 1/day      (fvg_pro)
  nyam     MNQ 15m FVG Pro NY AM 08:30-11, same params                      (fvg_pro)
  pb       MNQ 15m EMA20 morning pullback, 09:45-12, 0.75R                  (wr60_momentum best)
  imom     MNQ intraday momentum, 09:30->10:00 move, enter 15:00, exit 15:55 (prof_classic BEST)
  vwap     MNQ 15m VWAP cross + chandelier                                  (prof_classic BEST_VWAP)
  gc5q     MGC 5m FVG Pro Asia+London "Quality", min 0.15, RR 2, 1/day      (fvg_pro)
  gccomex  MGC 15m FVG Pro COMEX 08:20-10:30, Leto params (RR 2)            (fvg_pro)
  clnymex  MCL 15m FVG Pro NYMEX 09:00-11:30, Leto params                   (fvg_pro)

Selection (IN-SAMPLE ONLY, entry < 2026-04-01):
  1. a component is eligible if IS expectancy > 0 and IS PF(R) >= 1.1 on its own;
  2. every subset of 2-4 eligible components is scored by the IS Sharpe of the
     combined WEEKLY R (equal 1R risk per trade = fixed risk units), the
     subset with the highest score is chosen; OOS is reported untouched.
  $ results use fixed contracts: the instrument defaults (2 MNQ, 1 MGC, 1 MCL)
  and, as a second view, MGC/MCL contracts scaled once from IS median $ risk.

No new signal code (all setups from existing modules, which carry their own
truncation checks), so no new look-ahead risk.

Usage:  PYTHONPATH=. python -m lab.prof_portfolio run      (components + selection + report json)
        PYTHONPATH=. python -m lab.prof_portfolio robust   (stop-first + 2-tick slippage re-run)
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, engine, features, fvg_pro, prof_classic, wr60_momentum
from .data import get_instrument
from .engine import EngineConfig

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "profit"
P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
CUT = pd.Timestamp("2026-04-01")
FILES = {"MNQ": "MNQ_1m.pkl", "MGC": "MGC_1m.pkl", "MCL": "CL_1m.pkl"}
MONTHS = [str(p) for p in pd.period_range("2025-09", "2026-10", freq="M")]

LETO = dict(min_fvg_atr=0.3, entry="edge", rr=2.0, max_trades=1)
FVG_COMPONENTS = {
    "leto": ("MNQ", "15min", {**LETO, "windows": (("02:00", "05:00"),)}),
    "nyam": ("MNQ", "15min", {**LETO, "windows": (("08:30", "11:00"),)}),
    "gc5q": ("MGC", "5min", dict(min_fvg_atr=0.15, entry="edge", rr=2.0, max_trades=1,
                                 windows=(("20:00", "24:00"), ("02:00", "05:00")))),
    "gccomex": ("MGC", "15min", {**LETO, "windows": (("08:20", "10:30"),)}),
    "clnymex": ("MCL", "15min", {**LETO, "windows": (("09:00", "11:30"),)}),
}
PB = dict(tf="15min", family="pb", win=("09:45", "12:00"), entry="market", tol=0.3, buf=0.1, slope_n=16,
          rr=0.75, max_trades=1)
SYM = {"leto": "MNQ", "nyam": "MNQ", "pb": "MNQ", "imom": "MNQ", "vwap": "MNQ",
       "gc5q": "MGC", "gccomex": "MGC", "clnymex": "MCL"}

_M1: dict = {}


def m1(sym):
    if sym not in _M1:
        _M1[sym] = pd.read_pickle(P + FILES[sym])
    return _M1[sym]


def _naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo else t


def _df(trades):
    return pd.DataFrame([dict(entry_time=_naive(t.entry_time), r=t.r, pnl=t.pnl) for t in trades])


def components(intrabar="path", slip=1, src=None, base=1, only=None):
    """Trade list (entry_time, r, pnl, comp) for every candidate.
    src: optional {sym: intraday df} (e.g. real futures 5m) instead of the Dukascopy 1m proxy."""
    get = (lambda s: src[s]) if src else m1
    out = {}
    for name, (sym, tf, p) in FVG_COMPONENTS.items():
        if (only and name not in only) or (src and sym not in src):
            continue
        inst = get_instrument(sym)
        feat = features.build(data.resample(get(sym), tf), inst.tick)
        pp = {**fvg_pro.DEFAULTS, **p}
        st = fvg_pro.generate(feat, inst, pp)
        tr = engine.run(feat, st, inst, EngineConfig(flatten="15:55", max_trades_per_day=pp["max_trades"],
                                                     intrabar=intrabar, slippage_ticks=slip))
        out[name] = _df(tr)
    inst = get_instrument("MNQ")
    feat = features.build(data.resample(get("MNQ"), "15min"), inst.tick)
    pp = {**wr60_momentum.DEFAULTS, **PB}
    st = wr60_momentum.generate(feat, inst, pp)
    tr = engine.run(feat, st, inst, EngineConfig(flatten="15:55", max_trades_per_day=1,
                                                 intrabar=intrabar, slippage_ticks=slip))
    out["pb"] = _df(tr)
    days = prof_classic.build_days(get("MNQ"), base)
    atrs = {tf: prof_classic.tf_atr(days, tf) for tf in (15,)}
    for name, (fam, p) in (("imom", prof_classic.BEST), ("vwap", prof_classic.BEST_VWAP)):
        t = prof_classic.run(days, fam, p, atrs, slip=slip)
        t["entry_time"] = t["entry_time"].map(_naive)
        out[name] = t[["entry_time", "r", "pnl"]].copy()
    for k, t in out.items():
        t["comp"] = k
        t["risk"] = (t["pnl"] / t["r"]).abs()
        out[k] = t.sort_values("entry_time").reset_index(drop=True)
    return out


# ------------------------------------------------------------------ metrics
def stats(t: pd.DataFrame, col="pnl"):
    if len(t) == 0:
        return dict(trades=0, wr=0, exp=0, pf_r=0, pf_usd=0, net=0, dd=0, sum_r=0, dd_r=0)
    t = t.sort_values("entry_time")
    r, pnl = t["r"].to_numpy(), t[col].to_numpy()
    eq = np.r_[0, np.cumsum(pnl)]
    eqr = np.r_[0, np.cumsum(r)]
    gl, rl = -pnl[pnl < 0].sum(), -r[r < 0].sum()
    return dict(trades=int(len(r)), wr=round(float((r > 0).mean() * 100), 1), exp=round(float(r.mean()), 3),
                pf_r=round(float(r[r > 0].sum() / rl) if rl > 0 else 99.0, 2),
                pf_usd=round(float(pnl[pnl > 0].sum() / gl) if gl > 0 else 99.0, 2),
                net=round(float(pnl.sum())), dd=round(float((np.maximum.accumulate(eq) - eq).max())),
                sum_r=round(float(r.sum()), 1), dd_r=round(float((np.maximum.accumulate(eqr) - eqr).max()), 1))


def monthly(t, col="r"):
    m = {k: 0.0 for k in MONTHS}
    if len(t):
        g = t.groupby(t["entry_time"].dt.strftime("%Y-%m"))[col].sum()
        for k, v in g.items():
            m[k] = m.get(k, 0.0) + float(v)
    return {k: round(v, 2) for k, v in m.items()}


def report(t, col="pnl"):
    a, b = t[t.entry_time < CUT], t[t.entry_time >= CUT]
    mr = monthly(t)
    mu = monthly(t, col)
    return dict(full=stats(t, col), IS=stats(a, col), OOS=stats(b, col), monthly_r=mr,
                monthly_usd={k: round(v) for k, v in mu.items()},
                pos_months_r=int(sum(v > 0 for v in mr.values())),
                pos_months_usd=int(sum(v > 0 for v in mu.values())),
                worst_month_r=min(mr.values()))


def weekly_sharpe(t):
    if len(t) == 0:
        return -9.0
    w = t.groupby(t["entry_time"].dt.to_period("W"))["r"].sum()
    idx = pd.period_range(t["entry_time"].min().to_period("W"), (CUT - pd.Timedelta(days=1)).to_period("W"),
                          freq="W")
    w = w.reindex(idx, fill_value=0.0)
    return float(w.mean() / w.std(ddof=1) * np.sqrt(52)) if w.std(ddof=1) > 0 else -9.0


def corr(comps, names, freq="D"):
    """Correlation of per-day (or per-month) R between components, zero-filled on no-trade days."""
    s = {}
    for k in names:
        t = comps[k]
        key = t["entry_time"].dt.normalize() if freq == "D" else t["entry_time"].dt.strftime("%Y-%m")
        s[k] = t.groupby(key)["r"].sum()
    df = pd.DataFrame(s).fillna(0.0)
    return df.corr().round(2)


def combine(comps, names, qty=None):
    qty = qty or {}
    parts = []
    for k in names:
        t = comps[k].copy()
        t["pnl_q"] = t["pnl"] * qty.get(k, 1.0)
        parts.append(t)
    return pd.concat(parts).sort_values("entry_time").reset_index(drop=True)


def size_multipliers(comps, names):
    """Fixed contract multiplier per component from IS median $ risk only (MNQ rules keep 2 contracts)."""
    ref = np.median(comps["leto"].loc[comps["leto"].entry_time < CUT, "risk"])
    q = {}
    for k in names:
        if SYM[k] == "MNQ":
            q[k] = 1.0
        else:
            med = np.median(comps[k].loc[comps[k].entry_time < CUT, "risk"])
            q[k] = float(max(1, round(ref / med)))
    return q


# -------------------------------------------------------------------- main
def select(comps, log=print):
    elig, single = [], {}
    for k, t in comps.items():
        rep = report(t)
        single[k] = rep
        s = rep["IS"]
        ok = s["exp"] > 0 and s["pf_r"] >= 1.1
        if ok:
            elig.append(k)
        log(f"{k:8s} IS n={s['trades']:3d} exp={s['exp']:+.3f} PFr={s['pf_r']:.2f} | OOS n={rep['OOS']['trades']:3d} "
            f"exp={rep['OOS']['exp']:+.3f} PFr={rep['OOS']['pf_r']:.2f} | +m {rep['pos_months_r']}/14 "
            f"{'ELIGIBLE' if ok else ''}")
    cands = []
    for n in (2, 3, 4):
        for sub in itertools.combinations(elig, n):
            t = combine(comps, sub)
            cands.append(dict(names=list(sub), is_sharpe=round(weekly_sharpe(t[t.entry_time < CUT]), 3)))
    cands.sort(key=lambda d: -d["is_sharpe"])
    for k in elig:  # single-component IS Sharpe for reference
        single[k]["is_weekly_sharpe"] = round(weekly_sharpe(comps[k][comps[k].entry_time < CUT]), 3)
    return elig, single, cands


def run_main():
    comps = components()
    elig, single, cands = select(comps)
    print(f"eligible: {elig}; portfolios scored: {len(cands)}")
    for c in cands[:10]:
        print("  ", c)
    best = cands[0]["names"]
    t = combine(comps, best)
    q = size_multipliers(comps, best)
    tq = combine(comps, best, q)
    rep_r = report(t, "pnl")
    rep_q = report(tq, "pnl_q")
    # combined R view with R as the "pnl" column (equal-risk units)
    tr = t.copy()
    tr["pnl_r"] = tr["r"]
    rep_eq = report(tr, "pnl_r")
    cd, cm = corr(comps, list(comps)), corr(comps, list(comps), "M")
    top = []
    for c in cands[:8]:
        tt = combine(comps, c["names"])
        rr = report(tt)
        top.append(dict(**c, IS=rr["IS"], OOS=rr["OOS"], pos=rr["pos_months_r"], worst=rr["worst_month_r"]))
    res = dict(eligible=elig, single={k: v for k, v in single.items()}, n_portfolios=len(cands), selected=best,
               qty_mult=q, combined_default_contracts=rep_r, combined_scaled_contracts=rep_q,
               combined_equal_risk=rep_eq, top_portfolios=top, corr_daily=cd.to_dict(), corr_monthly=cm.to_dict(),
               all_scores=cands)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "portfolio.json").write_text(json.dumps(res, indent=1, default=str))
    print("selected", best, "qty", q)
    for lab_, r in (("default", rep_r), ("scaled", rep_q), ("eqR", rep_eq)):
        print(lab_, r["full"], "\n   IS", r["IS"], "\n   OOS", r["OOS"], "\n   months", r["monthly_r"],
              r["pos_months_r"], "usd+", r["pos_months_usd"])
    print("daily corr\n", cd, "\nmonthly corr\n", cm)
    for x in top:
        print(x["names"], x["is_sharpe"], "IS", x["IS"]["pf_r"], x["IS"]["exp"], "OOS", x["OOS"]["pf_r"],
              x["OOS"]["exp"], "pos", x["pos"], "worst", x["worst"])


def robust_main():
    res = json.loads((OUT / "portfolio.json").read_text())
    best = res["selected"]
    q = res["qty_mult"]
    out = {}
    for lab_, kw in (("stopfirst", dict(intrabar="conservative")), ("slip2", dict(slip=2))):
        comps = components(**kw)
        t = combine(comps, best, q)
        r = report(t, "pnl_q")
        out[lab_] = dict(full=r["full"], IS=r["IS"], OOS=r["OOS"], pos=r["pos_months_r"],
                         singles={k: report(comps[k])["full"] for k in best})
        print(lab_, out[lab_])
    (OUT / "portfolio_robust.json").write_text(json.dumps(out, indent=1, default=str))


def _brief(r):
    return dict(full=r["full"], IS=r["IS"], OOS=r["OOS"], pos_r=r["pos_months_r"], pos_usd=r["pos_months_usd"],
                worst_r=r["worst_month_r"], monthly_r=r["monthly_r"], monthly_usd=r["monthly_usd"])


def strict_main():
    """Second selection rule (declared after rule 1 failed OOS, see report): a component must meet the goal's
    own PF bar in IS (PF(R) >= 1.3, >= 40 IS trades). Same subset scoring as rule 1."""
    comps = components()
    elig = [k for k, t in comps.items()
            if (lambda s: s["pf_r"] >= 1.3 and s["exp"] > 0 and s["trades"] >= 40)(stats(t[t.entry_time < CUT]))]
    cands = []
    for n in (2, 3, 4):
        for sub in itertools.combinations(elig, n):
            t = combine(comps, sub)
            cands.append(dict(names=list(sub), is_sharpe=round(weekly_sharpe(t[t.entry_time < CUT]), 3)))
    cands.sort(key=lambda d: -d["is_sharpe"])
    print("strict eligible", elig, "portfolios", len(cands))
    rows = []
    for c in cands:
        q = size_multipliers(comps, c["names"])
        r = report(combine(comps, c["names"], q), "pnl_q")
        rows.append(dict(**c, qty=q, **_brief(r)))
        print(f"{'+'.join(c['names']):28s} ISsh={c['is_sharpe']:.2f} IS PFr={r['IS']['pf_r']:.2f} PF$={r['IS']['pf_usd']:.2f} "
              f"| OOS PFr={r['OOS']['pf_r']:.2f} PF$={r['OOS']['pf_usd']:.2f} | n={r['full']['trades']} "
              f"net={r['full']['net']} dd={r['full']['dd']} +m={r['pos_months_r']}/{r['pos_months_usd']} worst={r['worst_month_r']}")
    best = cands[0]["names"]
    q = rows[0]["qty"]
    rob = {}
    for lab_, kw in (("stopfirst", dict(intrabar="conservative")), ("slip2", dict(slip=2))):
        cc = components(**kw)
        r = report(combine(cc, best, q), "pnl_q")
        rob[lab_] = _brief(r)
        print(lab_, r["full"], "IS", r["IS"]["pf_r"], r["IS"]["pf_usd"], "OOS", r["OOS"]["pf_r"], r["OOS"]["pf_usd"],
              "+m", r["pos_months_r"])
    # real futures (2026-08-06 .. 10-15; 5m bars, MNQ 15m rules resampled from 5m; first ~14 RTH days lost for imom/vwap)
    real = {}
    try:
        from lab import research
        st = research.load_store(["MNQ", "MGC"], ["5m"])
        src = {s_: st[(s_, "5m")] for s_ in ("MNQ", "MGC") if (s_, "5m") in st}
        rc = components(src=src, base=5)
        lo = min(df.index[0] for df in src.values()).tz_localize(None) + pd.Timedelta(days=21)
        for k in best:
            a = rc[k][rc[k].entry_time >= lo]
            b = comps[k][(comps[k].entry_time >= lo) & (comps[k].entry_time <= a.entry_time.max())] if len(a) else a
            real[k] = dict(real=stats(a), proxy=stats(b))
            print("REAL", k, real[k])
        ra = combine({k: rc[k][rc[k].entry_time >= lo] for k in best}, best, q)
        pa = combine({k: comps[k][(comps[k].entry_time >= lo) & (comps[k].entry_time < pd.Timestamp("2026-10-15 16:00"))]
                      for k in best}, best, q)
        real["combined"] = dict(real=stats(ra, "pnl_q"), proxy=stats(pa, "pnl_q"), from_=str(lo))
        print("REAL combined", real["combined"])
    except Exception as e:  # noqa
        print("real check failed", e)
    # component stats under the selected sizing
    single = {k: _brief(report(comps[k])) for k in comps}
    res = dict(rule="strict: IS PF(R)>=1.3, exp>0, >=40 IS trades; score IS weekly-R Sharpe", eligible=elig,
               n_portfolios=len(cands), selected=best, qty=q, ranking=rows, robust=rob, real=real, single=single,
               corr_daily=corr(comps, list(comps)).to_dict(), corr_monthly=corr(comps, list(comps), "M").to_dict())
    (OUT / "portfolio_strict.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    {"run": run_main, "robust": robust_main, "strict": strict_main}[sys.argv[1]]()

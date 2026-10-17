"""wr60 / tfscan: FVG Pro (lab/fvg_pro.generate, unchanged rules) scanned over
timeframes x sessions x min-FVG x entry x LOW reward:risk, plus an optional
"sweep first" quality filter (the BOS must come after price ran a known
session high/low: Asia, London, prior RTH day, overnight).

Protocol
  IS  = trades with entry_time <  2026-04-01  (all choices)
  OOS = trades with entry_time >= 2026-04-01  (reported untouched)

Stage 1  rr = 1.0 for every tf x session x min_fvg x entry x sweep (300 configs).
Stage 2  the 12 best stage-1 configs by IS score, re-run at rr 0.75 / 1.25 / 1.5.
Pick     by IS only (score below), then OOS + monthly R reported.

Sweep filter (long; short mirrors), decided at the setup bar t:
  some bar j in [t - LB, t] of the same Globex day had low[j] < a level that
  was already known on bar j (asia_l, london_l, pdl, onl), LB = 180 minutes.
  Long BOS after a sell-side sweep = classic "sweep then shift" quality.

Run:  PYTHONPATH=. python -m lab.wr60_tfscan
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, engine, features, fvg_pro
from .engine import EngineConfig

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "wr60"
DUKA = Path("/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/"
            "scratchpad/duka/MNQ_1m.pkl")
CUT = "2026-04-01"
TFS = {"10m": "10min", "15m": "15min", "20m": "20min", "30m": "30min", "1h": "60min"}
SESSIONS = {
    "london": (("02:00", "05:00"),),
    "asia": (("20:00", "24:00"),),
    "asia+london": (("20:00", "24:00"), ("02:00", "05:00")),
    "ny_am": (("08:30", "11:00"),),
    "london+ny": (("02:00", "05:00"), ("08:30", "11:00")),
}
INST = data.get_instrument("MNQ")


def sweep_flags(feat, lb_min=180):
    """Per-bar booleans: a sell-side (low) / buy-side (high) sweep happened in
    the last lb_min minutes of the same Globex day, using levels known on the
    sweeping bar. Causal: uses bars <= i only."""
    n = feat.n
    lows = np.vstack([feat.asia_l, feat.london_l, feat.pdl, feat.onl])
    highs = np.vstack([feat.asia_h, feat.london_h, feat.pdh, feat.onh])
    with np.errstate(invalid="ignore"):
        sl = np.nan_to_num(feat.l[None, :] < lows, nan=False).any(axis=0)
        sh = np.nan_to_num(feat.h[None, :] > highs, nan=False).any(axis=0)
    lb = max(3, lb_min // max(1, feat.interval_min))
    rec_l, rec_h = np.zeros(n, bool), np.zeros(n, bool)
    last_l = last_h = -10 ** 9
    for i in range(n):
        if i > 0 and feat.day[i] != feat.day[i - 1]:
            last_l = last_h = -10 ** 9
        if sl[i]:
            last_l = i
        if sh[i]:
            last_h = i
        rec_l[i] = i - last_l <= lb
        rec_h[i] = i - last_h <= lb
    return rec_l, rec_h


def setups_for(feat, sess, mf, entry, rr, sweep, sw=None):
    p = {**fvg_pro.DEFAULTS, "windows": SESSIONS[sess], "min_fvg_atr": mf, "entry": entry, "rr": rr}
    st = fvg_pro.generate(feat, INST, p)
    if sweep:
        rec_l, rec_h = sw if sw is not None else sweep_flags(feat)
        st = [s for s in st if (rec_l[s.bar] if s.side > 0 else rec_h[s.bar])]
    return st


def run_cfg(feat, sess, mf, entry, rr, sweep, sw=None, setups=None):
    st = setups if setups is not None else setups_for(feat, sess, mf, entry, rr, sweep, sw)
    if setups is not None:
        st = [s.__class__(**{**s.__dict__, "rr": rr}) for s in st]
    cfg = EngineConfig(flatten="15:55", max_trades_per_day=len(SESSIONS[sess]), intrabar="path")
    return engine.run(feat, st, INST, cfg)


def stats(ts):
    if not ts:
        return {"trades": 0, "wr": 0.0, "exp_r": 0.0, "pf": 0.0, "net": 0.0, "max_dd": 0.0}
    pnl = np.array([t.pnl for t in ts])
    r = np.array([t.r for t in ts])
    eq = np.cumsum(pnl)
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    return {"trades": len(ts), "wr": float((pnl > 0).mean()), "exp_r": float(r.mean()),
            "pf": float(gp / gl) if gl > 0 else 99.0, "net": float(pnl.sum()),
            "max_dd": float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())}


def monthly(ts):
    if not ts:
        return {}
    s = pd.Series([t.r for t in ts], index=[t.entry_time[:7] for t in ts])
    return {k: round(float(v), 2) for k, v in s.groupby(level=0).sum().items()}


def evaluate(trades):
    is_ = [t for t in trades if t.entry_time < CUT]
    oos = [t for t in trades if t.entry_time >= CUT]
    m = monthly(trades)
    return {"is": stats(is_), "oos": stats(oos), "all": stats(trades), "monthly_r": m,
            "pos_months": int(sum(v > 0 for v in m.values())), "months": len(m),
            "is_pos_months": int(sum(v > 0 for k, v in m.items() if k < CUT[:7])),
            "is_months": int(sum(k < CUT[:7] for k in m))}


def is_score(ev):
    """IS-only score: wants ~60% WR AND positive expectancy with enough trades.
    Expectancy (R) with a penalty for WR distance below 58% and for too few
    IS trades (45 IS trades ~ 80/year)."""
    s = ev["is"]
    if s["trades"] < 30:
        return -9.0
    pen_wr = max(0.0, 0.58 - s["wr"]) * 2.0
    pen_n = max(0, 45 - s["trades"]) / 45 * 0.2
    return s["exp_r"] - pen_wr - pen_n


def truncation_check(m1):
    df = data.resample(m1, "15min")
    k = int(len(df) * 0.6)
    full = features.build(df, INST.tick)
    part = features.build(df.iloc[:k], INST.tick)
    a = [(s.bar, s.side, s.entry, s.stop) for s in setups_for(full, "london", 0.3, "edge", 1.0, True) if s.bar < k - 1]
    b = [(s.bar, s.side, s.entry, s.stop) for s in setups_for(part, "london", 0.3, "edge", 1.0, True) if s.bar < k - 1]
    return a == b, len(a)


def label(c):
    return f"{c['tf']} {c['sess']} mf={c['mf']} {c['entry']} rr={c['rr']} sweep={'Y' if c['sweep'] else 'N'}"


def main():
    m1 = pd.read_pickle(DUKA)
    ok, nset = truncation_check(m1)
    print(f"truncation check (setups on df[:k] == full for bars < k-1): {ok} ({nset} setups)", flush=True)
    feats, sws = {}, {}
    for tf, rule in TFS.items():
        feats[tf] = features.build(data.resample(m1, rule), INST.tick)
        sws[tf] = sweep_flags(feats[tf])
    rows = []
    for tf in TFS:
        for sess in SESSIONS:
            for mf in (0.15, 0.3, 0.5):
                for entry in ("edge", "ce"):
                    for sweep in (False, True):
                        c = dict(tf=tf, sess=sess, mf=mf, entry=entry, rr=1.0, sweep=sweep)
                        ev = evaluate(run_cfg(feats[tf], sess, mf, entry, 1.0, sweep, sws[tf]))
                        rows.append({**c, **ev, "score": is_score(ev)})
        print(f"  stage1 {tf} done ({len(rows)})", flush=True)
    top = sorted(rows, key=lambda r: -r["score"])[:12]
    for t in top:
        for rr in (0.75, 1.25, 1.5):
            c = {k: t[k] for k in ("tf", "sess", "mf", "entry", "sweep")}
            ev = evaluate(run_cfg(feats[c["tf"]], c["sess"], c["mf"], c["entry"], rr, c["sweep"], sws[c["tf"]]))
            rows.append({**c, "rr": rr, **ev, "score": is_score(ev)})
    print(f"configs tried: {len(rows)}", flush=True)
    rows.sort(key=lambda r: -r["score"])
    for r in rows[:25]:
        print(f"{label(r):48s} IS {r['is']['trades']:3d} {r['is']['wr']:.0%} {r['is']['exp_r']:+.3f}R PF {r['is']['pf']:.2f} | "
              f"OOS {r['oos']['trades']:3d} {r['oos']['wr']:.0%} {r['oos']['exp_r']:+.3f}R PF {r['oos']['pf']:.2f} | "
              f"months+ {r['pos_months']}/{r['months']}")
    # highest-WR configs with positive IS expectancy (for the WR question)
    print("--- IS WR >= 55% and IS exp > 0, by IS WR")
    hw = sorted([r for r in rows if r["is"]["wr"] >= 0.55 and r["is"]["exp_r"] > 0 and r["is"]["trades"] >= 30],
                key=lambda r: -r["is"]["wr"])
    for r in hw[:15]:
        print(f"{label(r):48s} IS {r['is']['trades']:3d} {r['is']['wr']:.0%} {r['is']['exp_r']:+.3f}R PF {r['is']['pf']:.2f} | "
              f"OOS {r['oos']['trades']:3d} {r['oos']['wr']:.0%} {r['oos']['exp_r']:+.3f}R PF {r['oos']['pf']:.2f} | "
              f"months+ {r['pos_months']}/{r['months']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tfscan.json").write_text(json.dumps({"truncation_ok": ok, "configs": len(rows), "rows": rows}, indent=1))


if __name__ == "__main__":
    sys.exit(main())

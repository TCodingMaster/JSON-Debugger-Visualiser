"""Cross-market FVG Pro: one rule set for MNQ, MGC (gold) and MCL (crude).

Direction "crossmarket". The FVG Pro family (lab/fvg_pro.py, BOS + FVG limit
entry, fixed RR) is run with ONE parameter set on every market, each market
in its own liquid session window (fixed a priori, not optimised):

  MNQ  London 02:00-05:00 NY   (the "Leto" window)
  MGC  London 03:00-06:00 NY   or COMEX open 08:20-10:30 NY
  MCL  NYMEX open 09:00-11:30 NY

Parameters scanned (small grid): min FVG size (x ATR14), RR, 1h EMA-slope
trend filter, stop at the swing (leg low/high) vs beyond the FVG, entry at the
gap edge vs 50 %.  Selection uses IN-SAMPLE trades only (entry < 2026-04-01),
by the combined (all-market) IS R with a requirement that every market used is
positive in-sample.  OOS (>= 2026-04-01) is reported untouched.

No new signal code: setups come from fvg_pro.generate (decided at bar close,
limit order worked from the next bar), so no extra truncation check is needed;
a quick one is still provided (`check`).

Usage:  PYTHONPATH=. python -m lab.prof_crossmarket grid     (runs + writes json)
        PYTHONPATH=. python -m lab.prof_crossmarket check
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, engine, features, fvg_pro
from .data import get_instrument
from .engine import EngineConfig

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "profit"
P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
CUT = "2026-04-01"
FILES = {"MNQ": "MNQ_1m.pkl", "MGC": "MGC_1m.pkl", "MCL": "CL_1m.pkl"}

WINDOWS = {
    "MNQ": {"london": (("02:00", "05:00"),), "nyam": (("08:30", "11:00"),)},
    "MGC": {"london": (("03:00", "06:00"),), "comex": (("08:20", "10:30"),)},
    "MCL": {"nymex": (("09:00", "11:30"),), "london": (("02:00", "05:00"),)},
}
MONTHS = [str(p) for p in pd.period_range("2025-09", "2026-10", freq="M")]

_FEAT: dict = {}


def feats(sym, tf="15min"):
    key = (sym, tf)
    if key not in _FEAT:
        m1 = pd.read_pickle(P + FILES[sym])
        df = data.resample(m1, tf)
        _FEAT[key] = features.build(df, get_instrument(sym).tick)
    return _FEAT[key]


def run(sym, params, tf="15min", intrabar="path", slip=1, feat=None):
    feat = feat or feats(sym, tf)
    inst = get_instrument(sym)
    p = {**fvg_pro.DEFAULTS, **params}
    setups = fvg_pro.generate(feat, inst, p)
    cfg = EngineConfig(flatten="15:55", max_trades_per_day=p["max_trades"], intrabar=intrabar, slippage_ticks=slip)
    return engine.run(feat, setups, inst, cfg)


def stats(trs):
    if not trs:
        return {"trades": 0, "wr": 0.0, "exp": 0.0, "pf": 0.0, "pf_r": 0.0, "net": 0.0, "dd": 0.0, "sum_r": 0.0}
    trs = sorted(trs, key=lambda t: t.entry_time)
    r = np.array([t.r for t in trs])
    pnl = np.array([t.pnl for t in trs])
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]))
    gp, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    rp, rl = r[r > 0].sum(), -r[r < 0].sum()
    return {"trades": int(len(r)), "wr": float((r > 0).mean()), "exp": float(r.mean()),
            "pf": float(gp / gl) if gl > 0 else 99.0, "pf_r": float(rp / rl) if rl > 0 else 99.0,
            "net": float(pnl.sum()), "dd": dd, "sum_r": float(r.sum())}


def monthly_r(trs):
    out = {m: 0.0 for m in MONTHS}
    for t in trs:
        m = str(pd.Timestamp(t.entry_time).tz_localize(None).to_period("M")) if pd.Timestamp(t.entry_time).tzinfo \
            else str(pd.Timestamp(t.entry_time).to_period("M"))
        out[m] = out.get(m, 0.0) + t.r
    return {k: round(v, 2) for k, v in out.items()}


def full(trs):
    a = [t for t in trs if t.entry_time < CUT]
    b = [t for t in trs if t.entry_time >= CUT]
    mr = monthly_r(trs)
    return {"all": stats(trs), "is": stats(a), "oos": stats(b), "monthly_r": mr,
            "pos_months": int(sum(v > 0 for v in mr.values()))}


def grid():
    out = []
    for mf, rr, tr, sm, en in itertools.product((0.15, 0.3, 0.5), (1.5, 2.0, 2.5), (False, True),
                                                ("leg", "fvg"), ("edge", "ce")):
        out.append(dict(min_fvg_atr=mf, rr=rr, trend_filter=tr, stop_mode=sm, entry=en, max_trades=1))
    return out


def scan(log=print):
    """Every market x window x param (144 x 6 = 864 engine runs, but only 144
    rule sets).  Results per run are summarised; the selection combines them."""
    rows = []
    G = grid()
    for sym, wins in WINDOWS.items():
        for wname, w in wins.items():
            for k, g in enumerate(G):
                trs = run(sym, {**g, "windows": w})
                f = full(trs)
                rows.append({"sym": sym, "win": wname, "gid": k, **g, **{x: f[x] for x in ("all", "is", "oos", "pos_months")},
                             "monthly_r": f["monthly_r"]})
            log(f"  {sym} {wname} done")
    return G, rows


SCHEMES = {  # market -> window name; a scheme is fixed before looking at results
    "nq+gcLon+cl": {"MNQ": "london", "MGC": "london", "MCL": "nymex"},
    "nq+gcComex+cl": {"MNQ": "london", "MGC": "comex", "MCL": "nymex"},
    "nq+gcLon": {"MNQ": "london", "MGC": "london"},
    "nq+gcComex": {"MNQ": "london", "MGC": "comex"},
    "nq+cl": {"MNQ": "london", "MCL": "nymex"},
}


def select(G, rows):
    by = {(r["sym"], r["win"], r["gid"]): r for r in rows}
    cands = []
    for sname, sch in SCHEMES.items():
        for k in range(len(G)):
            parts = [by[(s, w, k)] for s, w in sch.items()]
            is_r = sum(p["is"]["sum_r"] for p in parts)
            is_n = sum(p["is"]["trades"] for p in parts)
            all_pos = all(p["is"]["sum_r"] > 0 for p in parts)
            cands.append({"scheme": sname, "gid": k, "params": G[k], "is_r": is_r, "is_n": is_n,
                          "is_exp": is_r / max(is_n, 1), "all_pos_is": all_pos,
                          "oos_r": sum(p["oos"]["sum_r"] for p in parts),
                          "oos_n": sum(p["oos"]["trades"] for p in parts),
                          "per": {f"{p['sym']}-{p['win']}": {"is_exp": p["is"]["exp"], "is_n": p["is"]["trades"],
                                                             "oos_exp": p["oos"]["exp"], "oos_n": p["oos"]["trades"]}
                                  for p in parts}})
    return cands


def portfolio(sch, params, intrabar="path", slip=1, tf="15min"):
    res, alltr = {}, []
    for s, w in sch.items():
        trs = run(s, {**params, "windows": WINDOWS[s][w]}, tf=tf, intrabar=intrabar, slip=slip)
        res[f"{s}-{w}"] = full(trs)
        alltr += trs
    res["combined"] = full(alltr)
    return res


def check():
    """Truncation check: setups on data[:k] equal setups on the full data for bars < k-1."""
    for sym in ("MNQ", "MGC"):
        f = feats(sym)
        inst = get_instrument(sym)
        p = {**fvg_pro.DEFAULTS, "windows": (("00:00", "24:00"),), "min_fvg_atr": 0.3}
        full_s = [(s.bar, s.side, s.entry, s.stop) for s in fvg_pro.generate(f, inst, p)]
        for k in (3000, 9000, 15000):
            ft = features.build(f.df.iloc[:k], inst.tick)
            tr = [(s.bar, s.side, s.entry, s.stop) for s in fvg_pro.generate(ft, inst, p)]
            a = [x for x in full_s if x[0] < k - 1]
            b = [x for x in tr if x[0] < k - 1]
            print(sym, k, "OK" if a == b else f"MISMATCH {len(a)} vs {len(b)}")


def main():
    G, rows = scan()
    cands = select(G, rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crossmarket_grid.json").write_text(json.dumps({"rows": rows, "cands": cands}, default=float))
    ok = [c for c in cands if c["all_pos_is"] and c["is_n"] >= 60]
    ok.sort(key=lambda c: -c["is_r"])
    for c in ok[:25]:
        print(f"{c['scheme']:14s} {c['params']}  IS {c['is_n']} {c['is_exp']:+.3f}R ({c['is_r']:+.1f})  "
              f"OOS {c['oos_n']} {c['oos_r'] / max(c['oos_n'], 1):+.3f}R ({c['oos_r']:+.1f})")
    print("candidates", len(cands), "with all markets IS-positive", len(ok))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd != "final":
        {"grid": main, "check": check}[cmd]()


# --------------------------------------------------------------------------- #
# Final: selected rule set (IS-best with every market IS-positive) + checks
# --------------------------------------------------------------------------- #
SELECTED_SCHEME = SCHEMES["nq+gcComex"]
SELECTED = dict(min_fvg_atr=0.3, rr=2.5, trend_filter=False, stop_mode="leg", entry="edge", max_trades=1)


def _line(name, s):
    return (f"{name:34s} n{s['trades']:4d} WR {s['wr']:.0%} exp {s['exp']:+.3f}R PF$ {s['pf']:.2f} PFr {s['pf_r']:.2f} "
            f"net ${s['net']:>8,.0f} DD ${s['dd']:>6,.0f}")


def final():
    res = {}
    variants = {"base": dict(), "stopfirst": dict(intrabar="conservative"), "slip2": dict(slip=2),
                "slip2_stopfirst": dict(slip=2, intrabar="conservative")}
    for vn, kw in variants.items():
        r = portfolio(SELECTED_SCHEME, SELECTED, **kw)
        res[vn] = r
        print(f"--- {vn}")
        for k, v in r.items():
            print(_line(k + " ALL", v["all"]), f"pos {v['pos_months']}/14")
            print(_line(k + " IS", v["is"]))
            print(_line(k + " OOS", v["oos"]))
        print("   monthly combined", r["combined"]["monthly_r"])
    # neighbours (same rule on both markets)
    neigh = {}
    for mf in (0.2, 0.3, 0.4):
        for rr in (2.0, 2.25, 2.5, 2.75):
            r = portfolio(SELECTED_SCHEME, {**SELECTED, "min_fvg_atr": mf, "rr": rr})["combined"]
            neigh[f"mf{mf}_rr{rr}"] = r
            print(f"neigh mf {mf} rr {rr}: " + _line("", r["all"]) + f" IS PF$ {r['is']['pf']:.2f} OOS PF$ {r['oos']['pf']:.2f} pos {r['pos_months']}")
    # window shifts for gold (+-20 min) and NQ
    wins = {}
    for gw in ((("08:00", "10:30"),), (("08:20", "10:00"),), (("08:20", "11:00"),), (("08:40", "10:30"),)):
        trs = run("MNQ", {**SELECTED, "windows": WINDOWS["MNQ"]["london"]}) + run("MGC", {**SELECTED, "windows": gw})
        f = full(trs)
        wins[str(gw)] = f
        print(f"gold window {gw}: " + _line("", f["all"]) + f" IS PF$ {f['is']['pf']:.2f} OOS PF$ {f['oos']['pf']:.2f} pos {f['pos_months']}")
    # 5m timeframe (same rule)
    r5 = portfolio(SELECTED_SCHEME, SELECTED, tf="5min")
    for k, v in r5.items():
        print("5m", _line(k, v["all"]), f"IS PF$ {v['is']['pf']:.2f} OOS PF$ {v['oos']['pf']:.2f} pos {v['pos_months']}")
    # real futures sanity check (~70 days)
    real = {}
    try:
        from . import research
        st = research.load_store(["MNQ", "MGC"], ["15m"])
        for (sym, tf), df in st.items():
            w = SELECTED_SCHEME[sym]
            f_ = features.build(df, get_instrument(sym).tick)
            trs = run(sym, {**SELECTED, "windows": WINDOWS[sym][w]}, feat=f_)
            real[sym] = {"range": [str(df.index[0]), str(df.index[-1])], **stats(trs)}
            # same period on the Dukascopy proxy
            fd = feats(sym)
            trp = [t for t in run(sym, {**SELECTED, "windows": WINDOWS[sym][w]})
                   if str(df.index[0]) <= t.entry_time <= str(df.index[-1])]
            real[sym + "_proxy_same_period"] = stats(trp)
            print("REAL", sym, real[sym]["range"], _line("", real[sym]), "| proxy", _line("", stats(trp)))
    except Exception as e:  # pragma: no cover
        print("real futures check failed:", e)
    out = {"params": SELECTED, "scheme": SELECTED_SCHEME, "variants": res, "neighbours": neigh,
           "gold_windows": wins, "tf5": r5, "real": real}
    (OUT / "crossmarket.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "final":
    final()

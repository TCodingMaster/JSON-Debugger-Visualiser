"""Improve how MSS / sweep / FVG are detected without fooling ourselves.

Protocol:
  * Each dataset (symbol × timeframe) is split by sessions: first 60 % =
    in-sample (IS), last 40 % = out-of-sample (OOS).
  * Quality filters are chosen ONLY on IS, greedily, one at a time. A filter
    is added only if it raises the pooled IS expectancy by >= 0.03R AND
    improves IS expectancy on at least 6 of the 10 datasets (consistency, not
    a lucky chart), and the pooled IS sample stays >= 120 trades.
  * The OOS part is evaluated once, after the filters are locked.
"""

from __future__ import annotations

import numpy as np

from . import fvg_pro, mss_fvg

CANDIDATES = {
    "pivot_len=5 (pomembnejši swingi)": {"pivot_len": 5},
    "sweep wick (zapre nazaj)": {"sweep_close_back": True},
    "glavna likvidnost (PDH/PDL, Asia, London)": {"major_liq": True},
    "MSS ≤ 10 barov po sweepu": {"max_sweep_age": 10},
    "displacement ≥ 1.0 ATR": {"disp_atr": 1.0},
    "displacement ≥ 1.5 ATR": {"disp_atr": 1.5},
    "FVG ≥ 0.25 ATR": {"min_fvg_atr": 0.25},
    "respect z wickom ≥ 40 %": {"respect_wick": 0.4},
    "z 1h trendom": {"trend_filter": True},
}


def evaluate(datasets, params, cuts):
    per = {}
    for key, df in datasets.items():
        _, trades = mss_fvg.backtest(df, key[0], params)
        is_r = np.array([t.r for t in trades if t.entry_time < cuts[key]])
        oos_r = np.array([t.r for t in trades if t.entry_time >= cuts[key]])
        per[key] = (is_r, oos_r)
    is_all = np.concatenate([v[0] for v in per.values()]) if per else np.array([])
    oos_all = np.concatenate([v[1] for v in per.values()]) if per else np.array([])
    return per, is_all, oos_all


def _st(r):
    if not len(r):
        return {"n": 0, "wr": None, "exp": None}
    return {"n": int(len(r)), "wr": float((r > 0).mean()), "exp": float(r.mean())}


def boot_ci(r, runs=4000, seed=7):
    if len(r) < 5:
        return (None, None)
    rng = np.random.default_rng(seed)
    m = rng.choice(r, size=(runs, len(r))).mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def improve(datasets, log=print, max_steps=3):
    cuts = {k: fvg_pro.cut_time(df) for k, df in datasets.items()}
    base_p = {}
    per0, is0, _ = evaluate(datasets, base_p, cuts)
    log(f"osnova (tvoja metoda): IS n={len(is0)} WR={(is0 > 0).mean():.1%} exp={is0.mean():+.3f}R")

    singles = []
    for name, extra in CANDIDATES.items():
        per, is_r, _ = evaluate(datasets, extra, cuts)
        better = sum(1 for k in per if len(per[k][0]) >= 5 and len(per0[k][0]) >= 5
                     and per[k][0].mean() > per0[k][0].mean())
        singles.append({"name": name, **_st(is_r), "sets_better": better})
        log(f"  {name:42s} IS n={len(is_r):4d} WR={(is_r > 0).mean() if len(is_r) else 0:.1%} "
            f"exp={is_r.mean() if len(is_r) else 0:+.3f}R  boljše na {better}/10")

    chosen, params = [], dict(base_p)
    cur_per, cur_is = per0, is0
    for _ in range(max_steps):
        best = None
        for name, extra in CANDIDATES.items():
            if name in chosen or any(set(extra) & set(CANDIDATES[c]) for c in chosen):
                continue
            trial = {**params, **extra}
            per, is_r, _ = evaluate(datasets, trial, cuts)
            if len(is_r) < 120:
                continue
            better = sum(1 for k in per if len(per[k][0]) >= 5 and len(cur_per[k][0]) >= 5
                         and per[k][0].mean() > cur_per[k][0].mean())
            gain = is_r.mean() - cur_is.mean()
            if gain >= 0.03 and better >= 6 and (best is None or is_r.mean() > best[2].mean()):
                best = (name, per, is_r, better)
        if best is None:
            break
        name, cur_per, cur_is, better = best
        chosen.append(name)
        params.update(CANDIDATES[name])
        log(f"  + izbran: {name} → IS WR={(cur_is > 0).mean():.1%} exp={cur_is.mean():+.3f}R (boljše na {better}/10)")

    # one look at the untouched out-of-sample part
    _, is_b, oos_b = evaluate(datasets, base_p, cuts)
    per_f, is_f, oos_f = evaluate(datasets, params, cuts)
    res = {
        "chosen": chosen, "params": params, "singles": singles,
        "base": {"is": _st(is_b), "oos": _st(oos_b), "oos_ci": boot_ci(oos_b)},
        "final": {"is": _st(is_f), "oos": _st(oos_f), "oos_ci": boot_ci(oos_f)},
        "per_set_oos": {f"{k[0]} {k[1]}": _st(v[1]) for k, v in sorted(per_f.items())},
    }
    return res

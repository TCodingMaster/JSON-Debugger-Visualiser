"""wr60 / filters: raise FVG Pro win rate with signal-bar filters (walk-forward).

Protocol
  IS  = trades with entry_time <  2026-04-01  (used for ALL choices)
  OOS = trades with entry_time >= 2026-04-01  (reported untouched)

Steps
  1. Base universes: FVG Pro (lab/fvg_pro.generate rules, re-implemented here
     only to also return the BOS / gap bar indices; checked identical to
     fvg_pro.generate) for a few session presets × RR 1.0 / 1.5 / 2.0.
  2. For every setup compute features known at the close of its signal bar
     (ATR regime, ADX, Globex-VWAP distance, session bucket, weekday, prior-day
     range, day-so-far range and position, change vs prior RTH close, FVG size,
     BOS leg, displacement body, 1h / 4h EMA slope, EMA200 side, premium /
     discount in the last swing range, risk in ATR).
  3. Attribute each trade of the unfiltered run to its setup, rank single
     threshold filters and pairs on IS trades only (Wilson lower bound of the
     IS win rate, >= 45 IS trades), plus a small numpy logistic meta-label
     trained on IS only and thresholded on IS.
  4. The best few candidates per RR are re-simulated EXACTLY (filtered setups
     through the engine), the winner chosen by IS only, then OOS reported.

Run:  PYTHONPATH=. python -m lab.wr60_filters
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, engine, features, fvg_pro
from .engine import EngineConfig, Setup
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "wr60"
DUKA = Path("/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/"
            "scratchpad/duka/MNQ_1m.pkl")
CUT = "2026-04-01"
HALF = "2025-12-16"    # inner split of IS (nested walk-forward, used for the stability score)
MIN_IS = 45            # ~80 trades / year pro rata (IS is ~7 of 13.5 months)
N_CONFIGS = 0          # counted configurations


# ---------------------------------------------------------------- generator
def generate_meta(feat, inst, p):
    """Same rules as fvg_pro.generate, also returns per-setup meta dicts."""
    p = {**fvg_pro.DEFAULTS, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n = feat.n
    L = int(p["pivot_len"])
    buf = p["buffer_ticks"] * inst.tick
    lsh, lsl = fvg_pro._confirmed_swings(h, l, L)
    trend = fvg_pro.trend_sign(feat) if p["trend_filter"] else None
    win = np.zeros(n, bool)
    for s_, e_ in p["windows"]:
        win |= (feat.mod >= hm(s_)) & (feat.mod < hm(e_))

    def gap(k, side):
        if k < 2:
            return None
        if side > 0 and l[k] > h[k - 2] and l[k] - h[k - 2] >= p["min_fvg_atr"] * a[k]:
            return h[k - 2], l[k]
        if side < 0 and h[k] < l[k - 2] and l[k - 2] - h[k] >= p["min_fvg_atr"] * a[k]:
            return h[k], l[k - 2]
        return None

    out, meta = [], []
    waiting = []
    last_up = last_dn = None
    for i in range(1, n):
        events = []
        if not math.isnan(lsh[i]) and c[i] > lsh[i] and lsh[i] != last_up:
            events.append(1)
            last_up = lsh[i]
        if not math.isnan(lsl[i]) and c[i] < lsl[i] and lsl[i] != last_dn:
            events.append(-1)
            last_dn = lsl[i]
        found = []
        for side in events:
            g = None
            for k in range(max(2, i - p["fvg_before"]), i + 1):
                g = gap(k, side)
                if g:
                    found.append((i, side, k, g))
                    break
            if not g:
                waiting.append((i, side))
        still = []
        for bos, side in waiting:
            if bos == i:
                still.append((bos, side))
                continue
            g = gap(i, side)
            if g:
                found.append((bos, side, i, g))
            elif i - bos < p["fvg_after"]:
                still.append((bos, side))
        waiting = still
        for bos, side, k, (bot, top) in found:
            t = max(bos, k)
            if not win[t] or (trend is not None and trend[t] * side <= 0):
                continue
            lo_i = max(0, bos - p["stop_lookback"])
            if side > 0:
                stop = l[lo_i:k + 1].min() - buf
                entry = top if p["entry"] == "edge" else inst.round_price((bot + top) / 2)
                inval = bot
                leg = c[bos] - l[lo_i:bos + 1].min()
            else:
                stop = h[lo_i:k + 1].max() + buf
                entry = bot if p["entry"] == "edge" else inst.round_price((bot + top) / 2)
                inval = top
                leg = h[lo_i:bos + 1].max() - c[bos]
            out.append(Setup(t, side, "limit", entry, stop, rr=p["rr"], expiry=p["expiry"], invalidate=inval,
                             note=f"BOS {'up' if side > 0 else 'down'} + FVG {bot:.2f}-{top:.2f}"))
            meta.append(dict(t=t, bos=bos, k=k, side=side, bot=bot, top=top, entry=entry, stop=stop,
                             leg=leg, lsh=lsh[t], lsl=lsl[t]))
    return out, meta


# ---------------------------------------------------------------- features
def _rolling_median_past(x, w):
    return pd.Series(x).rolling(w, min_periods=w // 2).median().to_numpy()


def adx(h, l, c, n=14):
    up = np.r_[0, h[1:] - h[:-1]]
    dn = np.r_[0, l[:-1] - l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.abs(h - np.r_[c[0], c[:-1]]))
    tr = np.maximum(tr, np.abs(l - np.r_[c[0], c[:-1]]))
    al = 1.0 / n
    w = lambda x: pd.Series(x).ewm(alpha=al, adjust=False).mean().to_numpy()  # noqa: E731
    atr_ = w(tr)
    pdi = 100 * w(pdm) / np.maximum(atr_, 1e-9)
    ndi = 100 * w(ndm) / np.maximum(atr_, 1e-9)
    dx = 100 * np.abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-9)
    return w(dx)


def bar_features(feat):
    """Per-bar arrays, each value at bar i uses bars <= i only."""
    o, h, l, c, v, a = feat.o, feat.h, feat.l, feat.c, feat.v, feat.atr
    n = feat.n
    bpd = max(1, int(round(23 * 60 / feat.interval_min)))
    bph = max(1, 60 // feat.interval_min)
    F = {}
    F["atr_reg"] = a / _rolling_median_past(a, 20 * bpd)
    F["adx"] = adx(h, l, c)
    # Globex-day VWAP, day-so-far high/low, prior RTH close
    gv = np.full(n, np.nan)
    dhi = np.full(n, np.nan)
    dlo = np.full(n, np.nan)
    pclose = np.full(n, np.nan)
    starts = np.flatnonzero(np.r_[True, feat.day[1:] != feat.day[:-1]])
    ends = np.r_[starts[1:], n]
    prev_close = np.nan
    tp = (h + l + c) / 3
    for s, e in zip(starts, ends):
        cv = np.cumsum(v[s:e])
        gv[s:e] = np.cumsum(tp[s:e] * v[s:e]) / np.maximum(cv, 1e-12)
        dhi[s:e] = np.maximum.accumulate(h[s:e])
        dlo[s:e] = np.minimum.accumulate(l[s:e])
        pclose[s:e] = prev_close
        m = feat.mod[s:e]
        rth = np.flatnonzero((m >= 9 * 60 + 30) & (m < 16 * 60))
        if len(rth):
            prev_close = c[s + rth[-1]]
    F["gvwap"] = gv
    F["dhi"], F["dlo"], F["pclose"] = dhi, dlo, pclose
    pdr = feat.pdh - feat.pdl
    F["pdr_rel"] = pdr / _rolling_median_past(pdr, 20 * bpd)
    e1 = features.ema(c, 20 * bph)
    s1 = np.zeros(n)
    s1[bph:] = np.sign(e1[bph:] - e1[:-bph])
    e4 = features.ema(c, 20 * 4 * bph)
    s4 = np.zeros(n)
    s4[4 * bph:] = np.sign(e4[4 * bph:] - e4[:-4 * bph])
    F["slope1h"], F["slope4h"] = s1, s4
    F["ema200"] = features.ema(c, 200)
    return F


SESS = [(20 * 60, 24 * 60, "asia"), (0, 2 * 60, "midnight"), (2 * 60, 5 * 60, "london"),
        (5 * 60, 8 * 60 + 30, "preny"), (8 * 60 + 30, 11 * 60, "nyam"), (11 * 60, 16 * 60, "nypm"),
        (16 * 60, 20 * 60, "eve")]


def setup_features(feat, F, meta):
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    rows = []
    idx = feat.df.index
    for m in meta:
        t, s, k = m["t"], m["side"], m["k"]
        at = a[t] if a[t] > 0 else np.nan
        rng = F["dhi"][t] - F["dlo"][t]
        pos = (c[t] - F["dlo"][t]) / rng if rng > 0 else 0.5
        sw = m["lsh"] - m["lsl"]
        if s > 0:
            pdp = (m["entry"] - m["lsl"]) / sw if sw > 0 else np.nan
        else:
            pdp = (m["lsh"] - m["entry"]) / sw if sw > 0 else np.nan
        d = k - 1
        mod = feat.mod[t]
        sess = next(nm for a_, b_, nm in SESS if a_ <= mod < b_)
        rows.append(dict(
            t=t, side=s,
            atr_reg=F["atr_reg"][t],
            adx=F["adx"][t],
            vwap_d=s * (c[t] - F["gvwap"][t]) / at,
            pdr_rel=F["pdr_rel"][t],
            day_rng=rng / at,
            day_pos=pos if s > 0 else 1 - pos,
            chg_pc=s * (c[t] - F["pclose"][t]) / at,
            fvg_atr=(m["top"] - m["bot"]) / at,
            leg_atr=m["leg"] / at,
            body=abs(c[d] - o[d]) / max(h[d] - l[d], 1e-9),
            body_atr=abs(c[d] - o[d]) / at,
            tr1h=s * F["slope1h"][t],
            tr4h=s * F["slope4h"][t],
            ema200=s * (c[t] - F["ema200"][t]) / at,
            pd_pos=pdp,
            risk_atr=(m["entry"] - m["stop"]) * s / at,
            dist_entry=s * (c[t] - m["entry"]) / at,
            sess=sess,
            dow=int(idx[t].dayofweek if mod < 18 * 60 else (idx[t] + pd.Timedelta(hours=6)).dayofweek),
        ))
    return pd.DataFrame(rows)


CONT = ["atr_reg", "adx", "vwap_d", "pdr_rel", "day_rng", "day_pos", "chg_pc", "fvg_atr", "leg_atr", "body",
        "body_atr", "tr1h", "tr4h", "ema200", "pd_pos", "risk_atr", "dist_entry"]
CAT = ["sess", "dow"]


# ---------------------------------------------------------------- stats
def stats(trades):
    if not trades:
        return dict(trades=0)
    r = np.array([t.r for t in trades])
    pnl = np.array([t.pnl for t in trades])
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq)) if len(eq) else 0.0
    gw, gl = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return dict(trades=int(len(r)), win_rate=float((pnl > 0).mean()), exp_r=float(r.mean()),
                pf=float(gw / gl) if gl > 0 else float("inf"), net=float(pnl.sum()), max_dd=dd)


def monthly(trades):
    mo = {}
    for t in trades:
        k = t.entry_time[:7]
        mo[k] = mo.get(k, 0.0) + t.r
    return {k: round(v, 2) for k, v in sorted(mo.items())}


def split(trades):
    return [t for t in trades if t.entry_time < CUT], [t for t in trades if t.entry_time >= CUT]


def wilson_lb(w, n, z=1.0):
    if n == 0:
        return 0.0
    p = w / n
    d = 1 + z * z / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


def attribute(trades, setups, feat):
    """Index of the setup that produced each trade (latest setup with same note before entry)."""
    pos = {ts: i for i, ts in enumerate(feat.df.index.map(lambda x: x.isoformat()))}
    by_note = {}
    for j, s in enumerate(setups):
        by_note.setdefault(s.note, []).append(j)
    out = []
    for t in trades:
        i0 = pos[t.entry_time]
        cand = [j for j in by_note.get(t.note, []) if setups[j].bar < i0 and (setups[j].side > 0) == (t.side == "long")]
        out.append(max(cand, key=lambda j: setups[j].bar) if cand else -1)
    return np.array(out)


# ---------------------------------------------------------------- logistic
def logit_fit(X, y, l2=1.0, iters=3000, lr=0.1):
    w = np.zeros(X.shape[1])
    b = 0.0
    for _ in range(iters):
        z = X @ w + b
        p = 1 / (1 + np.exp(-z))
        g = p - y
        w -= lr * (X.T @ g / len(y) + l2 * w / len(y))
        b -= lr * g.mean()
    return w, b


# ---------------------------------------------------------------- research
def load(tf="15min"):
    m1 = pd.read_pickle(DUKA)
    return data.resample(m1, tf)


def run_filtered(feat, inst, setups, keep, max_trades):
    s = [x for x, k in zip(setups, keep) if k]
    return engine.run(feat, s, inst, EngineConfig(flatten="15:55", max_trades_per_day=max_trades, intrabar="path"))


def rule_mask(SF, rule):
    m = np.ones(len(SF), bool)
    for feat_name, op, thr in rule:
        x = SF[feat_name].to_numpy()
        if op == ">=":
            m &= np.nan_to_num(x.astype(float), nan=-1e9) >= thr
        elif op == "<=":
            m &= np.nan_to_num(x.astype(float), nan=1e9) <= thr
        elif op == "!=":
            m &= x != thr
    return m


def rule_str(rule):
    return " & ".join(f"{f}{op}{thr if isinstance(thr, str) else round(float(thr), 3)}" for f, op, thr in rule)


def explore(feat, inst, universe, rr, log=print):
    global N_CONFIGS
    p = dict(windows=fvg_pro.WINDOW_PRESETS[universe["win"]], min_fvg_atr=universe["min_fvg"], rr=rr, entry="edge")
    setups, meta = generate_meta(feat, inst, p)
    F = bar_features(feat)
    SF = setup_features(feat, F, meta)
    mt = universe["max_trades"]
    base = run_filtered(feat, inst, setups, np.ones(len(setups), bool), mt)
    att = attribute(base, setups, feat)
    assert (att >= 0).all()
    tr_is = np.array([t.entry_time < CUT for t in base])
    win = np.array([t.pnl > 0 for t in base])
    rr_ = np.array([t.r for t in base])
    h1 = np.array([t.entry_time < HALF for t in base])
    TF = SF.iloc[att].reset_index(drop=True)
    ISF = TF[tr_is]

    # ---- single rules from IS quantiles
    singles = []
    for f in CONT:
        vals = ISF[f].to_numpy(float)
        vals = vals[~np.isnan(vals)]
        if len(np.unique(vals)) <= 3:
            thr_list = sorted(set(np.unique(vals)))
        else:
            thr_list = sorted(set(np.quantile(vals, [0.15, 0.3, 0.5, 0.7, 0.85])))
        for thr in thr_list:
            for op in (">=", "<="):
                singles.append(((f, op, float(thr)),))
    for f in CAT:
        for v in sorted(ISF[f].unique()):
            singles.append(((f, "!=", v),))

    def score(rule):
        m = rule_mask(TF, rule)
        mi = m & tr_is
        n = int(mi.sum())
        if n < MIN_IS:
            return None
        w = int(win[mi].sum())
        m1, m2 = mi & h1, mi & ~h1
        stab = min(wilson_lb(int(win[m1].sum()), int(m1.sum())), wilson_lb(int(win[m2].sum()), int(m2.sum())))
        return dict(rule=rule, is_n=n, is_wr=w / n, is_lb=wilson_lb(w, n), is_exp=float(rr_[mi].mean()),
                    stab=stab, exp_min=min(float(rr_[m1].mean()) if m1.any() else -9,
                                           float(rr_[m2].mean()) if m2.any() else -9))

    sc = [x for x in (score(r) for r in singles) if x and x["is_exp"] > 0]
    N_CONFIGS += len(singles)
    sc_lb = sorted(sc, key=lambda d: -d["is_lb"])
    sc.sort(key=lambda d: -d["stab"])
    top = sc[:10] + [x for x in sc_lb[:10] if x not in sc[:10]]
    pairs = []
    for a_, b_ in combinations(top, 2):
        if a_["rule"][0][0] == b_["rule"][0][0]:
            continue
        pairs.append(a_["rule"] + b_["rule"])
    N_CONFIGS += len(pairs)
    sp = [x for x in (score(r) for r in pairs) if x and x["is_exp"] > 0]
    sp_lb = sorted(sp, key=lambda d: -d["is_lb"])
    sp.sort(key=lambda d: -d["stab"])

    # ---- logistic meta-label (IS only)
    cols = CONT
    Xall = SF[cols].to_numpy(float)
    mu = np.nanmean(TF[cols].to_numpy(float)[tr_is], axis=0)
    sd = np.nanstd(TF[cols].to_numpy(float)[tr_is], axis=0) + 1e-9

    def z(X):
        Z = (X - mu) / sd
        return np.clip(np.nan_to_num(Z, nan=0.0), -4, 4)
    Xi = z(TF[cols].to_numpy(float)[tr_is])
    w_, b_ = logit_fit(Xi, win[tr_is].astype(float), l2=20.0)
    p_tr = 1 / (1 + np.exp(-(z(TF[cols].to_numpy(float)) @ w_ + b_)))
    p_setup = 1 / (1 + np.exp(-(z(Xall) @ w_ + b_)))
    lr_rules = []
    for q in (0.2, 0.3, 0.4, 0.5):
        thr = float(np.quantile(p_tr[tr_is], q))
        mi = (p_tr >= thr) & tr_is
        n = int(mi.sum())
        N_CONFIGS += 1
        if n >= MIN_IS:
            lr_rules.append(dict(rule=(("logit", ">=", thr),), is_n=n, is_wr=float(win[mi].mean()),
                                 is_lb=wilson_lb(int(win[mi].sum()), n), is_exp=float(rr_[mi].mean()), q=q,
                                 stab=None))
    SF = SF.assign(logit=p_setup)
    TF = TF.assign(logit=p_tr)
    coefs = dict(zip(cols, np.round(w_, 3)))

    # ---- exact re-simulation of the best candidates; choose by IS only
    cands = []
    for x in sp[:10] + sp_lb[:6] + sc[:6] + sc_lb[:4] + lr_rules:
        if all(x["rule"] != y["rule"] for y in cands):
            cands.append(x)
    exact = []
    for cd in cands:
        keep = rule_mask(SF, cd["rule"])
        trs = run_filtered(feat, inst, setups, keep, mt)
        a, b = split(trs)
        sa, sb = stats(a), stats(b)
        a1 = [t for t in a if t.entry_time < HALF]
        a2 = [t for t in a if t.entry_time >= HALF]
        exact.append(dict(rule=rule_str(cd["rule"]), raw_rule=cd["rule"], IS=sa, OOS=sb, ALL=stats(trs),
                          IS1=stats(a1), IS2=stats(a2), months=monthly(trs), trades=trs,
                          universe=universe, rr=rr))
    base_is, base_oos = split(base)
    return dict(universe=universe, rr=rr, base=dict(IS=stats(base_is), OOS=stats(base_oos), ALL=stats(base),
                                                    months=monthly(base)),
                singles=sc[:10], pairs=sp[:10], logit=lr_rules, coefs=coefs, exact=exact,
                setups=setups, SF=SF)


def _lb(s):
    return wilson_lb(s["win_rate"] * s["trades"], s["trades"]) if s.get("trades") else 0.0


def is_score(e, mode="stab"):
    if mode == "lb":
        return _lb(e["IS"])
    return min(_lb(e["IS1"]), _lb(e["IS2"]))


def pick(exact, mode="stab"):
    """IS-only choice: IS trades >= MIN_IS, IS PF >= 1.2 and both IS halves PF >= 1.0;
    maximise the worse IS half's Wilson lower bound of the win rate ("stab") or the IS LB ("lb")."""
    if mode == "stab":   # the logit model is fitted on all of IS, so its IS halves are not a fair check
        exact = [e for e in exact if not e["rule"].startswith("logit")]
    ok = [e for e in exact if e["IS"]["trades"] >= MIN_IS and e["IS"].get("pf", 0) >= 1.2
          and (mode == "lb" or (e["IS1"].get("pf", 0) >= 1.0 and e["IS2"].get("pf", 0) >= 1.0))]
    if not ok:
        return None
    return max(ok, key=lambda e: is_score(e, mode))


def truncation_check(df, inst, universe):
    p = dict(windows=fvg_pro.WINDOW_PRESETS[universe["win"]], min_fvg_atr=universe["min_fvg"])
    full = features.build(df, inst.tick)
    s_full, m_full = generate_meta(full, inst, p)
    SF_full = setup_features(full, bar_features(full), m_full)
    ref = fvg_pro.generate(full, inst, p)
    assert [(s.bar, s.side, s.entry, s.stop) for s in ref] == [(s.bar, s.side, s.entry, s.stop) for s in s_full]
    k = int(len(df) * 0.6)
    tr = features.build(df.iloc[:k], inst.tick)
    s_tr, m_tr = generate_meta(tr, inst, p)
    SF_tr = setup_features(tr, bar_features(tr), m_tr)
    a = [(s.bar, s.side, s.entry, s.stop) for s in s_full if s.bar < k - 1]
    b = [(s.bar, s.side, s.entry, s.stop) for s in s_tr if s.bar < k - 1]
    assert a == b, "setup truncation mismatch"
    n = len(b)
    # atr_reg/pdr_rel use a rolling median which is causal; compare all numeric features
    x = SF_full.iloc[:n][CONT].to_numpy(float)
    y = SF_tr.iloc[:n][CONT].to_numpy(float)
    assert np.allclose(np.nan_to_num(x, nan=7.7), np.nan_to_num(y, nan=7.7)), "feature truncation mismatch"
    return n


def fmt(s):
    if not s or not s.get("trades"):
        return "0 tr"
    return (f"{s['trades']} tr, WR {s['win_rate']:.1%}, {s['exp_r']:+.3f}R, PF {s['pf']:.2f}, "
            f"net ${s['net']:,.0f}, DD ${s['max_dd']:,.0f}")


def main(log=print):
    df = load("15min")
    inst = data.get_instrument("MNQ")
    feat = features.build(df, inst.tick)
    universes = [dict(win="london", min_fvg=0.3, max_trades=1), dict(win="asia+london", min_fvg=0.3, max_trades=1),
                 dict(win="asia+london", min_fvg=0.15, max_trades=2), dict(win="all", min_fvg=0.3, max_trades=2)]
    log("truncation check: setups/features equal on", truncation_check(df, inst, universes[1]), "setups")
    results, allex = [], []
    for u in universes:
        for rr in (1.0, 1.5, 2.0):
            res = explore(feat, inst, u, rr)
            results.append(res)
            allex += res["exact"]
            log(f"\n== {u} RR {rr}  base IS {fmt(res['base']['IS'])} | OOS {fmt(res['base']['OOS'])}")
            for e in sorted(res["exact"], key=lambda e: -is_score(e))[:5]:
                log(f"   {e['rule'][:52]:52s} stab {is_score(e):.3f} IS {fmt(e['IS'])} | OOS {fmt(e['OOS'])}")
    summary = {"configs_tried": N_CONFIGS + len(universes) * 3, "picks": {}}
    for mode in ("stab", "lb"):
        for rr in (1.0, 1.5, 2.0, None):
            pool = [e for e in allex if rr is None or e["rr"] == rr]
            e = pick(pool, mode)
            if e is None:
                continue
            key = f"{mode}_rr{rr if rr else 'any'}"
            pos = sum(v > 0 for v in e["months"].values())
            summary["picks"][key] = dict(universe=e["universe"], rr=e["rr"], rule=e["rule"], IS=e["IS"],
                                         IS1=e["IS1"], IS2=e["IS2"], OOS=e["OOS"], ALL=e["ALL"],
                                         months=e["months"], pos_months=f"{pos}/{len(e['months'])}")
            log(f"\nPICK {key}: {e['universe']} RR {e['rr']} [{e['rule']}]\n  IS {fmt(e['IS'])}\n  OOS {fmt(e['OOS'])}"
                f"\n  ALL {fmt(e['ALL'])}  months+ {pos}/{len(e['months'])}\n  {e['months']}")
    summary["baselines"] = {f"{r['universe']['win']}|{r['universe']['min_fvg']}|{r['universe']['max_trades']}|rr{r['rr']}":
                            {k: r["base"][k] for k in ("IS", "OOS", "ALL")} for r in results}
    log("configs tried:", summary["configs_tried"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "filters.json").write_text(json.dumps(summary, indent=1, default=float))
    return df, feat, inst, results, allex, summary


if __name__ == "__main__" and "--candidate" not in sys.argv:
    main()


# ---------------------------------------------------------------- cross-universe selection
def cross_universe(feat, inst, universes, rr=1.0, log=print, n_exact=8):
    """Choose ONE filter rule (single or pair) that raises the IS win rate in EVERY
    universe and in both IS halves (min improvement over the base, IS only), like
    fvg_pro.develop chose one setting for all sets. Thresholds are pooled IS quantiles."""
    global N_CONFIGS
    F = bar_features(feat)
    sets = []
    for u in universes:
        p = dict(windows=fvg_pro.WINDOW_PRESETS[u["win"]], min_fvg_atr=u["min_fvg"], rr=rr, entry="edge")
        setups, meta = generate_meta(feat, inst, p)
        SF = setup_features(feat, F, meta)
        base = run_filtered(feat, inst, setups, np.ones(len(setups), bool), u["max_trades"])
        att = attribute(base, setups, feat)
        TF = SF.iloc[att].reset_index(drop=True)
        sets.append(dict(u=u, setups=setups, SF=SF, base=base, TF=TF,
                         is_=np.array([t.entry_time < CUT for t in base]),
                         h1=np.array([t.entry_time < HALF for t in base]),
                         win=np.array([t.pnl > 0 for t in base])))
    pool = pd.concat([s["TF"][s["is_"]] for s in sets])
    singles = []
    for f in CONT:
        vals = pool[f].to_numpy(float)
        vals = vals[~np.isnan(vals)]
        thr = sorted(set(np.unique(vals))) if len(np.unique(vals)) <= 3 else \
            sorted(set(np.round(np.quantile(vals, [0.2, 0.35, 0.5, 0.65, 0.8]), 3)))
        for t in thr:
            singles += [((f, ">=", float(t)),), ((f, "<=", float(t)),)]
    for f in CAT:
        for v in sorted(pool[f].unique()):
            singles.append(((f, "!=", v),))

    def score(rule):
        imp = []
        for s in sets:
            m = rule_mask(s["TF"], rule)
            for part in (s["is_"] & s["h1"], s["is_"] & ~s["h1"]):
                mi = m & part
                if mi.sum() < 15:
                    return None
                imp.append(s["win"][mi].mean() - s["win"][part].mean())
            keep = (m & s["is_"]).sum() / s["is_"].sum()
            if keep < 0.45:
                return None
        return dict(rule=rule, min_imp=float(min(imp)), mean_imp=float(np.mean(imp)))

    sc = [x for x in map(score, singles) if x]
    N_CONFIGS += len(singles)
    sc.sort(key=lambda d: -d["min_imp"])
    top = sc[:12]
    pairs = [a["rule"] + b["rule"] for a, b in combinations(top, 2) if a["rule"][0][0] != b["rule"][0][0]]
    N_CONFIGS += len(pairs)
    sp = sorted([x for x in map(score, pairs) if x], key=lambda d: -d["min_imp"])
    log("cross-universe singles:")
    for x in sc[:8]:
        log(f"   {rule_str(x['rule']):40s} min +{x['min_imp']:.3f} mean +{x['mean_imp']:.3f}")
    log("cross-universe pairs:")
    for x in sp[:8]:
        log(f"   {rule_str(x['rule']):40s} min +{x['min_imp']:.3f} mean +{x['mean_imp']:.3f}")
    out = []
    for cd in (sp[:n_exact // 2] + sc[:n_exact // 2]):
        for s in sets:
            trs = run_filtered(feat, inst, s["setups"], rule_mask(s["SF"], cd["rule"]), s["u"]["max_trades"])
            a, b = split(trs)
            out.append(dict(rule=rule_str(cd["rule"]), raw_rule=cd["rule"], universe=s["u"], rr=rr,
                            IS=stats(a), OOS=stats(b), ALL=stats(trs), months=monthly(trs), trades=trs,
                            IS1=stats([t for t in a if t.entry_time < HALF]),
                            IS2=stats([t for t in a if t.entry_time >= HALF]), cross=cd))
    return out


# ---------------------------------------------------------------- closest robust candidate
CANDIDATE = dict(universe=dict(win="asia+london", min_fvg=0.3, max_trades=1), rr=1.0,
                 rule=(("dist_entry", "<=", 0.942), ("ema200", "<=", 7.127)))


def candidate(df=None, cand=CANDIDATE):
    """Asia (20-24 NY) + London (02-05 NY) FVG Pro, min FVG 0.3 ATR, edge entry, 1 trade/day, RR 1.0, plus
       dist_entry <= 0.942: signal-bar close at most 0.94 ATR beyond the FVG entry edge (not chasing), and
       ema200 <= 7.127: close at most 7.1 ATR beyond the 15m EMA200 in the trade direction (not over-extended)."""
    df = load() if df is None else df
    inst = data.get_instrument("MNQ")
    feat = features.build(df, inst.tick)
    u = cand["universe"]
    p = dict(windows=fvg_pro.WINDOW_PRESETS[u["win"]], min_fvg_atr=u["min_fvg"], rr=cand["rr"], entry="edge")
    s, m = generate_meta(feat, inst, p)
    SF = setup_features(feat, bar_features(feat), m)
    trs = run_filtered(feat, inst, s, rule_mask(SF, cand["rule"]), u["max_trades"])
    a, b = split(trs)
    return dict(IS=stats(a), OOS=stats(b), ALL=stats(trs), months=monthly(trs), trades=trs)


if __name__ == "__main__" and "--candidate" in sys.argv:
    r = candidate()
    for k in ("IS", "OOS", "ALL"):
        print(k, fmt(r[k]))
    print(r["months"])

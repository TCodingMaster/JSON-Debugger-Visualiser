"""Daily direction "metalabel": one FVG Pro trade per day picked by a classifier.

1. Generate ALL FVG Pro setups (BOS + FVG, edge entry, min FVG 0.15 ATR) on
   MNQ, MGC and MCL 15m, all sessions (20:00-24:00 and 00:00-15:30 NY).
2. Label every setup on its own with the partial exit (1/2 at 1R -> BE ->
   runner 3R, time stop 8 bars, 2 contracts): win = net $ > 0. A setup that
   never fills has no label (it cannot be traded).
3. Features at the signal bar close only (truncation-checked).
4. Regularised logistic regression (numpy, L2) or shallow gradient boosting
   (depth-2 trees, shrinkage 0.05, 60 rounds, min leaf 40). Model choice,
   regularisation, threshold and max trades/day are chosen on IS only, using
   month-grouped cross-validation inside IS, purged by one day around each
   test month. Final model = fit on all IS labels, frozen for OOS.
5. Daily policy (causal): every setup with p >= threshold becomes a resting
   limit order; the first one that fills while flat is taken (any market),
   max N fills per Globex day, one position at a time.

Protocol: IS = entry < 2026-04-01, OOS = entry >= 2026-04-01.

Run: python -m lab.daily_metalabel
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features, fvg_pro
from . import wr60_exits as W
from .data import get_instrument

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "daily"
P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
CACHE = Path("/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/metalabel")
CUT = "2026-04-01"
MARKETS = {"MNQ": "MNQ_1m.pkl", "MGC": "MGC_1m.pkl", "MCL": "CL_1m.pkl"}
MG = dict(tp1=1.0, frac1=0.5, tp=3.0, be_tp1=True, tstop=8)
GEN = dict(windows=fvg_pro.WINDOW_PRESETS["all"], min_fvg_atr=0.15, entry="edge", max_trades=99)
WIN_BARS = 48  # expiry 20 + time stop 8 + margin; positions are flat by day end anyway

_ADVERSE = {1: lambda o, h, l, c: [o, l, h, c], -1: lambda o, h, l, c: [o, h, l, c]}
_PATH = W._path


class _Slice:
    """Minimal Features view on bars [a, b) for the single-setup simulator."""

    def __init__(self, f, a, b):
        self.o, self.h, self.l, self.c = f.o[a:b], f.h[a:b], f.l[a:b], f.c[a:b]
        self.mod, self.day, self.atr = f.mod[a:b], f.day[a:b], f.atr[a:b]
        self.df = f.df.iloc[a:b]
        self.n = b - a


def label(feat, inst, s, mode="path"):
    """Outcome of setup s traded alone (dict or None if never filled)."""
    a, b = s.bar, min(feat.n, s.bar + WIN_BARS)
    sl = _Slice(feat, a, b)
    s2 = dataclasses.replace(s, bar=0)
    W._path = _ADVERSE[s.side] if mode == "conservative" else _PATH
    try:
        tr = W.simulate(sl, [s2], inst, MG, max_trades=1)
    finally:
        W._path = _PATH
    return tr[0] if tr else None


# ----------------------------------------------------------------- features

def _rolling_mean_past(x, w):
    return pd.Series(x).rolling(w, min_periods=max(5, w // 4)).mean().to_numpy()


def bar_context(feat):
    """Per-bar context arrays (only data up to and including each bar)."""
    n, o, h, l, c, v, a = feat.n, feat.o, feat.h, feat.l, feat.c, feat.v, feat.atr
    day = feat.day
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], n]
    dhi, dlo, dop, gvw = np.empty(n), np.empty(n), np.empty(n), np.empty(n)
    pdr_rel, pdc = np.full(n, np.nan), np.full(n, np.nan)
    ranges, closes = [], []
    tp = (h + l + c) / 3
    for s, e in zip(starts, ends):
        dhi[s:e] = np.maximum.accumulate(h[s:e])
        dlo[s:e] = np.minimum.accumulate(l[s:e])
        dop[s:e] = o[s]
        cv = np.cumsum(v[s:e]) + 1e-12
        gvw[s:e] = np.cumsum(tp[s:e] * v[s:e]) / cv
        if len(ranges) >= 3:
            pdr_rel[s:e] = ranges[-1] / np.mean(ranges[-10:])
            pdc[s:e] = closes[-1]
        ranges.append(h[s:e].max() - l[s:e].min())
        closes.append(c[e - 1])
    bph = max(1, 60 // feat.interval_min)
    e20h = features.ema(c, 20 * bph)
    e50 = features.ema(c, 50)
    slope = np.zeros(n)
    slope[bph:] = e20h[bph:] - e20h[:-bph]
    atr_reg = a / _rolling_mean_past(a, 20 * 24 * 60 // feat.interval_min)
    body = np.abs(c - o)
    return dict(dhi=dhi, dlo=dlo, dop=dop, gvw=gvw, pdr_rel=pdr_rel, pdc=pdc, slope=slope,
                e20h=e20h, e50=e50, atr_reg=atr_reg, body=body)


SESS = (("asia", 18 * 60, 24 * 60), ("london", 0, 5 * 60), ("pre", 5 * 60, 8 * 60 + 30),
        ("nyam", 8 * 60 + 30, 11 * 60), ("mid", 11 * 60, 16 * 60))


def session_of(m):
    for name, a, b in SESS:
        if a <= m < b:
            return name
    return "mid"


def setup_features(feat, ctx, s, sym):
    t, side = s.bar, s.side
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, max(feat.atr[s.bar], 1e-9)
    bot, top = (float(x) for x in s.note.split("FVG ")[1].split("-")) if "FVG " in s.note else (s.entry, s.entry)
    clip = lambda x, k=5.0: float(np.clip(np.nan_to_num(x, nan=0.0), -k, k))  # noqa: E731
    rng = ctx["dhi"][t] - ctx["dlo"][t]
    pos = (c[t] - ctx["dlo"][t]) / rng if rng > 0 else 0.5
    lo10, hi10 = l[max(0, t - 10):t + 1].min(), h[max(0, t - 10):t + 1].max()
    leg = ((c[t] - lo10) if side > 0 else (hi10 - c[t])) / a
    x = dict(
        fvg_atr=clip((top - bot) / a),
        chase=clip(side * (c[t] - s.entry) / a),
        risk_atr=clip((s.entry - s.stop) * side / a),
        body_t=clip(ctx["body"][t] / a),
        body3=clip(ctx["body"][max(0, t - 3):t + 1].max() / a),
        dir_t=clip(side * (c[t] - o[t]) / a),
        leg=clip(leg, 8),
        vwap_d=clip(side * (c[t] - ctx["gvw"][t]) / a),
        pdh_d=clip(side * (c[t] - feat.pdh[t]) / a, 10) / 2,
        pdl_d=clip(side * (c[t] - feat.pdl[t]) / a, 10) / 2,
        day_pos=(pos if side > 0 else 1 - pos) - 0.5,
        day_move=clip(side * (c[t] - ctx["dop"][t]) / a, 10) / 2,
        pdc_d=clip(side * (c[t] - ctx["pdc"][t]) / a, 10) / 2,
        atr_reg=clip(np.log(max(ctx["atr_reg"][t], 1e-3)) if np.isfinite(ctx["atr_reg"][t]) else 0.0, 2),
        pdr_rel=clip(np.log(ctx["pdr_rel"][t]) if np.isfinite(ctx["pdr_rel"][t]) else 0.0, 2),
        htf_slope=clip(side * ctx["slope"][t] / a, 3),
        htf_with=float(np.sign(side * ctx["slope"][t])),
        e20h_d=clip(side * (c[t] - ctx["e20h"][t]) / a, 8) / 2,
        e50_d=clip(side * (c[t] - ctx["e50"][t]) / a, 8) / 2,
        side=float(side),
    )
    se = session_of(int(feat.mod[t]))
    for name, _, _ in SESS:
        x["s_" + name] = float(se == name)
    for m in MARKETS:
        x["m_" + m] = float(sym == m)
        for name, _, _ in SESS:
            x[f"x_{m}_{name}"] = float(sym == m and se == name)
    return x


# ----------------------------------------------------------------- dataset

def load_market(sym, tf="15min"):
    m1 = pd.read_pickle(P + MARKETS[sym])
    return data.resample(m1, tf)


def inst_of(sym):
    return dataclasses.replace(get_instrument(sym), contracts=2)


def build_dataset(df, sym, modes=("path", "conservative")):
    inst = inst_of(sym)
    feat = features.build(df, inst.tick)
    ctx = bar_context(feat)
    setups = fvg_pro.generate(feat, inst, GEN)
    rows = []
    for s in setups:
        if feat.mod[s.bar] >= 15 * 60 + 30 and feat.mod[s.bar] < 18 * 60:
            continue
        r = dict(sym=sym, bar=s.bar, sig_time=feat.df.index[s.bar].isoformat(),
                 **setup_features(feat, ctx, s, sym))
        for mode in modes:
            t = label(feat, inst, s, mode)
            pre = "" if mode == "path" else "c_"
            r[pre + "filled"] = t is not None
            if t is not None:
                r[pre + "entry_time"], r[pre + "exit_time"] = t["entry_time"], t["exit_time"]
                r[pre + "pnl"], r[pre + "r"] = t["pnl"], t["r"]
                # 2-tick stress: one more tick against on entry and on exit, per contract
                extra = 2 * inst.tick * inst.point_value * inst.contracts
                r[pre + "pnl2"] = t["pnl"] - extra
                r[pre + "r2"] = r[pre + "pnl2"] / (t["risk_pts"] * inst.point_value * inst.contracts)
        rows.append(r)
    return pd.DataFrame(rows)


def dataset(refresh=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "setups.pkl"
    if f.exists() and not refresh:
        return pd.read_pickle(f)
    parts = []
    for sym in MARKETS:
        d = build_dataset(load_market(sym), sym)
        print(sym, len(d), "setups", int(d["filled"].sum()), "filled", flush=True)
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["gday"] = (pd.to_datetime(d["sig_time"], utc=True).dt.tz_convert("America/New_York")
                 + pd.Timedelta(hours=6)).dt.strftime("%Y-%m-%d")
    d.to_pickle(f)
    return d


SMALL = ["fvg_atr", "chase", "risk_atr", "htf_with", "atr_reg"]


def feat_cols(d, inter=True):
    if inter == "small":
        return SMALL + [k for k in d.columns if k.startswith("x_")]
    skip = {"sym", "bar", "sig_time", "side", "gday", "filled", "entry_time", "exit_time", "pnl", "r", "pnl2", "r2"}
    cols = [k for k in d.columns if k not in skip and not k.startswith(("c_", "x_"))]
    if inter:
        cols += [k for k in d.columns if k.startswith("x_")]
    return cols


# ----------------------------------------------------------------- models

class Logit:
    def __init__(self, lam=1.0):
        self.lam = lam

    def fit(self, X, y):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = np.c_[np.ones(len(X)), (X - self.mu) / self.sd]
        w = np.zeros(Z.shape[1])
        R = np.eye(Z.shape[1]) * self.lam
        R[0, 0] = 0
        for _ in range(50):
            p = 1 / (1 + np.exp(-Z @ w))
            g = Z.T @ (p - y) + R @ w
            H = (Z * (p * (1 - p))[:, None]).T @ Z + R
            step = np.linalg.solve(H, g)
            w -= step
            if np.abs(step).max() < 1e-8:
                break
        self.w = w
        return self

    def predict(self, X):
        Z = np.c_[np.ones(len(X)), (X - self.mu) / self.sd]
        return 1 / (1 + np.exp(-Z @ self.w))


class GBM:
    """Depth-2 gradient boosted trees on quantile bins (log-loss)."""

    def __init__(self, rounds=60, lr=0.05, min_leaf=40, bins=12):
        self.rounds, self.lr, self.min_leaf, self.bins = rounds, lr, min_leaf, bins

    def _bin(self, X):
        return np.stack([np.searchsorted(self.edges[j], X[:, j], side="right") for j in range(X.shape[1])], 1)

    def _best_split(self, B, g, hss, idx):
        best = (0.0, None, None)
        G, Hh = g[idx].sum(), hss[idx].sum()
        base = G * G / (Hh + 1.0)
        for j in range(B.shape[1]):
            bj = B[idx, j]
            gs = np.bincount(bj, g[idx], self.bins + 1)
            hs = np.bincount(bj, hss[idx], self.bins + 1)
            cnt = np.bincount(bj, minlength=self.bins + 1)
            gl, hl, cl = np.cumsum(gs)[:-1], np.cumsum(hs)[:-1], np.cumsum(cnt)[:-1]
            ok = (cl >= self.min_leaf) & (len(idx) - cl >= self.min_leaf)
            if not ok.any():
                continue
            gain = gl ** 2 / (hl + 1) + (G - gl) ** 2 / (Hh - hl + 1) - base
            gain[~ok] = -1
            k = int(gain.argmax())
            if gain[k] > best[0]:
                best = (gain[k], j, k)
        return best[1], best[2]

    def fit(self, X, y):
        self.edges = [np.unique(np.quantile(X[:, j], np.linspace(0, 1, self.bins + 1)[1:-1])) for j in range(X.shape[1])]
        B = self._bin(X)
        p0 = np.clip(y.mean(), 1e-3, 1 - 1e-3)
        self.f0 = np.log(p0 / (1 - p0))
        F = np.full(len(y), self.f0)
        self.trees = []
        for _ in range(self.rounds):
            p = 1 / (1 + np.exp(-F))
            g, hs = y - p, p * (1 - p)
            all_i = np.arange(len(y))
            j1, k1 = self._best_split(B, g, hs, all_i)
            if j1 is None:
                break
            left = all_i[B[:, j1] <= k1]
            right = all_i[B[:, j1] > k1]
            sub = []
            for part in (left, right):
                j2, k2 = self._best_split(B, g, hs, part)
                if j2 is None:
                    v = g[part].sum() / (hs[part].sum() + 1)
                    sub.append((None, None, v, v))
                else:
                    a_ = part[B[part, j2] <= k2]
                    b_ = part[B[part, j2] > k2]
                    sub.append((j2, k2, g[a_].sum() / (hs[a_].sum() + 1), g[b_].sum() / (hs[b_].sum() + 1)))
            self.trees.append((j1, k1, sub))
            F += self.lr * self._tree(B, (j1, k1, sub))
        return self

    @staticmethod
    def _tree(B, tree):
        j1, k1, sub = tree
        out = np.empty(len(B))
        m = B[:, j1] <= k1
        for side_mask, (j2, k2, va, vb) in ((m, sub[0]), (~m, sub[1])):
            if j2 is None:
                out[side_mask] = va
            else:
                mm = B[:, j2] <= k2
                out[side_mask & mm] = va
                out[side_mask & ~mm] = vb
        return out

    def predict(self, X):
        B = self._bin(X)
        F = np.full(len(X), self.f0)
        for tr in self.trees:
            F += self.lr * self._tree(B, tr)
        return 1 / (1 + np.exp(-F))


def make_model(spec):
    kind, val = spec
    return Logit(val) if kind == "lr" else GBM(rounds=val)


def oof_is(d, cols, spec):
    """Month-grouped CV predictions inside IS (purged one day around each test month)."""
    lab_ = d[d["filled"] & (d["entry_time"] < CUT)].copy()
    month = lab_["gday"].str[:7]
    pred = pd.Series(np.nan, index=lab_.index)
    for m in sorted(month.unique()):
        te = month == m
        days = sorted(lab_.loc[te, "gday"].unique())
        lo = (pd.Timestamp(days[0]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        hi = (pd.Timestamp(days[-1]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        tr = ~te & ((lab_["gday"] < lo) | (lab_["gday"] > hi))
        mdl = make_model(spec).fit(lab_.loc[tr, cols].to_numpy(float), (lab_.loc[tr, "pnl"] > 0).to_numpy(float))
        pred[te] = mdl.predict(lab_.loc[te, cols].to_numpy(float))
    return pred


def fit_predict_frozen(d, cols, spec):
    tr = d["filled"] & (d["entry_time"] < CUT)
    mdl = make_model(spec).fit(d.loc[tr, cols].to_numpy(float), (d.loc[tr, "pnl"] > 0).to_numpy(float))
    return pd.Series(mdl.predict(d[cols].to_numpy(float)), index=d.index), mdl


def fit_predict_walkforward(d, cols, spec):
    """Expanding monthly retrain: month m is predicted by a model fit on labels whose
    exit happened before the first day of m minus 1 day (IS months use the frozen OOF-free
    rule: they are predicted by the model fit on all prior data only)."""
    month = d["gday"].str[:7]
    pred = pd.Series(np.nan, index=d.index)
    for m in sorted(month.unique()):
        start = pd.Timestamp(m + "-01") - pd.Timedelta(days=1)
        tr = d["filled"] & (pd.to_datetime(d["gday"]) < start)
        if tr.sum() < 300:
            continue
        mdl = make_model(spec).fit(d.loc[tr, cols].to_numpy(float), (d.loc[tr, "pnl"] > 0).to_numpy(float))
        te = month == m
        pred[te] = mdl.predict(d.loc[te, cols].to_numpy(float))
    return pred


# ----------------------------------------------------------------- daily policy

def select(d, prob, thr, max_day, pre=""):
    """Causal selection: resting orders for every setup with prob >= thr; trade the
    fills in time order, one position at a time, max_day per Globex day."""
    c = d[(prob >= thr) & d[pre + "filled"]].copy()
    c["p"] = prob[c.index]
    c = c.sort_values([pre + "entry_time", "p"], ascending=[True, False])
    out, last_exit, cnt = [], "", {}
    for idx, r in c.iterrows():
        et = r[pre + "entry_time"]
        if et < last_exit or et < r["sig_time"]:
            continue
        gd = r["gday"]
        if cnt.get(gd, 0) >= max_day:
            continue
        cnt[gd] = cnt.get(gd, 0) + 1
        last_exit = r[pre + "exit_time"]
        out.append(idx)
    return d.loc[out]


def trading_days(d, lo=None, hi=None):
    g = d["gday"]
    g = g[pd.to_datetime(g).dt.dayofweek < 5]
    if lo:
        g = g[g >= lo]
    if hi:
        g = g[g < hi]
    return g.nunique()


def stats(t, ndays, pre="", pnl="pnl", r="r"):
    if not len(t):
        return dict(trades=0, tpd=0.0, wr=None, exp=None, pf=None, net=0.0, dd=0.0)
    p = t[pre + pnl].to_numpy(float)
    rr = t[pre + r].to_numpy(float)
    eq = np.cumsum(p)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    gl = -p[p < 0].sum()
    return dict(trades=int(len(p)), tpd=len(p) / ndays, wr=float((p > 0).mean()), exp=float(rr.mean()),
                pf=float(p[p > 0].sum() / gl) if gl > 0 else 99.0, net=float(p.sum()), dd=dd)


def months_pos(t, pre="", pnl="pnl"):
    m = t.groupby(t[pre + "entry_time"].str[:7])[pre + pnl].sum()
    return int((m > 0).sum()), int(len(m)), {k: round(v) for k, v in m.items()}


def report(d, prob, thr, max_day, pre="", pnl="pnl", r="r"):
    t = select(d, prob, thr, max_day, pre)
    et = t[pre + "entry_time"]
    nd_is = trading_days(d, hi="2026-04-01")
    nd_oos = trading_days(d, lo="2026-04-01")
    res = dict(is_=stats(t[et < CUT], nd_is, pre, pnl, r), oos=stats(t[et >= CUT], nd_oos, pre, pnl, r),
               full=stats(t, nd_is + nd_oos, pre, pnl, r))
    res["pos_months"], res["n_months"], res["months"] = months_pos(t, pre, pnl)
    res["by_market"] = t["sym"].value_counts().to_dict()
    return res, t


def fmt(s):
    if not s["trades"]:
        return "0 tr"
    return (f"{s['trades']:3d} tr {s['tpd']:.2f}/d WR {s['wr']:.0%} {s['exp']:+.2f}R PF {s['pf']:.2f} "
            f"${s['net']:,.0f} DD ${s['dd']:,.0f}")


# ----------------------------------------------------------------- truncation check

def truncation_check(sym="MNQ", ks=(6000, 15000, 24000)):
    inst = inst_of(sym)
    df = load_market(sym)
    full_f = features.build(df, inst.tick)
    full_ctx = bar_context(full_f)
    full_s = {(s.bar, s.side, s.entry): s for s in fvg_pro.generate(full_f, inst, GEN)}
    for k in ks:
        f = features.build(df.iloc[:k], inst.tick)
        ctx = bar_context(f)
        for s in fvg_pro.generate(f, inst, GEN):
            if s.bar >= k - 1:
                continue
            assert (s.bar, s.side, s.entry) in full_s, (k, s.bar)
            a = setup_features(f, ctx, s, sym)
            b = setup_features(full_f, full_ctx, full_s[(s.bar, s.side, s.entry)], sym)
            for key in a:
                assert abs(a[key] - b[key]) < 1e-9, (k, s.bar, key, a[key], b[key])
    return True


# ----------------------------------------------------------------- research driver

SPECS = [("lr", 1.0), ("lr", 30.0), ("lr", 300.0), ("gbm", 40), ("gbm", 100)]
THRS = [round(x, 3) for x in np.arange(0.46, 0.661, 0.02)]
MAXD = (1, 2)


def search(d, log=print):
    rows = []
    nd_is = trading_days(d, hi=CUT)
    for inter in (False, True, "small"):
        cols = feat_cols(d, inter)
        for spec in (SPECS if inter != "small" else SPECS[:3]):
            pred = oof_is(d, cols, spec)
            lab_ = d.loc[pred.index]
            y = (lab_["pnl"] > 0).to_numpy(float)
            auc = _auc(pred.to_numpy(), y)
            dd = d.loc[pred.index]
            for thr in THRS:
                for md in MAXD:
                    t = select(dd, pred, thr, md)
                    s = stats(t, nd_is)
                    pm = months_pos(t)[0] if len(t) else 0
                    rows.append(dict(inter=inter, spec=spec, thr=thr, maxd=md, auc=auc, pos_m=pm, **s))
            log(f"inter={inter} {spec} IS-CV AUC {auc:.3f}")
    return pd.DataFrame(rows)


def _auc(p, y):
    o = np.argsort(p)
    rk = np.empty(len(p))
    rk[o] = np.arange(1, len(p) + 1)
    n1, n0 = y.sum(), len(y) - y.sum()
    return float((rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def choose(grid):
    """IS-only rule: trades/day >= 0.85 and PF >= 1.3 on IS-CV; max WR, then expectancy."""
    ok = grid[(grid["tpd"] >= 0.85) & (grid["pf"] >= 1.3)]
    if not len(ok):
        ok = grid[grid["tpd"] >= 0.85]
    return ok.sort_values(["wr", "exp"], ascending=False).iloc[0]


def final(d, best, log=print):
    cols = feat_cols(d, best["inter"])
    spec = tuple(best["spec"])
    thr, md = float(best["thr"]), int(best["maxd"])
    prob, _ = fit_predict_frozen(d, cols, spec)
    out = {}
    for name, kw in (("frozen path 1 tick", {}), ("frozen path 2 ticks", dict(pnl="pnl2", r="r2")),
                     ("frozen conservative", dict(pre="c_")), ("frozen conservative 2 ticks", dict(pre="c_", pnl="pnl2", r="r2"))):
        res, _ = report(d, prob, thr, md, **kw)
        out[name] = res
        log(f"{name:28s} | IS {fmt(res['is_'])} | OOS {fmt(res['oos'])} | +m {res['pos_months']}/{res['n_months']}")
    wf = fit_predict_walkforward(d, cols, spec)
    res, _ = report(d, wf.fillna(0.0), thr, md)
    out["walk-forward monthly retrain"] = res
    log(f"{'walk-forward monthly retrain':28s} | IS {fmt(res['is_'])} | OOS {fmt(res['oos'])} | +m {res['pos_months']}/{res['n_months']}")
    # neighbours: threshold +-0.02, other max/day
    for t2 in (thr - 0.04, thr - 0.02, thr + 0.02, thr + 0.04):
        res, _ = report(d, prob, t2, md)
        out[f"thr {t2:.2f}"] = res
        log(f"{'neighbour thr %.2f' % t2:28s} | IS {fmt(res['is_'])} | OOS {fmt(res['oos'])} | +m {res['pos_months']}/{res['n_months']}")
    # baseline: no model, every fill (first-come, max md/day)
    res, _ = report(d, pd.Series(1.0, index=d.index), 0.5, md)
    out["no model (first fill)"] = res
    log(f"{'no model, first fill':28s} | IS {fmt(res['is_'])} | OOS {fmt(res['oos'])} | +m {res['pos_months']}/{res['n_months']}")
    # OOS AUC of the frozen model
    m = d["filled"] & (d["entry_time"] >= CUT)
    out["oos_auc"] = _auc(prob[m].to_numpy(), (d.loc[m, "pnl"] > 0).to_numpy(float))
    log(f"frozen model OOS AUC {out['oos_auc']:.3f}")
    return out


if __name__ == "__main__":
    d = dataset(refresh="--refresh" in sys.argv)
    print(len(d), "setups;", int(d["filled"].sum()), "filled; base WR",
          f"{(d.loc[d['filled'], 'pnl'] > 0).mean():.1%}")
    print("truncation check:", truncation_check())
    g = search(d)
    CACHE.mkdir(parents=True, exist_ok=True)
    g.to_pickle(CACHE / "grid.pkl")
    print("configs tried:", len(g))
    print(g.sort_values("wr", ascending=False).head(10).to_string())
    best = choose(g)
    print("chosen on IS:", best.to_dict())
    out = final(d, best)
    OUT.mkdir(parents=True, exist_ok=True)
    (CACHE / "final.json").write_text(json.dumps({"best": {k: (list(v) if isinstance(v, tuple) else v)
                                                            for k, v in best.to_dict().items()}, **out}, default=str))

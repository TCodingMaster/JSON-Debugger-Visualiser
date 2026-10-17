"""Regime filters for FVG Pro Leto (MNQ 15m, London 02:00-05:00 NY).

Direction "regime": try to make the London FVG continuation more consistent by
skipping setups in bad regimes. Every regime value is computed causally from
data up to and including the signal bar (Setup.bar); setups failing a filter
are removed BEFORE the engine runs, so the engine may then take a later setup
that day (as live trading would).

Filters tested (thresholds chosen on in-sample only, IS = entry < 2026-04-01):
  datr_pct   20-day ATR of Globex-day ranges, percentile vs prior 120 days
  pr_rel     prior Globex-day range / 20-day daily ATR
  asia_rel   Asia range (20:00-24:00) / 20-day daily ATR
  er         efficiency ratio of 15m closes over the last 32 bars (8h)
  adx1h      ADX(14) on completed 1-hour bars
  on_move    |close - prior RTH close| / daily ATR (overnight gap/move)
  on_dir     side * (close - prior RTH close) / daily ATR (with / against move)
  vol_rel    15m ATR / daily ATR
  weekday    Globex day of week
  equity     skip after N consecutive (shadow) losses; skip while rolling-20 R < 0
  weekly     weekly loss limit in R
NY AM (08:30-11:00) as a second rule set, own small grid, IS only.

Run:  PYTHONPATH=. python -m lab.prof_regime
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
OUT = ROOT / "results" / "profit"
P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
CUT = "2026-04-01"
LETO = dict(windows=fvg_pro.WINDOW_PRESETS["london"], min_fvg_atr=0.3, entry="edge", rr=2.0, max_trades=1)
N_CONFIGS = 0


# --------------------------------------------------------------------------- #
# regime features (causal)
# --------------------------------------------------------------------------- #
def _adx(h, l, c, n=14):
    up = np.r_[0, np.diff(h)]
    dn = np.r_[0, -np.diff(l)]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - l, np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])])
    a = 1.0 / n

    def rma(x):
        out = np.empty_like(x)
        s = x[0]
        for i, v in enumerate(x):
            s = s + a * (v - s) if i else v
            out[i] = s
        return out
    atr_ = rma(tr)
    pdi = 100 * rma(pdm) / np.where(atr_ > 0, atr_, np.nan)
    ndi = 100 * rma(ndm) / np.where(atr_ > 0, atr_, np.nan)
    dx = 100 * np.abs(pdi - ndi) / np.where(pdi + ndi > 0, pdi + ndi, np.nan)
    return rma(np.nan_to_num(dx))


def regime(df: pd.DataFrame, feat) -> dict:
    """Per-bar regime arrays, each using only bars <= i."""
    n = feat.n
    h, l, c = feat.h, feat.l, feat.c
    day = feat.day
    nd = day.max() + 1
    dhi = np.full(nd, -np.inf)
    dlo = np.full(nd, np.inf)
    np.maximum.at(dhi, day, h)
    np.minimum.at(dlo, day, l)
    dr = dhi - dlo                                   # range of each Globex day (complete)
    # values known at the start of day d: built from days < d only
    s = pd.Series(dr)
    datr_d = s.rolling(20, min_periods=10).mean().shift(1).values
    pr_d = s.shift(1).values
    pct_d = pd.Series(datr_d).rolling(120, min_periods=40).apply(
        lambda x: (x[:-1] < x[-1]).mean() if len(x) > 1 else np.nan, raw=True).values
    datr = datr_d[day]
    out = dict(datr_pct=pct_d[day], pr_rel=pr_d[day] / datr_d[day])
    out["asia_rel"] = (feat.asia_h - feat.asia_l) / datr
    # efficiency ratio over 32 bars
    N = 32
    er = np.full(n, np.nan)
    ad = np.abs(np.diff(c, prepend=c[0]))
    cs = np.cumsum(ad)
    er[N:] = np.abs(c[N:] - c[:-N]) / np.maximum(cs[N:] - cs[:-N], 1e-9)
    out["er"] = er
    # ADX on completed 1h bars
    h1 = data.resample(df, "60min")
    adx = _adx(h1["high"].values, h1["low"].values, h1["close"].values)
    h1_close_t = (h1.index + pd.Timedelta(minutes=60)).asi8
    bar_close_t = (df.index + pd.Timedelta(minutes=feat.interval_min)).asi8
    k = np.searchsorted(h1_close_t, bar_close_t, side="right") - 1
    out["adx1h"] = np.where(k >= 0, adx[np.clip(k, 0, None)], np.nan)
    # prior RTH close (last bar ending at/before 16:00 of an earlier Globex day)
    rth_close = np.full(n, np.nan)
    last = np.nan
    cur_day, carry = -1, np.nan
    for i in range(n):
        if day[i] != cur_day:
            cur_day, carry = day[i], last
        if 9 * 60 + 30 <= feat.mod[i] < 16 * 60:
            last = c[i]
        rth_close[i] = carry
    mv = (c - rth_close) / datr
    out["on_move"] = np.abs(mv)
    out["on_signed"] = mv
    out["vol_rel"] = feat.atr / datr
    gd = (df.index + pd.Timedelta(hours=6)).dayofweek.values  # Globex day weekday
    out["weekday"] = gd.astype(float)
    return out


def truncation_check(df, k=None):
    """Regime values on df[:k] must equal those on the full df for bars < k-1."""
    inst = data.get_instrument("MNQ")
    k = k or int(len(df) * 0.6)
    fa = features.build(df, inst.tick)
    fb = features.build(df.iloc[:k], inst.tick)
    ra, rb = regime(df, fa), regime(df.iloc[:k], fb)
    bad = []
    for key in ra:
        a, b = ra[key][:k - 1], rb[key][:k - 1]
        if not np.allclose(np.nan_to_num(a, nan=-9), np.nan_to_num(b, nan=-9), equal_nan=True):
            bad.append(key)
    return bad


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def stats(trades) -> dict:
    if not trades:
        return dict(n=0, wr=0, exp=0, pf=0, net=0, dd=0)
    r = np.array([t.r for t in trades])
    pnl = np.array([t.pnl for t in trades])
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    return dict(n=len(r), wr=round(float((r > 0).mean()), 3), exp=round(float(r.mean()), 3),
                pf=round(float(gw / gl) if gl > 0 else 99.0, 2), net=round(float(pnl.sum())), dd=round(dd),
                R=round(float(r.sum()), 1),
                pf_usd=round(float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else 99.0, 2))


def monthly(trades) -> dict:
    months = pd.period_range("2025-09", "2026-10", freq="M").astype(str)
    m = {k: 0.0 for k in months}
    for t in trades:
        m[t.entry_time[:7]] = m.get(t.entry_time[:7], 0.0) + t.r
    return {k: round(v, 1) for k, v in m.items()}


def full_report(trades) -> dict:
    is_ = [t for t in trades if t.entry_time < CUT]
    oos = [t for t in trades if t.entry_time >= CUT]
    mo = monthly(trades)
    return dict(full=stats(trades), is_=stats(is_), oos=stats(oos), monthly=mo,
                pos_months=sum(v > 0 for v in mo.values()), worst=min(mo.values()))


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
class Lab:
    def __init__(self, df):
        self.df = df
        self.inst = data.get_instrument("MNQ")
        self.feat = features.build(df, self.inst.tick)
        self.reg = regime(df, self.feat)
        self._setups = {}

    def setups(self, p):
        key = json.dumps(p, sort_keys=True, default=str)
        if key not in self._setups:
            self._setups[key] = fvg_pro.generate(self.feat, self.inst, {**fvg_pro.DEFAULTS, **p})
        return self._setups[key]

    def run(self, p=LETO, filt=None, intrabar="path", slip=1):
        global N_CONFIGS
        N_CONFIGS += 1
        S = self.setups(p)
        if filt is not None:
            S = [s for s in S if filt(s, self.reg)]
        cfg = EngineConfig(flatten="15:55", max_trades_per_day=p.get("max_trades", 1), intrabar=intrabar,
                           slippage_ticks=slip)
        return engine.run(self.feat, S, self.inst, cfg)


def mk_filter(key, lo=-np.inf, hi=np.inf, signed=False):
    """Keep setups whose regime[key] (times side if signed) is within [lo, hi]."""
    def f(s, reg):
        v = reg[key][s.bar]
        if np.isnan(v):
            return True
        if signed:
            v *= s.side
        return lo <= v <= hi
    f.desc = f"{key}{'*side' if signed else ''} in [{lo:.3g}, {hi:.3g}]"
    return f


def equity_filter(trades, mode, n):
    """Shadow-equity filters: decide each trade from previous shadow trades only."""
    kept, hist = [], []
    week_r, week_id = 0.0, None
    for t in trades:
        take = True
        if mode == "streak":
            take = not (len(hist) >= n and all(x < 0 for x in hist[-n:]))
        elif mode == "roll":
            take = not (len(hist) >= n and sum(hist[-n:]) < 0)
        elif mode == "weekly":
            wk = pd.Timestamp(t.entry_time).to_period("W").ordinal
            if wk != week_id:
                week_id, week_r = wk, 0.0
            take = week_r > -n
        if take:
            kept.append(t)
            if mode == "weekly":
                week_r += t.r
        hist.append(t.r)
    return kept


def score_is(rep):
    """IS-only selection score: PF and positive-month share, need >= 35 IS trades."""
    s = rep["is_"]
    if s["n"] < 35:
        return -9
    im = [v for k, v in rep["monthly"].items() if k < CUT[:7]]
    return s["exp"] * np.sqrt(s["n"]) + 0.5 * sum(v > 0 for v in im) / len(im)


def main(log=print):
    m1 = pd.read_pickle(P + "MNQ_1m.pkl")
    df = data.resample(m1, "15min")
    bad = truncation_check(df)
    log(f"truncation check (regime): {'OK' if not bad else 'FAIL ' + str(bad)}")
    lab = Lab(df)
    res = dict(truncation_ok=not bad)

    base = lab.run()
    res["baseline"] = full_report(base)
    log("baseline", res["baseline"]["full"], res["baseline"]["is_"], res["baseline"]["oos"], res["baseline"]["pos_months"])

    # ---------------- single regime filters: thresholds at IS-setup quantiles
    S = lab.setups(LETO)
    is_bars = [s.bar for s in S if str(df.index[s.bar]) < CUT]
    rows = []
    for key, signed in [("datr_pct", False), ("pr_rel", False), ("asia_rel", False), ("er", False),
                        ("adx1h", False), ("on_move", False), ("on_signed", True), ("vol_rel", False)]:
        vals = np.array([lab.reg[key][s.bar] * (s.side if signed else 1) for s in S if str(df.index[s.bar]) < CUT])
        vals = vals[~np.isnan(vals)]
        for q in (0.2, 0.33, 0.5, 0.67, 0.8):
            thr = float(np.quantile(vals, q))
            for side_ in ("below", "above"):
                f = mk_filter(key, hi=thr, signed=signed) if side_ == "below" else mk_filter(key, lo=thr, signed=signed)
                rep = full_report(lab.run(filt=f))
                rows.append(dict(kind="regime", desc=f.desc, key=key, q=q, keep=side_, rep=rep, sc=score_is(rep)))
    for wd in range(5):
        f = (lambda w: (lambda s, reg: reg["weekday"][s.bar] != w))(wd)
        rep = full_report(lab.run(filt=f))
        rows.append(dict(kind="weekday", desc=f"skip weekday {wd}", key="weekday", q=wd, keep="skip", rep=rep,
                         sc=score_is(rep)))
    for mode, ns in (("streak", (2, 3, 4)), ("roll", (10, 20, 30)), ("weekly", (1.0, 2.0, 3.0))):
        for n in ns:
            rep = full_report(equity_filter(base, mode, n))
            rows.append(dict(kind="equity", desc=f"{mode} {n}", key=mode, q=n, keep="", rep=rep, sc=score_is(rep)))
    res["n_single"] = len(rows)

    def line(r):
        a, i, o = r["rep"]["full"], r["rep"]["is_"], r["rep"]["oos"]
        return (f"{r['desc']:<34} sc {r['sc']:+.2f} | full {a['n']:3d} {a['exp']:+.2f}R PF {a['pf']:.2f} ${a['net']:>6} "
                f"DD {a['dd']:>5} | IS {i['n']:3d} {i['exp']:+.2f} PF {i['pf']:.2f} | OOS {o['n']:3d} {o['exp']:+.2f} "
                f"PF {o['pf']:.2f} | +m {r['rep']['pos_months']}/14 worst {r['rep']['worst']}")
    rows.sort(key=lambda r: -r["sc"])
    log("\nTop single filters by IS score:")
    for r in rows[:20]:
        log(line(r))
    bscore = score_is(res["baseline"])
    log(f"baseline IS score {bscore:+.2f}")
    # IS-rank vs OOS correlation over all single filters
    sc = np.array([r["sc"] for r in rows if r["sc"] > -9])
    oo = np.array([r["rep"]["oos"]["exp"] for r in rows if r["sc"] > -9])
    res["is_oos_corr"] = round(float(np.corrcoef(sc, oo)[0, 1]), 2)
    res["frac_oos_better"] = round(float((oo > res["baseline"]["oos"]["exp"]).mean()), 2)
    log(f"single filters: IS score vs OOS exp corr {res['is_oos_corr']}, "
        f"share with OOS exp > baseline {res['frac_oos_better']}")
    res["single"] = [dict(desc=r["desc"], sc=round(r["sc"], 3), full=r["rep"]["full"], is_=r["rep"]["is_"],
                          oos=r["rep"]["oos"], pos_months=r["rep"]["pos_months"], worst=r["rep"]["worst"])
                     for r in rows]

    # neighbours of the IS-best regime filter
    best = next(r for r in rows if r["kind"] == "regime")
    log(f"\nneighbours of IS-best regime filter: {best['key']} keep {best['keep']}")
    for r in sorted([r for r in rows if r["key"] == best["key"] and r["keep"] == best["keep"]], key=lambda r: r["q"]):
        log(line(r))
    res["best_single"] = best["desc"]

    # ---------------- NY AM rule set (IS-only selection)
    log("\nNY AM 08:30-11:00 grid:")
    ny_rows = []
    for mf in (0.15, 0.3, 0.5):
        for rr in (1.5, 2.0, 2.5):
            for tf in (False, True):
                p = dict(windows=fvg_pro.WINDOW_PRESETS["ny_am"], min_fvg_atr=mf, entry="edge", rr=rr,
                         max_trades=1, trend_filter=tf)
                rep = full_report(lab.run(p=p))
                ny_rows.append(dict(p=p, rep=rep, sc=score_is(rep),
                                    desc=f"NY mf{mf} rr{rr} trend{int(tf)}"))
    ny_rows.sort(key=lambda r: -r["sc"])
    for r in ny_rows[:8]:
        log(line(r))
    ny_pos = sum(r["rep"]["is_"]["exp"] > 0 for r in ny_rows)
    log(f"NY configs positive in IS: {ny_pos}/{len(ny_rows)}")
    res["ny"] = [dict(desc=r["desc"], full=r["rep"]["full"], is_=r["rep"]["is_"], oos=r["rep"]["oos"],
                      pos_months=r["rep"]["pos_months"]) for r in ny_rows]
    ny_best = ny_rows[0]

    # ---------------- final candidates + robustness
    finals = {}

    def eval_variant(name, filt=None, eqf=None, p=LETO):
        out = {}
        for tag, ib, sl in (("path", "path", 1), ("conservative", "conservative", 1), ("slip2", "path", 2)):
            tr = lab.run(p=p, filt=filt, intrabar=ib, slip=sl)
            if eqf:
                tr = equity_filter(tr, *eqf)
            out[tag] = full_report(tr)
            if tag == "path":
                out["trades"] = tr
        finals[name] = out
        a = out["path"]
        log(f"{name:<28} full {a['full']} | IS {a['is_']['exp']} PF {a['is_']['pf']} | OOS {a['oos']['exp']} "
            f"PF {a['oos']['pf']} | +m {a['pos_months']} | cons {out['conservative']['full']['exp']} "
            f"PF {out['conservative']['full']['pf']} | slip2 {out['slip2']['full']['exp']} PF {out['slip2']['full']['pf']}")
        return out

    log("\nFinal candidates (robustness: stop-first intrabar, 2 ticks slippage):")
    eval_variant("baseline")
    bf = mk_filter(best["key"], **({"hi": float(best["desc"].split(",")[1].strip(" ]"))} if best["keep"] == "below"
                                    else {"lo": float(best["desc"].split("[")[1].split(",")[0])}),
                   signed=best["key"] == "on_signed")
    eval_variant("best_regime_filter", filt=bf)
    eq_rows = [r for r in rows if r["kind"] == "equity"]
    eb = max(eq_rows, key=lambda r: r["sc"])
    eval_variant(f"best_equity_{eb['desc']}", eqf=(eb["key"], eb["q"]))
    if ny_best["rep"]["is_"]["exp"] > 0:
        ny = eval_variant("ny_am_best", p=ny_best["p"])
        # portfolio: two separate rule sets (positions may overlap in time)
        lon = finals["baseline"]["trades"]
        port = sorted(lon + ny["trades"], key=lambda t: t.entry_time)
        rep = full_report(port)
        finals["portfolio_leto_plus_ny"] = dict(path=rep)
        log(f"portfolio Leto + NY: full {rep['full']} IS {rep['is_']} OOS {rep['oos']} +m {rep['pos_months']} "
            f"monthly {rep['monthly']}")
        for tag in ("conservative", "slip2"):
            ib, sl = ("conservative", 1) if tag == "conservative" else ("path", 2)
            pt = sorted(lab.run(intrabar=ib, slip=sl) + lab.run(p=ny_best["p"], intrabar=ib, slip=sl),
                        key=lambda t: t.entry_time)
            finals["portfolio_leto_plus_ny"][tag] = full_report(pt)
            log(f"  portfolio {tag}: {finals['portfolio_leto_plus_ny'][tag]['full']} "
                f"+m {finals['portfolio_leto_plus_ny'][tag]['pos_months']}")
    for v in finals.values():
        v.pop("trades", None)
    res["finals"] = finals
    res["n_configs"] = N_CONFIGS
    log(f"\nengine runs (configurations incl. robustness re-runs): {N_CONFIGS}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "regime.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def stage2(log=print):
    """Fixed a-priori threshold grids for the regime ideas that ranked high in stage 1,
    alone and combined with the streak-3 equity filter. Selection: IS score with >= 40 IS trades."""
    m1 = pd.read_pickle(P + "MNQ_1m.pkl")
    df = data.resample(m1, "15min")
    lab = Lab(df)
    grids = {
        ("datr_pct", "below"): (0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95),
        ("asia_rel", "above"): (0.10, 0.12, 0.14, 0.16, 0.18, 0.20),
        ("vol_rel", "above"): (0.040, 0.045, 0.050, 0.055, 0.060),
        ("adx1h", "above"): (12, 14, 16, 18, 20),
        ("pr_rel", "above"): (0.6, 0.7, 0.8, 0.9, 1.0),
    }
    rows = []
    for (key, keep), thrs in grids.items():
        for thr in thrs:
            f = mk_filter(key, hi=thr) if keep == "below" else mk_filter(key, lo=thr)
            tr = lab.run(filt=f)
            for eq in (None, ("streak", 3)):
                t2 = equity_filter(tr, *eq) if eq else tr
                rep = full_report(t2)
                rep["is_n_ok"] = rep["is_"]["n"] >= 40
                rows.append(dict(key=key, keep=keep, thr=thr, eq=eq, rep=rep,
                                 sc=score_is(rep) if rep["is_n_ok"] else -9))
    # two-filter combos of the stage-1 leaders at middle thresholds (datr_pct<=0.85 & asia_rel>=0.14 etc.)
    combos = [(("datr_pct", "below", 0.85), ("asia_rel", "above", 0.12)),
              (("datr_pct", "below", 0.85), ("vol_rel", "above", 0.045)),
              (("datr_pct", "below", 0.85), ("adx1h", "above", 14)),
              (("asia_rel", "above", 0.12), ("adx1h", "above", 14))]
    for c in combos:
        fs = [mk_filter(k, hi=t) if kp == "below" else mk_filter(k, lo=t) for k, kp, t in c]
        tr = lab.run(filt=lambda s, reg, fs=fs: all(f(s, reg) for f in fs))
        rep = full_report(tr)
        rows.append(dict(key=" & ".join(f"{k} {kp} {t}" for k, kp, t in c), keep="", thr=0, eq=None, rep=rep,
                         sc=score_is(rep) if rep["is_"]["n"] >= 40 else -9))
    for r in rows:
        a, i, o = r["rep"]["full"], r["rep"]["is_"], r["rep"]["oos"]
        log(f"{r['key']:<44} {r['keep']:<5} {r['thr']:<5} eq={'s3' if r['eq'] else '-':<2} sc {r['sc']:+.2f} | "
            f"full {a['n']:3d} {a['exp']:+.2f}R PFr {a['pf']:.2f} PF$ {a['pf_usd']:.2f} ${a['net']:>6} DD {a['dd']:>5} | "
            f"IS {i['n']:2d} {i['exp']:+.2f} PF$ {i['pf_usd']:.2f} | OOS {o['n']:2d} {o['exp']:+.2f} PF$ {o['pf_usd']:.2f} | "
            f"+m {r['rep']['pos_months']} worst {r['rep']['worst']}")
    sc = np.array([r["sc"] for r in rows if r["sc"] > -9])
    oo = np.array([r["rep"]["oos"]["exp"] for r in rows if r["sc"] > -9])
    log(f"stage2: {len(rows)} variants, IS score vs OOS exp corr {np.corrcoef(sc, oo)[0, 1]:.2f}")
    best = max(rows, key=lambda r: r["sc"])
    log(f"IS-selected: {best['key']} {best['keep']} {best['thr']} eq={best['eq']}  monthly {best['rep']['monthly']}")
    return rows, best, lab


SELECTED = dict(key="asia_rel", lo=0.10, eq=("streak", 3))   # IS-selected in stage2


def selected_trades(lab, intrabar="path", slip=1, sel=SELECTED):
    tr = lab.run(filt=mk_filter(sel["key"], lo=sel["lo"]), intrabar=intrabar, slip=slip)
    return equity_filter(tr, *sel["eq"]) if sel.get("eq") else tr


def final(log=print):
    m1 = pd.read_pickle(P + "MNQ_1m.pkl")
    lab = Lab(data.resample(m1, "15min"))
    out = {}
    for tag, ib, sl in (("path", "path", 1), ("conservative", "conservative", 1), ("slip2", "path", 2),
                        ("slip3", "path", 3)):
        rep = full_report(selected_trades(lab, ib, sl))
        out[tag] = rep
        log(tag, rep["full"], "IS", rep["is_"], "OOS", rep["oos"], "+m", rep["pos_months"])
    log("monthly", out["path"]["monthly"])
    # streak-3 alone and baseline for comparison
    out["streak3_only"] = full_report(equity_filter(lab.run(), "streak", 3))
    log("streak3 only", out["streak3_only"]["full"], out["streak3_only"]["monthly"])
    # real futures sanity check (~70 days)
    from . import research
    st = research.load_store(["MNQ"], ["15m"])
    if ("MNQ", "15m") in st:
        rl = Lab(st[("MNQ", "15m")])
        b = rl.run()
        s_ = selected_trades(rl)
        out["real_baseline"], out["real_selected"] = stats(b), stats(s_)
        log("real MNQ baseline", out["real_baseline"], "| selected", out["real_selected"],
            st[("MNQ", "15m")].index[0], st[("MNQ", "15m")].index[-1])
    (OUT / "regime_final.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stage2":
        stage2()
    elif len(sys.argv) > 1 and sys.argv[1] == "final":
        final()
    else:
        main()

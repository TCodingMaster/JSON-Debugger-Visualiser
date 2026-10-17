"""Daily direction "levels": liquidity sweep of a key level, then FVG / IFVG reversal entry.

Idea (user): every day look for a sweep of PDH/PDL, overnight high/low, Asia or London
high/low, then enter on the FVG (or inverted FVG) that forms after the sweep, against the
sweep (reversal). Exit = the standard partial exit (1/2 at 1R -> BE -> runner 3R, time stop 8 bars).

Signal (short side shown; long mirrors), all decided at bar CLOSE, order works from the next bar:
  1. Levels (lab.features, all causal): pdh, onh (known 09:30), asia_h (known 00:00),
     london_h (known 05:00). A level is "armed" on a bar whose close is below it.
  2. Sweep: an armed level is traded through (high > level) on a bar whose start lies in
     the sweep window. One sweep per level per Globex day.
     Optional `htf` (5m execution after a 15m sweep): the sweep only counts once the
     15-minute bucket that contains it has CLOSED back below the level (checked at the
     close of the last entry-TF bar of that bucket).
     Optional `reclaim`: on the plain path the sweep bar (or a later bar in the watch)
     must close back below the level before an entry is allowed.
  3. Within `look` bars after the sweep:
       FVG  : a bearish gap h[k] < l[k-2] with size >= mf*ATR and k-2 >= sweep bar.
              Limit sell at the gap's near edge h[k]; invalidate on a close above l[k-2].
       IFVG : a bullish gap formed in the `ifvg_back` bars up to the sweep is closed
              through (close < its bottom) -> limit sell at the gap bottom (retest);
              invalidate on a close above the gap top.
     Stop: highest high since the sweep + 2 ticks. One setup per sweep (the first).
  4. Chase filter (optional): skip if (entry - close)/ATR > chase at the signal bar.
Execution/stats: lab.daily_portfolio.simulate (copy of wr60_exits.simulate + slip ticks,
conservative intrabar, 1-minute replay). Costs $/side as data.py, 2 contracts per market.

Protocol: IS = entry < 2026-04-01, OOS >= 2026-04-01; choices on IS only.

Run:
  PYTHONPATH=. python -m lab.daily_levels trunc     # truncation (look-ahead) check
  PYTHONPATH=. python -m lab.daily_levels grid      # component grid -> scratchpad json
  PYTHONPATH=. python -m lab.daily_levels final     # selection on IS + portfolio + robustness
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features
from . import daily_portfolio as DP
from .engine import Setup
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "daily"
SCR = Path("/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/levels")
CUT = DP.CUT

LEVELSETS = {
    "pd": ("pd",),
    "sess": ("asia", "london", "on"),
    "all": ("pd", "on", "asia", "london"),
}
SWEEP_WINDOWS = {
    "london": (("02:00", "05:00"),),
    "ny": (("08:30", "11:30"),),
    "lon+ny": (("02:00", "05:00"), ("08:30", "11:30")),
    "day": (("00:00", "11:30"),),
}

DEF = dict(levels="all", win="lon+ny", mode="fvg", mf=0.15, look=6, reclaim=False, chase=0.0,
           ifvg_back=6, htf=0, buffer_ticks=2, expiry=8, entry="edge", stop_mode="ext", trend=0)


def _level_arrays(feat, names):
    out = []
    for nm in names:
        if nm == "pd":
            out.append((nm, feat.pdh, feat.pdl))
        elif nm == "on":
            out.append((nm, feat.onh, feat.onl))
        elif nm == "asia":
            out.append((nm, feat.asia_h, feat.asia_l))
        elif nm == "london":
            out.append((nm, feat.london_h, feat.london_l))
    return out


def generate(feat, inst, p=None):
    p = {**DEF, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n, mod, day = feat.n, feat.mod, feat.day
    buf = p["buffer_ticks"] * inst.tick
    win = np.zeros(n, bool)
    for s_, e_ in SWEEP_WINDOWS[p["win"]]:
        win |= (mod >= hm(s_)) & (mod < hm(e_))
    lv = _level_arrays(feat, LEVELSETS[p["levels"]])
    htf = int(p["htf"] or 0)
    step = feat.interval_min
    if htf:
        # bucket id of each bar (htf-minute buckets on the clock) and "last bar of bucket" flag
        ts = feat.df.index
        mins = np.asarray((ts - pd.Timestamp("2000-01-01", tz="UTC")) // pd.Timedelta(minutes=1), dtype=np.int64)
        bucket = mins // htf
        last_in_bucket = ((mins + step) % htf) == 0   # by the clock: this bar closes the bucket
        # the bar after which the bucket is complete: last bar whose start + step <= bucket end
        # (with step | htf the last bar of the bucket closes exactly at the bucket end)
    mf, look, chase = p["mf"], int(p["look"]), p["chase"]
    tsign = None
    if p["trend"]:
        from .fvg_pro import trend_sign
        tsign = trend_sign(feat)   # slope of a 20-hour EMA, causal
    out = []
    armed = {}           # (name, side) -> bool, reset each day
    used = set()         # (day, name, side) sweeps already taken
    watches = []         # dicts: side, level, bar, ext, reclaimed, confirmed, done
    cur_day = -1
    for i in range(2, n):
        if day[i] != cur_day:
            cur_day = day[i]
            armed = {}
            watches = []
        # --- update watches with this bar (extreme, reclaim, confirmation)
        for w in watches:
            if w["done"]:
                continue
            side = w["side"]
            if i > w["bar"]:
                w["ext"] = max(w["ext"], h[i]) if side < 0 else min(w["ext"], l[i])
            if (c[i] < w["level"]) if side < 0 else (c[i] > w["level"]):
                w["reclaimed"] = True
            if htf and not w["confirmed"] and i >= w["bar"] and bucket[i] == w["bucket"] and last_in_bucket[i]:
                # 15m bucket close relative to the level
                w["confirmed"] = bool(w["reclaimed_now"](i))
                if not w["confirmed"]:
                    w["done"] = True
            if i - w["bar"] > look:
                w["done"] = True
        # --- new sweeps on this bar
        for nm, hi_a, lo_a in lv:
            for side, arr in ((-1, hi_a), (1, lo_a)):
                L = arr[i]
                if np.isnan(L) or (cur_day, nm, side) in used:
                    continue
                key = (nm, side)
                if armed.get(key) and win[i] and ((h[i] > L) if side < 0 else (l[i] < L)):
                    used.add((cur_day, nm, side))
                    ext = h[i] if side < 0 else l[i]
                    w = dict(side=side, level=L, bar=i, ext=ext, done=False, name=nm,
                             reclaimed=bool((c[i] < L) if side < 0 else (c[i] > L)), confirmed=not htf)
                    if htf:
                        w["bucket"] = bucket[i]
                        lvl = L
                        w["reclaimed_now"] = (lambda j, lvl=lvl, sd=side: (c[j] < lvl) if sd < 0 else (c[j] > lvl))
                        if last_in_bucket[i]:
                            w["confirmed"] = bool(w["reclaimed_now"](i))
                            if not w["confirmed"]:
                                w["done"] = True
                    # IFVG candidates: opposite-direction gaps formed shortly before / at the sweep
                    cands = []
                    for k in range(max(2, i - int(p["ifvg_back"])), i + 1):
                        if side < 0 and l[k] > h[k - 2] and l[k] - h[k - 2] >= mf * a[k]:
                            cands.append((h[k - 2], l[k]))   # bullish gap bot, top
                        if side > 0 and h[k] < l[k - 2] and l[k - 2] - h[k] >= mf * a[k]:
                            cands.append((h[k], l[k - 2]))   # bearish gap bot, top
                    w["ifvg"] = cands
                    watches.append(w)
                # arming uses this bar's close (after the sweep test, so a level becomes armed for the next bar)
                if (c[i] < L) if side < 0 else (c[i] > L):
                    armed[key] = True
        # --- entries
        for w in watches:
            if w["done"] or not w["confirmed"]:
                continue
            if p["reclaim"] and not w["reclaimed"]:
                continue
            side = w["side"]
            setup = None
            if p["mode"] in ("fvg", "both") and i - 2 >= w["bar"]:
                if side < 0 and h[i] < l[i - 2] and l[i - 2] - h[i] >= mf * a[i]:
                    setup = (h[i], l[i - 2], h[i])        # entry at near edge (bottom)
                elif side > 0 and l[i] > h[i - 2] and l[i] - h[i - 2] >= mf * a[i]:
                    setup = (l[i], h[i - 2], l[i])        # entry at near edge (top), inval bottom
            if setup is None and p["mode"] in ("ifvg", "both") and i > w["bar"]:
                for bot, top in w["ifvg"]:
                    if side < 0 and c[i] < bot:
                        setup = (bot, top, bot)
                        break
                    if side > 0 and c[i] > top:
                        setup = (top, bot, top)
                        break
            if setup is None:
                continue
            entry, inval, _ = setup
            if p["entry"] == "ce":
                entry = inst.round_price((entry + inval) / 2)
            if p["stop_mode"] == "fvg":
                stop = inval + buf if side < 0 else inval - buf
            else:
                stop = w["ext"] + buf if side < 0 else w["ext"] - buf
            w["done"] = True
            if tsign is not None and tsign[i] * side * p["trend"] <= 0:
                continue
            if chase and a[i] > 0 and side * (c[i] - entry) / a[i] > chase:
                continue
            if (entry - stop) * side <= 0:
                continue
            out.append(Setup(i, side, "limit", float(entry), float(stop), rr=3.0, expiry=int(p["expiry"]),
                             invalidate=float(inval), note=f"sweep {w['name']} {'H' if side < 0 else 'L'}"))
    return out


# ----------------------------------------------------------------- running

_C: dict = {}


def feat_of(sym, tf, shift=0, m1df=None):
    k = (sym, tf, shift, id(m1df) if m1df is not None else None)
    if k not in _C:
        src = DP.m1(sym) if m1df is None else m1df
        if shift:
            df = src.resample(tf, label="left", closed="left", offset=f"{shift}min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
        else:
            df = data.resample(src, tf)
        _C[k] = features.build(df, DP.inst_of(sym).tick)
    return _C[k]


def ckey(c):
    return "|".join(f"{k}={c[k]}" for k in sorted(c))


def run(c, slip_ticks=1, intrabar="path", m1replay=False, shift=0, max_trades=1):
    sym = c["sym"]
    feat = feat_of(sym, c["tf"], shift)
    p = {k: v for k, v in c.items() if k not in ("sym", "tf")}
    ss = generate(feat, DP.inst_of(sym), p)
    tr = DP.simulate(feat, ss, DP.inst_of(sym), slip_ticks=slip_ticks, intrabar=intrabar,
                     m1df=DP.m1(sym) if m1replay else None, max_trades=max_trades)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = ckey(c), sym, pd.Timestamp(t["entry_time"])
    return tr


def summarize(tr, nd):
    rep = DP.report_port(tr, nd)
    return rep


def line(rep):
    return DP.line(rep)


def truncation_check():
    for sym, tf, extra in (("MNQ", "15min", {}), ("MGC", "15min", dict(mode="both")),
                           ("MNQ", "5min", dict(htf=15, mode="both", reclaim=True))):
        inst = DP.inst_of(sym)
        df = data.resample(DP.m1(sym), tf)
        p = {**DEF, **extra}
        full = [(s.bar, s.side, s.entry, s.stop, s.invalidate) for s in generate(features.build(df, inst.tick), inst, p)]
        for k in (7000, 15000, 23000) if tf == "15min" else (30000, 50000, 70000):
            part = [(s.bar, s.side, s.entry, s.stop, s.invalidate)
                    for s in generate(features.build(df.iloc[:k], inst.tick), inst, p)]
            # a setup at bar k-1 may differ only if htf bucket completion is ambiguous at the end
            assert [x for x in full if x[0] < k - 1] == [x for x in part if x[0] < k - 1], (sym, tf, k)
    print("truncation check OK")


# ----------------------------------------------------------------- grid

def grid_configs():
    cfgs = []
    for sym in ("MNQ", "MGC"):
        for lev, win, mode, mf, rec in itertools.product(("pd", "sess", "all"), ("london", "ny", "day"),
                                                       ("fvg", "ifvg", "both"), (0.15, 0.3), (False, True)):
            cfgs.append(dict(sym=sym, tf="15min", levels=lev, win=win, mode=mode, mf=mf, reclaim=rec, look=6, htf=0))
        # 5m execution after a 15m sweep (confirmed 15m close back inside), look 12 x 5m = 1 hour
        for lev, win, mode, mf in itertools.product(("pd", "sess", "all"), ("london", "ny", "day"),
                                                  ("fvg", "ifvg", "both"), (0.15, 0.3)):
            cfgs.append(dict(sym=sym, tf="5min", levels=lev, win=win, mode=mode, mf=mf, reclaim=True, look=12, htf=15))
    return cfgs


def grid(log=print):
    nd = DP.trading_days()
    rows = []
    for c in grid_configs():
        tr = run(c)
        rep = summarize(tr, nd)
        rows.append(dict(cfg=c, key=ckey(c), is_=rep["is_"], oos=rep["oos"], full=rep["full"],
                         pos_months=rep["pos_months"]))
        log(f"{c['sym']} {c['tf']:5s} {c['levels']:4s} {c['win']:6s} {c['mode']:4s} mf{c['mf']} rec{int(c['reclaim'])} "
            f"| IS {DP.fmt(rep['is_'])} | OOS {DP.fmt(rep['oos'])}")
    SCR.mkdir(parents=True, exist_ok=True)
    (SCR / "grid.json").write_text(json.dumps(rows, default=str))
    return rows


def stage2_configs():
    """Stage 2 (declared after stage 1 showed ~47 % WR everywhere): frequency-capable bases
    (all-day sweep window 00:00-11:30, FVG or IFVG, mf 0.15) x entry x stop x 1h trend x chase."""
    cfgs = []
    for sym in ("MNQ", "MGC"):
        for (tf, rec, look, htf), lev, ent, stp, tr, ch in itertools.product(
                (("15min", False, 6, 0), ("5min", True, 12, 15)), ("all", "sess"), ("edge", "ce"),
                ("ext", "fvg"), (0, 1, -1), (0.0, 1.0)):
            cfgs.append(dict(sym=sym, tf=tf, levels=lev, win="day", mode="both", mf=0.15, reclaim=rec, look=look,
                             htf=htf, entry=ent, stop_mode=stp, trend=tr, chase=ch))
    return cfgs


def grid2(log=print):
    nd = DP.trading_days()
    rows = []
    for c in stage2_configs():
        rep = summarize(run(c), nd)
        rows.append(dict(cfg=c, key=ckey(c), is_=rep["is_"], oos=rep["oos"], full=rep["full"],
                         pos_months=rep["pos_months"]))
        log(f"{c['sym']} {c['tf']:5s} {c['levels']:4s} {c['entry']:4s} {c['stop_mode']:3s} tr{c['trend']:+d} ch{c['chase']} "
            f"| IS {DP.fmt(rep['is_'])} | OOS {DP.fmt(rep['oos'])}")
    SCR.mkdir(parents=True, exist_ok=True)
    (SCR / "grid2.json").write_text(json.dumps(rows, default=str))
    return rows


# ----------------------------------------------------------------- stage 3: daily portfolio

# Pre-existing, already verified legs (chosen in earlier research, IS-only there):
LETO = dict(kind="fvg", sym="MNQ", tf="15min", win="london", mf=0.3, chase=1.0)
COMEX = dict(kind="fvg", sym="MGC", tf="15min", win="comex", mf=0.3, chase=0.0)
# New levels legs: per market the stage-2 config with the highest IS WR among configs with >= 0.4 trades/day
LVL_MGC = dict(kind="lvl", sym="MGC", tf="15min", levels="sess", win="day", mode="both", mf=0.15, reclaim=False,
               look=6, htf=0, entry="ce", stop_mode="ext", trend=-1, chase=0.0)
LVL_MNQ = dict(kind="lvl", sym="MNQ", tf="15min", levels="all", win="day", mode="both", mf=0.15, reclaim=False,
               look=6, htf=0, entry="ce", stop_mode="ext", trend=-1, chase=0.0)
PORTS = {"P3 Leto+COMEX+lvlMGC": [LETO, COMEX, LVL_MGC],
         "P4 Leto+COMEX+lvlMGC+lvlMNQ": [LETO, COMEX, LVL_MGC, LVL_MNQ]}


def _bars(sym, tf, shift=0, src=None):
    src = DP.m1(sym) if src is None else src
    return src.resample(tf, label="left", closed="left", offset=f"{shift}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])


def leg_trades(spec, shift=0, df=None, slip_ticks=1, intrabar="path", m1replay=False):
    sym, tf = spec["sym"], spec["tf"]
    inst = DP.inst_of(sym)
    key = ("leg", sym, tf, shift, id(df) if df is not None else None)
    if key not in _C:
        _C[key] = features.build(df if df is not None else _bars(sym, tf, shift), inst.tick)
    feat = _C[key]
    if spec["kind"] == "fvg":
        from . import fvg_pro
        ss = fvg_pro.generate(feat, inst, dict(windows=DP.WINDOWS[spec["win"]], min_fvg_atr=spec["mf"],
                                               max_trades=1, entry="edge"))
        if spec["chase"]:
            ss = [x for x in ss if not (feat.atr[x.bar] > 0 and x.side * (feat.c[x.bar] - x.entry) / feat.atr[x.bar] > spec["chase"])]
    else:
        ss = generate(feat, inst, {k: v for k, v in spec.items() if k not in ("kind", "sym", "tf")})
    tr = DP.simulate(feat, ss, inst, slip_ticks=slip_ticks, intrabar=intrabar,
                     m1df=DP.m1(sym) if m1replay else None)
    k = ckey(spec)
    for t in tr:
        t["comp"], t["sym"], t["ts"] = k, sym, pd.Timestamp(t["entry_time"])
    return tr


def portfolio(legs, **kw):
    trs = [leg_trades(l, **kw) for l in legs]
    return DP.combine(trs, "per_market", [ckey(l) for l in legs])


def neighbours(spec):
    out = []
    for k, alts in (("entry", ("edge", "ce")), ("trend", (0, -1)), ("chase", (0.0, 1.0)), ("levels", ("sess", "all", "pd")),
                    ("look", (4, 6, 8)), ("mf", (0.1, 0.15, 0.3)), ("mode", ("fvg", "ifvg", "both")),
                    ("win", ("day", "lon+ny"))):
        for v in alts:
            if v != spec[k]:
                out.append((f"{k}={v}", dict(spec, **{k: v})))
    return out


def final(log=print):
    nd = DP.trading_days()
    res = {"trading_days": nd}
    for name, legs in PORTS.items():
        r = {}
        for tag, kw in (("base", {}), ("conservative", dict(intrabar="conservative")), ("slip2", dict(slip_ticks=2)),
                        ("cons+slip2", dict(intrabar="conservative", slip_ticks=2)), ("m1 replay", dict(m1replay=True))):
            rep = summarize(portfolio(legs, **kw), nd)
            r[tag] = rep
            log(f"{name:30s} {tag:12s} {line(rep)}")
        for sh in (1, 2, 3, 4):
            rep = summarize(portfolio(legs, shift=sh), nd)
            r[f"shift{sh}"] = rep
            log(f"{name:30s} shift {sh}min    {line(rep)}")
        res[name] = r
    log("legs alone (base):")
    for l in (LETO, COMEX, LVL_MGC, LVL_MNQ):
        rep = summarize(leg_trades(l), nd)
        res["leg " + ckey(l)] = rep
        log(f"  {l['sym']} {l['kind']} {l.get('win')} {l.get('levels', '')}: {line(rep)}")
    log("neighbours (one levels-leg parameter changed, P4):")
    nb = []
    for which in ("LVL_MGC", "LVL_MNQ"):
        base = globals()[which]
        for tag, alt in neighbours(base):
            legs = [alt if l is base else l for l in PORTS["P4 Leto+COMEX+lvlMGC+lvlMNQ"]]
            rep = summarize(portfolio(legs), nd)
            nb.append(dict(leg=which, change=tag, rep=rep))
            log(f"  {which} {tag:14s} {line(rep)}")
    res["neighbours"] = nb
    OUT.mkdir(parents=True, exist_ok=True)
    (SCR / "final.json").write_text(json.dumps(res, default=str))
    return res


def real_check(log=print):
    from . import research
    st = research.load_store(["MNQ", "MGC"], ["5m"])
    res = {}
    for name, legs in list(PORTS.items()) + [("lvlMGC alone", [LVL_MGC]), ("lvlMNQ alone", [LVL_MNQ])]:
        for src in ("real", "proxy"):
            trs = []
            for l in legs:
                real = st[(l["sym"], "5m")]
                lo, hi = real.index[0], real.index[-1]
                if src == "real":
                    df = data.resample(real, l["tf"])
                else:
                    d1 = DP.m1(l["sym"])
                    df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], l["tf"])
                trs.append(leg_trades(l, df=df))
            pt = DP.combine(trs, "per_market", [ckey(l) for l in legs])
            s_ = DP.stats(pt)
            res[f"{name} {src}"] = s_
            log(f"{name:30s} {src:5s} {lo:%Y-%m-%d}..{hi:%Y-%m-%d} {DP.fmt(s_)}")
    (SCR / "real.json").write_text(json.dumps(res, default=str))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "trunc":
        truncation_check()
    elif cmd == "grid":
        grid()
    elif cmd == "grid2":
        grid2()
    elif cmd == "final":
        final()
    elif cmd == "real":
        real_check()

"""Prop direction "daily": more trades / more winning days per week from the PROVEN
FVG Pro Leto sessions (MNQ London, MGC COMEX) through day-management rules only.

Entries: unchanged lab/fvg_pro.generate (BOS + FVG, limit at the gap edge), min FVG 0.3,
"don't chase" 1.0 ATR on MNQ (off on MGC), decided at bar close, order works from the next bar.
Exit: half at 1R -> stop to BE (next bar) -> runner 3R, time stop 8 bars, flat 15:55 / new Globex day.

What is varied (per market):
  window  London 02-05 (Leto) / 01-05 / 02-06 / 02-07 / 01-06 / 01-07 ;
          COMEX 08:20-10:30 (Leto) / 08:20-11:30 / 08:00-11:00 / 08:20-12:30 / 07:30-11:30
  day rule (gate evaluated when a setup is armed; all earlier trades of the day are CLOSED
            at that moment because a setup is only armed while flat -> causal):
     max1          1 trade/day (Leto)
     anyN          up to N trades, any outcome
     lossN         up to N trades, the next one only if the previous trade lost (<= $0)
                   == "stop for the day after the first winning trade"
     timeN         up to N, next one if the previous lost OR ended by the time stop  (d)
     greenN        up to N, next one only while the day's net is <= $0
     ...+ls<L>     plus daily loss stop: no new trade once the day's R sum <= -L
Portfolio: markets simulated independently (London and COMEX hardly overlap); optional
cross-market rule "skip MGC for the day once MNQ's CLOSED trades are already >= target".

SELECTION RULE (written before any OOS number was looked at; IS = entry < 2026-04-01):
  per market, eligible if  IS PF >= 1.30, IS WR >= 55 %, IS exp > 0, IS pos. months >= 5 of 7,
                           and IS PF >= 1.15 at every bar offset 0..4 min (IS only);
  pick = highest IS green-day rate (days with day net > 0 per week), tie -> higher IS PF.
  Accept the pick only if IS PF >= 1.15 AND OOS PF >= 1.15 at every offset 0..4 (protocol);
  if the pick fails, it is reported as a fail (no re-picking on OOS).
  Prop size: k units (unit = 2 MNQ + 2 MGC, the partial needs an even count);
  k = largest with IS max trailing end-of-day DD <= $1,500 (buffer to a $2,000 50K MLL).
  Cross-market rule: chosen on IS winning days/week (>= $150) at size k.

Run:  PYTHONPATH=. python -m lab.prop_daily trunc
      PYTHONPATH=. python -m lab.prop_daily grid      (IS-only print, writes json incl. OOS)
      PYTHONPATH=. python -m lab.prop_daily final
      PYTHONPATH=. python -m lab.prop_daily real
"""

from __future__ import annotations

import itertools
import json
import sys
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
EXIT = DP.EXIT
WIN_TARGET = 150.0

WINS = {
    "MNQ": {"L02-05": (("02:00", "05:00"),), "L01-05": (("01:00", "05:00"),), "L02-06": (("02:00", "06:00"),),
            "L02-07": (("02:00", "07:00"),), "L01-06": (("01:00", "06:00"),), "L01-07": (("01:00", "07:00"),)},
    "MGC": {"C0820-1030": (("08:20", "10:30"),), "C0820-1130": (("08:20", "11:30"),),
            "C0800-1100": (("08:00", "11:00"),), "C0820-1230": (("08:20", "12:30"),),
            "C0730-1130": (("07:30", "11:30"),)},
}
BASE_WIN = {"MNQ": "L02-05", "MGC": "C0820-1030"}
CHASE = {"MNQ": 1.0, "MGC": 0.0}
MF = 0.3
RULES = ["max1", "any2", "any3", "loss2", "loss3", "time2", "time3", "green2", "green3",
         "loss3+ls1.5", "time3+ls1.5", "any3+ls1.5", "loss4+ls2", "time4+ls2"]


def parse_rule(rule):
    ls = None
    if "+ls" in rule:
        rule, l_ = rule.split("+ls")
        ls = float(l_)
    if rule == "max1":
        return "any", 1, ls
    kind = rule.rstrip("0123456789")
    return kind, int(rule[len(kind):]), ls


def make_gate(rule):
    kind, n, ls = parse_rule(rule)

    def gate(day_tr):
        if len(day_tr) >= n:
            return False
        if ls is not None and day_tr and sum(t["r"] for t in day_tr) <= -ls:
            return False
        if not day_tr or kind == "any":
            return True
        last = day_tr[-1]
        if kind == "loss":
            return last["pnl"] <= 0
        if kind == "time":
            return last["pnl"] <= 0 or last["reason"] == "time"
        if kind == "green":
            return sum(t["pnl"] for t in day_tr) <= 0
        raise ValueError(kind)
    return gate, n


# ----------------------------------------------------------------- simulator (DP.simulate + day gate)

_path, _fill = DP._path, DP._fill


def simulate(feat, setups, inst, gate, max_n, mg=EXIT, flatten="15:55", slip_ticks=1, intrabar="path",
             min_risk_ticks=4, max_risk_atr=3.0, m1df=None):
    """lab.daily_portfolio.simulate, unchanged except that the per-day trade cap is replaced by
    gate(list of today's closed trades). With gate = 'count < 1' it equals DP.simulate(max_trades=1)."""
    tp, tp1 = float(mg["tp"]), mg.get("tp1")
    frac1, be_tp1, tstop = float(mg.get("frac1", .5)), bool(mg.get("be_tp1", True)), int(mg.get("tstop", 0))
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
            return [_path(o[i], h[i], l[i], c[i], side, intrabar)]
        a, b = m1i.searchsorted(idx[i]), m1i.searchsorted(idx[i] + step)
        if b <= a:
            return [_path(o[i], h[i], l[i], c[i], side, intrabar)]
        return [_path(m1o[j], m1h[j], m1l[j], m1c[j], side, intrabar) for j in range(a, b)]

    trades = []
    day_tr = {}
    pending, pend_age, pos = None, 0, None
    day_count = {}

    def finish(i, reason):
        nonlocal pos
        p = pos
        pnl = p["pts_qty"] * pv - costs
        t = dict(entry_time=idx[p["i0"]].isoformat(), exit_time=idx[i].isoformat(), side=p["side"],
                 entry=p["entry"], stop=p["stop0"], risk_pts=p["risk"],
                 r=pnl / (p["risk"] * pv * qty), pnl=pnl, reason=reason, bars=i - p["i0"],
                 day=int(feat.day[p["i0"]]), nth=p["nth"])
        trades.append(t)
        day_tr.setdefault(t["day"], []).append(t)
        pos = None

    def exit_qty(price, q):
        pos["pts_qty"] += (price - pos["entry"]) * pos["side"] * q
        pos["open_qty"] -= q

    def walk(i, pts, check_open):
        side, stop = pos["side"], pos["stop"]
        lv = []
        if pos["tp1_px"] is not None and not pos["tp1_done"]:
            lv.append(("tp1", pos["tp1_px"]))
        lv.append(("tp", pos["tp_px"]))
        if check_open:
            a = pts[0]
            if (a <= stop) if side > 0 else (a >= stop):
                exit_qty(a - side * slip, pos["open_qty"])
                finish(i, "be" if pos["be_done"] else "sl")
                return True
            for name, px in list(lv):
                if (a >= px) if side > 0 else (a <= px):
                    if name == "tp1":
                        exit_qty(a, q1)
                        pos["tp1_done"] = True
                        pos["be_pending"] |= be_tp1
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
                    finish(i, "be" if pos["be_done"] else ("sl_after_tp1" if pos["tp1_done"] else "sl"))
                    return True
                if name == "tp1" and not pos["tp1_done"]:
                    exit_qty(px, q1)
                    pos["tp1_done"] = True
                    pos["be_pending"] |= be_tp1
                    lv = [x for x in lv if x[0] != "tp1"]
                elif name == "tp":
                    exit_qty(px, pos["open_qty"])
                    finish(i, "tp")
                    return True
        return False

    def walk_bar(i):
        for pts in bar_paths(i, pos["side"]):
            if pos is None:
                return
            if walk(i, pts, True):
                return

    for i in range(n):
        new_day = i > 0 and feat.day[i] != feat.day[i - 1]
        if pos is not None:
            side = pos["side"]
            if pos["be_pending"] and not pos["be_done"]:
                pos["stop"], pos["be_done"] = pos["entry"], True
            if new_day or after_flat(i):
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "eod")
            elif pos["tstop_due"]:
                exit_qty(o[i] - side * slip, pos["open_qty"])
                finish(i, "time")
            else:
                walk_bar(i)
            if pos is not None and tstop > 0 and i - pos["i0"] >= tstop:
                pos["tstop_due"] = True

        if pending is not None and pos is None:
            s = pending
            pend_age += 1
            d = int(feat.day[i])
            if new_day or after_flat(i) or pend_age > s.expiry or not gate(day_tr.get(d, [])):
                pending = None
            else:
                subs = bar_paths(i, s.side) if m1df is not None else None
                rest_paths = None
                if subs is None:
                    res = _fill(s, o[i], h[i], l[i], c[i], intrabar)
                else:
                    res = None
                    for j, pts in enumerate(subs):
                        r_ = _fill(s, pts[0], max(pts), min(pts), pts[-1], intrabar)
                        if r_ is not None:
                            res = r_
                            rest_paths = subs[j + 1:]
                            break
                if res is None:
                    if s.invalidate is not None and ((c[i] < s.invalidate) if s.side > 0 else (c[i] > s.invalidate)):
                        pending = None
                elif res[0] == "cancel":
                    pending = None
                else:
                    _, fill, rest = res
                    pending = None
                    risk = (fill - s.stop) * s.side
                    day_count[d] = day_count.get(d, 0) + 1
                    pos = dict(side=s.side, entry=fill, stop=s.stop, stop0=s.stop, risk=risk, i0=i,
                               tp_px=fill + s.side * tp * risk, tp1_px=(fill + s.side * tp1 * risk) if tp1 else None,
                               tp1_done=False, be_pending=False, be_done=False, tstop_due=False,
                               open_qty=qty, pts_qty=0.0, nth=day_count[d])
                    walk(i, rest, False)
                    if pos is not None and rest_paths:
                        for pts in rest_paths:
                            if pos is None or walk(i, pts, True):
                                break
                    if pos is not None and tstop > 0 and i - pos["i0"] >= tstop:
                        pos["tstop_due"] = True

        if pos is None and i in by_bar:
            for s in by_bar[i]:
                if after_flat(i) or not gate(day_tr.get(int(feat.day[i]), [])):
                    continue
                risk = (s.entry - s.stop) * s.side
                if risk < min_risk_ticks * inst.tick or (feat.atr[i] > 0 and risk > max_risk_atr * feat.atr[i]):
                    continue
                pending, pend_age = s, 0
    if pos is not None:
        exit_qty(c[n - 1], pos["open_qty"])
        finish(n - 1, "eod")
    return trades


# ----------------------------------------------------------------- legs

_S: dict = {}


def setups(sym, win, shift=0, feat=None):
    k = (sym, win, shift)
    if feat is not None or k not in _S:
        f = feat if feat is not None else DL.feat_of(sym, "15min", shift)
        ss = fvg_pro.generate(f, DP.inst_of(sym), dict(windows=WINS[sym][win], min_fvg_atr=MF, max_trades=1, entry="edge"))
        ch = CHASE[sym]
        if ch:
            ss = [s for s in ss if not (f.atr[s.bar] > 0 and s.side * (f.c[s.bar] - s.entry) / f.atr[s.bar] > ch)]
        if feat is not None:
            return ss          # external bars: never cached
        _S[k] = ss
    return _S[k]


def leg(sym, win, rule, shift=0, slip_ticks=1, intrabar="path", m1replay=False, feat=None):
    f = feat if feat is not None else DL.feat_of(sym, "15min", shift)
    gate, n = make_gate(rule)
    tr = simulate(f, setups(sym, win, shift, feat), DP.inst_of(sym), gate, n, slip_ticks=slip_ticks,
                  intrabar=intrabar, m1df=DP.m1(sym) if m1replay else None)
    for t in tr:
        t["sym"], t["comp"], t["ts"] = sym, f"{sym}|{win}|{rule}", pd.Timestamp(t["entry_time"])
    return tr


# ----------------------------------------------------------------- stats / prop metrics

def day_key(ts):
    return (pd.Timestamp(ts) + pd.Timedelta(hours=6)).normalize()


_CAL: dict = {}


def calendar(split_=None):
    if split_ not in _CAL:
        _CAL[split_] = _calendar(split_)
    return _CAL[split_]


def _calendar(split_=None):
    """Globex trading days of the MNQ calendar (as dates of day_key)."""
    f = DP.feat_of("MNQ", "15min")
    first = pd.Series(f.df.index).groupby(f.day).first()
    days = pd.DatetimeIndex([day_key(t).tz_localize(None) for t in first])
    first_iso = np.array([t.isoformat() for t in first])
    # a Globex day is IS if its first bar is before the cut (as DP.trading_days)
    if split_ == "is":
        days = days[first_iso < CUT]
    elif split_ == "oos":
        days = days[first_iso >= CUT]
    return days


def prop(tr, days, k=1):
    """Prop metrics at k units. days = trading-day calendar of the period."""
    dn = pd.Series(0.0, index=days)
    for t in tr:
        d = day_key(t["ts"]).tz_localize(None)
        if d in dn.index:
            dn[d] += t["pnl"] * k
    weeks = dn.groupby(dn.index.to_period("W")).size()
    nweeks = len(weeks)
    eq = dn.cumsum().to_numpy()
    tdd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    wd = dn >= WIN_TARGET
    wpw = wd.groupby(dn.index.to_period("W")).sum()
    return dict(k=k, days=len(dn), weeks=nweeks, trades_per_week=len(tr) / nweeks if nweeks else 0,
                trades_per_day=len(tr) / len(dn) if len(dn) else 0,
                win_days_per_week=float(wd.sum() / nweeks), green_days_per_week=float((dn > 0).sum() / nweeks),
                red_days_per_week=float((dn < 0).sum() / nweeks),
                weeks_ge5_windays=int((wpw >= 5).sum()), weeks_ge3_windays=int((wpw >= 3).sum()),
                worst_day=float(dn.min()), best_day=float(dn.max()), max_trailing_eod_dd=tdd,
                net=float(dn.sum()))


def full_report(tr, k=1):
    a, b = DP.split(tr)
    mo = DP.months(tr)
    out = dict(full=DP.stats(tr), is_=DP.stats(a), oos=DP.stats(b), months={m: v * k for m, v in mo.items()},
               pos_months=sum(v > 0 for v in mo.values()), n_months=len(mo),
               prop_full=prop(tr, calendar(), k), prop_is=prop(a, calendar("is"), k), prop_oos=prop(b, calendar("oos"), k))
    for key in ("full", "is_", "oos"):
        if out[key]["trades"]:
            out[key]["net"] *= k
            out[key]["dd"] *= k
    return out


def fmt(s):
    return DP.fmt(s)


def pline(p):
    return (f"tr/wk {p['trades_per_week']:.2f} tr/d {p['trades_per_day']:.2f} win$150 d/wk {p['win_days_per_week']:.2f} "
            f"green d/wk {p['green_days_per_week']:.2f} worst ${p['worst_day']:,.0f} tDD ${p['max_trailing_eod_dd']:,.0f}")


def is_months_pos(tr):
    mo = DP.months([t for t in tr if t["entry_time"] < CUT])
    return int(sum(v > 0 for v in mo.values())), len(mo)


# ----------------------------------------------------------------- truncation check

def truncation_check():
    """(1) setups on df[:k] == setups on full df for bars < k-1;
    (2) gated simulation on df[:k]: every trade that exited before bar k-2 equals the full run."""
    for sym in ("MNQ", "MGC"):
        inst = DP.inst_of(sym)
        for shift in (0, 2):
            src = DP.m1(sym)
            df = DL._bars(sym, "15min", shift) if shift else data.resample(src, "15min")
            win = list(WINS[sym])[-1]
            ff = features.build(df, inst.tick)
            full_ss = setups(sym, win, shift, ff)
            full_tr = simulate(ff, full_ss, inst, *make_gate("time4+ls2"))
            for k in (6000, 15000, 22000):
                fp = features.build(df.iloc[:k], inst.tick)
                part_ss = setups(sym, win, shift, fp)
                A = [(s.bar, s.side, s.entry, s.stop) for s in full_ss if s.bar < k - 1]
                B = [(s.bar, s.side, s.entry, s.stop) for s in part_ss if s.bar < k - 1]
                assert A == B, (sym, shift, k, "setups")
                part_tr = simulate(fp, part_ss, inst, *make_gate("time4+ls2"))
                cut_t = df.index[k - 2].isoformat()
                fa = [(t["entry_time"], t["exit_time"], round(t["pnl"], 6)) for t in full_tr if t["exit_time"] < cut_t]
                pa = [(t["entry_time"], t["exit_time"], round(t["pnl"], 6)) for t in part_tr if t["exit_time"] < cut_t]
                assert fa == pa, (sym, shift, k, "trades")
    # gate max1 == DP.simulate(max_trades=1)
    for sym in ("MNQ", "MGC"):
        f = DP.feat_of(sym, "15min")
        ss = setups(sym, BASE_WIN[sym], 0, f)
        a = DP.simulate(f, ss, DP.inst_of(sym))
        b = simulate(f, ss, DP.inst_of(sym), *make_gate("max1"))
        assert [(t["entry_time"], round(t["pnl"], 6)) for t in a] == [(t["entry_time"], round(t["pnl"], 6)) for t in b], sym
    print("truncation check OK (setups + gated trades, shifts 0/2; max1 == DP.simulate)")
    return True


# ----------------------------------------------------------------- grid

def grid(log=print):
    rows = []
    for sym in ("MNQ", "MGC"):
        for win, rule in itertools.product(WINS[sym], RULES):
            row = dict(sym=sym, win=win, rule=rule, shifts={})
            for sh in range(5):
                tr = leg(sym, win, rule, shift=sh)
                a, b = DP.split(tr)
                row["shifts"][sh] = dict(is_=DP.stats(a), oos=DP.stats(b))
                if sh == 0:
                    row["is_"], row["oos"] = DP.stats(a), DP.stats(b)
                    row["is_pos_m"] = is_months_pos(tr)
                    row["prop_is"] = prop(a, calendar("is"))
                    row["prop_oos"] = prop(b, calendar("oos"))
            row["is_min_pf_shift"] = min(v["is_"]["pf"] or 0 for v in row["shifts"].values())
            row["oos_min_pf_shift"] = min(v["oos"]["pf"] or 0 for v in row["shifts"].values())
            rows.append(row)
            # IS-only print (OOS is written to json, not looked at during selection)
            log(f"{sym} {win:11s} {rule:12s} IS {fmt(row['is_'])} minPF@shift {row['is_min_pf_shift']:.2f} "
                f"+m {row['is_pos_m'][0]}/{row['is_pos_m'][1]} | {pline(row['prop_is'])}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "daily_grid.json").write_text(json.dumps(rows, indent=1, default=str))
    return rows


def eligible(r):
    s = r["is_"]
    return (s["trades"] >= 20 and s["pf"] >= 1.30 and s["wr"] >= 0.55 and s["exp"] > 0
            and r["is_pos_m"][0] >= 5 and r["is_min_pf_shift"] >= 1.15)


def select(rows):
    pick = {}
    for sym in ("MNQ", "MGC"):
        el = [r for r in rows if r["sym"] == sym and eligible(r)]
        el.sort(key=lambda r: (-r["prop_is"]["green_days_per_week"], -r["is_"]["pf"]))
        pick[sym] = el[0] if el else None
    return pick


def accepted(r):
    return all((v["is_"]["pf"] or 0) >= 1.15 and (v["oos"]["pf"] or 0) >= 1.15 for v in r["shifts"].values())


def combine(mnq, mgc, cross=None):
    """cross=None: independent; cross=X: drop the day's MGC trades whose entry comes after MNQ's
    CLOSED trades of that day already sum to >= X $ (unit size) -> causal."""
    if cross is None:
        return sorted(mnq + mgc, key=lambda t: t["ts"])
    by = {}
    for t in mnq:
        by.setdefault(day_key(t["ts"]), []).append(t)
    keep = []
    for t in mgc:
        done = sum(x["pnl"] for x in by.get(day_key(t["ts"]), []) if x["exit_time"] <= t["entry_time"])
        if done < cross:
            keep.append(t)
    return sorted(mnq + keep, key=lambda t: t["ts"])


def choose_k(tr):
    a, _ = DP.split(tr)
    k = 1
    for kk in range(1, 11):
        if prop(a, calendar("is"), kk)["max_trailing_eod_dd"] <= 1500:
            k = kk
    return k


def final(log=print):
    rows = json.loads((OUT / "daily_grid.json").read_text())
    for r in rows:
        r["shifts"] = {int(k): v for k, v in r["shifts"].items()}
        r["is_pos_m"] = tuple(int(x) for x in r["is_pos_m"])
    pick = select(rows)
    res = {"selection_rule": __doc__.split("SELECTION RULE")[1].split("Run:")[0].strip(), "picks": {}, "legs": {}}
    base = {sym: next(r for r in rows if r["sym"] == sym and r["win"] == BASE_WIN[sym] and r["rule"] == "max1")
            for sym in ("MNQ", "MGC")}
    log("IS picks:")
    for sym, r in pick.items():
        res["picks"][sym] = None if r is None else dict(win=r["win"], rule=r["rule"], accepted=accepted(r))
        if r is None:
            log(f"  {sym}: none eligible")
            continue
        log(f"  {sym} {r['win']} {r['rule']}: IS {fmt(r['is_'])} green/wk {r['prop_is']['green_days_per_week']:.2f}")
        log(f"     OOS {fmt(r['oos'])} | shifts IS PF " +
            " ".join(f"{v['is_']['pf']:.2f}" for v in r["shifts"].values()) + " | OOS PF " +
            " ".join(f"{(v['oos']['pf'] or 0):.2f}" for v in r["shifts"].values()) + f" | accepted {accepted(r)}")
    legs_used = {}
    for sym in ("MNQ", "MGC"):
        r = pick[sym] if pick[sym] is not None and accepted(pick[sym]) else base[sym]
        legs_used[sym] = r
    # per-leg robustness reports
    variants = {"base": {}, "slip2": dict(slip_ticks=2), "conservative": dict(intrabar="conservative"),
                "cons+slip2": dict(intrabar="conservative", slip_ticks=2), "m1 replay": dict(m1replay=True),
                "m1+slip2": dict(m1replay=True, slip_ticks=2)}
    all_rows = {}
    for tag, r in [("Leto base " + s, base[s]) for s in base] + [("pick " + s, legs_used[s]) for s in legs_used]:
        rr = {}
        for vt, kw in variants.items():
            tr = leg(r["sym"], r["win"], r["rule"], **kw)
            rr[vt] = full_report(tr)
        rr["shifts"] = r["shifts"]
        all_rows[f"{tag} {r['win']} {r['rule']}"] = rr
        f = rr["base"]
        log(f"{tag:14s} {r['win']} {r['rule']:12s} FULL {fmt(f['full'])} +m {f['pos_months']}/{f['n_months']} | "
            f"IS {fmt(f['is_'])} | OOS {fmt(f['oos'])}")
        for vt in variants:
            if vt != "base":
                log(f"      {vt:12s} IS PF {rr[vt]['is_']['pf']:.2f} OOS PF {rr[vt]['oos']['pf']:.2f} "
                    f"WR {rr[vt]['full']['wr']:.1%}")
    res["legs"] = all_rows
    # portfolio
    port = {}
    for name, use in (("Leto (base, 1/day each)", base), ("Daily-rule portfolio", legs_used)):
        trs = {s: leg(s, use[s]["win"], use[s]["rule"]) for s in use}
        k = choose_k(combine(trs["MNQ"], trs["MGC"]))
        cands = {}
        for cross in (None, 75.0, 150.0 / k if k else 150.0):
            pt = combine(trs["MNQ"], trs["MGC"], cross)
            a, _ = DP.split(pt)
            cands[cross] = prop(a, calendar("is"), k)["win_days_per_week"]
        best_cross = max(cands, key=lambda c: (cands[c], c is None))
        out = {}
        for vt, kw in variants.items():
            t2 = {s: leg(s, use[s]["win"], use[s]["rule"], **kw) for s in use}
            out[vt] = full_report(combine(t2["MNQ"], t2["MGC"], best_cross), k)
        for sh in range(1, 5):
            t2 = {s: leg(s, use[s]["win"], use[s]["rule"], shift=sh) for s in use}
            out[f"shift{sh}"] = full_report(combine(t2["MNQ"], t2["MGC"], best_cross), k)
        out["k"], out["cross"], out["cross_is_cands"] = k, best_cross, {str(c): v for c, v in cands.items()}
        port[name] = out
        f = out["base"]
        log(f"\n{name}: k={k} units ({2*k} MNQ + {2*k} MGC), cross={best_cross}")
        for per in ("full", "is_", "oos"):
            pp = f["prop_" + ("full" if per == "full" else per.rstrip("_"))]
            log(f"  {per:4s} {fmt(f[per])} | {pline(pp)}")
        log(f"  +months {f['pos_months']}/{f['n_months']}")
        for vt in list(variants)[1:] + [f"shift{s}" for s in range(1, 5)]:
            log(f"  {vt:12s} IS PF {out[vt]['is_']['pf']:.2f} OOS PF {out[vt]['oos']['pf']:.2f} "
                f"OOS win$150/wk {out[vt]['prop_oos']['win_days_per_week']:.2f}")
    res["portfolios"] = port
    (OUT / "daily.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def real_check(log=print):
    from . import research
    st = research.load_store(["MNQ", "MGC"], ["5m"])
    res = json.loads((OUT / "daily.json").read_text())
    out = {}
    for name, (use_win, use_rule) in {
            "Leto base": ({"MNQ": BASE_WIN["MNQ"], "MGC": BASE_WIN["MGC"]}, {"MNQ": "max1", "MGC": "max1"}),
            "pick": ({s: (res["picks"][s] or {}).get("win", BASE_WIN[s]) if (res["picks"][s] or {}).get("accepted") else BASE_WIN[s] for s in ("MNQ", "MGC")},
                     {s: (res["picks"][s] or {}).get("rule", "max1") if (res["picks"][s] or {}).get("accepted") else "max1" for s in ("MNQ", "MGC")}),
    }.items():
        for src in ("real", "proxy"):
            trs = {}
            for s in ("MNQ", "MGC"):
                real = st.get((s, "5m"))
                lo, hi = real.index[0], real.index[-1]
                if src == "real":
                    df = data.resample(real, "15min")
                else:
                    d1 = DP.m1(s)
                    df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], "15min")
                f = features.build(df, DP.inst_of(s).tick)
                trs[s] = leg(s, use_win[s], use_rule[s], feat=f)
                _S.clear()
            pt = combine(trs["MNQ"], trs["MGC"])
            stt = DP.stats(pt)
            out[f"{name} {src}"] = dict(stats=stt, start=str(lo), end=str(hi), win=use_win, rule=use_rule)
            log(f"{name:10s} {src:5s} {lo:%Y-%m-%d}..{hi:%Y-%m-%d} {fmt(stt)}")
    (OUT / "daily_real.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def diag(log=print):
    """Post-hoc diagnostics (NOT used for selection): decomposition window vs day rule (IS / OOS),
    which trade of the day earns what, per-leg prop metrics, sizes k = 1..3."""
    rows = json.loads((OUT / "daily_grid.json").read_text())
    res = {"decomp": [], "nth": {}, "legs_prop": {}, "sizes": {}}
    log("decomposition (IS | OOS PF, min PF over shifts IS/OOS):")
    for sym, wins, rules in (("MNQ", ("L02-05", "L02-07", "L01-07"), ("max1", "loss2", "time2", "any3", "green3")),
                             ("MGC", ("C0820-1030", "C0800-1100", "C0730-1130"), ("max1", "loss2", "time2", "any2", "any3"))):
        for w in wins:
            for ru in rules:
                r = next(x for x in rows if x["sym"] == sym and x["win"] == w and x["rule"] == ru)
                d = dict(sym=sym, win=w, rule=ru, is_=r["is_"], oos=r["oos"], is_min=r["is_min_pf_shift"],
                         oos_min=r["oos_min_pf_shift"], green_is=r["prop_is"]["green_days_per_week"],
                         green_oos=r["prop_oos"]["green_days_per_week"])
                res["decomp"].append(d)
                log(f"  {sym} {w:11s} {ru:6s} IS {fmt(r['is_'])} | OOS {fmt(r['oos'])} | min PF IS {d['is_min']:.2f} OOS {d['oos_min']:.2f}")
    picks = {"MNQ": ("L01-07", "time2"), "MGC": ("C0820-1030", "max1")}
    trs = {}
    for sym, (w, ru) in picks.items():
        tr = leg(sym, w, ru)
        trs[sym] = tr
        for nth in (1, 2, 3):
            sub = [t for t in tr if t["nth"] == nth]
            a, b = DP.split(sub)
            res["nth"][f"{sym} #{nth}"] = dict(full=DP.stats(sub), is_=DP.stats(a), oos=DP.stats(b))
            if sub:
                log(f"  {sym} trade #{nth} of day: FULL {fmt(DP.stats(sub))} | IS {fmt(DP.stats(a))} | OOS {fmt(DP.stats(b))}")
        early = [t for t in tr if pd.Timestamp(t["entry_time"]).hour in (1,) or pd.Timestamp(t["entry_time"]).hour >= 5]
        if sym == "MNQ":
            a, b = DP.split(early)
            log(f"  MNQ entries outside 02-05: FULL {fmt(DP.stats(early))} | IS {fmt(DP.stats(a))} | OOS {fmt(DP.stats(b))}")
            res["nth"]["MNQ outside 02-05"] = dict(full=DP.stats(early), is_=DP.stats(a), oos=DP.stats(b))
        for k in (1, 2):
            rep = full_report(tr, k)
            res["legs_prop"][f"{sym} k{k}"] = {x: rep[x] for x in ("prop_full", "prop_is", "prop_oos")}
            log(f"  {sym} k={k} full {pline(rep['prop_full'])}")
    for base_name, use in (("Leto", {"MNQ": ("L02-05", "max1"), "MGC": ("C0820-1030", "max1")}), ("pick", picks)):
        t2 = {s: leg(s, *use[s]) for s in use}
        for k in (1, 2, 3):
            pt = combine(t2["MNQ"], t2["MGC"], 75.0 / 1 if base_name == "pick" else 150.0)
            rep = full_report(pt, k)
            res["sizes"][f"{base_name} k{k}"] = {x: rep[x] for x in ("prop_full", "prop_is", "prop_oos")}
            log(f"  {base_name} k={k} ({2*k}+{2*k}) IS {pline(rep['prop_is'])}")
            log(f"  {base_name} k={k} ({2*k}+{2*k}) OOS {pline(rep['prop_oos'])} wk>=3 win-days {rep['prop_full']['weeks_ge3_windays']} wk>=5 {rep['prop_full']['weeks_ge5_windays']} of {rep['prop_full']['weeks']}")
    (OUT / "daily_diag.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    {"trunc": truncation_check, "grid": grid, "final": final, "real": real_check, "diag": diag}[cmd]()

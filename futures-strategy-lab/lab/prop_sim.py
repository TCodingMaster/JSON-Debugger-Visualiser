"""Prop direction "prop": prop-firm simulation (Topstep-style 50K and an FTMO-style rule proxy) on the
daily P&L of
  (1) "leto": baseline FVG Pro Leto = MNQ 15m London 02:00-05:00 (mf 0.3, chase 1.0, max 1/day)
                                     + MGC 15m COMEX 08:20-10:30 (mf 0.3, no chase, max 1/day), independent;
  (2) "ext":  the best VERIFIED extended portfolio = prop_daily's IS pick: MNQ 15m 01:00-07:00 "time2"
              (2nd trade only after a loss / time-stop exit) + the same MGC COMEX leg, cross-market rule
              "skip MGC for the day once MNQ's CLOSED trades are >= $75 per 2 MNQ" (scaled with size).
Why only these: of the three verified directions only "legs" has bar_shift_ok=True, and the only leg that
passes its gate is Leto MNQ London.  "daily" failed bar_shift_ok ONLY because of the baseline MGC Leto leg;
its new MNQ 01-07 time2 leg passes IS/OOS PF >= 1.15 at every offset 0..4 -> it is the only new leg allowed.
"concepts" legs all fail the gate -> excluded.  No verified MCL leg exists -> MCL size is 0.

Entries / exits are unchanged (lab.fvg_pro.generate via lab.prop_daily.setups, lab.prop_daily.simulate):
decided at bar close, order works from the next bar; half at 1R -> BE -> runner 3R, time stop 8 bars,
flat 15:55.  With ONE contract the half-out is impossible; 1-contract legs exit ALL at 1R (time stop 8).
3 contracts: 2 out at 1R, 1 runner.  Costs: data.py commissions, 1 tick slippage on stop/BE/time/EOD exits.

Daily P&L: Globex day = day_key(entry) (18:00 NY roll); IS = trade-day date < 2026-04-01, OOS >= 2026-04-01.
Intraday path inside a day = cumulative CLOSED trade P&L in exit order ("closed" basis; used for the
pre-registered selection).  "MAE" basis (added after the first OOS run, see results/prop/prop_sim.md):
while a trade is open its unrealised low = max adverse excursion on the 1m proxy from the entry bar's open
to the exit bar's close, full size (ignores the half taken at 1R -> conservative), capped at stop+slip,
plus round-turn costs.  Topstep / FTMO limits are breached intraday on unrealised P&L, so MAE is the more
realistic basis.

RULES (50K account, start balance 50,000)
 Topstep-style:
   Evaluation: profit target $3,000; trailing max loss $2,000 from the highest END-OF-DAY balance, locked at
   the start balance (MLL = min(peak EOD - 2,000, 50,000)); breach = intraday low <= MLL -> account lost;
   daily loss limit $1,000 = trading stops for the day and the day is liquidated at -$1,000 (not a fail);
   consistency: pass only when profit >= $3,000 AND best day <= 50 % of total profit; >= 2 trading days.
   Funded (XFA-like): new 50K, same MLL / DLL; payout when >= 5 winning days (day net >= +$150) since the
   last payout and balance > start: withdraw min(50 % of profit, $5,000), trader keeps 90 %; after the first
   payout the MLL is fixed at the start balance (Topstep sets MLL to $0 balance after a payout).
 FTMO-style (rule proxy only: FTMO sells CFDs, not CME futures; costs/contract specs would differ):
   Phase 1 target 10 % ($5,000), Phase 2 target 5 % ($2,500), each >= 4 trading days; max loss 10 % static
   (equity floor $45,000); max daily loss 5 % ($2,500) from the day's start balance = account lost.
   Funded: same limits, payout of 80 % of the profit every 10 trading days (~14 calendar days), balance reset.
Horizon 3 months = 63 trading days, ONE attempt per path (no resets; a bust ends the path).

Bootstrap: weekly blocks (calendar weeks Mon-Sun of the period's daily series, 0-trade days included) drawn
with replacement until 63 trading days; 5,000 paths; fixed seed.

SELECTION RULE (written before any OOS number was looked at; `select` prints/uses IS only):
  For each portfolio x firm style, contracts per leg (MNQ 1..4) x (MGC 1..3), MCL 0 (no verified leg):
  feasible  = IS-bootstrap P(any max-loss breach within 3 months, eval or funded, closed basis) < 10 %;
  pick      = feasible size with the highest IS expected trader payout per month; tie -> fewer contracts.
  Recommended portfolio = the Topstep-style pick with the higher IS expected payout/month among
  {leto, ext}; tie (within 5 %) -> leto (simpler, stronger IS PF).
  OOS (bootstrap of the OOS weeks, rolling-start historical replays), cost/intrabar/1m/bar-shift variants
  and an "expectancy halved" stress are then reported for the IS-chosen sizes, never used to re-pick.

Run:  PYTHONPATH=. python -m lab.prop_sim trunc     (look-ahead / reproduction check)
      PYTHONPATH=. python -m lab.prop_sim select    (IS only -> results/prop/prop_sim_select.json)
      PYTHONPATH=. python -m lab.prop_sim final     (OOS + robustness -> results/prop/prop_sim.json)
      PYTHONPATH=. python -m lab.prop_sim real      (real CME 5m (Yahoo) sanity -> prop_sim_real.json)
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, features
from . import daily_portfolio as DP
from . import daily_levels as DL
from . import prop_daily as PD

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "prop"
CUT = DP.CUT
CUT_DAY = pd.Timestamp(CUT)
WIN_TARGET = 150.0
N_PATHS = 5000
HORIZON = 63
SEED = 20261017

PORTS = {
    "leto": dict(legs={"MNQ": ("L02-05", "max1"), "MGC": ("C0820-1030", "max1")}, cross=None),
    "ext": dict(legs={"MNQ": ("L01-07", "time2"), "MGC": ("C0820-1030", "max1")}, cross=75.0),
}
SIZES = list(itertools.product((1, 2, 3, 4), (1, 2, 3)))       # (MNQ, MGC); MCL = 0
EXIT1 = dict(tp=1.0, tp1=None, frac1=0.5, be_tp1=True, tstop=8)  # 1 contract: all out at 1R

TOPSTEP = dict(kind="topstep", start=50_000.0, target=3_000.0, mll=2_000.0, dll=1_000.0, consistency=0.5,
               min_days=2, win_day=150.0, need_wd=5, payout_frac=0.5, payout_cap=5_000.0, split=0.9)
FTMO = dict(kind="ftmo", start=50_000.0, t1=5_000.0, t2=2_500.0, maxloss=5_000.0, dll=2_500.0, min_days=4,
            payout_every=10, split=0.8)
FIRMS = {"topstep": TOPSTEP, "ftmo": FTMO}


# ----------------------------------------------------------------- trades at a given size

_LEG: dict = {}


def leg_trades(sym, win, rule, q, shift=0, slip_ticks=1, intrabar="path", m1replay=False, feat=None):
    key = (sym, win, rule, q, shift, slip_ticks, intrabar, m1replay)
    if feat is None and key in _LEG:
        return _LEG[key]
    f = feat if feat is not None else DL.feat_of(sym, "15min", shift)
    ss = PD.setups(sym, win, shift, feat)
    inst = dataclasses.replace(DP.inst_of(sym), contracts=q)
    gate, n = PD.make_gate(rule)
    tr = PD.simulate(f, ss, inst, gate, n, mg=DP.EXIT if q >= 2 else EXIT1, slip_ticks=slip_ticks,
                     intrabar=intrabar, m1df=DP.m1(sym) if m1replay else None)
    for t in tr:
        t["sym"], t["ts"] = sym, pd.Timestamp(t["entry_time"])
        t["risk_usd"] = (t["risk_pts"] + slip_ticks * inst.tick) * inst.point_value * q + 2 * inst.commission * q
        t["dday"] = PD.day_key(t["ts"]).tz_localize(None)
        t["mae_usd"] = mae_usd(sym, t, inst, slip_ticks, f.interval_min) if feat is None else max(-t["pnl"], 0.0)
    if feat is None:
        _LEG[key] = tr
    return tr


_M1A: dict = {}


def mae_usd(sym, t, inst, slip_ticks, tfm):
    if sym not in _M1A:
        d = DP.m1(sym)
        _M1A[sym] = (d.index, d["low"].to_numpy(), d["high"].to_numpy())
    idx, lo, hi = _M1A[sym]
    a = idx.searchsorted(pd.Timestamp(t["entry_time"]))
    b = idx.searchsorted(pd.Timestamp(t["exit_time"]) + pd.Timedelta(minutes=tfm))
    if b <= a:
        adv = 0.0
    elif t["side"] > 0:
        adv = t["entry"] - lo[a:b].min()
    else:
        adv = hi[a:b].max() - t["entry"]
    adv = min(max(adv, 0.0), t["risk_pts"] + slip_ticks * inst.tick)
    q = inst.contracts
    return max(adv * inst.point_value * q + 2 * inst.commission * q, -t["pnl"])


def port_trades(port, qn, qg, feats=None, **kw):
    P = PORTS[port]
    (wn, rn), (wg, rg) = P["legs"]["MNQ"], P["legs"]["MGC"]
    mnq = leg_trades("MNQ", wn, rn, qn, feat=(feats or {}).get("MNQ"), **kw)
    mgc = leg_trades("MGC", wg, rg, qg, feat=(feats or {}).get("MGC"), **kw)
    cross = None if P["cross"] is None else P["cross"] * qn / 2.0
    return PD.combine(mnq, mgc, cross)


# ----------------------------------------------------------------- daily series

def calendar_days():
    days = PD.calendar()          # all Globex days of the MNQ calendar (naive dates of day_key)
    return pd.DatetimeIndex(days)


def day_table(tr, days, dll_ts=TOPSTEP["dll"]):
    """Per day: net / intraday low for the Topstep DLL (liquidated at -dll), and raw (no DLL),
    closed basis and stress basis."""
    pos = {d: i for i, d in enumerate(days)}
    per = [[] for _ in days]
    for t in sorted(tr, key=lambda t: t["exit_time"]):
        if t["dday"] in pos:
            per[pos[t["dday"]]].append(t)
    n = len(days)
    out = {k: np.zeros(n) for k in ("net_raw", "lo_raw", "net_dll", "lo_dll",
                                    "net_raw_s", "lo_raw_s", "net_dll_s", "lo_dll_s")}
    ntr = np.zeros(n, int)
    for i, ts in enumerate(per):
        ntr[i] = len(ts)
        for stress in (False, True):
            sfx = "_s" if stress else ""
            cum, lo = 0.0, 0.0
            cd, lod, stopped = 0.0, 0.0, False
            for t in ts:
                low_t = cum - t["mae_usd"] if stress else cum + min(t["pnl"], 0.0)
                lo = min(lo, low_t, cum + t["pnl"])
                if not stopped:
                    low_d = cd - t["mae_usd"] if stress else cd + min(t["pnl"], 0.0)
                    if low_d <= -dll_ts or cd + t["pnl"] <= -dll_ts:
                        cd, lod, stopped = -dll_ts, -dll_ts, True
                    else:
                        cd += t["pnl"]
                        lod = min(lod, low_d, cd)
                cum += t["pnl"]
            out["net_raw" + sfx][i], out["lo_raw" + sfx][i] = cum, lo
            out["net_dll" + sfx][i], out["lo_dll" + sfx][i] = cd, lod
    out["ntr"] = ntr
    out["days"] = days
    return out


def period_idx(days, per):
    if per == "is":
        return np.where(days < CUT_DAY)[0]
    if per == "oos":
        return np.where(days >= CUT_DAY)[0]
    return np.arange(len(days))


def weeks_of(days, idx):
    wk = pd.DatetimeIndex(days[idx]).to_period("W")
    blocks = []
    for w in pd.unique(wk):
        blocks.append(idx[np.asarray(wk == w)])
    return blocks


def boot_paths(blocks, n_paths=N_PATHS, horizon=HORIZON, seed=SEED):
    rng = np.random.default_rng(seed)
    out = np.empty((n_paths, horizon), int)
    nb = len(blocks)
    for p in range(n_paths):
        seq, L = [], 0
        while L < horizon:
            b = blocks[rng.integers(nb)]
            seq.append(b)
            L += len(b)
        out[p] = np.concatenate(seq)[:horizon]
    return out


def replay_paths(blocks, horizon=HORIZON):
    """Rolling-start historical replays: start at each week, run the real sequence for `horizon` days
    (only starts with a full horizon inside the period)."""
    allidx = np.concatenate(blocks)
    starts, k = [], 0
    for b in blocks:
        if len(allidx) - k >= horizon:
            starts.append(allidx[k:k + horizon])
        k += len(b)
    return np.array(starts) if starts else np.empty((0, horizon), int)


# ----------------------------------------------------------------- prop rule engines (vectorised)

def sim_topstep(tab, paths, R=TOPSTEP, stress=False, start_funded=False):
    sfx = "_s" if stress else ""
    NET, LO = tab["net_dll" + sfx], tab["lo_dll" + sfx]
    N, D = paths.shape
    S = R["start"]
    phase = np.full(N, 1 if start_funded else 0)   # 0 eval, 1 funded, 2 lost
    bal = np.full(N, S)
    peak = bal.copy()
    mll = np.full(N, S - R["mll"])
    locked = np.zeros(N, bool)
    edays = np.zeros(N, int)
    best = np.full(N, -np.inf)
    pass_day = np.full(N, 0 if start_funded else -1)
    bust_ph = np.full(N, -1)
    wd = np.zeros(N, int)
    fdays = np.zeros(N, int)
    firstq = np.full(N, -1)
    paid = np.zeros(N)
    npay = np.zeros(N, int)
    for t in range(D):
        d, lo = NET[paths[:, t]], LO[paths[:, t]]
        act = phase < 2
        br = act & (bal + lo <= mll + 1e-9)
        bust_ph[br] = phase[br]
        phase[br] = 2
        ok = act & ~br
        bal = np.where(ok, bal + d, bal)
        peak = np.where(ok, np.maximum(peak, bal), peak)
        mll = np.where(ok & ~locked, np.minimum(np.maximum(mll, peak - R["mll"]), S), mll)
        ev = ok & (phase == 0)
        edays[ev] += 1
        best[ev] = np.maximum(best[ev], d[ev])
        prof = bal - S
        ps = ev & (prof >= R["target"]) & (best <= R["consistency"] * prof) & (edays >= R["min_days"])
        pass_day[ps] = t
        phase[ps] = 1
        bal[ps], peak[ps], mll[ps], locked[ps] = S, S, S - R["mll"], False
        fu = ok & (phase == 1) & ~ps
        fdays[fu] += 1
        wd[fu] += (d[fu] >= R["win_day"])
        el = fu & (wd >= R["need_wd"]) & (bal > S)
        firstq[el & (firstq < 0)] = fdays[el & (firstq < 0)]
        amt = np.minimum(R["payout_frac"] * (bal - S), R["payout_cap"])
        paid[el] += R["split"] * amt[el]
        npay[el] += 1
        bal[el] -= amt[el]
        wd[el] = 0
        locked[el] = True
        mll[el] = S
    return summarize(paths, pass_day, bust_ph, paid, npay, firstq, phase, D)


def sim_ftmo(tab, paths, R=FTMO, stress=False, start_funded=False):
    sfx = "_s" if stress else ""
    NET, LO = tab["net_raw" + sfx], tab["lo_raw" + sfx]
    N, D = paths.shape
    S = R["start"]
    phase = np.full(N, 2 if start_funded else 0)   # 0 phase 1, 1 phase 2, 2 funded, 3 lost
    bal = np.full(N, S)
    pdays = np.zeros(N, int)
    pass_day = np.full(N, 0 if start_funded else -1)
    bust_ph = np.full(N, -1)
    fdays = np.zeros(N, int)
    firstq = np.full(N, -1)
    paid = np.zeros(N)
    npay = np.zeros(N, int)
    for t in range(D):
        d, lo = NET[paths[:, t]], LO[paths[:, t]]
        act = phase < 3
        br = act & ((bal + lo <= S - R["maxloss"] + 1e-9) | (lo <= -R["dll"] + 1e-9))
        bust_ph[br] = np.minimum(phase[br], 2)
        phase[br] = 3
        ok = act & ~br
        bal = np.where(ok, bal + d, bal)
        ev = ok & (phase < 2)
        pdays[ev] += 1
        tgt = np.where(phase == 0, R["t1"], R["t2"])
        ps = ev & (bal - S >= tgt) & (pdays >= R["min_days"])
        p2 = ps & (phase == 1)
        pass_day[p2] = t
        phase[ps] += 1
        bal[ps], pdays[ps] = S, 0
        fu = ok & (phase == 2) & ~p2
        fdays[fu] += 1
        el = fu & (fdays % R["payout_every"] == 0) & (bal > S)
        firstq[el & (firstq < 0)] = fdays[el & (firstq < 0)]
        paid[el] += R["split"] * (bal[el] - S)
        npay[el] += 1
        bal[el] = S
    lost = phase == 3
    return summarize(paths, pass_day, bust_ph, paid, npay, firstq, np.where(lost, 2, 0), D)


def summarize(paths, pass_day, bust_ph, paid, npay, firstq, phase, D):
    months = D / 21.0
    passed = pass_day >= 0
    lost = phase == 2
    return dict(paths=int(len(paths)), p_pass=float(passed.mean()) if len(paths) else None,
                med_days_to_pass=float(np.median(pass_day[passed] + 1)) if passed.any() else None,
                p_bust=float(lost.mean()) if len(paths) else None,
                p_bust_eval=None,
                p_bust_funded=float((lost & passed).mean()) if len(paths) else None,
                p_any_payout=float((npay > 0).mean()) if len(paths) else None,
                payout_per_month=float(paid.mean() / months) if len(paths) else None,
                payout_per_month_p10_p50_p90=[float(x / months) for x in np.percentile(paid, [10, 50, 90])] if len(paths) else None,
                payouts_count_per_month=float(npay.mean() / months) if len(paths) else None,
                med_funded_days_to_first_payout=float(np.median(firstq[firstq > 0])) if (firstq > 0).any() else None)


def run_firm(firm, tab, paths, stress=False, start_funded=False):
    return (sim_topstep if firm == "topstep" else sim_ftmo)(tab, paths, stress=stress, start_funded=start_funded)


def bust_split(firm, tab, paths, stress=False, start_funded=False):
    """Eval vs funded busts (lost paths split by whether the evaluation had been passed)."""
    r = run_firm(firm, tab, paths, stress, start_funded)
    r["p_bust_eval"] = r["p_bust"] - r["p_bust_funded"]
    return r


# ----------------------------------------------------------------- per-series stats

def series_stats(tr, tab, per):
    idx = period_idx(tab["days"], per)
    days = tab["days"][idx]
    net = tab["net_raw"][idx]
    if per == "is":
        tr = [t for t in tr if t["dday"] < CUT_DAY]
    elif per == "oos":
        tr = [t for t in tr if t["dday"] >= CUT_DAY]
    wk = pd.DatetimeIndex(days).to_period("W")
    nweeks = len(pd.unique(wk))
    eq = np.cumsum(net)
    tdd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    s = DP.stats(tr)
    mo = DP.months(tr)
    wdw = pd.Series(net >= WIN_TARGET, index=wk).groupby(level=0).sum()
    return dict(**s, trades_per_week=len(tr) / nweeks, trades_per_day=len(tr) / len(days), days=len(days),
                weeks=nweeks, win_days_per_week=float((net >= WIN_TARGET).sum() / nweeks),
                green_days_per_week=float((net > 0).sum() / nweeks), worst_day=float(net.min()),
                best_day=float(net.max()), max_trailing_eod_dd=tdd, pos_months=int(sum(v > 0 for v in mo.values())),
                n_months=len(mo), weeks_ge5_windays=int((wdw >= 5).sum()), weeks_ge3_windays=int((wdw >= 3).sum()),
                dll_days=int((tab["net_dll"][idx] <= -TOPSTEP["dll"] + 1e-9).sum()))


def eval_size(port, qn, qg, per, firms=("topstep", "ftmo"), stress=False, tr=None, tab=None, seed=SEED,
              replay=True):
    if tr is None:
        tr = port_trades(port, qn, qg)
    if tab is None:
        tab = day_table(tr, calendar_days())
    blocks = weeks_of(tab["days"], period_idx(tab["days"], per))
    paths = boot_paths(blocks, seed=seed)
    out = dict(port=port, mnq=qn, mgc=qg, mcl=0, per=per, series=series_stats(tr, tab, per))
    for f in firms:
        out[f] = bust_split(f, tab, paths, stress)
        if replay:
            rp = replay_paths(blocks)
            out[f + "_replay"] = bust_split(f, tab, rp, stress) if len(rp) else None
    return out


def short(r, firm):
    x = r[firm]
    return (f"pass {x['p_pass']:.1%} med {x['med_days_to_pass'] or float('nan'):.0f}d | bust {x['p_bust']:.1%} "
            f"(eval {x['p_bust_eval']:.1%}, funded {x['p_bust_funded']:.1%}) | payout ${x['payout_per_month']:,.0f}/mo "
            f"P(>=1 payout) {x['p_any_payout']:.1%}")


# ----------------------------------------------------------------- selection (IS only)

def pick(rows, firm):
    feas = [r for r in rows if r[firm]["p_bust"] < 0.10]
    if not feas:
        return None
    feas.sort(key=lambda r: (-r[firm]["payout_per_month"], r["mnq"] + r["mgc"]))
    return feas[0]


def select(log=print):
    t0 = time.time()
    res = {"rule": __doc__.split("SELECTION RULE")[1].split("Run:")[0].strip(), "grid": [], "picks": {}}
    for port in PORTS:
        for qn, qg in SIZES:
            r = eval_size(port, qn, qg, "is", replay=False)
            res["grid"].append(r)
            s = r["series"]
            log(f"{port:4s} MNQ{qn} MGC{qg} IS {s['trades']} tr {s['trades_per_week']:.2f}/wk WR {s['wr']:.1%} "
                f"PF {s['pf']:.2f} ${s['net']:,.0f} windays/wk {s['win_days_per_week']:.2f} worst ${s['worst_day']:,.0f} "
                f"tDD ${s['max_trailing_eod_dd']:,.0f}")
            for f in FIRMS:
                log(f"      {f:7s} {short(r, f)}")
    for port in PORTS:
        for f in FIRMS:
            p = pick([r for r in res["grid"] if r["port"] == port], f)
            res["picks"][f"{port}|{f}"] = None if p is None else dict(mnq=p["mnq"], mgc=p["mgc"], mcl=0,
                                                                       is_payout=p[f]["payout_per_month"],
                                                                       is_bust=p[f]["p_bust"])
            log(f"PICK {port} {f}: {res['picks'][f'{port}|{f}']}")
    # POST-HOC AMENDMENT (added after the first OOS run had been seen): same IS rule on the MAE basis
    res["grid_mae"], res["picks_mae"] = [], {}
    for port in PORTS:
        for qn, qg in SIZES:
            r = eval_size(port, qn, qg, "is", replay=False, stress=True)
            res["grid_mae"].append(r)
            log(f"MAE {port:4s} MNQ{qn} MGC{qg} | " + " | ".join(f"{f} {short(r, f)}" for f in FIRMS))
        for f in FIRMS:
            p = pick([r for r in res["grid_mae"] if r["port"] == port], f)
            res["picks_mae"][f"{port}|{f}"] = None if p is None else dict(mnq=p["mnq"], mgc=p["mgc"], mcl=0,
                                                                           is_payout=p[f]["payout_per_month"],
                                                                           is_bust=p[f]["p_bust"])
            log(f"PICK (MAE basis) {port} {f}: {res['picks_mae'][f'{port}|{f}']}")
    a, b = res["picks"]["leto|topstep"], res["picks"]["ext|topstep"]
    if a is None and b is None:
        rec = None
    elif b is None or (a is not None and b["is_payout"] <= a["is_payout"] * 1.05):
        rec = "leto"
    else:
        rec = "ext"
    res["recommended"] = rec
    log(f"RECOMMENDED (IS rule): {rec}  ({time.time() - t0:.0f}s)")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "prop_sim_select.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ----------------------------------------------------------------- final (OOS + robustness)

VARIANTS = {"slip2": dict(slip_ticks=2), "conservative": dict(intrabar="conservative"),
            "cons+slip2": dict(intrabar="conservative", slip_ticks=2), "m1 replay": dict(m1replay=True),
            "m1+slip2": dict(m1replay=True, slip_ticks=2),
            "shift1": dict(shift=1), "shift2": dict(shift=2), "shift3": dict(shift=3), "shift4": dict(shift=4)}


def halved(tr):
    """Expectancy-halved stress: subtract half the mean trade P&L (per leg) from every trade."""
    out = []
    for sym in ("MNQ", "MGC"):
        ts = [t for t in tr if t["sym"] == sym]
        if not ts:
            continue
        m = np.mean([t["pnl"] for t in ts if t["dday"] < CUT_DAY] or [0.0]) / 2.0
        for t in ts:
            u = dict(t)
            u["pnl"] = t["pnl"] - m
            u["r"] = t["r"] * (u["pnl"] / t["pnl"]) if t["pnl"] else t["r"]
            out.append(u)
    return sorted(out, key=lambda t: t["ts"])


def param_uncertainty_mae(tab, per, firm):
    return param_uncertainty(tab, per, firm, stress=True)


def param_uncertainty(tab, per, firm, n_hist=200, n_paths=1000, seed=SEED + 7, stress=False):
    """Outer bootstrap: alternative histories of the same length (weeks resampled), each run with
    n_paths inner paths -> spread of P(bust) and payout/month caused by the short sample."""
    rng = np.random.default_rng(seed)
    blocks = weeks_of(tab["days"], period_idx(tab["days"], per))
    pb, pp, ps = [], [], []
    for h in range(n_hist):
        hist = [blocks[i] for i in rng.integers(len(blocks), size=len(blocks))]
        paths = boot_paths(hist, n_paths=n_paths, seed=int(rng.integers(1 << 31)))
        r = run_firm(firm, tab, paths, stress=stress)
        pb.append(r["p_bust"])
        pp.append(r["payout_per_month"])
        ps.append(r["p_pass"])
    q = lambda v: [float(x) for x in np.percentile(v, [10, 50, 90])]
    return dict(p_bust_p10_50_90=q(pb), payout_p10_50_90=q(pp), p_pass_p10_50_90=q(ps),
                p_bust_ge10pct=float(np.mean(np.array(pb) >= 0.10)))


def final(log=print):
    sel = json.loads((OUT / "prop_sim_select.json").read_text())
    res = {"selection": {k: sel[k] for k in ("rule", "picks", "recommended")}, "legs": {}, "chosen": {},
           "grid_oos_hindsight": []}
    # per-leg stats at the standard 2 contracts and at the chosen sizes
    days = calendar_days()
    for port in PORTS:
        for sym in ("MNQ", "MGC"):
            w, ru = PORTS[port]["legs"][sym]
            qs = {2} | {sel["picks"][f"{port}|{f}"][sym.lower()] for f in FIRMS if sel["picks"][f"{port}|{f}"]}
            for q in sorted(qs):
                tr = leg_trades(sym, w, ru, q)
                tab = day_table(tr, days)
                res["legs"][f"{port} {sym} {w} {ru} x{q}"] = {per: series_stats(tr, tab, per) for per in ("full", "is", "oos")}
                f_, i_, o_ = (res["legs"][f"{port} {sym} {w} {ru} x{q}"][p] for p in ("full", "is", "oos"))
                log(f"LEG {port} {sym} {w} {ru} x{q}: FULL {DP.fmt(f_)} {f_['trades_per_week']:.2f}/wk +m {f_['pos_months']}/{f_['n_months']} "
                    f"wd/wk {f_['win_days_per_week']:.2f} worst ${f_['worst_day']:,.0f} tDD ${f_['max_trailing_eod_dd']:,.0f} | IS PF {i_['pf']:.2f} OOS PF {o_['pf']:.2f}")
    # chosen sizes
    for key, p in sel["picks"].items():
        if p is None:
            continue
        port, firm = key.split("|")
        qn, qg = p["mnq"], p["mgc"]
        tr = port_trades(port, qn, qg)
        tab = day_table(tr, days)
        ent = {}
        for per in ("full", "is", "oos"):
            ent[per] = eval_size(port, qn, qg, per, firms=(firm,), tr=tr, tab=tab)
            ent[per + "_stress"] = eval_size(port, qn, qg, per, firms=(firm,), tr=tr, tab=tab, stress=True)
        trh = halved(tr)
        tabh = day_table(trh, days)
        ent["halved"] = {per: eval_size(port, qn, qg, per, firms=(firm,), tr=trh, tab=tabh, replay=False) for per in ("is", "oos")}
        ent["uncertainty"] = {per: param_uncertainty(tab, per, firm) for per in ("is", "oos")}
        # context (not a selection input): already-funded start, and a 6-month horizon
        ent["funded_only"], ent["h6m"] = {}, {}
        for per in ("is", "oos"):
            bl = weeks_of(tab["days"], period_idx(tab["days"], per))
            ent["funded_only"][per] = bust_split(firm, tab, boot_paths(bl), start_funded=True)
            ent["h6m"][per] = bust_split(firm, tab, boot_paths(bl, horizon=126))
        ent["variants"] = {}
        for vt, kw in VARIANTS.items():
            tv = port_trades(port, qn, qg, **kw)
            tbv = day_table(tv, days)
            ent["variants"][vt] = {per: eval_size(port, qn, qg, per, firms=(firm,), tr=tv, tab=tbv, replay=False)
                                   for per in ("is", "oos")}
        res["chosen"][key] = ent
        log(f"\n== {key}: MNQ {qn} MGC {qg} MCL 0")
        for per in ("full", "is", "oos"):
            s = ent[per]["series"]
            log(f"  {per:4s} {DP.fmt(s)} {s['trades_per_week']:.2f}/wk +m {s['pos_months']}/{s['n_months']} wd/wk {s['win_days_per_week']:.2f} "
                f"worst ${s['worst_day']:,.0f} tDD ${s['max_trailing_eod_dd']:,.0f} wk>=5wd {s['weeks_ge5_windays']}/{s['weeks']}")
            log(f"       boot   {short(ent[per], firm)}")
            if ent[per].get(firm + "_replay"):
                log(f"       replay {short({firm: ent[per][firm + '_replay']}, firm)} (n={ent[per][firm + '_replay']['paths']})")
            log(f"       MAE    {short(ent[per + '_stress'], firm)}")
            if ent[per + "_stress"].get(firm + "_replay"):
                log(f"       MAE replay {short({firm: ent[per + '_stress'][firm + '_replay']}, firm)}")
        for per in ("is", "oos"):
            u = ent["uncertainty"][per]
            log(f"  uncertainty {per}: bust p10/50/90 {[round(v, 3) for v in u['p_bust_p10_50_90']]} payout {[round(v) for v in u['payout_p10_50_90']]} "
                f"P(bust>=10%) {u['p_bust_ge10pct']:.0%}")
            h = ent["halved"][per]
            log(f"  halved {per}: PF {h['series']['pf']:.2f} {short(h, firm)}")
            log(f"  funded-start {per}: {short({firm: ent['funded_only'][per]}, firm)} med funded days to 1st payout {ent['funded_only'][per]['med_funded_days_to_first_payout']}")
            log(f"  6-month {per}: {short({firm: ent['h6m'][per]}, firm)}")
        for vt, v in ent["variants"].items():
            log(f"  {vt:12s} IS PF {v['is']['series']['pf']:.2f} OOS PF {v['oos']['series']['pf']:.2f} | OOS {short(v['oos'], firm)}")
    res["chosen_mae"] = {}
    for key, p in sel.get("picks_mae", {}).items():
        if p is None:
            continue
        port, firm = key.split("|")
        tr = port_trades(port, p["mnq"], p["mgc"])
        tab = day_table(tr, days)
        ent = {per: eval_size(port, p["mnq"], p["mgc"], per, firms=(firm,), tr=tr, tab=tab, stress=True) for per in ("full", "is", "oos")}
        ent["uncertainty"] = {per: param_uncertainty_mae(tab, per, firm) for per in ("is", "oos")}
        ent["variants"] = {}
        for vt, kw in VARIANTS.items():
            tv = port_trades(port, p["mnq"], p["mgc"], **kw)
            tbv = day_table(tv, days)
            ent["variants"][vt] = {per: eval_size(port, p["mnq"], p["mgc"], per, firms=(firm,), tr=tv, tab=tbv,
                                                  replay=False, stress=True) for per in ("is", "oos")}
        res["chosen_mae"][key] = ent
        log(f"\n== MAE-basis pick {key}: MNQ {p['mnq']} MGC {p['mgc']}")
        for per in ("full", "is", "oos"):
            s_ = ent[per]["series"]
            log(f"  {per:4s} {DP.fmt(s_)} {s_['trades_per_week']:.2f}/wk wd/wk {s_['win_days_per_week']:.2f} worst ${s_['worst_day']:,.0f} tDD ${s_['max_trailing_eod_dd']:,.0f}")
            log(f"       boot   {short(ent[per], firm)}")
            if ent[per].get(firm + "_replay"):
                log(f"       replay {short({firm: ent[per][firm + '_replay']}, firm)} (n={ent[per][firm + '_replay']['paths']})")
        for per in ("is", "oos"):
            u = ent["uncertainty"][per]
            log(f"  uncertainty {per}: bust p10/50/90 {[round(v, 3) for v in u['p_bust_p10_50_90']]} payout {[round(v) for v in u['payout_p10_50_90']]} P(bust>=10%) {u['p_bust_ge10pct']:.0%}")
        for vt, v in ent["variants"].items():
            log(f"  {vt:12s} OOS PF {v['oos']['series']['pf']:.2f} | IS {short(v['is'], firm)} | OOS {short(v['oos'], firm)}")
    # hindsight: OOS-best sizes (NOT used; shows how much the IS choice leaves on the table)
    for port in PORTS:
        for qn, qg in SIZES:
            r = eval_size(port, qn, qg, "oos", replay=False)
            rm = eval_size(port, qn, qg, "oos", replay=False, stress=True)
            res["grid_oos_hindsight"].append({k: r[k] for k in ("port", "mnq", "mgc", "topstep", "ftmo")} |
                                             {"pf": r["series"]["pf"], "wd": r["series"]["win_days_per_week"],
                                              "topstep_mae": rm["topstep"], "ftmo_mae": rm["ftmo"]})
    for port in PORTS:
        for f in FIRMS:
            p = pick([r for r in res["grid_oos_hindsight"] if r["port"] == port], f)
            log(f"HINDSIGHT OOS-best {port} {f}: " + ("none" if p is None else f"MNQ{p['mnq']} MGC{p['mgc']} payout ${p[f]['payout_per_month']:,.0f} bust {p[f]['p_bust']:.1%}"))
    (OUT / "prop_sim.json").write_text(json.dumps(res, indent=1, default=str))
    return res


# ----------------------------------------------------------------- checks

def truncation_check(log=print):
    """(1) reproduces prop_daily at 2+2 contracts; (2) trades built from bars truncated at a date equal the
    full-run trades that exited before it, for every new size (1 and 3 contracts) and both portfolios;
    (3) a day's P&L only uses trades of that day (day_table on truncated trades == full for earlier days)."""
    a = leg_trades("MNQ", "L02-05", "max1", 2)
    b = leg_trades("MGC", "C0820-1030", "max1", 2)
    c = leg_trades("MNQ", "L01-07", "time2", 2)
    ok = (len(a), round(DP.stats(a)["pf"], 2), len(b), round(DP.stats(b)["pf"], 2), len(c), round(DP.stats(c)["pf"], 2))
    log(f"reproduction: Leto MNQ {ok[0]} tr PF {ok[1]}, MGC {ok[2]} tr PF {ok[3]}, MNQ 01-07 time2 {ok[4]} tr PF {ok[5]}")
    assert ok == (70, 2.50, 78, 1.70, 121, 1.82), ok
    ext = port_trades("ext", 2, 2)
    s = DP.stats(ext)
    log(f"reproduction: ext 2+2 {s['trades']} tr PF {s['pf']:.2f} net ${s['net']:,.0f}")
    assert s["trades"] == 186 and round(s["pf"], 2) == 1.80
    days = calendar_days()
    for cut in ("2025-12-15", "2026-04-01", "2026-07-20"):
        feats = {}
        for sym in ("MNQ", "MGC"):
            src = DP.m1(sym)
            df = data.resample(src[src.index < pd.Timestamp(cut, tz=src.index.tz)], "15min")
            feats[sym] = features.build(df, DP.inst_of(sym).tick)
        for port in PORTS:
            for qn, qg in ((1, 1), (3, 3), (4, 2)):
                full = port_trades(port, qn, qg)
                part = port_trades(port, qn, qg, feats=feats)
                lim = (pd.Timestamp(cut) - pd.Timedelta(days=1)).isoformat()
                fa = [(t["entry_time"], t["exit_time"], round(t["pnl"], 6)) for t in full if t["exit_time"] < lim]
                pa = [(t["entry_time"], t["exit_time"], round(t["pnl"], 6)) for t in part if t["exit_time"] < lim]
                assert fa == pa, (cut, port, qn, qg)
                tf, tp = day_table(full, days), day_table(part, days)
                m = days < pd.Timestamp(cut) - pd.Timedelta(days=1)
                assert np.allclose(tf["net_dll"][m], tp["net_dll"][m]) and np.allclose(tf["lo_raw"][m], tp["lo_raw"][m])
    log("truncation check OK (cuts 2025-12-15 / 2026-04-01 / 2026-07-20; sizes 1+1, 3+3, 4+2; both portfolios)")
    return True


def real_check(log=print):
    """Real CME 5m bars (Yahoo, lab.research store) -> 15m; chosen sizes; one historical prop replay from
    the first day (no bootstrap; ~50 days is far too short to say anything statistically)."""
    from . import research
    sel = json.loads((OUT / "prop_sim_select.json").read_text())
    st = research.load_store(["MNQ", "MGC"], ["5m"])
    out = {}
    for key, p in sel["picks"].items():
        if p is None:
            continue
        port, firm = key.split("|")
        for src_name in ("real", "proxy"):
            feats, lo, hi = {}, None, None
            for s in ("MNQ", "MGC"):
                real = st.get((s, "5m"))
                lo, hi = real.index[0], real.index[-1]
                if src_name == "real":
                    df = data.resample(real, "15min")
                else:
                    d1 = DP.m1(s)
                    df = data.resample(d1[(d1.index >= lo) & (d1.index <= hi)], "15min")
                feats[s] = features.build(df, DP.inst_of(s).tick)
            tr = port_trades(port, p["mnq"], p["mgc"], feats=feats)
            f = feats["MNQ"]
            first = pd.Series(f.df.index).groupby(f.day).first()
            days = pd.DatetimeIndex(sorted({PD.day_key(t).tz_localize(None) for t in first}))
            tab = day_table(tr, days)
            idx = np.arange(len(days))[None, :]
            r = run_firm(firm, tab, idx)
            net = tab["net_raw"]
            wk = days.to_period("W")
            st_ = DP.stats(tr)
            out[f"{key} {src_name}"] = dict(stats=st_, start=str(lo), end=str(hi), days=len(days),
                                            win_days_per_week=float((net >= WIN_TARGET).sum() / len(pd.unique(wk))),
                                            worst_day=float(net.min()), replay=r)
            log(f"{key:13s} {src_name:5s} {lo:%Y-%m-%d}..{hi:%Y-%m-%d} {len(days)}d {DP.fmt(st_)} "
                f"wd/wk {out[f'{key} {src_name}']['win_days_per_week']:.2f} | passed {r['p_pass']:.0%} "
                f"day {r['med_days_to_pass']} lost {r['p_bust']:.0%} payout total ${r['payout_per_month'] * len(days) / 21:,.0f}")
    (OUT / "prop_sim_real.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "select"
    {"trunc": truncation_check, "select": select, "final": final, "real": real_check}[cmd]()

"""Classic (non-ICT) intraday edges on MNQ, simulated on 1-minute bars.

Families
  orb   opening-range breakout (OR 15 or 30 min) with gap/trend and OR-width filters
  imom  intraday momentum: sign of (overnight+)first-30-min return -> last 30-55 min
  gap   gap fill (fade toward prior close) and gap-and-go
  vwap  VWAP trend following with VWAP-close / chandelier exits
  pdx   prior-day high/low breakout with ATR stops

Execution model (no look-ahead): signals use only completed bars of the signal
timeframe (5/15/30 min, aligned to 09:30); entry at the open of the next 1-minute
bar (market, 1 tick slippage) or with a resting stop order worked on 1-minute bars.
Exits are simulated on 1-minute bars: stop first when stop and target share a
minute, stop/market exits pay slippage, targets fill at price, flat at 15:55.
Costs: 2 MNQ, $0.62/side/contract.  R = net $ / planned $ risk.

Usage:  PYTHONPATH=. python -m lab.prof_classic grid      (all families, IS selection)
        PYTHONPATH=. python -m lab.prof_classic check     (truncation check)
"""

from __future__ import annotations

import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

P = "/tmp/claude-0/-home-user-JSON-Debugger-Visualiser/9ad27238-8feb-5ae8-a1cd-bf476dc0f305/scratchpad/duka/"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "profit"
SPLIT = "2026-04-01"

TICK, PV, QTY, COMM = 0.25, 2.0, 2, 0.62
OPEN_M, FLAT_M = 570, 955          # 09:30, 15:55


# --------------------------------------------------------------------------- #
# Data: RTH days on a fixed base-bar grid
# --------------------------------------------------------------------------- #
@dataclass
class Day:
    date: pd.Timestamp
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    vw: np.ndarray      # session VWAP at each base-bar close
    base: int           # base bar minutes
    prev_close: float
    prev_high: float
    prev_low: float
    on_high: float
    on_low: float
    datr: float         # mean of prior 14 RTH ranges
    trend20: int        # sign(prev_close - SMA20 of prior closes)


def build_days(m1: pd.DataFrame, base: int = 1) -> list[Day]:
    df = m1 if base == 1 else m1.resample(f"{base}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
    mod = df.index.hour * 60 + df.index.minute
    nslot = 390 // base
    rth = df[(mod >= OPEN_M) & (mod < 960)]
    # overnight: 18:00 prev day .. 09:29
    gday = (df.index + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    on = df[((mod >= 1080) | (mod < OPEN_M))]
    on_g = on.groupby(gday[((mod >= 1080) | (mod < OPEN_M))])
    on_hi, on_lo = on_g["high"].max(), on_g["low"].min()
    days, hist = [], []
    for d, g in rth.groupby(rth.index.normalize().tz_localize(None)):
        if len(g) < int(0.95 * nslot):
            hist.append(None)  # half day / missing data: not traded, not used as prior day
            continue
        slot = ((g.index.hour * 60 + g.index.minute) - OPEN_M) // base
        idx = np.arange(nslot)
        gg = g.set_axis(slot).reindex(idx)
        c = gg["close"].ffill().bfill().to_numpy()
        o = gg["open"].fillna(pd.Series(c, index=idx).shift(1)).bfill().to_numpy()
        h = gg["high"].fillna(pd.Series(np.maximum(o, c), index=idx)).to_numpy()
        l = gg["low"].fillna(pd.Series(np.minimum(o, c), index=idx)).to_numpy()
        v = gg["volume"].fillna(0).to_numpy() + 1e-9
        tp = (h + l + c) / 3
        vw = np.cumsum(tp * v) / np.cumsum(v)
        prior = [x for x in hist if x is not None]
        if len(prior) >= 8 and d in on_hi.index:
            pc, ph, pl = prior[-1]
            datr = float(np.mean([x[1] - x[2] for x in prior[-14:]]))
            sma = np.mean([x[0] for x in prior[-20:]])
            days.append(Day(d, o, h, l, c, vw, base, pc, ph, pl, float(on_hi[d]), float(on_lo[d]),
                            datr, int(np.sign(pc - sma))))
        hist.append((c[-1], h.max(), l.min()))
    return days


def tf_bars(day: Day, tf: int):
    """Signal-timeframe bars (aligned to 09:30). Returns o,h,l,c,vw arrays and the
    base index at which each bar's information becomes actionable (next bar open)."""
    k = tf // day.base
    nb = len(day.c) // k
    o = day.o[: nb * k].reshape(nb, k)[:, 0]
    h = day.h[: nb * k].reshape(nb, k).max(1)
    l = day.l[: nb * k].reshape(nb, k).min(1)
    c = day.c[: nb * k].reshape(nb, k)[:, -1]
    vw = day.vw[: nb * k].reshape(nb, k)[:, -1]
    act = (np.arange(nb) + 1) * k
    return o, h, l, c, vw, act


def slot_of(day: Day, minute: int) -> int:
    return (minute - OPEN_M) // day.base


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #
@dataclass
class Sig:
    k0: int                 # base index of entry (fill at its open, or resting stop from here)
    side: int
    stop: float             # initial stop price
    target: float = np.nan  # nan = none
    kx: int | None = None   # exit at open of this base index (default 15:55)
    entry_px: float = np.nan  # resting stop-entry price (nan = market at open of k0)
    entry_until: int | None = None  # resting order expiry (base index)
    rr: float = np.nan      # if set, target = entry + rr*risk (computed from actual fill)
    trail: str = ""         # "" | "vwap:<tf>" | "chand:<mult>:<tf>"
    trail_atr: float = 0.0
    note: str = ""


def simulate(day: Day, s: Sig, slip_ticks: int = 1):
    slip = slip_ticks * TICK
    o, h, l, c = day.o, day.h, day.l, day.c
    kx = s.kx if s.kx is not None else slot_of(day, FLAT_M)
    side = s.side
    k0 = s.k0
    if np.isnan(s.entry_px):
        fill = o[k0] + side * slip
    else:
        end = min(s.entry_until or kx, kx)
        fill = None
        for k in range(k0, end):
            if side > 0 and h[k] >= s.entry_px:
                if l[k] <= s.stop and o[k] < s.entry_px:   # traded through the stop first? treat as void if open below stop
                    if o[k] <= s.stop:
                        return None
                fill = max(o[k], s.entry_px) + slip
                k0 = k
                break
            if side < 0 and l[k] <= s.entry_px:
                if o[k] >= s.stop:
                    return None
                fill = min(o[k], s.entry_px) - slip
                k0 = k
                break
        if fill is None:
            return None
    risk = (fill - s.stop) * side
    if risk < 4 * TICK:
        return None
    tgt = fill + side * s.rr * risk if not np.isnan(s.rr) else s.target
    stop_arr = np.full(kx - k0, s.stop)
    exit_sig = np.zeros(kx - k0, bool)
    if s.trail:
        kind, *args = s.trail.split(":")
        tf = int(args[-1])
        _, bh, bl, bc, bvw, act = tf_bars(day, tf)
        for b in range(len(bc)):
            a = act[b]
            if a <= k0 or a >= kx:
                continue
            # bar b must have started at/after entry bar's TF bar to count
            if kind == "vwap":
                if (bc[b] < bvw[b]) if side > 0 else (bc[b] > bvw[b]):
                    exit_sig[a - k0] = True
            elif kind == "chand":
                m = float(args[0])
                k_start = k0
                seg_hi = np.max(h[k_start:a]) if side > 0 else np.min(l[k_start:a])
                lvl = seg_hi - side * m * s.trail_atr
                if side > 0:
                    stop_arr[a - k0:] = np.maximum(stop_arr[a - k0:], lvl)
                else:
                    stop_arr[a - k0:] = np.minimum(stop_arr[a - k0:], lvl)
    hs, ls, os_ = h[k0:kx], l[k0:kx], o[k0:kx]
    if side > 0:
        hit_s = ls <= stop_arr
        hit_t = hs >= tgt if not np.isnan(tgt) else np.zeros_like(hit_s)
    else:
        hit_s = hs >= stop_arr
        hit_t = ls <= tgt if not np.isnan(tgt) else np.zeros_like(hit_s)
    ev = hit_s | hit_t | exit_sig
    j = int(np.argmax(ev)) if ev.any() else None
    if j is None:
        px, reason, kexit = o[kx] - side * slip if kx < len(o) else c[-1] - side * slip, "eod", kx
    elif exit_sig[j]:
        px, reason, kexit = os_[j] - side * slip, "trail", k0 + j
    elif hit_s[j]:
        st = stop_arr[j]
        gap = (os_[j] <= st) if side > 0 else (os_[j] >= st)
        px = (os_[j] if (gap and j > 0) else st) - side * slip
        reason, kexit = ("sl" if st == s.stop else "tsl"), k0 + j
    else:
        gap = (os_[j] >= tgt) if side > 0 else (os_[j] <= tgt)
        px, reason, kexit = (os_[j] if (gap and j > 0) else tgt), "tp", k0 + j
    pnl = (px - fill) * side * PV * QTY - 2 * COMM * QTY
    r = pnl / (risk * PV * QTY)
    t = day.date + pd.Timedelta(minutes=OPEN_M + k0 * day.base)
    return dict(entry_time=t, side=side, entry=fill, stop=s.stop, exit=px, r=r, pnl=pnl,
                reason=reason, bars=kexit - k0, note=s.note)


# --------------------------------------------------------------------------- #
# Strategy families: each returns at most one Sig per day (decided causally)
# --------------------------------------------------------------------------- #
def tf_atr(days: list[Day], tf: int) -> dict:
    """RTH-only ATR(14) on tf bars; value for day d bar b uses bars <= b."""
    out, prev_c, a = {}, None, None
    for di, d in enumerate(days):
        _, h, l, c, _, _ = tf_bars(d, tf)
        arr = np.empty(len(c))
        for b in range(len(c)):
            pc = prev_c if prev_c is not None else c[b]
            tr = max(h[b] - l[b], abs(h[b] - pc), abs(l[b] - pc))
            a = tr if a is None else a + (tr - a) / 14
            arr[b] = a
            prev_c = c[b]
        out[di] = arr
    return out


def sig_orb(d: Day, p, atrs=None, di=None):
    orl = p["or"] // d.base
    ORH, ORL = d.h[:orl].max(), d.l[:orl].min()
    rng = ORH - ORL
    if rng <= 0:
        return None
    if p["width"] == "narrow" and rng > 0.25 * d.datr:
        return None
    if p["width"] == "wide" and rng < 0.25 * d.datr:
        return None
    gap = d.o[0] - d.prev_close
    last = slot_of(d, 12 * 60)
    mid = (ORH + ORL) / 2
    stops = {+1: ORL if p["stop"] == "opp" else mid, -1: ORH if p["stop"] == "opp" else mid}
    rr = p["rr"] if p["rr"] else np.nan
    if p["entry"] == "stop":
        # earliest side touched after the OR (resting OCO stop orders)
        for k in range(orl, last):
            up, dn = d.h[k] >= ORH + TICK, d.l[k] <= ORL - TICK
            if up and dn:
                return None
            if up or dn:
                side = 1 if up else -1
                break
        else:
            return None
        if not _orb_filter(p, side, gap, d):
            return None
        return Sig(k, side, stops[side], entry_px=ORH + TICK if side > 0 else ORL - TICK,
                   entry_until=k + 1, rr=rr, note="orb")
    tf = int(p["entry"][5:])
    _, bh, bl, bc, _, act = tf_bars(d, tf)
    for b in range(len(bc)):
        if act[b] <= orl or act[b] > last:
            continue
        side = 1 if bc[b] > ORH else -1 if bc[b] < ORL else 0
        if side:
            if not _orb_filter(p, side, gap, d):
                return None
            return Sig(act[b], side, stops[side], rr=rr, note="orb")
    return None


def _orb_filter(p, side, gap, d):
    f = p["filt"]
    if f == "gap":
        return np.sign(gap) == side
    if f == "trend":
        return d.trend20 == side
    return True


def sig_imom(d: Day, p, atrs=None, di=None):
    s10 = slot_of(d, 600)
    ref = {"on30": d.prev_close, "f30": d.o[0]}
    if p["sig"] in ref:
        r = d.c[s10 - 1] - ref[p["sig"]]
    else:  # "rod": rest of day up to entry time, from prior close
        r = d.c[slot_of(d, p["entry"]) - 1] - d.prev_close
    if abs(r) < p["thr"] * d.datr:
        return None
    side = int(np.sign(r))
    if side == 0:
        return None
    k0 = slot_of(d, p["entry"])
    stop = d.o[k0] - side * p["stop"] * d.datr
    return Sig(k0, side, stop, note="imom")


def sig_gap(d: Day, p, atrs=None, di=None):
    gap = d.o[0] - d.prev_close
    g = abs(gap) / d.datr
    gs = int(np.sign(gap))
    if gs == 0:
        return None
    if p["mode"] == "fade":
        if not (p["lo"] <= g < p["hi"]):
            return None
        side = -gs
        k0 = 1 if p["wait"] == 0 else slot_of(d, OPEN_M + p["wait"])  # gap set by the 09:30 print; enter next bar
        if p["wait"]:
            # require the first bars to have NOT extended the gap (close back toward prior close)
            if (d.c[k0 - 1] - d.o[0]) * gs > 0:
                return None
        ent = d.o[k0]
        if (ent - d.prev_close) * gs <= 0:
            return None  # already filled
        stop = ent - side * p["stopx"] * abs(ent - d.prev_close)
        kx = slot_of(d, p["exit"])
        return Sig(k0, side, stop, target=d.prev_close, kx=kx, note="gapfade")
    # gap and go
    if g < p["lo"]:
        return None
    tf = p["tf"]
    _, bh, bl, bc, _, act = tf_bars(d, tf)
    if (bc[0] - d.o[0]) * gs <= 0:
        return None
    stop = bl[0] if gs > 0 else bh[0]
    return Sig(act[0], gs, stop, rr=p["rr"] if p["rr"] else np.nan, note="gapgo")


def sig_vwap(d: Day, p, atrs, di):
    tf = p["tf"]
    _, bh, bl, bc, bvw, act = tf_bars(d, tf)
    a = atrs[tf][di]
    first = slot_of(d, p["start"])
    last = slot_of(d, 13 * 60)
    for b in range(len(bc)):
        if act[b] < first or act[b] > last:
            continue
        if p["entry"] == "hold":
            # all bars so far on one side of VWAP and VWAP sloping that way
            seg = bc[: b + 1] - bvw[: b + 1]
            if np.all(seg > 0) and bvw[b] > bvw[0]:
                side = 1
            elif np.all(seg < 0) and bvw[b] < bvw[0]:
                side = -1
            else:
                return None  # decided once at the first eligible bar
        else:  # first cross after start, in the direction of today's move (close vs open)
            if b == 0:
                continue
            up = bc[b - 1] <= bvw[b - 1] and bc[b] > bvw[b] and bc[b] > d.o[0]
            dn = bc[b - 1] >= bvw[b - 1] and bc[b] < bvw[b] and bc[b] < d.o[0]
            side = 1 if up else -1 if dn else 0
            if not side:
                continue
        stop = bc[b] - side * p["stop"] * a[b]
        trail = f"vwap:{tf}" if p["exit"] == "vwap" else f"chand:{p['stop']}:{tf}"
        return Sig(act[b], side, stop, trail=trail, trail_atr=a[b], note="vwap")
    return None


def sig_pdx(d: Day, p, atrs, di):
    if p["filt"] == "inside" and not (d.prev_low < d.o[0] < d.prev_high):
        return None
    tf = p["tf"]
    _, bh, bl, bc, _, act = tf_bars(d, tf)
    a = atrs[tf][di]
    first, last = slot_of(d, 585), slot_of(d, 14 * 60)
    rr = p["rr"] if p["rr"] else np.nan
    for b in range(len(bc)):
        if act[b] < first or act[b] > last:
            continue
        # first close beyond prior-day high/low today (previous bars stayed inside)
        prevmax = bc[:b].max() if b else -np.inf
        prevmin = bc[:b].min() if b else np.inf
        side = 0
        if bc[b] > d.prev_high and prevmax <= d.prev_high:
            side = 1
        elif bc[b] < d.prev_low and prevmin >= d.prev_low:
            side = -1
        if side:
            stop = bc[b] - side * p["stop"] * a[b]
            trail = f"chand:{p['stop']}:{tf}" if p["exit"] == "chand" else ""
            return Sig(act[b], side, stop, rr=rr if not trail else np.nan, trail=trail,
                       trail_atr=a[b], note="pdx")
    return None


FAMILIES = {"orb": sig_orb, "imom": sig_imom, "gap": sig_gap, "vwap": sig_vwap, "pdx": sig_pdx}


def grids():
    g = []
    for o_, e, st, rr, f, w in itertools.product([15, 30], ["stop", "close5", "close15"], ["opp", "mid"],
                                                 [1.0, 2.0, 0], ["none", "gap", "trend"], ["any", "narrow"]):
        g.append(("orb", dict(**{"or": o_}, entry=e, stop=st, rr=rr, filt=f, width=w)))          # 144
    for sg, en, stp, th in itertools.product(["on30", "f30", "rod"], [900, 930], [0.15, 0.3], [0.0, 0.2]):
        g.append(("imom", dict(sig=sg, entry=en, stop=stp, thr=th)))                              # 24
    for lo, hi, w, sx, ex in itertools.product([0.05, 0.15], [0.5, 1.0], [0, 15], [1.0, 2.0], [720, 955]):
        g.append(("gap", dict(mode="fade", lo=lo, hi=hi, wait=w, stopx=sx, exit=ex)))              # 32
    for lo, tf, rr in itertools.product([0.2, 0.4], [15, 30], [1.0, 2.0, 0]):
        g.append(("gap", dict(mode="go", lo=lo, tf=tf, rr=rr)))                                    # 12
    for tf, en, ex, stp, stt in itertools.product([5, 15, 30], ["hold", "cross"], ["vwap", "chand"], [1.0, 2.0],
                                                  [600, 630]):
        g.append(("vwap", dict(tf=tf, entry=en, exit=ex, stop=stp, start=stt)))                    # 48
    for tf, stp, rr, f in itertools.product([5, 15, 30], [1.0, 2.0], [1.5, 3.0, 0], ["none", "inside"]):
        g.append(("pdx", dict(tf=tf, stop=stp, rr=rr, filt=f, exit="fixed")))                     # 36
    for tf, stp, f in itertools.product([5, 15, 30], [1.5, 2.5], ["none", "inside"]):
        g.append(("pdx", dict(tf=tf, stop=stp, rr=0, filt=f, exit="chand")))                      # 12
    return g


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def run(days, fam, p, atrs, slip=1):
    fn = FAMILIES[fam]
    out = []
    for di, d in enumerate(days):
        s = fn(d, p, atrs, di)
        if s is None:
            continue
        t = simulate(d, s, slip)
        if t is not None:
            out.append(t)
    return pd.DataFrame(out)


def stats(t: pd.DataFrame) -> dict:
    if t is None or len(t) == 0:
        return dict(n=0, wr=0, exp=0, pf=0, net=0, dd=0, t=0)
    r = t["r"].to_numpy()
    pnl = t["pnl"].to_numpy()
    eq = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]))
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    sd = r.std(ddof=1) if len(r) > 1 else 1
    return dict(n=len(r), wr=round(float((r > 0).mean() * 100), 1), exp=round(float(r.mean()), 3),
                pf=round(float(gw / gl) if gl > 0 else 99.0, 2), net=round(float(pnl.sum())), dd=round(dd),
                t=round(float(r.mean() / sd * np.sqrt(len(r))) if sd > 0 else 0, 2))


def split(t):
    if len(t) == 0:
        return t, t
    cut = pd.Timestamp(SPLIT)
    et = t["entry_time"]
    return t[et < cut], t[et >= cut]


def monthly(t):
    if len(t) == 0:
        return {}
    m = t.groupby(t["entry_time"].dt.strftime("%Y-%m"))["r"].sum().round(2)
    return m.to_dict()


def full_report(t):
    i, o = split(t)
    m = monthly(t)
    return dict(full=stats(t), IS=stats(i), OOS=stats(o), months=m,
                pos=sum(v > 0 for v in m.values()), nmonths=len(m))


# --------------------------------------------------------------------------- #
def load(base=1):
    m1 = pd.read_pickle(P + "MNQ_1m.pkl")
    return build_days(m1, base)


def grid_main():
    days = load()
    atrs = {tf: tf_atr(days, tf) for tf in (5, 15, 30)}
    rows = []
    g = grids()
    print(f"days {len(days)}  configs {len(g)}", flush=True)
    for fam, p in g:
        t = run(days, fam, p, atrs)
        rep = full_report(t)
        rows.append(dict(fam=fam, p=p, **{k: rep[k] for k in ("IS", "OOS", "full", "pos", "nmonths")}))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "classic_grid.json").write_text(json.dumps(rows, default=str, indent=0))
    # IS-only selection per family: rank by IS t-stat with >= 40 IS trades
    for fam in FAMILIES:
        fr = [r for r in rows if r["fam"] == fam and r["IS"]["n"] >= 40]
        fr.sort(key=lambda r: -r["IS"]["t"])
        print(f"\n== {fam}: {len([r for r in rows if r['fam']==fam])} configs; top 5 by IS t-stat")
        for r in fr[:5]:
            print(r["p"], "IS", r["IS"], "\n    OOS", r["OOS"], "pos", r["pos"], "/", r["nmonths"])


def check_main():
    """Truncation check: signals computed on a day truncated after bar k equal those on the full day
    whenever the full-day signal is actionable at or before k."""
    days = load()
    atrs = {tf: tf_atr(days, tf) for tf in (5, 15, 30)}
    bad = tot = 0
    rng = np.random.default_rng(0)
    for fam, p in grids()[::7]:
        for di in rng.choice(len(days), 25, replace=False):
            d = days[di]
            s = FAMILIES[fam](d, p, atrs, di)
            if s is None:
                continue
            k = s.k0 + (0 if np.isnan(s.entry_px) else 1)  # data before k0 (stop orders: through the touch bar)
            dd = Day(d.date, d.o.copy(), d.h.copy(), d.l.copy(), d.c.copy(), d.vw.copy(), d.base,
                     d.prev_close, d.prev_high, d.prev_low, d.on_high, d.on_low, d.datr, d.trend20)
            noise = rng.normal(0, 50, len(d.c) - k)
            for arr in (dd.o, dd.h, dd.l, dd.c, dd.vw):
                arr[k:] = arr[k:] + noise          # corrupt the future
            dd.h[k:] = np.maximum(dd.h[k:], np.maximum(dd.o[k:], dd.c[k:]))
            dd.l[k:] = np.minimum(dd.l[k:], np.minimum(dd.o[k:], dd.c[k:]))
            s2 = FAMILIES[fam](dd, p, atrs, di)
            tot += 1
            ok = s2 is not None and s2.k0 == s.k0 and s2.side == s.side
            bad += not ok
            if not ok: print("FAIL", fam, p, s, s2)
    print(f"truncation check: {tot - bad}/{tot} identical")


BEST = ("imom", dict(sig="f30", entry=900, stop=0.15, thr=0.2))       # IS-best of family imom
BEST_VWAP = ("vwap", dict(tf=15, entry="cross", exit="chand", stop=1.0, start=600))  # IS-best of family vwap


def _line(name, rep):
    f, i, o = rep["full"], rep["IS"], rep["OOS"]
    return (f"| {name} | {f['n']} | {f['wr']} | {f['exp']:+.3f} | {f['pf']} | {f['net']} | {f['dd']} | "
            f"{rep['pos']}/{rep['nmonths']} | {i['n']} / {i['pf']} / {i['exp']:+.3f} | {o['n']} / {o['pf']} / {o['exp']:+.3f} |")


def deep_main():
    days = load()
    atrs = {tf: tf_atr(days, tf) for tf in (5, 15, 30)}
    res = {}
    hdr = "| variant | n | WR% | exp R | PF | net $ | maxDD $ | +months | IS n/PF/exp | OOS n/PF/exp |\n|---|---|---|---|---|---|---|---|---|---|"
    print(hdr)
    fam, p0 = BEST
    t = run(days, fam, p0, atrs)
    rep = full_report(t)
    res["best"] = rep
    print(_line("BEST imom f30 15:00 stop0.15 thr0.2", rep))
    print("months", rep["months"])
    t2 = run(days, fam, p0, atrs, slip=2)
    print(_line("BEST, 2 ticks slippage", full_report(t2)))
    for side in (1, -1):
        print(_line(f"BEST side {side}", full_report(t[t.side == side])))
    nb = 0
    # neighbourhood (reported, not used for selection)
    for k, vals in dict(thr=[0.0, 0.1, 0.15, 0.25, 0.3, 0.4], stop=[0.1, 0.2, 0.25], entry=[870, 885, 915, 930]).items():
        for v in vals:
            p = dict(p0, **{k: v})
            nb += 1
            print(_line(f"{k}={v}", full_report(run(days, fam, p, atrs))))
    # exit time variants
    for ex in (930, 945):
        nb += 1
        tt = []
        for di, d in enumerate(days):
            sg = sig_imom(d, p0)
            if sg is None:
                continue
            sg.kx = slot_of(d, ex)
            r_ = simulate(d, sg)
            if r_:
                tt.append(r_)
        print(_line(f"exit {ex//60}:{ex%60:02d}", full_report(pd.DataFrame(tt))))
    # portfolio with the IS-best VWAP rule (both picked IS-only, one per family)
    tv = run(days, *BEST_VWAP, atrs)
    print(_line("VWAP cross 15m chand (IS-best vwap)", full_report(tv)))
    port = pd.concat([t, tv]).sort_values("entry_time")
    print(_line("PORTFOLIO imom + vwap", full_report(port)))
    print("portfolio months", full_report(port)["months"])
    # coarser base bars (5-minute replay) on Dukascopy
    days5 = load(5)
    print(_line("BEST on 5m base bars", full_report(run(days5, fam, p0, None))))
    # real MNQ futures (5m, ~70 days) vs Dukascopy same window
    from lab import research
    st = research.load_store(["MNQ"], ["5m"])
    rd = build_days(st[("MNQ", "5m")], 5)
    tr = run(rd, fam, p0, None)
    lo = rd[0].date
    td = t[t.entry_time >= lo]
    print("real MNQ window from", lo.date(), "real:", stats(tr), "\n  dukascopy same window:", stats(td))
    print("real trades:\n", tr[["entry_time", "side", "r", "pnl", "reason"]].to_string() if len(tr) else "none")
    m = pd.merge(tr[["entry_time", "side", "r"]], td[["entry_time", "side", "r"]], on="entry_time", how="outer",
                 suffixes=("_real", "_duka"))
    print(m.to_string())
    print("neighbour configs:", nb + 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "classic.json").write_text(json.dumps(dict(best=BEST, report=rep, port=full_report(port),
                                                      real=stats(tr), duka_same=stats(td)), default=str, indent=1))



def combo_main():
    """FVG Pro Leto (baseline, not re-tuned) + intraday momentum as a two-rule portfolio."""
    from lab import data as ldata, fvg_pro
    m1 = pd.read_pickle(P + "MNQ_1m.pkl")
    leto = dict(windows=fvg_pro.WINDOW_PRESETS["london"], min_fvg_atr=0.3, entry="edge", rr=2.0, max_trades=1)
    _, tr = fvg_pro.backtest(ldata.resample(m1, "15min"), "MNQ", leto, intrabar="path")
    tl = pd.DataFrame([dict(entry_time=pd.Timestamp(t.entry_time).tz_localize(None), r=t.r, pnl=t.pnl,
                            exit_time=pd.Timestamp(t.exit_time).tz_localize(None)) for t in tr])
    days = build_days(m1)
    ti = run(days, *BEST, None)
    print("Leto  ", full_report(tl))
    print("Leto overlapping 15:00-15:55:", int(((tl.exit_time.dt.hour * 60 + tl.exit_time.dt.minute) > 900).sum()))
    port = pd.concat([tl[["entry_time", "r", "pnl"]], ti[["entry_time", "r", "pnl"]]]).sort_values("entry_time")
    rep = full_report(port)
    print("Leto+imom", rep)


if __name__ == "__main__":
    {"grid": grid_main, "check": check_main, "deep": deep_main, "combo": combo_main}[sys.argv[1]]()

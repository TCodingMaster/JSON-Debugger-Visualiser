"""Concept-only study: liquidity sweep (S), rejection block (R) and FVG
respected (F), tested alone and in every combination, with no trader's rules
attached. Each combination keeps the user's plan (fixed 2R, 2 MNQ / 1 MGC).

Definitions (identical across combinations, so differences come from the
components themselves):

  S  sweep      a bar trades through a liquidity pool (3-bar swing high/low,
                prior-day high/low, overnight high/low) and CLOSES back on
                the other side.
  R  rejection  the trigger bar's wick against the trade is >= 40 % of its range
                (with S: the sweep bar; without S: any bar whose range is
                >= 1 ATR and wick >= 50 %, so it's a real rejection candle).
  F  FVG        a 3-candle fair value gap in the trade direction. With a
                trigger (S and/or R) it must form within 10 bars after it;
                entry = limit at the gap's 50 % (CE); cancelled if a bar closes
                through the far edge (the "respected" test). F alone: every gap
                in the session window.

Stops: beyond the trigger bar's extreme (S/R), or beyond the 3-candle
pattern (F alone). Without F, entry is at market on the next bar.
CONTROL: random direction at random bars, 1 ATR stop, same 2R target —
the baseline that tells you what "no edge" looks like after costs.
"""

from __future__ import annotations

import math

import numpy as np

from . import engine, features, metrics
from .data import Instrument, get_instrument
from .engine import Setup
from .features import Features, hm, pivots

COMBOS = {
    "S": "Liquidity sweep only",
    "R": "Rejection block only",
    "F": "FVG respected only",
    "SR": "Sweep + rejection",
    "SF": "Sweep + FVG",
    "RF": "Rejection + FVG",
    "SRF": "Sweep + rejection + FVG (full)",
    "CONTROL": "Random entries (control)",
}

# Liquidity sweep + order block + FVG study (the user's second playbook).
OB_COMBOS = {
    "S": "Liquidity sweep only",
    "F": "FVG respected only",
    "SF": "Sweep + FVG (no order block)",
    "SOF": "Sweep + order block + FVG, entry at FVG 50%",
    "SOF@OB": "Sweep + order block + FVG, entry at order block",
    "CONTROL": "Random entries (control)",
}

OB_WINDOWS = {
    "ny_10_13": [("10:00", "13:00")],
    "asia_20_04": [("20:00", "24:00"), ("00:00", "04:00")],
    "both": [("20:00", "24:00"), ("00:00", "04:00"), ("10:00", "13:00")],
}

WINDOWS = {
    "ny_am": [("09:30", "11:30")],
    "extended": [("03:00", "05:00"), ("08:30", "15:00")],
}

DEFAULTS = dict(pivot_len=3, max_pool_age=300, wick_ratio=0.40, rej_wick=0.50, rej_range_atr=1.0,
                fvg_window=10, min_fvg_atr=0.10, order_expiry=20, buffer_ticks=2, rr=2.0,
                asia_levels=False)


def _in(feat, i, windows):
    m = feat.mod[i]
    return any(hm(a) <= m < hm(b) for a, b in windows)


def _ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def generate(combo: str, feat: Features, inst: Instrument, windows, p: dict | None = None,
             seed: int = 0) -> list[Setup]:
    p = {**DEFAULTS, **(p or {})}
    if combo == "CONTROL":
        return _control(feat, windows, p, seed)
    use_s, use_r, use_f = "S" in combo, "R" in combo, "F" in combo
    use_o, ob_entry = "O" in combo, combo.endswith("@OB")
    if use_f and not (use_s or use_r):
        return _fvg_only(feat, inst, windows, p)

    h, l, o, c, a = feat.h, feat.l, feat.o, feat.c, feat.atr
    buf = p["buffer_ticks"] * inst.tick
    L = int(p["pivot_len"])
    ph, pl = pivots(h, l, L)
    ph_at = {k + L: k for k in ph}
    pl_at = {k + L: k for k in pl}
    highs: list[list] = []
    lows: list[list] = []
    armed = {1: None, -1: None}
    out: list[Setup] = []

    for i in range(2, feat.n):
        triggers = []  # (side, extreme, label)
        rng = h[i] - l[i]
        if use_s:
            if i in ph_at:
                highs.append([h[ph_at[i]], ph_at[i]])
            if i in pl_at:
                lows.append([l[pl_at[i]], pl_at[i]])
            if feat.mod[i] == hm("09:30"):
                for lvl, fresh in ((feat.pdh[i], feat.pdh[i] > feat.onh[i]), (feat.onh[i], True)):
                    if _ok(lvl) and fresh:
                        highs.append([lvl, i - 1])
                for lvl, fresh in ((feat.pdl[i], feat.pdl[i] < feat.onl[i]), (feat.onl[i], True)):
                    if _ok(lvl) and fresh:
                        lows.append([lvl, i - 1])
            if p["asia_levels"] and feat.mod[i] == hm("20:00"):
                # the RTH session that just closed is resting liquidity for Asia
                if _ok(feat.pdh[i]):
                    highs.append([feat.pdh[i], i - 1])
                if _ok(feat.pdl[i]):
                    lows.append([feat.pdl[i], i - 1])
            highs[:] = [x for x in highs if i - x[1] <= p["max_pool_age"]]
            lows[:] = [x for x in lows if i - x[1] <= p["max_pool_age"]]
            taken_h = [x for x in highs if h[i] > x[0] and x[1] < i]
            if taken_h:
                highs[:] = [x for x in highs if x not in taken_h]
                lvl = max(x[0] for x in taken_h)
                wick_ok = rng > 0 and (h[i] - max(o[i], c[i])) >= p["wick_ratio"] * rng
                if c[i] < lvl and (wick_ok or not use_r):
                    triggers.append((-1, h[i], f"swept {lvl:.2f}"))
            taken_l = [x for x in lows if l[i] < x[0] and x[1] < i]
            if taken_l:
                lows[:] = [x for x in lows if x not in taken_l]
                lvl = min(x[0] for x in taken_l)
                wick_ok = rng > 0 and (min(o[i], c[i]) - l[i]) >= p["wick_ratio"] * rng
                if c[i] > lvl and (wick_ok or not use_r):
                    triggers.append((1, l[i], f"swept {lvl:.2f}"))
        elif use_r and rng > 0 and rng >= p["rej_range_atr"] * a[i - 1]:
            if (h[i] - max(o[i], c[i])) >= p["rej_wick"] * rng:
                triggers.append((-1, h[i], "rejection candle"))
            elif (min(o[i], c[i]) - l[i]) >= p["rej_wick"] * rng:
                triggers.append((1, l[i], "rejection candle"))

        in_win = _in(feat, i, windows)
        for side, extreme, label in triggers:
            if not in_win:
                continue
            if use_f:
                armed[side] = dict(extreme=extreme, bar=i, label=label)
            else:
                stop = extreme - side * buf
                out.append(Setup(i, side, "market", 0.0, stop, rr=p["rr"], expiry=1, note=label))

        if not use_f:
            continue
        for side in (1, -1):
            st = armed[side]
            if st is None or st["bar"] == i:
                continue
            if i - st["bar"] > p["fvg_window"] or not in_win:
                armed[side] = None
                continue
            if (side < 0 and h[i] > st["extreme"]) or (side > 0 and l[i] < st["extreme"]):
                armed[side] = None
                continue
            if i - 2 < st["bar"]:
                continue
            gap = _gap(h, l, i, side)
            if gap is None or gap[1] - gap[0] < p["min_fvg_atr"] * a[i]:
                continue
            bot, top = gap
            entry = inst.round_price((top + bot) / 2)
            invalidate = top if side < 0 else bot
            note = f"{st['label']} -> FVG {bot:.2f}-{top:.2f}"
            if use_o:
                ob = _order_block(o, h, l, c, st["bar"], i, side)
                if ob is None:
                    continue  # no valid order block behind this gap; keep waiting
                ob_lo, ob_hi = ob
                note += f", OB {ob_lo:.2f}-{ob_hi:.2f}"
                if ob_entry:
                    # retrace through the FVG into the order block's near edge
                    entry = inst.round_price(ob_lo if side < 0 else ob_hi)
                    invalidate = ob_hi if side < 0 else ob_lo
            stop = st["extreme"] - side * buf
            out.append(Setup(i, side, "limit", entry, stop, rr=p["rr"], expiry=p["order_expiry"],
                             invalidate=invalidate, note=note))
            armed[side] = None
    return out


def _gap(h, l, i, side):
    if side < 0 and h[i] < l[i - 2]:
        return h[i], l[i - 2]
    if side > 0 and l[i] > h[i - 2]:
        return h[i - 2], l[i]
    return None


def _order_block(o, h, l, c, start, i, side):
    """ICT-style order block for a reversal after a sweep: the LAST candle of
    the opposite colour (up-close candle for a short, down-close for a long)
    between the sweep bar and the first candle of the FVG, provided the
    displacement candle(s) then CLOSE through it (bearish: close below its
    low). Returns (low, high) of that candle or None."""
    for j in range(i - 2, start - 1, -1):
        opposite = c[j] > o[j] if side < 0 else c[j] < o[j]
        if opposite:
            broke = min(c[i - 1], c[i]) < l[j] if side < 0 else max(c[i - 1], c[i]) > h[j]
            return (l[j], h[j]) if broke else None
    return None


def _fvg_only(feat, inst, windows, p):
    h, l, a = feat.h, feat.l, feat.atr
    buf = p["buffer_ticks"] * inst.tick
    out = []
    for i in range(2, feat.n):
        if not _in(feat, i, windows):
            continue
        for side in (1, -1):
            gap = _gap(h, l, i, side)
            if gap is None or gap[1] - gap[0] < p["min_fvg_atr"] * a[i]:
                continue
            bot, top = gap
            entry = inst.round_price((top + bot) / 2)
            ext = min(l[i - 2:i + 1]) if side > 0 else max(h[i - 2:i + 1])
            out.append(Setup(i, side, "limit", entry, ext - side * buf, rr=p["rr"], expiry=p["order_expiry"],
                             invalidate=bot if side > 0 else top, note=f"FVG {bot:.2f}-{top:.2f}"))
    return out


def _control(feat, windows, p, seed):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(20, feat.n):
        if _in(feat, i, windows) and rng.random() < 0.03:
            side = 1 if rng.random() < 0.5 else -1
            out.append(Setup(i, side, "market", 0.0, feat.c[i] - side * feat.atr[i], rr=p["rr"], expiry=1,
                             note="random"))
    return out


# --------------------------------------------------------------------------- #

def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 0.0
    ph = k / n
    d = 1 + z * z / n
    centre = (ph + z * z / (2 * n)) / d
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def boot_ci(r: np.ndarray, runs: int = 2000, seed: int = 3):
    if len(r) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = rng.choice(r, size=(runs, len(r)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def run_study(datasets: dict, cfg: engine.EngineConfig, windows=None, log=print,
              combos: dict | None = None, params: dict | None = None) -> list[dict]:
    """datasets: {(symbol, timeframe): DataFrame}. Returns one row per
    combo × symbol × timeframe × window."""
    windows = windows or WINDOWS
    combos = combos or COMBOS
    rows = []
    for (sym, tf), df in datasets.items():
        inst = get_instrument(sym)
        feat = features.build(df, inst.tick)
        days = len(np.unique(feat.day))
        for wname, win in windows.items():
            for combo in combos:
                trades = engine.run(feat, generate(combo, feat, inst, win, params), inst, cfg)
                r = np.array([t.r for t in trades])
                m = metrics.summarize(trades, mc_runs=200) if trades else {"trades": 0}
                k = int((r > 0).sum())
                wlo, whi = wilson(k, len(r))
                elo, ehi = boot_ci(r)
                row = {
                    "combo": combo, "label": combos[combo], "symbol": sym, "timeframe": tf, "window": wname,
                    "sessions": int(days), "trades": int(len(r)),
                    "win_rate": float(k / len(r)) if len(r) else None, "wr_lo": wlo, "wr_hi": whi,
                    "expectancy_r": float(r.mean()) if len(r) else None,
                    "exp_lo": None if math.isnan(elo) else elo, "exp_hi": None if math.isnan(ehi) else ehi,
                    "profit_factor": m.get("profit_factor"), "payoff_ratio": m.get("payoff_ratio"),
                    "net_pnl": m.get("net_pnl", 0.0), "max_dd": m.get("max_dd", 0.0),
                    "trades_per_week": float(len(r) / max(days, 1) * 5),
                }
                rows.append(row)
                if len(r):
                    log(f"  {sym} {tf:>3s} {wname:8s} {combo:7s} n={len(r):4d}  WR {k/len(r):5.1%} "
                        f"[{wlo:4.0%}-{whi:4.0%}]  exp {r.mean():+.2f}R [{elo:+.2f},{ehi:+.2f}]  net ${m['net_pnl']:>8,.0f}")
    return rows


def pooled(rows: list[dict], combos: dict | None = None) -> list[dict]:
    """Per combination, all symbol/timeframe/window rows added together.
    The rows overlap (same days on 2m/5m/15m), so this is a summary, not
    independent evidence."""
    out = []
    for combo, label in (combos or COMBOS).items():
        sub = [r for r in rows if r["combo"] == combo and r["trades"]]
        n = sum(r["trades"] for r in sub)
        if not n:
            continue
        wins = sum(round(r["win_rate"] * r["trades"]) for r in sub)
        out.append({"combo": combo, "label": label, "trades": n, "win_rate": wins / n,
                    "expectancy_r": sum(r["expectancy_r"] * r["trades"] for r in sub) / n,
                    "net_pnl": sum(r["net_pnl"] for r in sub),
                    "positive_rows": sum(r["expectancy_r"] > 0 for r in sub), "rows": len(sub)})
    return out


def markdown(rows: list[dict], note: str, combos: dict | None = None,
             title: str = "Concepts only: sweep (S), rejection block (R), FVG respected (F)") -> str:
    out = [f"# {title}", "", note, "",
           "Fixed 2R, 2 MNQ / 1 MGC, commissions + 1 tick slippage on stop/market fills. "
           "Brackets are 95 % confidence intervals. Rows where the interval for expectancy stays above 0 are marked ✅. "
           "Max 2 trades per day (your plan), so frequent signals are capped at the first two each day.", "",
           "## Pooled by combination (all markets, timeframes and windows)", "",
           "| Combo | Trades | Win rate | Expectancy | Rows positive |", "|---|---|---|---|---|"]
    for p in pooled(rows, combos):
        out.append(f"| {p['label']} | {p['trades']} | {p['win_rate']:.1%} | {p['expectancy_r']:+.3f}R | "
                   f"{p['positive_rows']}/{p['rows']} |")
    out += ["", "Rows overlap (the same days on 2m, 5m and 15m), so the pooled numbers are a summary, "
            "not independent samples.", ""]
    keys = sorted({(r["symbol"], r["timeframe"], r["window"]) for r in rows},
                  key=lambda k: (k[0], int(''.join(ch for ch in k[1] if ch.isdigit()) or 0), k[2]))
    for sym, tf, w in keys:
        sub = [r for r in rows if (r["symbol"], r["timeframe"], r["window"]) == (sym, tf, w)]
        out += [f"## {sym} · {tf} · {w} ({sub[0]['sessions']} sessions)", "",
                "| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |", "|---|---|---|---|---|---|---|"]
        for r in sub:
            if not r["trades"]:
                out.append(f"| {r['label']} | 0 | – | – | – | – | – |")
                continue
            flag = " ✅" if r["exp_lo"] is not None and r["exp_lo"] > 0 else ""
            out.append(f"| {r['label']}{flag} | {r['trades']} | {r['trades_per_week']:.1f} | "
                       f"{r['win_rate']:.0%} [{r['wr_lo']:.0%}–{r['wr_hi']:.0%}] | "
                       f"{r['expectancy_r']:+.2f}R [{r['exp_lo']:+.2f}, {r['exp_hi']:+.2f}] | "
                       f"{r['profit_factor']:.2f} | {r['net_pnl']:,.0f} |")
        out.append("")
    return "\n".join(out)

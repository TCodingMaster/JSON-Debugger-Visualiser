"""FVG Pro: break of structure + fair value gap continuation, fixed 2R.

The family that held up best in the research engine (positive on MNQ and
MGC across 1, 2, 3, 5 and 15 minutes). Written bar-for-bar like the Pine
strategy in pine/fvg_pro_strategy.pine so the two can be compared trade by
trade.

Rules (long; short mirrors):
  1. Structure: a swing high is confirmed `pivot_len` bars after it prints
     (higher than the `pivot_len` bars before it, >= the ones after).
  2. BOS: a bar CLOSES above the last confirmed swing high (each swing level
     counts once).
  3. FVG: the earliest bullish gap (low[0] > high[2], size >= min_fvg_atr ×
     ATR14) from 3 bars before the BOS up to 3 bars after it.
  4. Entry: limit at the gap's near edge (its top) — or its 50 % with
     entry="ce" — placed on the later of the BOS / gap bar.
  5. Stop: lowest low from 10 bars before the BOS to the gap bar, minus
     `buffer_ticks`. Target: entry + rr × risk (2R).
  6. The order is cancelled after `expiry` bars, if a bar closes below the
     gap (the FVG was not respected), at the flatten time or at the next
     Globex day. Only while flat; a newer setup replaces an older order.
  7. Optional filters: session windows (New York time) and the 1-hour trend
     (slope of a 20-hour EMA).
  8. Max `max_trades` entries per Globex day; flat by `flatten`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine, features, metrics
from .data import get_instrument
from .engine import EngineConfig, Setup
from .features import hm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "fvg_pro"

DEFAULTS = dict(
    pivot_len=3, min_fvg_atr=0.15, entry="edge", rr=2.0, buffer_ticks=2, stop_lookback=10,
    fvg_before=3, fvg_after=3, expiry=20, trend_filter=False,
    # chosen on in-sample data only (most consistent setting: positive on 10/10
    # market × timeframe sets), then checked on untouched out-of-sample data
    windows=(("20:00", "24:00"), ("02:00", "05:00")),
    flatten="15:55", max_trades=2,
)

WINDOW_PRESETS = {
    "all": (("20:00", "24:00"), ("00:00", "15:30")),
    "asia": (("20:00", "24:00"),),
    "london": (("02:00", "05:00"),),
    "ny_am": (("08:30", "11:00"),),
    "asia+london": (("20:00", "24:00"), ("02:00", "05:00")),
}


def _confirmed_swings(h, l, L):
    """Value of the last confirmed swing high/low on each bar (NaN until one)."""
    n = len(h)
    lsh, lsl = np.full(n, np.nan), np.full(n, np.nan)
    ch = cl = np.nan
    for i in range(2 * L, n):
        k = i - L
        if h[k] > h[k - L:k].max() and h[k] >= h[k + 1:i + 1].max():
            ch = h[k]
        if l[k] < l[k - L:k].min() and l[k] <= l[k + 1:i + 1].min():
            cl = l[k]
        lsh[i], lsl[i] = ch, cl
    return lsh, lsl


def trend_sign(feat):
    bph = max(1, 60 // max(1, feat.interval_min))
    e = features.ema(feat.c, 20 * bph)
    s = np.zeros(feat.n)
    s[bph:] = np.sign(e[bph:] - e[:-bph])
    return s


def generate(feat, inst, p: dict | None = None) -> list[Setup]:
    p = {**DEFAULTS, **(p or {})}
    o, h, l, c, a = feat.o, feat.h, feat.l, feat.c, feat.atr
    n = feat.n
    L = int(p["pivot_len"])
    buf = p["buffer_ticks"] * inst.tick
    lsh, lsl = _confirmed_swings(h, l, L)
    trend = trend_sign(feat) if p["trend_filter"] else None
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

    out = []
    waiting = []          # BOS events still looking for a gap: (bos_bar, side)
    last_up = last_dn = None
    for i in range(1, n):
        # BOS events on this bar
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
            for k in range(max(2, i - p["fvg_before"]), i + 1):  # earliest gap first
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
            else:
                stop = h[lo_i:k + 1].max() + buf
                entry = bot if p["entry"] == "edge" else inst.round_price((bot + top) / 2)
                inval = top
            if p.get("stop_mode", "leg") == "fvg":
                # tighter: just beyond the far edge of the gap
                stop = (bot - buf) if side > 0 else (top + buf)
            out.append(Setup(t, side, "limit", entry, stop, rr=p["rr"], expiry=p["expiry"], invalidate=inval,
                             note=f"BOS {'up' if side > 0 else 'down'} + FVG {bot:.2f}-{top:.2f}"))
    return out


def backtest(df, symbol, p: dict | None = None, intrabar="path"):
    p = {**DEFAULTS, **(p or {})}
    inst = get_instrument(symbol)
    feat = features.build(df, inst.tick)
    setups = generate(feat, inst, p)
    cfg = EngineConfig(flatten=p["flatten"], max_trades_per_day=p["max_trades"], intrabar=intrabar)
    return feat, engine.run(feat, setups, inst, cfg)


def split_stats(trades, cut_iso):
    def st(ts):
        r = np.array([t.r for t in ts])
        if not len(r):
            return {"trades": 0, "win_rate": None, "expectancy_r": None, "net_pnl": 0.0}
        return {"trades": int(len(r)), "win_rate": float((r > 0).mean()), "expectancy_r": float(r.mean()),
                "net_pnl": float(sum(t.pnl for t in ts))}
    return st([t for t in trades if t.entry_time < cut_iso]), st([t for t in trades if t.entry_time >= cut_iso])


def cut_time(df, frac=0.6):
    days = (df.index + pd.Timedelta(hours=6)).normalize()
    u = days.unique()
    return df.index[np.argmax(days >= u[int(len(u) * frac)])].isoformat()


def develop(datasets: dict, log=print):
    """Pick settings on the IN-SAMPLE part only (first 60 % of sessions of
    every dataset), using the median in-sample expectancy across ALL
    markets and timeframes (one setting for everything, no per-chart
    cherry-picking). Then report the untouched out-of-sample part."""
    grid = []
    for w in WINDOW_PRESETS:
        for trend in (False, True):
            for entry in ("edge", "ce"):
                for mf in (0.15, 0.30):
                    grid.append({"windows": WINDOW_PRESETS[w], "window_name": w, "trend_filter": trend,
                                 "entry": entry, "min_fvg_atr": mf})
    cuts = {k: cut_time(df) for k, df in datasets.items()}
    feats = {k: features.build(df, get_instrument(k[0]).tick) for k, df in datasets.items()}
    rows = []
    for g in grid:
        p = {**DEFAULTS, **{k: v for k, v in g.items() if k != "window_name"}}
        res = {}
        for (sym, tf), feat in feats.items():
            inst = get_instrument(sym)
            tr = engine.run(feat, generate(feat, inst, p), inst,
                            EngineConfig(flatten=p["flatten"], max_trades_per_day=p["max_trades"], intrabar="path"))
            res[(sym, tf)] = split_stats(tr, cuts[(sym, tf)])
        is_ex = [v[0]["expectancy_r"] for v in res.values() if v[0]["trades"] >= 10]
        rows.append({**g, "is_median_exp": float(np.median(is_ex)) if len(is_ex) >= 6 else -9.0,
                     "is_positive": int(sum(x > 0 for x in is_ex)), "is_sets": len(is_ex), "res": res})
    rows.sort(key=lambda r: -r["is_median_exp"])
    for r in rows[:8]:
        log(f"  IS median {r['is_median_exp']:+.3f}R  positive {r['is_positive']}/{r['is_sets']}  "
            f"{r['window_name']:11s} trend={r['trend_filter']!s:5s} entry={r['entry']:4s} min_fvg={r['min_fvg_atr']}")
    return rows


def _json_default(o):
    if isinstance(o, float) and math.isnan(o):
        return None
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(type(o))


def final_report(datasets: dict, log=print) -> dict:
    """Backtest the locked settings on every dataset, write trades, charts
    and the replay page data."""
    import csv

    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"params": {k: (list(map(list, v)) if k == "windows" else v) for k, v in DEFAULTS.items()},
               "sets": {}}
    replay = {}
    for (sym, tf), df in sorted(datasets.items()):
        feat, trades = backtest(df, sym)
        cut = cut_time(df)
        m = metrics.summarize(trades, mc_runs=1000) if trades else {"trades": 0}
        a, b = split_stats(trades, cut)
        summary["sets"][f"{sym} {tf}"] = {"metrics": m, "in_sample": a, "out_of_sample": b, "cut": cut,
                                          "start": df.index[0].isoformat(), "end": df.index[-1].isoformat()}
        with open(OUT / f"trades_{sym}_{tf}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(engine.Trade.__dataclass_fields__))
            w.writeheader()
            for t in trades:
                w.writerow(t.to_dict())
        if m["trades"]:
            log(f"  {sym} {tf:>3s}: {m['trades']:3d} trades  WR {m['win_rate']:5.1%}  exp {m['expectancy_r']:+.2f}R  "
                f"PF {m['profit_factor']:.2f}  net ${m['net_pnl']:>8,.0f}  maxDD ${m['max_dd']:>6,.0f}  "
                f"| OOS {b['trades']} tr WR {(b['win_rate'] or 0):.0%} exp {(b['expectancy_r'] or 0):+.2f}R")
        if tf in ("2m", "5m"):
            replay[f"{sym} {tf}"] = _replay_payload(df, trades, cut)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=_json_default, allow_nan=False))
    write_page(summary, replay)
    write_charts(datasets, summary)
    return summary


def _wall(ts) -> int:
    """New York wall-clock time as epoch seconds (the chart shows NY time)."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("America/New_York").tz_localize(None)
    return int((t - pd.Timestamp("1970-01-01")).total_seconds())


def _replay_payload(df, trades, cut):
    wall = ((df.index.tz_localize(None) - pd.Timestamp("1970-01-01")).total_seconds()).astype(int)
    ohlc = df[["open", "high", "low", "close"]].round(2).to_numpy()
    return {"bars": [[int(t), *map(float, row)] for t, row in zip(wall, ohlc)], "cut": cut,
            "trades": [{**tr.to_dict(), "entry_ts": _wall(tr.entry_time), "exit_ts": _wall(tr.exit_time)}
                       for tr in trades]}


def write_page(summary, replay, path=None):
    tpl = (Path(__file__).parent / "templates" / "fvg_pro.html").read_text()
    blob = json.dumps({"summary": summary, "replay": replay}, default=_json_default, allow_nan=False)
    blob = blob.replace("</", "<\\/")  # never close the <script> early
    path = path or ROOT / "fvg-pro.html"
    path.write_text(tpl.replace("/*__DATA__*/null", blob))
    return path


def write_charts(datasets, summary):
    """Static PNGs: equity curves for every set + one zoomed example trade."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for key in sorted(summary["sets"]):
        sym, tf = key.split()
        tr = pd.read_csv(OUT / f"trades_{sym}_{tf}.csv")
        if len(tr):
            ax.plot(range(1, len(tr) + 1), tr["pnl"].cumsum(), label=f"{key} ({len(tr)})", lw=1.6)
    ax.axhline(0, color="#888", lw=.8)
    ax.set_title("FVG Pro: equity per market/timeframe (net $, 2 MNQ / 1 MGC, fixed 2R)")
    ax.set_xlabel("trade #"); ax.set_ylabel("$"); ax.legend(ncol=2, fontsize=8); ax.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(OUT / "equity.png", dpi=130); plt.close(fig)

    key = ("MNQ", "5m")
    if key in datasets:
        df = datasets[key]
        tr = pd.read_csv(OUT / "trades_MNQ_5m.csv")
        wins = tr[tr["reason"] == "tp"]
        pick = wins.iloc[-1] if len(wins) else (tr.iloc[-1] if len(tr) else None)
        if pick is not None:
            t0, t1 = pd.Timestamp(pick["entry_time"]), pd.Timestamp(pick["exit_time"])
            w = df[(df.index >= t0 - pd.Timedelta(minutes=120)) & (df.index <= t1 + pd.Timedelta(minutes=60))]
            fig, ax = plt.subplots(figsize=(11, 5.5))
            for x, (ts, r) in enumerate(w.iterrows()):
                col = "#1d7a52" if r.close >= r.open else "#b3361f"
                ax.vlines(x, r.low, r.high, color=col, lw=1)
                ax.add_patch(plt.Rectangle((x - .35, min(r.open, r.close)), .7, max(abs(r.close - r.open), 1e-9), color=col))
            g = [float(v) for v in pick["note"].split("FVG ")[1].split("-")] if "FVG " in pick["note"] else None
            if g:
                ax.axhspan(g[0], g[1], color="#1f6f5c", alpha=.15, label="FVG")
            for y, c, lab in ((pick["entry"], "#1d7a52", "entry"), (pick["stop"], "#b3361f", "stop"), (pick["target"], "#2557c7", "2R target")):
                ax.axhline(y, color=c, lw=1.2, ls="--" if lab == "2R target" else "-", label=f"{lab} {y:.2f}")
            xi = list(w.index)
            for ts, m, c in ((t0, "^" if pick["side"] == "long" else "v", "#1d7a52"), (t1, "o", "#2557c7")):
                if ts in xi:
                    ax.plot(xi.index(ts), pick["entry"] if m != "o" else pick["exit"], m, color=c, ms=10)
            step = max(1, len(w) // 10)
            ax.set_xticks(range(0, len(w), step)); ax.set_xticklabels([ts.strftime("%m-%d %H:%M") for ts in w.index[::step]], rotation=30, fontsize=8)
            ax.set_title(f"Example trade, MNQ 5m: {pick['side']} {t0:%Y-%m-%d %H:%M} ET, {pick['note']}, result {pick['r']:+.2f}R")
            ax.legend(fontsize=8); ax.grid(alpha=.2)
            fig.tight_layout(); fig.savefig(OUT / "example_trade.png", dpi=130); plt.close(fig)



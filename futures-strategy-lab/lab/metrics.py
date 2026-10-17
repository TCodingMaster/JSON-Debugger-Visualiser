"""Performance statistics, in-sample/out-of-sample split and Monte Carlo."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import Trade


def _wr(r):
    return float((r > 0).mean()) if len(r) else 0.0


def _max_dd(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    curve = np.r_[0.0, equity]
    return float((np.maximum.accumulate(curve) - curve).max())


def _streak(r: np.ndarray) -> int:
    best = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return best


def summarize(trades: list[Trade], oos_frac: float = 0.3, mc_runs: int = 2000, seed: int = 1) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    r = np.array([t.r for t in trades])
    pnl = np.array([t.pnl for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    eq = np.cumsum(pnl)
    ratios = pnl[r != 0] / r[r != 0]  # $ risked per trade
    risk_usd = float(np.median(np.abs(ratios))) if len(ratios) else 1.0
    gp, gl = float(pnl[pnl > 0].sum()), float(-pnl[pnl <= 0].sum())
    longs = np.array([t.side == "long" for t in trades])
    cut = int(round(n * (1 - oos_frac)))

    def part(x):
        return {"trades": int(len(x)), "win_rate": _wr(x), "expectancy_r": float(x.mean()) if len(x) else 0.0}

    rng = np.random.default_rng(seed)
    sims = rng.choice(pnl, size=(mc_runs, n), replace=True)
    sim_eq = np.cumsum(sims, axis=1)
    sim_dd = (np.maximum.accumulate(np.c_[np.zeros(mc_runs), sim_eq], axis=1)[:, 1:] - sim_eq).max(axis=1)

    return {
        "trades": n,
        "wins": int((r > 0).sum()),
        "losses": int((r <= 0).sum()),
        "win_rate": _wr(r),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(-losses.mean()) if len(losses) else 0.0,
        "payoff_ratio": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else 0.0,
        "expectancy_r": float(r.mean()),
        "profit_factor": min(gp / gl, 99.0) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "net_pnl": float(pnl.sum()),
        "gross_profit": gp,
        "gross_loss": gl,
        "max_dd": _max_dd(eq),
        "max_dd_r": _max_dd(eq) / risk_usd if risk_usd else 0.0,
        "avg_trade_pnl": float(pnl.mean()),
        "avg_risk_usd": risk_usd,
        "max_consec_losses": _streak(r),
        "long_trades": int(longs.sum()),
        "short_trades": int((~longs).sum()),
        "long_wr": _wr(r[longs]),
        "short_wr": _wr(r[~longs]),
        "avg_bars_in_trade": float(np.mean([t.bars for t in trades])),
        "exit_reasons": {k: int(v) for k, v in pd.Series([t.reason for t in trades]).value_counts().items()},
        "start": trades[0].entry_time,
        "end": trades[-1].exit_time,
        "is": part(r[:cut]),
        "oos": part(r[cut:]),
        "mc": {"dd_p50": float(np.percentile(sim_dd, 50)), "dd_p95": float(np.percentile(sim_dd, 95)),
               "prob_profit": float((sim_eq[:, -1] > 0).mean()), "runs": mc_runs},
    }


def equity_series(trades: list[Trade], max_points: int = 400) -> list:
    if not trades:
        return []
    eq = np.cumsum([t.pnl for t in trades])
    pts = [[t.exit_time, round(float(e), 2)] for t, e in zip(trades, eq)]
    if len(pts) > max_points:
        keep = np.unique(np.linspace(0, len(pts) - 1, max_points).astype(int))
        pts = [pts[k] for k in keep]
    return pts


def r_histogram(trades: list[Trade]) -> dict:
    edges = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    r = np.clip([t.r for t in trades], edges[0], edges[-1] - 1e-9) if trades else []
    counts, _ = np.histogram(r, bins=edges)
    return {"bins": edges, "counts": [int(x) for x in counts]}


def monthly(trades: list[Trade]) -> dict:
    out: dict[str, float] = {}
    for t in trades:
        key = t.exit_time[:7]
        out[key] = round(out.get(key, 0.0) + t.pnl, 2)
    return out

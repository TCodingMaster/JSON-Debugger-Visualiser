"""Easy Score: one 0-100 number (and an A-F grade) per concept.

Components (each 0-100, combined as a weighted average; missing components
are skipped and their weight redistributed, which marks the score provisional):

  backtest     win rate vs. target, expectancy, profit factor, drawdown,
               shrunk toward 0 when the sample is small
  fit          overlap with the user's playbook (sweep / rejection / FVG)
  credibility  source track record (see data/concepts.json)
  ease         how mechanical and simple the rules are to execute
  robustness   out-of-sample holds up, IS vs OOS stability, works on both
               instruments
"""

from __future__ import annotations

import math

WEIGHTS = {"backtest": 40, "fit": 20, "credibility": 15, "ease": 15, "robustness": 10}
GRADES = [(80, "A"), (65, "B"), (50, "C"), (35, "D")]
MIN_TRADES_FULL_CONFIDENCE = 100
PROVISIONAL_CAP = 45.0  # untested ideas can't outrank tested ones on opinion alone
LOSING_CAP = 40.0       # a tested loser can't outrank an untested idea


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def grade(total: float) -> str:
    for cut, g in GRADES:
        if total >= cut:
            return g
    return "F"


def backtest_component(m: dict, goals: dict) -> float | None:
    n = m.get("trades", 0)
    if n < 10:
        return None
    wr = _clamp(m["win_rate"] / goals["target_wr"])                  # 60% WR = full marks
    ex = _clamp(m["expectancy_r"] / 0.5)                              # +0.5R/trade = full marks
    pf = _clamp((m["profit_factor"] - 1.0) / 1.0)                    # PF 2.0 = full marks
    dd = _clamp(1 - m["max_dd_r"] / 20.0)                             # 20R drawdown = zero
    raw = 100 * (0.30 * wr + 0.35 * ex + 0.15 * pf + 0.20 * dd)
    if m["expectancy_r"] <= 0:
        raw = min(raw, 30.0)  # losing systems can't score well on win rate alone
    confidence = math.sqrt(_clamp(n / MIN_TRADES_FULL_CONFIDENCE))
    return round(raw * confidence, 1)


def robustness_component(per_symbol: dict) -> float | None:
    ms = [m for m in per_symbol.values() if m.get("trades", 0) >= 10]
    if not ms:
        return None
    parts = []
    for m in ms:
        is_, oos = m["is"], m["oos"]
        oos_ok = 1.0 if oos["trades"] and oos["expectancy_r"] > 0 else 0.0
        stable = _clamp(1 - abs(is_["win_rate"] - oos["win_rate"]) / 0.15) if oos["trades"] else 0.0
        parts.append(0.6 * oos_ok + 0.4 * stable)
    cross = sum(m["expectancy_r"] > 0 for m in ms) / len(ms)
    return round(100 * (0.7 * sum(parts) / len(parts) + 0.3 * cross), 1)


def score_concept(concept: dict, per_symbol: dict, goals: dict, weights: dict | None = None) -> dict:
    weights = weights or WEIGHTS
    best_sym, best = None, None
    for sym, m in per_symbol.items():
        if m.get("trades", 0) and (best is None or m["expectancy_r"] > best["expectancy_r"]):
            best_sym, best = sym, m

    comps = {
        "backtest": backtest_component(best, goals) if best else None,
        "fit": concept["playbook_fit"] * 10.0,
        "credibility": concept["source"]["credibility_score"] * 10.0,
        "ease": round(60 * (concept["mechanizability"] - 1) / 4 + 40 * (5 - concept["complexity"]) / 4, 1),
        "robustness": robustness_component(per_symbol) if per_symbol else None,
    }
    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(weights[k] for k in avail)
    total = round(sum(weights[k] * v for k, v in avail.items()) / wsum, 1) if wsum else 0.0
    if comps["backtest"] is None:
        total = min(total, PROVISIONAL_CAP)
    elif best["expectancy_r"] <= 0:
        total = min(total, LOSING_CAP)

    checks = {}
    if best:
        checks = {
            "win_rate": {"value": best["win_rate"], "target": goals["target_wr"],
                         "pass": best["win_rate"] >= goals["target_wr"]},
            "avg_rr": {"value": best["payoff_ratio"], "target": goals["target_avg_rr"],
                       "pass": best["payoff_ratio"] >= goals["target_avg_rr"]},
            "planned_rr": {"value": goals["planned_rr"], "target": goals["planned_rr"], "pass": True},
            "expectancy": {"value": best["expectancy_r"], "pass": best["expectancy_r"] > 0},
        }
    return {"components": comps, "total": total, "grade": grade(total),
            "provisional": comps["backtest"] is None, "goal_checks": checks, "best_symbol": best_sym}

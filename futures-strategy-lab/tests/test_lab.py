import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lab import data, discover, engine, features, metrics, report, scoring, strategies  # noqa: E402
from lab.engine import EngineConfig, Setup  # noqa: E402

FREE = data.Instrument("TST", tick=0.25, point_value=1.0, contracts=1, commission=0.0)


def bars(rows, start="2026-03-02 09:30"):
    idx = pd.date_range(start, periods=len(rows), freq="5min", tz=data.NY)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = 100.0
    return df


def run(df, setups, **cfg):
    f = features.build(df, FREE.tick)
    base = dict(slippage_ticks=0, min_risk_ticks=1, max_risk_atr=1e9, max_trades_per_day=99)
    base.update(cfg)
    return engine.run(f, setups, FREE, EngineConfig(**base))


# --------------------------------------------------------------------- engine
def test_limit_long_hits_target():
    df = bars([[100, 101, 99, 100], [100, 100.5, 98, 99], [99, 103, 99, 102.5], [102, 102, 101, 101]])
    t = run(df, [Setup(0, 1, "limit", 99.0, 97.5, rr=2.0)])
    assert len(t) == 1 and t[0].reason == "tp" and t[0].entry == 99.0 and t[0].exit == 102.0
    assert t[0].r == pytest.approx(2.0)


def test_stop_and_target_same_bar_counts_as_loss():
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [100, 103, 98, 100], [100, 100, 100, 100]])
    t = run(df, [Setup(0, 1, "market", 0.0, 99.0, rr=2.0)])
    assert t[0].reason == "sl" and t[0].r == pytest.approx(-1.0)


def test_stop_entry_not_filled_when_stop_trades_first():
    # bar opens near its low: path O -> L (hits stop 98) -> H (would trigger entry 101)
    df = bars([[100, 100, 100, 100], [99, 102, 97.5, 101], [101, 101, 101, 101]])
    t = run(df, [Setup(0, 1, "stop", 101.0, 98.0)])
    assert t == []


def test_invalidation_cancels_pending_limit():
    df = bars([[100, 100, 100, 100], [100, 100.5, 99.5, 99.0], [101, 101, 95, 96], [96, 96, 96, 96]])
    t = run(df, [Setup(0, 1, "limit", 98.0, 94.0, invalidate=99.5)])
    assert t == []  # closed below 99.5 on bar 1 before the limit could fill


def test_flatten_at_session_end():
    df = bars([[100, 100, 100, 100]] * 5, start="2026-03-02 15:40")
    t = run(df, [Setup(0, 1, "market", 0.0, 90.0)])
    assert t[0].reason == "eod"


def test_costs_and_contract_math():
    inst = data.get_instrument("MNQ")
    assert inst.contracts == 2 and inst.point_value == 2.0
    assert data.get_instrument("MGC").contracts == 1 and data.get_instrument("MGC1!").point_value == 10.0
    df = bars([[100, 100, 100, 100], [100, 100, 100, 100], [100, 120, 100, 119], [119, 119, 119, 119]])
    f = features.build(df, inst.tick)
    t = engine.run(f, [Setup(0, 1, "market", 0.0, 90.0)], inst, EngineConfig(slippage_ticks=0, max_risk_atr=1e9))
    # +20 pts × $2 × 2 contracts − 2 sides × $0.62 × 2 contracts
    assert t[0].pnl == pytest.approx(80 - 2.48)


def test_engine_unbiased_on_random_walk():
    """Random entries with a 2R target must win ~1/3 on a fine-grained random walk."""
    rng = np.random.default_rng(11)
    nb, sub = 30000, 20
    path = 20000 + np.cumsum(rng.standard_normal(nb * sub)).reshape(nb, sub)
    o = np.r_[20000, path[:-1, -1]]
    df = pd.DataFrame({"open": o, "high": np.maximum(path.max(1), o), "low": np.minimum(path.min(1), o),
                       "close": path[:, -1], "volume": 1.0},
                      index=pd.date_range("2026-01-05", periods=nb, freq="5min", tz=data.NY))
    f = features.build(df, 0.0001)
    f.day, f.mod = np.zeros(nb, int), np.full(nb, 600)
    inst = data.Instrument("X", 0.0001, 1.0, 1, 0.0)
    setups = [Setup(i, 1 if rng.random() < .5 else -1, "market", 0, 0) for i in range(50, nb - 300, 5)]
    for s in setups:
        s.stop = f.c[s.bar] - s.side * 1.5 * f.atr[s.bar]
    t = engine.run(f, setups, inst, EngineConfig(slippage_ticks=0, max_trades_per_day=10**9,
                                                 min_risk_ticks=0, max_risk_atr=99))
    wr = np.mean([x.r > 0 for x in t])
    assert len(t) > 2000 and 0.30 < wr < 0.37


# ------------------------------------------------------------------ strategies
def test_lsrb_fvg_detects_sweep_rejection_fvg():
    rows = [[100, 101, 99, 100]] * 3
    rows += [[100, 105, 100, 104], [104, 104.5, 103, 103.5], [103.5, 104, 102, 102.5]]  # swing high 105
    rows += [[102.5, 103, 101.5, 102], [102, 103.5, 101.5, 103]]
    rows += [[103, 106, 102.8, 103.2]]       # sweep 105, close back below, long upper wick
    rows += [[103.2, 103.4, 100, 100.2]]     # displacement down
    rows += [[100.2, 101, 98, 98.5]]         # FVG: high 101 < low 102.8 two bars back
    rows += [[98.5, 99, 97, 97.5]] * 3
    df = bars(rows)
    f = features.build(df, FREE.tick)
    setups = strategies.generate("lsrb_fvg", f, FREE, {"min_fvg_atr": 0.0, "use_session_levels": False})
    assert len(setups) == 1
    s = setups[0]
    assert s.side == -1 and s.bar == 10
    assert s.entry == pytest.approx((101 + 102.8) / 2, abs=0.25)
    assert s.stop == pytest.approx(106 + 2 * FREE.tick)
    assert s.invalidate == pytest.approx(102.8)


def test_all_strategies_run_and_no_lookahead():
    df = data.synthetic("MNQ", days=30, seed=3)
    inst = data.get_instrument("MNQ")
    f = features.build(df, inst.tick)
    for sid in strategies.REGISTRY:
        full = strategies.generate(sid, f, inst)
        # Truncating the future must not change past decisions.
        cut = f.n // 2
        f2 = features.build(df.iloc[:cut], inst.tick)
        part = strategies.generate(sid, f2, inst)
        past = [(s.bar, s.side, round(s.entry, 4), round(s.stop, 4)) for s in full if s.bar < cut - 1]
        got = [(s.bar, s.side, round(s.entry, 4), round(s.stop, 4)) for s in part if s.bar < cut - 1]
        assert past == got, sid


def test_features_levels_known_only_after_formed():
    df = data.synthetic("MNQ", days=3, seed=1)
    f = features.build(df, 0.25)
    assert np.isnan(f.or_h[f.mod == 9 * 60 + 40]).all()          # OR not known before 09:45
    assert not np.isnan(f.or_h[f.mod == 10 * 60]).all()
    assert np.isnan(f.onh[f.mod == 9 * 60]).all()                # overnight high known from 09:30


# ------------------------------------------------------------------ data
def test_load_csv_tradingview_unix(tmp_path):
    p = tmp_path / "tv.csv"
    p.write_text("time,open,high,low,close,Volume\n1767623400,1,2,0.5,1.5,10\n1767623700,1.5,2,1,1.8,12\n")
    df = data.load_csv(p)
    assert str(df.index.tz) == data.NY and df.index[0].hour == 9 and df.index[0].minute == 30
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_load_csv_ninjatrader(tmp_path):
    p = tmp_path / "nt.txt"
    p.write_text("20260105 093000;1;2;0.5;1.5;10\n20260105 093500;1.5;2;1;1.8;12\n")
    df = data.load_csv(p)
    assert len(df) == 2 and df.index[1].minute == 35


# ------------------------------------------------------------------ scoring / report
def test_scoring_and_grades():
    assert scoring.grade(81) == "A" and scoring.grade(50) == "C" and scoring.grade(10) == "F"
    c = report.load_concepts()[0]
    s = scoring.score_concept(c, {}, report.GOALS)
    assert s["provisional"] and s["components"]["backtest"] is None and 0 <= s["total"] <= scoring.PROVISIONAL_CAP


def test_report_export_roundtrip(tmp_path):
    df = data.synthetic("MGC", days=20, seed=2)
    res = report.run_all({"MGC": df}, list(strategies.REGISTRY), EngineConfig(), log=lambda *_: None)
    path = report.export(res, "synthetic", "test", out_dir=tmp_path)
    payload = json.loads((tmp_path / "results" / "lab-data.json").read_text())
    assert path.read_text().startswith("// generated")
    assert {c["id"] for c in payload["concepts"]} == set(strategies.REGISTRY)
    assert set(payload["scores"]) == set(strategies.REGISTRY)


def test_concepts_cover_registry():
    ids = {c["id"] for c in report.load_concepts()}
    assert ids == set(strategies.REGISTRY)


def test_discover_screening():
    bad = discover.screen_channel("I make $5k a day, join my VIP discord, 100% win rate, quit your job")
    good = discover.screen_channel("Former prop desk trader, Robbins World Cup finalist, backtest statistics")
    assert bad["verdict"] == "reject" and "income claim" in bad["guru_flags"]
    assert good["credibility_score"] > bad["credibility_score"] and not good["guru_flags"]
    assert set(discover.tag_text("Liquidity sweep into a fair value gap")) >= {"liquidity_sweep", "fvg"}


def test_losing_strategy_capped_below_untested():
    c = report.load_concepts()[1]
    m = {"trades": 200, "win_rate": 0.25, "expectancy_r": -0.3, "profit_factor": 0.5, "max_dd_r": 30,
         "payoff_ratio": 1.8, "is": {"trades": 140, "win_rate": 0.25, "expectancy_r": -0.3},
         "oos": {"trades": 60, "win_rate": 0.25, "expectancy_r": -0.3}}
    s = scoring.score_concept(c, {"MNQ": m}, report.GOALS)
    assert not s["provisional"] and s["total"] <= scoring.LOSING_CAP


def test_components_full_combo_matches_core_playbook():
    from lab import components
    df = data.synthetic("MNQ", days=40, seed=5)
    inst = data.get_instrument("MNQ")
    f = features.build(df, inst.tick)
    win = [("09:30", "11:30")]
    a = components.generate("SRF", f, inst, win)
    b = strategies.generate("lsrb_fvg", f, inst, {"windows": win})
    key = lambda s: (s.bar, s.side, s.entry, s.stop, s.invalidate)  # noqa: E731
    assert [key(s) for s in a] == [key(s) for s in b] and len(a) > 0
    for combo in components.COMBOS:
        components.generate(combo, f, inst, win)  # every combination runs


def test_wilson_interval():
    from lab import components
    lo, hi = components.wilson(6, 10)
    assert 0.3 < lo < 0.6 < hi < 0.9


def test_sweep_order_block_fvg():
    from lab import components
    rows = [[100, 101, 99, 100]] * 3
    rows += [[100, 105, 100, 104], [104, 104.5, 103, 103.5], [103.5, 104, 102, 102.5]]  # swing high 105
    rows += [[102.5, 103, 101.5, 102], [102, 103.5, 101.5, 103]]
    rows += [[103, 106, 102.8, 103.2]]       # sweep 105; up-close candle = order block 102.8-106
    rows += [[103.2, 103.4, 100, 100.2]]     # displacement closes below the OB low
    rows += [[100.2, 101, 98, 98.5]]         # FVG 101-102.8
    rows += [[98.5, 99, 97, 97.5]] * 3
    f = features.build(bars(rows), FREE.tick)
    win = [("09:30", "11:30")]
    p = {"min_fvg_atr": 0.0}
    ce = components.generate("SOF", f, FREE, win, p)
    at_ob = components.generate("SOF@OB", f, FREE, win, p)
    assert len(ce) == 1 and ce[0].entry == pytest.approx(101.9, abs=0.25) and ce[0].side == -1
    assert len(at_ob) == 1 and at_ob[0].entry == pytest.approx(102.75, abs=0.25) and at_ob[0].invalidate == 106
    # no opposite-colour candle broken by the displacement -> no order block -> no trade
    rows[8] = [103.2, 106, 102.8, 103]       # sweep candle closes DOWN: no up-close OB candle after it
    rows[7] = [102, 103.5, 101.5, 101.6]
    f2 = features.build(bars(rows), FREE.tick)
    assert components.generate("SOF", f2, FREE, win, p) == []

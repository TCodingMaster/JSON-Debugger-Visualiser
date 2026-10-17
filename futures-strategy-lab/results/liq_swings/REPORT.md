# Liquidity Swings [LuxAlgo] strategies

Code: `lab/liq_swings.py` (zones re-implemented from the LuxAlgo indicator, CC BY-NC-SA 4.0),
Pine: `pine/liq_swings_retest_strategy.pine`. Data: Yahoo MNQ/MGC 15m + 5m and CL 5m + 15m,
2026-08-06 → 10-15, costs + 1 tick slippage, TradingView-like intrabar path, 1 trade/day, flat 15:55 NY.
IS = first 60 % of sessions, OOS = rest.

Grid: 3 entry modes (sweep of the zone / rejection in the zone / break + retest) × pivot 5, 8, 14, 20 ×
area (wick, full) × min count 0, 2, 5 × EMA slope 0, 50, 200 × 4 sessions × RR 1.5, 2 = 1,728 per market.

Mean OOS expectancy over all configs: sweep and reject modes negative on MNQ (−0.10 / −0.19R);
**break + retest positive on MNQ 15m (+0.37R) and MNQ 5m (+0.15R)**.

## Preset `PRESET_MNQ15`: retest, pivot 5, Full Range, London + NY 02:00–12:00 NY, 2R

| Set | Trades | WR | Exp. R | Net | IS | OOS |
|---|---|---|---|---|---|---|
| MNQ 15m 2R | 43 | 58 % | +0.67 | +$6,790 (PF 2.63, max DD $1,105) | 25 · 60 % · +0.76 | 18 · 56 % · +0.55 |
| MNQ 15m 1.5R | 43 | 65 % | +0.58 | +$5,923 | 25 · 64 % | 18 · 67 % |
| MNQ 5m 2R | 50 | 32 % | −0.07 | | | |
| MGC 15m 2R | 40 | 42 % | +0.19 | | | |
| CL 5m 2R | 49 | 41 % | +0.19 | | | |

Neighbouring settings (min count 2, EMA 50) give 55–57 % at 2R on MNQ 15m — the result is not a
single lucky point. Works on MNQ 15m only. Trade list: `trades_MNQ_15m.csv`. Sample ≈ 50 sessions.

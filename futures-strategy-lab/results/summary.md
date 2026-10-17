# Futures Strategy Lab — results (real data)

Generated 2026-10-15T16:16:56+00:00. Yahoo Finance 5m bars, period 60d (front-month continuous, unadjusted)

Plan: fixed 2R per trade, 2 MNQ or 1 MGC; goals WR ≥ 60 %, avg RR ≥ 1.5.

| # | Concept | Score | Grade | Best | Trades | WR | Payoff | Exp (R) | PF | Net $ | Max DD $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Opening-range breakout failure | 60 | C | MGC | 45 | 44.4% | 1.84 | +0.262 | 1.61 | 1,230 | 503 |
| 2 | Liquidity Sweep + Rejection Block + FVG | 45* | D | MGC | 7 | 42.9% | 1.91 | +0.257 | 1.64 | 204 | 254 |
| 3 | "Oops" — open outside yesterday's range, reclaim | 45* | D | MGC | 6 | 66.7% | 1.44 | +0.646 | 5.92 | 1,029 | 121 |
| 4 | Value-area re-entry (Market Profile 80% rule) | 45* | D | MNQ | 3 | 100.0% | 0.00 | +1.048 | 99.00 | 1,067 | 0 |
| 5 | Turtle Soup (false breakout of a 20-bar extreme) | 40 | D | MNQ | 52 | 25.0% | 1.73 | -0.332 | 0.47 | -3,145 | 3,145 |
| 6 | Session-liquidity sweep & reclaim (Asia / London / overnight) | 40 | D | MGC | 18 | 33.3% | 1.65 | -0.124 | 0.65 | -367 | 470 |
| 7 | VWAP ±2σ band sweep & reclaim | 40 | D | MNQ | 66 | 33.3% | 1.80 | -0.071 | 0.82 | -1,059 | 2,109 |
| 8 | Inventory Retracement Bar (IRB) | 36 | D | MNQ | 23 | 39.1% | 1.78 | +0.091 | 1.00 | 1 | 965 |
| 9 | Al Brooks H2 / L2 second entry | 29 | F | MGC | 75 | 29.3% | 1.77 | -0.195 | 0.70 | -1,228 | 1,696 |

\* provisional: fewer than 10 trades: score built from qualitative components only and capped at 45.

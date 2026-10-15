# Futures Strategy Lab — results (synthetic data)

Generated 2026-10-15T16:04:10+00:00. Synthetic random-walk bars (250 sessions) with injected stop-runs. For checking the pipeline only — these numbers are not evidence.

Plan: fixed 2R per trade, 2 MNQ or 1 MGC; goals WR ≥ 60 %, avg RR ≥ 1.5.

| # | Concept | Score | Grade | Best | Trades | WR | Payoff | Exp (R) | PF | Net $ | Max DD $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Session-liquidity sweep & reclaim (Asia / London / overnight) | 67 | B | MGC | 119 | 41.2% | 1.86 | +0.186 | 1.29 | 1,132 | 809 |
| 2 | Liquidity Sweep + Rejection Block + FVG | 65 | B | MGC | 50 | 48.0% | 1.82 | +0.363 | 1.65 | 1,795 | 642 |
| 3 | Value-area re-entry (Market Profile 80% rule) | 64* | C | MNQ | 9 | 44.4% | 1.98 | +0.326 | 1.10 | 240 | 1,372 |
| 4 | "Oops" — open outside yesterday's range, reclaim | 62 | C | MNQ | 21 | 57.1% | 1.65 | +0.526 | 2.65 | 3,644 | 797 |
| 5 | Turtle Soup (false breakout of a 20-bar extreme) | 55 | C | MNQ | 319 | 32.6% | 1.79 | -0.091 | 0.74 | -11,436 | 11,659 |
| 6 | VWAP ±2σ band sweep & reclaim | 47 | D | MNQ | 405 | 35.6% | 1.86 | +0.019 | 0.96 | -1,742 | 5,276 |
| 7 | Opening-range breakout failure | 46 | D | MNQ | 188 | 26.6% | 1.91 | -0.232 | 0.65 | -10,773 | 11,525 |
| 8 | Inventory Retracement Bar (IRB) | 41 | D | MNQ | 203 | 35.5% | 1.90 | +0.027 | 1.00 | 48 | 3,029 |
| 9 | Al Brooks H2 / L2 second entry | 30 | F | MNQ | 328 | 33.2% | 1.93 | -0.026 | 0.90 | -4,027 | 7,665 |

\* provisional: fewer than 10 trades, score built from qualitative components only.

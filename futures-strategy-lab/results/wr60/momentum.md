# wr60 / momentum — trend & momentum families on MNQ (Dukascopy NQ proxy, 2025-09 .. 2026-10)

Code: `lab/wr60_momentum.py` (`PYTHONPATH=. python -m lab.wr60_momentum grid|refine|check`).
Engine: lab.engine, intrabar="path", flatten 15:55, 1 tick slippage, $0.62/side, 2 MNQ contracts.
Protocol: IS = entry < 2026-04-01 (selection), OOS = entry >= 2026-04-01.
Look-ahead: truncation check OK for all 5 families (signals on df[:k] == full for bars < k-1).

## Configurations tried: 384
* Stage 1 (312): pb (EMA20 pullback in EMA20/50 trend), ibb (inside-bar breakout in trend),
  odpb (first pullback after open drive), orbr (OR breakout + retest limit), lonc (London-direction
  continuation into NY), 15m and 5m, rr 0.75 / 1.0 / 1.5.
* Stage 2 (72): refinement of 15m pb (window, touch tolerance, stop buffer, EMA50 slope length), rr 0.75.

Stage-1 IS-best was lonc 15m rr 0.75 (IS 65.5% / PF 1.34; OOS 60.3% / PF 1.06): fails PF.
Families that did NOT hold OOS: orbr (OOS PF 0.67-0.86), odpb (OOS 44-55% WR), 5m pb (OOS PF ~1.0), ibb (~51% WR).

## Best (stage-2 IS-best): 15m EMA20 pullback, rr 0.75
Params: window 09:45-12:00 NY, trend = close & EMA20 beyond EMA50 and EMA50 rising/falling over 16 bars;
signal = bar touches EMA20 (within 0.3 ATR) and closes back in trend direction with a trend-coloured body;
entry market next bar open; stop = signal bar low/high -/+ 0.1 ATR; target 0.75R; 1 trade/day.

| set | trades | WR | exp R | PF | net $ | max DD $ |
|---|---|---|---|---|---|---|
| IS  | 91  | 69.2% | +0.197 | 1.72 | 5961 | 1340 |
| OOS | 87  | 66.7% | +0.140 | 1.28 | 3203 | 2513 |
| Full year | 178 | 68.0% | +0.169 | 1.47 | 9164 | 2513 |

Monthly R: 2025-09 +0.73, 10 +7.27, 11 +0.86, 12 -0.03, 2026-01 +3.13, 02 +0.81, 03 +5.14, 04 +3.59,
05 -1.11, 06 +2.67, 07 +3.36, 08 +4.00, 09 -0.25, 10 (partial) -0.09 -> 10/14 positive.
Robust to intrabar=conservative (identical) and 2-tick slippage (PF 1.46). Longs PF 1.57, shorts 1.35.

## Caveats (why goal_met = false)
* Real MNQ futures check (2026-08-06 .. 2026-10-15, 33 trades): WR 57.6%, PF 0.95, -$221,
  vs Dukascopy same period 66.7% / PF 1.63. Small sample, but the proxy looks optimistic.
* Stage-2 region was chosen after the stage-1 printout (which showed OOS too) -> mild selection leakage.
* Neighbouring stage-2 configs: OOS WR 56-67%, OOS PF 0.82-1.32 -> WR is stable (~60-67%), PF is fragile.
* WR is high only because target is 0.75R; the edge is ~0.1-0.2R/trade.
Closest robust takeaway: "15m EMA20 pullback in trend, morning only, 0.75R" gives ~60-68% WR with small positive
expectancy across the year on proxy data; needs more real-MNQ validation before trading.

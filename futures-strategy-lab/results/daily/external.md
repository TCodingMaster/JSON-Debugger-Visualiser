# External liquidity sweep -> MSS + displacement -> FVG of that leg (user's model). Result: FAIL

Code: `lab/external_sweep.py`. Run it with `PYTHONPATH=. python -m lab.external_sweep trunc|grid`. The truncation (look-ahead) check passes.

Data: Dukascopy 1m proxies, 2025-09 .. 2026-10, 291 Globex days. IS means entry before 2026-04-01.

Exit: half at 1R, then the stop goes to BE and the runner targets 3R. Time stop 8 bars. Max 1 trade per day, flat at 15:55, 1 tick slippage.

## Rules
External levels (all causal):
- PDH/PDL
- Asia H/L
- London H/L
- overnight H/L
- equal highs/lows at the range edge: 2 pivots within 0.1 ATR that are the extreme of the prior 32 bars

Entry sequence:
1. **Sweep:** the first breach of the level that day.
2. **MSS:** within 12 bars, a close beyond the extreme of the 4 bars before the sweep.
3. **Displacement:** a candle with body >= 0.5 or 1.0 ATR.
4. **Optional filters:**
   - efficiency ratio of the leg >= 0.4 (no chop);
   - ATR expansion.
5. **FVG:** the first FVG of the leg (up to 4 bars after the MSS). Limit order at the edge or at the CE, stop beyond the sweep extreme.

## Grid: 192 configs
- Dimensions: MNQ/MGC × 15m/5m × level set × window (02-11:30, London, NY AM) × displacement × ER × entry.
- **MNQ:** mean WR is 53.5% IS and 49.8% OOS. No config has IS WR >= 60% with OOS holding. Frequency is only 0.03-0.25 trades/day.
- **MGC:** mean WR is 55% IS and 40% OOS.

Best IS config: MGC 5m, 02:00-11:30, levels PD/Asia/London/ON, displacement 1.0, edge entry.

| Run | Trades | WR | PF |
|---|---|---|---|
| IS | 24 | 67% | 3.00 |
| OOS | 17 | 71% | 2.76 |
| conservative fills | | 71% / 71% | |
| 2-tick slippage | | 67% / 71% | |

- The year has only 41 trades, which is 0.14 trades/day.
- **The bar-alignment test fails.** Shifting the 5m bars by 1/2/3/4 minutes gives OOS WR of 56/40/45/47% and OOS PF of 1.93/0.88/1.16/1.10.

The edge depends on where the bars start, so it is not a stable pattern.

## Verdict
The user's model, as written in rules, is close to 50/50 on both markets. It also produces only about 0.1-0.2 trades per day, not 1 per day.

The next step is to calibrate the detector on the user's own verified examples (date, time, side) to see which rule differs from the user's discretionary read.

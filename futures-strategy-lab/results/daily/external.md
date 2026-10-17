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

## 3m follow-up after the user's screenshots (3m charts, NY session, targets of 2.4-3R)
Changes:
- New `rng` level: the range high/low of the previous 40 bars (about 2 h).
- 3m bars, look 15, expiry 20.
- Time stop of 40 bars.
- Up to 2 trades per day (`max_setups`, `max_trades`).

Grid: 192 configs, stored in `external_3m_grid.json`. Mean over all configs:

| Market and exit | IS PF | OOS PF | IS WR | OOS WR |
|---|---|---|---|---|
| MNQ, fixed 2.5R | 0.75 | 0.90 | 33% | 28% |
| MNQ, partial 1R/3R | 1.37 | 0.97 | — | 42% |
| MGC, fixed 2.5R | 1.22 | 1.78 | 38% | 48% |
| MGC, partial | 1.67 | 1.86 | 61% | 56% |

On MNQ, none of the configs holds.

The best MGC config by IS PF:
- 3m, 02:00-15:00
- all levels including `rng`
- displacement 1.5 ATR, `mss_n` 10
- CE entry, partial exit
- 2 trades/day

Results for that config:

| Run | Trades | WR | PF | Other |
|---|---|---|---|---|
| Full year | 107 | 64.5% | 2.62 | +$7.8k (2 MGC), 0.37 trades/day, 12/14 months positive |
| IS | — | 62% | 2.12 | |
| OOS | — | 68% | 3.45 | |
| Conservative fills | — | 69% | 2.93 | |
| Slippage 2 ticks | — | 64% | 2.57 | |
| 1m replay | — | 64.5% | 2.62 | |
| Bars shifted 1 min, full year | — | 54% | 1.19 | IS PF 1.05 |
| Bars shifted 2 min, full year | — | 49% | 1.31 | IS PF 0.95 |

The same rules on MNQ, 2 trades/day: 43% WR, PF 0.71.

Verdict: the MGC 3m model is positive across nearly the whole grid, and OOS is better than IS. The 60%+ WR, however, only appears on the standard bar grid, which is the one TradingView uses. With shifted bars the WR is about 50% and the PF about 1.2-1.3. Treat it as a forward-test candidate, not a proven 60% system. MNQ fails.

## Session windows (user's rule: skip the NY AM open). No guard, MGC/MNQ 3m, 2 trades/day, partial exit
The best result is MGC with the window 02:00-09:30 + 10:00-15:00, i.e. the whole day except the 09:30-10:00 NY open (disp 1.5, CE entry):

| Period | Trades | WR | PF |
|---|---|---|---|
| Full year | 101 | 64.4% | 2.77 |
| IS | — | 60.3% | 1.99 |
| OOS | — | 71.1% | 4.48 |

The full year has 12/14 positive months.

The 02:00-15:00 baseline with the open included: 64.5% WR, PF 2.62.

Only NY 10:00-13:00 or 10:30-13:00, on MGC and MNQ:
- 7-61 trades per year;
- WR 29-47%;
- PF 0.5-0.96.

The edge comes from London/early-NY sweeps, not from midday NY alone.

London + NY 10-13: 81 trades, 56.8% WR, PF 1.99.

MNQ is negative in every window.

The guard grid was stopped at the user's request ("no guard").

# wr60 / meanrev: non-ICT mean reversion on MNQ (1 year Dukascopy NQ proxy)

Code: `lab/wr60_meanrev.py` (`PYTHONPATH=. python -m lab.wr60_meanrev grid` runs the grid, `... check` runs the truncation/no-look-ahead check, which passes for all 4 families).
Protocol: IS = entry < 2026-04-01 (all choices), OOS = entry >= 2026-04-01. Engine: lab.engine, market entry at the next bar open (+1 tick slip), stop-loss slip 1 tick, $0.62/side x 2 MNQ, flatten 15:55, intrabar="path" (the conservative mode gives the same numbers for the best config).

## Families tested (320-config pre-declared grid, 15m and 5m)
- **vwap**: wick beyond VWAP +/- k*sd (k 1.5/2/2.5), close back inside -> fade. Best IS was PF 1.1-1.36 and it fell apart OOS (PF 0.6-1.16).
- **orf**: failed breakout of the 09:30-09:45 OR. IS PF <= 1.5 on 53-64 trades, OOS PF < 1 for most settings.
- **lvl**: PDH/PDL/ONH/ONL rejection (wick through, open and close on the inside, first test per level per day), stop = signal-bar extreme + buf*ATR.
- **rsi**: RSI(2) < 5/10 (> 95/90) + close outside Bollinger(20, k). WR 45-63%, not robust OOS.

## Best by IS score (picked on IS only)
`family=lvl, levels=PDH/PDL+ONH/ONL, 5m bars, window 09:30-15:30 NY, stop = signal-bar extreme + 0.5*ATR(14), target 0.75R fixed, 1 trade/day`

| | trades | WR | exp (R, net) | PF | net $ | max DD $ |
|---|---|---|---|---|---|---|
| IS  | 82 | 68.3% | +0.173 | 1.47 | +2145 | 816 |
| OOS | 66 | 60.6% | +0.045 | 1.33 | +1854 | 1059 |
| Year | 148 | 64.9% | +0.116 | 1.39 | +3999 | 1059 |

Monthly R: 2025-09 +3.79, 10 +0.23, 11 -0.06, 12 +5.22, 2026-01 +3.10, 02 +0.50, 03 +1.38, 04 +0.74, 05 +1.05, 06 +1.42, 07 -0.65, 08 +0.09, 09 -0.15, 10 +0.47 -> **11/14 positive**.
Quarters: Sep-mid Dec 69% PF 1.30; mid Dec-Mar 67% PF 1.59; Apr-mid Jul 64% PF 1.76; **mid Jul-Oct 57% PF 0.94 (fading)**.
Real MNQ 5m (Aug 6 - Oct 15, 21 trades): WR 76%, PF 2.2 (Duka on the same window: 19 trades, 63%, PF 1.22).
Neighbours (same bars): buf 0.1/0.25 and rr 0.5/0.6 also pass (OOS WR 66-74%, PF 1.57-1.97); rr 0.9-1.0 or buf >= 0.75 drop OOS to WR 48-56%.

## Why this is NOT an honest "goal met"
Robustness checks the headline numbers fail:
1. **Same rules on 10m or 15m bars lose money** (15m: year PF 0.87, 10m: PF 0.73).
2. **Shifting the 5m bar boundaries by 1-4 minutes** (same 1m data) keeps WR at 55-60% OOS but **OOS PF goes to 0.81-0.98** for all 4 shifts.
   Averaged over the 5 alignments, no config in the IS top-40 has OOS PF > 1 (best lvl 0.75R: IS WR 64% PF 1.31, OOS WR 58% PF 0.97).
So the ~60% win rate at 0.75R is real and stable, but at 0.75R you need ~58-59% just to break even after costs -> the expectancy is essentially zero; the positive PF at the standard :00 alignment (what TradingView uses) is mostly luck of bar alignment.

## Conclusion
Win rate ~60% is easy to get with mean reversion at 0.5-0.75R, but no mean-reversion family here is *robustly* profitable over the year. The closest result is the lvl 5m 0.75R config above (meets every numeric criterion at the standard bar alignment, but fails the bar-alignment and timeframe robustness tests; last 3 months are flat/negative).
Configurations: 320 grid + 12 neighbour checks (+ ~190 bar-offset robustness runs of the IS top-40).

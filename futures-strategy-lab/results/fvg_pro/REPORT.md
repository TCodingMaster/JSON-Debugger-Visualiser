# FVG Pro: break of structure + FVG, fixed 2R

**Files:** Python strategy in `lab/fvg_pro.py`; TradingView strategy in `pine/fvg_pro_strategy.pine`;
trade replay page in `fvg-pro.html`; trades in `results/fvg_pro/trades_*.csv`.

## Why this concept

The research engine tested about 3,400 ICT variants. One family held up across everything: **break of
structure followed by a fair value gap, entering at the gap's edge**. It was positive on MNQ and MGC on
all five timeframes (1, 2, 3, 5 and 15 minutes). Liquidity sweeps, order blocks and breakers did not hold up.

## Rules (long; shorts mirror)

1. A swing high is confirmed 3 bars after it prints.
2. **BOS:** a candle closes above the last confirmed swing high.
3. **FVG:** the earliest bullish gap of at least 0.15 × ATR(14), from 3 bars before the BOS to 3 bars after it.
4. **Entry:** limit order at the top edge of the gap, valid 20 bars. Cancelled if a candle closes below the gap.
5. **Stop:** 2 ticks below the lowest low of the move. **Target:** 2R.
6. **When:** new setups only during Asia (20:00–24:00) and London (02:00–05:00), New York time.
   Max 2 trades per day, flat by 15:55.
7. **Size:** 2 MNQ or 1 MGC. Costs: commissions plus 1 tick of slippage on stops.

## How the settings were chosen

* 80 variations (session × trend filter × entry × gap size) were scored on the **first 60 % of
  sessions only**.
* The variant with the best average in that period won **58–70 % on MNQ 1m/2m**, then fell to
  **23–39 %** on the later 40 %. That is what curve-fitting looks like, so it was rejected.
* The pick was the **most consistent** variant instead: profitable on 10 of 10 market × timeframe sets in
  the first period. The last 40 % stayed untouched until the rules were locked.

## Results (real Yahoo Finance data, Aug 6 – Oct 15 2026; 1m only from Sep 17)

| | Trades | Win rate | Avg per trade | Net |
|---|---|---|---|---|
| All 10 market × timeframe sets | 481 | 43.5 % | — | +$17,727 |
| Out-of-sample only (never used for picking) | 203 | 40.4 % | +0.16R | |
| Best set: MNQ 15m | 33 | 57.6 % | +0.70R | +$7,221 |
| Worst set: MNQ 3m | 40 | 32.5 % | −0.05R | −$198 |

Nine of ten sets were profitable. The sets overlap (the same days on different timeframes), so
the combined total is a summary and not 481 independent trades.

## Against your goal

**60 % win rate at 2:1: not reached.** On data it hadn't seen, the strategy wins about 40 % at 2:1.
Breakeven at 2:1 is 33.3 %, so 40 % is a real, modest edge of about +0.16R per trade. The 58–70 %
numbers that came up during development came from fitting to noise and disappeared on new data.

## Checks

* The Pine logic was transliterated to Python line by line and produces **identical setups** to the
  Python strategy on real MNQ/MGC 1m and 5m data (199–435 setups each).
* The Pine file passes a Pine syntax parser. It still has to compile in TradingView itself, which
  can't be done from here.
* Look-ahead test: cutting off future bars never changes a past signal.

*Hypothetical results on about 50 sessions. Not financial advice.*

## Update: 1.5R target and the MNQ 15m setup indicator

Same locked rules, target changed from 2R to 1.5R (nothing else re-tuned):

| | Trades | Win rate | Avg per trade | Out-of-sample |
|---|---|---|---|---|
| All 10 market × timeframe sets | 484 | 49.8 % | +0.22R | — |
| **MNQ 15m** | 34 | **67.6 %** (95 % range 51–81 %) | **+0.68R** | 13 trades, 69 % |
| MNQ 2m | 52 | 55.8 % | +0.37R | 64 % |
| MGC 5m | 72 | 52.8 % | +0.30R | 55 % |

On MNQ 15m the sessions matter: Asia 71 % (17 trades), London 60 % (20), NY AM 50 % (16), all
sessions 49 % (69). MNQ 15m was singled out after seeing the results, and 34 trades is a small
sample, so the daily forward test decides whether it holds.

`pine/fvg_pro_setups_indicator.pine` draws these setups on the chart (BOS, FVG box, limit entry,
stop, 1.5R target), plays each one out virtually with a running win-rate table, and sends alerts.
Its fill-bar handling is simpler than the backtester's, so its table is a close guide; the Python lab
and the Pine strategy remain the reference.

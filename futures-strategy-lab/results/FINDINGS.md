# Findings — real MNQ / MGC data (first run)

**Data:** Yahoo Finance 5-minute bars, front-month continuous, 2026-08-06 → 2026-10-15
(50 RTH sessions per instrument). **Plan:** fixed 2R; 2 MNQ or 1 MGC; commissions and
1 tick of slippage on stop/market fills. Full table: `summary.md`; interactive: `../mock.html`.

## Headline

1. **Nothing reaches the 60 % win-rate goal on a meaningful sample.** The best tested
   concept is the opening-range breakout failure on MGC: 45 trades, 44 % WR, +0.26R per
   trade, profit factor 1.6. That's a working edge at 2R (breakeven is 33 %), but the
   95 % range for a 44 % win rate on 45 trades is roughly 30–59 %.
2. **Your playbook (LSRB-FVG) is rare on 5-minute NY-AM rules:** 7–8 trades per instrument
   in 50 days. It's positive on MGC (+0.26R) and negative on MNQ (−0.32R). The sample is too
   small to judge either way.
3. **Turtle Soup, VWAP-band sweeps and Brooks H2/L2 lost money** on both instruments in this window.

## Your playbook under different settings (robustness, not optimization)

| Variant | MNQ n | MNQ WR | MNQ exp | MGC n | MGC WR | MGC exp |
|---|---|---|---|---|---|---|
| Default (NY 09:30–11:30, CE entry, wick ≥ 40 %) | 8 | 38 % | −0.32R | 7 | 43 % | +0.26R |
| Wick ≥ 30 % | 9 | 33 % | −0.40R | 8 | 50 % | +0.47R |
| NY 08:30–12:00 | 13 | 31 % | −0.36R | 14 | 36 % | +0.05R |
| NY + London 03:00–05:00 | 17 | 35 % | −0.17R | 12 | 58 % | +0.72R |
| All day 03:00–15:00 | 57 | 26 % | −0.33R | 41 | 46 % | +0.34R |
| All day, break-even at 1R | 58 | 22 % | −0.16R | 41 | 44 % | +0.44R |

Pattern: **gold is positive in almost every variant, Nasdaq is negative in every variant.**
A setup that holds up across reasonable settings is more trustworthy than one tuned
setting. The defaults were not changed after seeing these numbers, to avoid curve-fitting.

## What to do next

* **Get more history.** 50 days is one market regime. Free Yahoo intraday data stops at 60
  days. A longer export (TradingView, NinjaTrader, Databento, FirstRate Data) through
  `--csv` would give hundreds of trades.
* **Forward-test before risking money.** Re-run `python lab.py backtest --source yf` every
  few weeks: each run adds new out-of-sample days.
* **Test your playbook on MGC across the London and NY sessions.** It's the most promising
  variant here.
* **Replay-journal MNQ by hand.** On Nasdaq the coded rules don't match your results. Logging
  replay trades in mock.html shows whether your discretionary read adds what the code
  misses.

*Hypothetical results on a short sample. Not financial advice.*

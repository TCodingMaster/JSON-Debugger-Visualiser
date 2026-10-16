# Profitable over a full year? — 5 research directions, each independently verified

Data: Dukascopy 1m CFD proxies (Nasdaq, gold, WTI), 2025-09-01 → 2026-10-14; settings chosen on Sep–Mar,
tested on Apr–Oct; costs included; each result re-implemented by a skeptic agent (1m replays, 2-tick slippage).

| Direction | Best | Year | IS / OOS PF | + months | Verifier |
|---|---|---|---|---|---|
| **crossmarket** | FVG Pro Leto rules on MNQ London 02–05 + MGC COMEX 08:20–10:30, 2.5R | 180 tr, 46 % WR, +0.34R, PF 1.80, +$17,708, DD $2,871 | 1.96 / 1.66 | 11/14 | **trustworthy** (all 12 neighbours positive in both halves) |
| regime | Leto + skip after 3 straight losses (shadow equity) | 81–85 tr, PF 1.86, +$10.5k, DD $1.6k | 2.27 / 1.65 | 9–10/14 | trustworthy, but only cuts drawdown, OOS edge unchanged |
| classic | Intraday momentum: 09:30→10:00 move, enter 15:00, exit 15:55 | 149 tr, 51 % WR, +0.22R, PF 1.61, +$8k | 1.72 / 1.51 | 9/14 | trustworthy mechanics; chosen cell is an IS peak, family OOS PF 1.2–1.6 |
| trend | Daily-trend pullback-bar breakout + VWAP, chandelier exit | 178 tr, PF 1.51–1.83 | 1.51 / 1.83 | 13/14 | doubtful: chosen after seeing OOS; strict IS pick failed OOS |
| portfolio | 4 rule sets (gold COMEX, EMA20 pullback, imom, VWAP) | 605 tr, PF 1.46, +$27k | 1.65 / 1.31 | 12/14 | doubtful: selection leakage; OOS at the 1.3 bar |

Recommendation: FVG Pro Leto on MNQ (London) + MGC (COMEX open) at 2.5R — `pine/fvg_pro_year_strategy.pine`
picks the session from the chart symbol. Crude oil was not robust in any scheme.
Per-direction reports: `results/profit/*.md`; code: `lab/prof_*.py`.

## Win-rate filter "don't chase" (added to FVG Pro Leto, default 1.0 ATR)

Skip a setup when the signal close is already more than N × ATR past the FVG entry edge.
MNQ London 2.5R, one year: 102 → 70 trades, WR 41 → 46 %, PF 1.81 → 2.40, net +$13,408 → +$14,307,
max DD $2,846 → $1,431; IS PF 3.28 / OOS 1.92. Improves every RR (2, 2.5, 3R) and every threshold 0.7–1.2
in both halves. MGC COMEX 2.5R: PF 1.75 → 2.13 (39 trades). Real MNQ (~70 days, 2.5R): 11 trades, PF 2.89.
Caveat: the filter was found by the earlier "filters" research on Asia+London; on Leto it was checked, not selected.
Other WR filters: skipping the top 20 % volatility regime (datr_pct ≤ 0.8) also helps (PF 2.91) but leaves 53 trades.

## Losing streaks and large losses (MNQ London 2.5R + don't chase, 2 MNQ, one year)

Longest losing streak: 6. The largest losses ($500–640) are ordinary −1R stops on wide-stop trades, not gaps
or end-of-day exits. Wide-stop trades are profitable on average, so shrinking them costs money:

| Rule | Net | PF | Max DD | Max loss |
|---|---|---|---|---|
| Fixed 2 MNQ (default) | $14,307 | 2.40 | $1,431 | $638 |
| $ risk cap 600 (2→1 contract above) | $13,667 | 2.42 | $1,384 | $576 |
| $ risk cap 400 | $11,120 | 2.29 | $1,384 | $360 |
| 1 MNQ after 2 losses until a win | $11,927 | 2.31 | $1,172 | $638 |
| Risk-based sizing $300/trade (1–4 MNQ) | $8,801 | 2.02 | $1,855 | $299 |
| Pause after 3 losses | $9,962 | 2.05 | $1,551 | $638 |

Both the cap and the half-size rule are optional inputs in the Pine strategy (off by default).

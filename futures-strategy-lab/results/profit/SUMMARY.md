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

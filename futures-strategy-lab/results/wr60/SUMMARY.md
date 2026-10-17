# Can a ~60 % win rate hold for a full year? (MNQ, 1-year walk-forward)

Five independent research agents (exits, filters, mean-reversion, momentum, timeframe scan), each
result reproduced by an independent skeptic agent. Data: Dukascopy Nasdaq-100 1m (MNQ proxy),
2025-09-01 → 2026-10-14; settings chosen on Sep–Mar, tested on Apr–Oct; costs included.

| Direction | Best config | Year WR | IS / OOS WR | Exp. | PF | Net (2 MNQ) | Verifier |
|---|---|---|---|---|---|---|---|
| exits | FVG Pro Leto, ½ at 0.75R → BE → 3R, time stop 8 bars | 62 % | 63 / 60 % | +0.15R | 1.54 | +$3,717 | doubtful: neighbours 50–62 % OOS WR |
| filters | Asia+London, 1R, "don't chase" (≤0.94 ATR past edge) + EMA200 | 65 % | 67 / 62 % | +0.28R | 1.68 | +$8,108 | doubtful: session pick not IS-only, 3,800 rules |
| meanrev | 5m PDH/PDL/ONH/ONL rejection, 0.75R | 65 % | 68 / 61 % | +0.12R | 1.39 | +$3,999 | fragile: shifting 5m bars 1–4 min → OOS PF < 1 |
| momentum | 15m EMA20 pullback in trend, 09:45–12:00, 0.75R | 68 % | 69 / 67 % | +0.17R | 1.47 | +$9,164 | doubtful: real MNQ 70 days 58 %, PF 0.95 |
| tfscan | FVG Pro Leto at 1R | 57 % | 59 / 54 % | +0.12R | 1.30 | +$3,919 | trustworthy |
| baseline | FVG Pro Leto at 2R | 43 % | 43 / 44 % | +0.26R | 1.65 | +$10,460 | — |

Conclusion: ~60 % WR over a year only comes with targets of 0.75–1R, and then the edge per trade
is small (+0.1–0.2R); costs and intrabar assumptions decide whether it is profitable. Every
60 %+ candidate lost some win rate out of sample or on real MNQ. The most robust money-maker
remains FVG Pro Leto at 2R; the partial-exit version is offered as the ~60 % WR option.
Code: `lab/wr60_*.py`, per-direction reports in this folder.

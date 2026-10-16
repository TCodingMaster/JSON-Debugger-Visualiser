# profit / portfolio — 2-4 independent rule sets, combined with fixed contracts

Code: `lab/prof_portfolio.py` (`PYTHONPATH=. python -m lab.prof_portfolio run` = rule 1, `... strict` = rule 2 + robustness + real futures).
Data: Dukascopy 1m (NQ, XAU, WTI proxies), 2025-09-01 .. 2026-10-14. IS = entries < 2026-04-01, OOS = after.
Costs: as in each component's own module (MNQ 2 contracts at $0.62/side, MGC 1 at $0.82/side, 1 tick slippage). Each component keeps its own fixed contracts. The IS-risk scaling rule gave 1x for every component.
No new signal code: setups come from `fvg_pro`, `wr60_momentum` and `prof_classic`, each with its own truncation check.

## Candidate pool (fixed before running; parameters copied from earlier reports, not re-tuned)
| comp | market / rule | IS n / exp / PF(R) | OOS n / exp / PF(R) | +months | eligible rule1 / rule2 |
|---|---|---|---|---|---|
| leto | MNQ 15m FVG Pro London 02-05, min 0.3, RR 2 | 54 / +0.26 / 1.45 | 48 / +0.27 / 1.47 | 10 | yes / yes |
| nyam | MNQ 15m FVG Pro NY AM 08:30-11, same params | 39 / +0.10 / 1.17 | 45 / -0.10 / 0.83 | 6 | yes / no |
| gc5q | MGC 5m FVG Asia+London "Quality", min 0.15, RR 2 | 142 / +0.14 / 1.21 | 118 / +0.19 / 1.32 | 8 | yes / no |
| gccomex | MGC 15m FVG Pro COMEX 08:20-10:30, Leto params | 45 / +0.37 / 1.82 | 33 / +0.07 / 1.19 | 10 | yes / yes |
| clnymex | MCL 15m FVG Pro NYMEX 09-11:30, Leto params | 37 / -0.22 / 0.59 | 17 / -0.16 / 0.67 | 6 | no / no |
| pb | MNQ 15m EMA20 pullback 09:45-12, 0.75R | 91 / +0.20 / 1.65 | 87 / +0.14 / 1.42 | 10 | yes / yes |
| imom | MNQ intraday momentum (09:30-10:00 move, enter 15:00) | 78 / +0.24 / 1.72 | 71 / +0.20 / 1.51 | 9 | yes / yes |
| vwap | MNQ 15m VWAP cross + 1 ATR chandelier | 97 / +0.20 / 1.58 | 103 / +0.10 / 1.26 | 11 | yes / yes |

Subset score: the IS Sharpe of combined weekly R (1R per trade). The highest score wins.
* **Rule 1** (declared first): a component is eligible when IS exp > 0 and IS PF(R) >= 1.1. That gives 7 components and 91 subsets. Winner: nyam+pb+imom+vwap. It has 611 trades, IS PF $ 1.55, **OOS PF $ 1.14 / R 1.26 (fails)**, 10/14 months. The weak NY-AM FVG component (IS PF 1.17 on 39 trades) went negative OOS.
* **Rule 2** (declared after rule 1 failed, which is selection leakage): a component must meet the goal's own bar in IS (PF(R) >= 1.3, >= 40 IS trades). That gives 5 components and 25 subsets (all already among the 91).

Configurations tried: 8 component runs + 91 rule-1 portfolios + 25 rule-2 portfolios (overlapping) = 124 evaluations. Robustness and real-futures re-runs are not counted.

## Selected (rule 2): gccomex + pb + imom + vwap  (MGC COMEX FVG + three MNQ day-session rules)
| set | trades | WR | exp R | PF R | PF $ | net $ | max DD $ |
|---|---|---|---|---|---|---|---|
| IS | 311 | 55.3% | +0.232 | 1.68 | 1.65 | 17,226 | 2,199 |
| OOS | 294 | 53.4% | +0.130 | 1.36 | 1.31 | 9,983 | 3,083 |
| Year | 605 | 54.4% | +0.183 | 1.52 | 1.46 | 27,209 | 3,083 |

Monthly R: 25-09 +1.9, 10 +29.2, 11 +11.3, 12 +5.7, 26-01 +2.8, 02 +11.4, 03 +10.0, 04 +11.1, 05 +4.0, **06 +9.5, 07 +11.8, 08 -2.8**, 09 +8.5, 10 (partial) -3.7. That is **12/14 positive in R** and 11/14 in $ (Jan $-38, May $-194, Oct $-367). Worst month: -3.7R. Max DD 7.1R.
Summer (Jun-Aug) total: +18.5R. Leto alone lost -3.0R in June.

Correlation between the 4 components: daily R between -0.04 and +0.06 (practically independent). Monthly R: pb/vwap +0.41, pb/gccomex +0.39, vwap/gccomex +0.38, imom about 0 against all of them. imom is the real diversifier.
Caveat: pb, vwap and imom all trade MNQ in the day session. pb and vwap can hold MNQ positions at the same time (up to 6 MNQ open together).

Robustness:
* Stop-first intrabar gives an identical result. 2 ticks of slippage: PF $ 1.44, IS 1.63 / OOS 1.29, +$26.4k, 12/14 months.
* Neighbouring portfolios: all 25 rule-2 subsets have IS PF(R) 1.52-1.77 and OOS PF(R) 1.24-1.49. 24/25 have OOS PF(R) >= 1.3 (the exception is gccomex+vwap at 1.24), and all have 9-13/14 positive months. The result does not hinge on the exact subset.
  Examples:
  * leto+pb+imom+vwap: 629 trades, PF $ 1.48 (IS 1.62 / OOS 1.38), +$33.7k, DD $4.6k, 13/14 months, worst -1.2R.
  * pb+imom+vwap: 11/14 months, OOS PF $ 1.31.
  * leto+imom: OOS PF $ 1.59, but worst month -9.4R.
* Real futures (2026-08-27 .. 10-15, 5m bars, about 7 weeks): 81 trades, +0.04R, PF $ 1.05, +$433. The proxy over the same window: 77 trades, PF $ 1.18, +$1,316.
  By component (real): imom PF 1.33, gccomex 1.15, vwap 1.10, pb 0.90 (pb was also below its proxy in the wr60 check). This recent stretch is weak on both data sets. Real data does not contradict the proxy, but it does not confirm it either.

## Honest reading
* On paper the goal is met: PF >= 1.3 in IS (1.65) and OOS (1.31 $, 1.36 R), 12/14 months, 605 trades, DD $3.1k against $27.2k net. It is more consistent than Leto alone: 12 vs 10 months, worst month -3.7R vs -8.1R, about 2.6x the profit at a similar $ DD. PF is lower (1.46 vs 1.65).
* OOS PF $ 1.31 is right at the bar, and 2 ticks of slippage push it to 1.29.
* The selection is not clean:
  * Rule 2 was declared after rule 1's OOS failed.
  * The components themselves came from other searches whose OOS printouts were visible.
  The broad neighbourhood result (almost every IS-qualified mix holds OOS) matters more than the exact pick.
* The diversification works mostly because of timing (London / COMEX open / NY morning / last hour), not because of different markets. Crude adds nothing, and gold adds a small, thin-OOS edge.

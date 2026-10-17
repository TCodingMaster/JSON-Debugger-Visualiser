# profit / classic — non-ICT intraday edges on MNQ (Dukascopy NQ proxy, 2025-09 .. 2026-10)

Code: `lab/prof_classic.py` (`PYTHONPATH=. python -m lab.prof_classic grid|deep|combo|check`).
Simulation on **1-minute bars** (signals on completed 5/15/30m bars aligned to 09:30, entry next 1m open
or resting stop; stop-first inside a minute; 1 tick slippage on entries/stops/time exits; 2 MNQ, $0.62/side;
flat 15:55). Protocol: IS = entry < 2026-04-01 (selection, t-stat of R, >= 40 IS trades), OOS = after.
Truncation check (future bars corrupted after the decision bar): 590/593 identical; the 3 misses are
gap fades whose stop is sized from the fill-bar open (fill price, not a signal input).

## Configurations tried: 399
380 grid (ORB 216, intraday momentum 24, gap fade/go 44, VWAP trend 48, PDH/PDL breakout 48)
+ 17 neighbourhood checks of the winner + 2 portfolios.

| Family | IS-best | IS PF / exp | OOS PF / exp | verdict |
|---|---|---|---|---|
| ORB (OR15, 15m close, opp-side stop, 1R) | IS 131 tr | 1.48 / +0.15 | 0.93 / -0.03 | fails OOS (all ORB variants OOS PF < 1) |
| **Intraday momentum** | f30, 15:00, stop 0.15 dATR, thr 0.2 | **1.72 / +0.24** | **1.51 / +0.20** | **passes** |
| Gap-and-go (gap > 0.2 dATR, 15m bar confirms, 2R) | 46 tr | 1.50 / +0.26 | 0.98 / -0.01 | fails; gap fades ~0 |
| VWAP cross 15m + chandelier 1 ATR | 97 tr | 1.58 / +0.20 | 1.26 / +0.10 | borderline (11/14 months) |
| PDH/PDL break 5m, 2 ATR stop, 3R | 45 tr | 1.77 / +0.36 | 0.90 / -0.06 | fails OOS |

## Best: intraday momentum ("first half-hour predicts the last hour")
Rule: r = 09:30 open -> 10:00 price (close of the 09:59 bar). If |r| >= 0.2 x daily ATR (mean of prior 14 RTH
ranges), at 15:00:00 enter market in the sign of r; stop = entry -/+ 0.15 x daily ATR; exit 15:55. Max 1/day.

| set | trades | WR | exp R | PF | net $ | max DD $ |
|---|---|---|---|---|---|---|
| IS | 78 | 52.6% | +0.236 | 1.72 | 4,444 | 1,289 |
| OOS | 71 | 49.3% | +0.197 | 1.51 | 3,522 | 841 |
| Year | 149 | 51.0% | +0.218 | 1.61 | 7,966 | 1,289 |

Monthly R: 2025-09 -2.99, 10 +5.33, 11 +6.29, 12 +4.87, 2026-01 -6.32, 02 +7.84, 03 +3.39, 04 -2.18,
05 +4.31, **06 +4.94, 07 +6.58, 08 -1.35**, 09 +3.16, 10 (partial) -1.45 -> 9/14 positive.

Robustness: 2 ticks slippage PF 1.58; longs PF 1.41 / shorts 1.84 (both halves > 1.3); no target, so
intrabar ordering is irrelevant (5m replay identical). Threshold 0.15-0.4: PF 1.30-2.35 in both IS and OOS;
stop 0.1-0.25 dATR: PF 1.21-2.09 (all >1.2 both halves); exit 15:45: PF 1.65. **Weak spot: entry time** —
14:30 / 14:45 / 15:15 / 15:30 entries give PF 1.14-1.56 (all positive, but 15:00 is the peak).
Real MNQ futures (2026-08-18..10-14, 23 trades): PF 1.09, +$223 vs Dukascopy same window PF 1.24, +$452;
22/23 trades identical in direction and nearly identical R (one stop hit only on real data).

## Portfolios (each component selected without OOS)
| portfolio | trades | PF | IS PF | OOS PF | net $ | maxDD $ | +months | Jun/Jul/Aug R |
|---|---|---|---|---|---|---|---|---|
| imom alone | 149 | 1.61 | 1.72 | 1.51 | 7,966 | 1,289 | 9/14 | +4.9 / +6.6 / -1.4 |
| imom + VWAP cross | 349 | 1.50 | 1.64 | 1.37 | 14,042 | 2,377 | 10/14 | +6.1 / +10.3 / -5.4 |
| **FVG Pro Leto + imom** | 251 | 1.53 | 1.57 | 1.49 | **18,426** | 2,564 | **12/14** | **+1.9 / +8.4 / +4.0** |

(Leto alone in the same R-PF metric: PF 1.46, 10/14, Jun -3.05R.) Leto trades London, imom 15:00-15:55,
so they almost never overlap (2 of 102 Leto trades still open after 15:00). The summer weakness of Leto
(June) is covered by the late-day momentum rule, and Leto covers imom's weak months (Sep-25, Apr-26).

Caveats: one year of proxy data; the momentum edge is a documented anomaly (Gao-Han-Li-Zhou 2018) but
its per-trade sample is small (149); the real-futures window is too short to confirm (positive, smaller).

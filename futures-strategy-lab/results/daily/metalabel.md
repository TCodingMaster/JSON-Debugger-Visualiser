# Daily direction "metalabel": a classifier that picks one FVG Pro setup per day

**Result: FAIL.** The classifier has no skill out of sample (OOS AUC 0.49). Inside IS, under month-grouped
CV, AUC was 0.47 to 0.50 for every model. The OOS win rate is 53 %, about the same as taking every fill
with no model (54 %).

## Setup
- All FVG Pro setups (BOS + FVG, edge entry, min FVG 0.15 ATR, sessions 20:00–24:00 + 00:00–15:30 NY) on MNQ, MGC and
  MCL (Dukascopy proxies) at 15m: 3,227 setups, 1,828 of which fill. That is about 6 fills per day. Base WR is 51.4 %.
- Each setup is labelled on its own with the partial exit (half at 1R, then BE, runner to 3R, time stop 8 bars,
  2 contracts each market). A win means net $ > 0. Labels were checked against `wr60_exits.simulate` and match exactly.
- There are 26 features, all computed at the signal-bar close: FVG/ATR, chase, risk/ATR, body and displacement, BOS leg, distance to
  Globex VWAP / PDH / PDL / prior close, position in the day's range, day move, ATR regime, prior-day range,
  1h-EMA slope, EMA distances, session, market, side, and optional market×session interactions. A truncation check passes.
- Models: numpy L2 logistic regression (λ 1/30/300) and depth-2 gradient boosting (40/100 rounds, lr 0.05,
  min leaf 40). Feature sets: base, base+interactions, small (5 features + market×session).
- Selection used IS only, with month-grouped 7-fold CV purged by ±1 day. Rule: trades/day ≥ 0.85 and PF ≥ 1.3, then highest WR.
  Final model fit on all IS and frozen.
- Daily policy (causal): every setup with p ≥ threshold becomes a resting limit order. The first one to fill while flat is
  taken, max N per Globex day, any market. Without look-ahead you cannot know which setup will be the day's highest-probability one.
- **Configurations tried: 286** (13 model/feature variants × 11 thresholds 0.46–0.66 × max 1 or 2 per day).

## Chosen on IS: GBM 100 rounds, base features, p ≥ 0.50, max 1/day

| | trades | /day | WR | exp R | PF | net $ | max DD |
|---|---|---|---|---|---|---|---|
| IS, honest (month-CV predictions) | 150 | 1.00 | 56 % | +0.05 | 1.39 | +4,010 | 1,374 |
| IS, frozen model (in-sample fit, optimistic) | 151 | 1.01 | 64 % | +0.18 | 2.30 | +12,042 | 1,270 |
| **OOS (untouched)** | 131 | 0.93 | **53 %** | +0.03 | 1.40 | +4,027 | 1,618 |
| Full year (frozen) | 282 | 0.97 | 59 % | +0.11 | 1.84 | +16,069 | 1,618 |
| OOS, conservative intrabar | 131 | 0.93 | 56 % | +0.04 | 1.46 | +4,266 | 1,468 |
| OOS, conservative + 2-tick slippage | 131 | 0.93 | 56 % | +0.03 | 1.41 | +3,838 | 1,500 |
| OOS, walk-forward monthly retrain | 133 | 0.94 | 53 % | +0.01 | 1.24 | +3,025 | 2,229 |
| OOS, no model (first fill per day) | 140 | 0.99 | 54 % | +0.00 | 1.37 | +3,631 | 2,345 |

10 of 14 months are positive (frozen). The full-year 59 % comes from the in-sample fit and is not real.
Neighbouring thresholds give OOS WR 0.46: 52 %, 0.48: 57 %, 0.52: 49 %, 0.54: 49 %. A higher IS WR goes with a lower OOS WR,
which is the usual sign of overfitting.

## Why it fails
Every feature's relation to winning flips between Sep–mid-Dec, mid-Dec–Mar and Apr–Oct. For example, low risk/ATR has 58 % WR in the first part and
51 % in the second; VWAP distance Q4 has 36 % in the first part and 50–57 % later. The same happens with market×session cells. The one stable pattern is
MNQ London + FVG ≥ 0.3 ATR + chase ≤ 1 (55–59 % WR in every part), which is the existing Leto rule, and it gives only about 2 trades per week.
Across all sessions and markets, a 1R-partial FVG setup is close to a coin flip (51 %), and these features cannot
separate winners from losers in a way that holds up over time.

Pass check: trades/day 0.93–0.97 passes. WR ≥ 58 % in both halves fails (OOS 53–56 %). PF ≥ 1.3 passes only on the frozen IS fit;
the honest IS-CV PF is 1.39 and passes, OOS 1.40 passes. 10/14 months passes. Not passed overall. The real-futures check was not run because the result already failed.

Reproduce: `cd futures-strategy-lab && PYTHONPATH=. python -m lab.daily_metalabel` (about 3 min; the setup cache is in the scratchpad `metalabel/`).

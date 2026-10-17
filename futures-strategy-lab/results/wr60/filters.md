# wr60 / filters — FVG Pro + signal-bar filters (MNQ 15m, 1 year)

Code: `lab/wr60_filters.py` (`PYTHONPATH=. python -m lab.wr60_filters` = full search, `... --candidate` = final config).
Data: Dukascopy NQ 1m → 15m, 2025-09-01 → 2026-10-14. IS = entry < 2026-04-01, OOS = after. Costs: 2 MNQ,
$0.62/side, 1 tick slippage, TradingView path intrabar, flat 15:55. Win = trade net $ > 0.
No look-ahead: all features use bars ≤ signal bar; truncation check (setups + features on df[:60%] == full df) passes;
the re-implemented generator is asserted identical to `fvg_pro.generate`.

## Verdict: goal NOT met under the strict protocol

The fully automatic IS-only pipeline (rank single filters + pairs + logistic meta-label on IS, choose the best by IS,
including the choice of session universe) picks filters that **collapse out-of-sample**:

| IS-only pick | RR | IS | OOS |
|---|---|---|---|
| all sessions, `body>=0.85 & vwap_d<=3.18` (best IS stability) | 1.0 | 66 tr, **65 %**, +0.30R, PF 2.14 | 58 tr, **41 %**, −0.20R, PF 0.67 |
| Asia+London, logistic meta-label (best IS win rate) | 1.0 | 52 tr, **71 %**, +0.41R, PF 2.24 | 50 tr, **52 %**, +0.03R, PF 1.32 |
| Asia+London 0.15, `pdr_rel>=0.80 & dow!=Tue` | 1.5 | 66 tr, 56 %, +0.37R | 53 tr, 49 %, +0.21R (13/14 months +) |
| Asia+London 0.15, `pdr_rel>=0.80 & risk_atr<=2.17` | 2.0 | 54 tr, 54 %, +0.60R | 39 tr, 41 %, +0.22R |

Typical pattern: filters that lift the IS win rate by 10-15 points give back most of it OOS. A cross-universe
selection (one rule must lift IS win rate in all 4 universes and both IS halves) also did not survive OOS
(`chg_pc<=4.95 & body>=0.73`: IS 62 % → OOS 50 %). Also: the plain Asia+London 1R base is regime-dependent
(IS 52 % / OOS 61 %), so IS→OOS comparisons are noisy.

## Closest robust result (RR 1.0) — not a clean IS-only choice

Asia (20:00-24:00 NY) + London (02:00-05:00 NY), min FVG 0.3 ATR, edge entry, **1 trade/day, RR 1.0**, take a setup only if
- `dist_entry <= 0.94`: signal-bar close is at most 0.94 ATR beyond the FVG entry edge (do not chase), and
- `ema200 <= 7.1`: close is at most 7.1 ATR beyond the 15m EMA200 in the trade direction (not over-extended).

| | Trades | WR | Exp. | PF | Net | Max DD |
|---|---|---|---|---|---|---|
| IS (Sep–Mar) | 49 | 67.3 % | +0.33R | 1.72 | +$3,280 | $711 |
| OOS (Apr–Oct) | 47 | 61.7 % | +0.23R | 1.66 | +$4,829 | $2,638 |
| Full year | 96 | 64.6 % | +0.28R | 1.68 | +$8,108 | $2,638 |
| Real MNQ (Aug 31–Oct 15) | 10 | 80 % | +0.59R | 5.16 | +$2,082 | $285 |

Monthly R: 25-09 +3.8, 25-10 −1.1, 25-11 +3.9, 25-12 +3.9, 26-01 +0.9, 26-02 +3.9, 26-03 +0.9, 26-04 −2.1,
26-05 −1.0, 26-06 −0.1, 26-07 +6.9, 26-08 +1.0, 26-09 +1.9, 26-10 +4.0 → **10/14 months positive**.

It is the top IS-stability rule *within* that universe (thresholds = IS quantiles), but the universe itself was not
the IS-only winner (the global IS pick was "all sessions", which failed OOS) — so treat it as a promising
hypothesis that needs forward testing, not as proven. Supporting evidence: the `dist_entry` ("don't chase") filter is
stable on neighbouring thresholds (0.7 / 0.94 / 1.2) and helps OOS in both Asia+London universes and on London
(table from the sensitivity run); the EMA200 part adds little. One-parameter version (`dist_entry<=0.94` only):
IS 57 tr 58 % +0.14R, OOS 62 tr 66 % +0.30R. At RR 1.5 the same filter gives ≈ 48-51 % WR, +0.2-0.3R.

Compared with the baseline "FVG Pro Leto" (London only, 2R: 43 % WR, +0.26R, PF 1.65): similar expectancy,
much higher win rate because of RR 1.0, smaller drawdown in IS, equal in OOS.

## Configurations tried
≈ 3,800 rule evaluations: 3,208 in the per-universe search (4 universes × 3 RR × ~180 singles + ~80 pairs + 4 logit
thresholds, with ~290 exact re-simulations), 456 in the cross-universe search, 128 in the sensitivity grid.
With this many tries, a 65 % IS win rate on ~50 trades is expected by chance — hence the scepticism above.

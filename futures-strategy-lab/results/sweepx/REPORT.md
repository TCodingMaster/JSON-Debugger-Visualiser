# sweepX — mechanized test of the written strategy

Source: the user's "sweepX" document (liquidity sweep + FVG/IFVG, HTF bias 1h/4h,
MSS/BOS, displacement, PDH/PDL A+, 3-5 min execution, 1-2R).
Code: `lab/sweepx.py`, Pine: `pine/sweepx_strategy.pine`.
Data: Yahoo, MNQ/MGC 3m (2026-09-18 → 10-15) and 5m (2026-08-06 → 10-15), costs + 1 tick slippage,
TradingView-like intrabar path, max 2 trades/day, flat 15:55 NY. IS = first 60 % of sessions, OOS = rest.

## Doc-literal settings (bias 1h+4h agree, MSS required, displacement 0.5 ATR, 1.5R, all sessions)

| Set | Trades | WR | Exp. R | IS | OOS |
|---|---|---|---|---|---|
| MNQ 3m | 32 | 56 % | +0.37 | 21 · 62 % · +0.50 | 11 · 45 % · +0.11 |
| MNQ 5m | 77 | 43 % | +0.03 | 47 · 38 % · −0.06 | 30 · 50 % · +0.16 |
| MGC 3m | 26 | 38 % | −0.13 | 15 · 40 % · −0.13 | 11 · 36 % · −0.14 |
| MGC 5m | 58 | 41 % | −0.04 | 35 · 43 % · +0.04 | 23 · 39 % · −0.16 |
| Pooled | 193 | 44 % | +0.04 | | |

Variants: 2R → pooled 38 %, +0.07R; break-even at 1R ("trail") → 39 %, +0.04R;
London+NY only → 33 %, −0.22R; MNQ 15m → 41 %, −0.01R.

## Filter search (480 combinations, chosen on IS only)

model × HTF bias × session × displacement × MSS × A+ only. Ranking on IS did not predict OOS:
top-20 % by IS had mean OOS −0.03R (all markets) / +0.02R (MNQ); only about a third of
configurations were positive OOS. No setting is recommended over the doc-literal one.

## Conclusion

Mechanized, sweepX is roughly break-even (≈ 40-55 % WR at 1.5R, ≈ 0R) on this sample —
no edge that survives out-of-sample. Samples are small (3m only 4 weeks). Signals pass a
truncation (look-ahead) test; the Pine port is syntax-checked only (no trade-by-trade parity).

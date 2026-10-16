# wr60 / tfscan — FVG Pro across timeframes, sessions and low reward:risk

Code: `lab/wr60_tfscan.py` (run `PYTHONPATH=. python -m lab.wr60_tfscan`, ~6 min). Raw rows: `results/wr60/tfscan.json`.
Data: Dukascopy NAS100 1m → resampled, 2025-09-01..2026-10-14, MNQ costs (2 contracts, $0.62/side, 1 tick slip on stops), engine intrabar="path", flatten 15:55.
Protocol: IS = entry < 2026-04-01 (all choices), OOS = entry >= 2026-04-01 (untouched).
Rules = `fvg_pro.generate` unchanged; max_trades = number of session windows.
Truncation check of the setup pipeline (incl. the new sweep filter): passed.

## Grid (336 configurations)
- Stage 1 (rr 1.0): TF {10m,15m,20m,30m,1h} × session {london, asia, asia+london, ny_am, london+ny} × min_fvg {0.15,0.3,0.5} × entry {edge,ce} × sweep-first {no,yes} = 300.
- Stage 2: 12 best by IS score × rr {0.75,1.25,1.5} = 36.
- Sweep-first filter: long BOS only if within the last 180 min of the same Globex day a bar traded below an already-known asia_l / london_l / pdl / onl (short mirrors).

## IS-chosen config (rule: IS trades >= 45, IS WR >= 58 %, IS PF >= 1.2, highest IS expectancy)
**15m, London 02:00-05:00 NY, min_fvg 0.3 ATR, entry edge, RR 1.0, no sweep filter, 1 trade/day**

| | trades | WR | exp R | PF | net $ | max DD $ |
|---|---|---|---|---|---|---|
| IS | 54 | 59.3 % | +0.170 | 1.49 | +2,466 | 1,348 |
| OOS | 48 | 54.2 % | +0.073 | 1.18 | +1,453 | 1,958 |
| Year | 102 | 56.9 % | +0.124 | 1.30 | +3,919 | 1,958 |

Monthly R: 09 +3.74, 10 -0.07, 11 +4.89, 12 +0.87, 01 -4.10, 02 +0.87, 03 +2.96, 04 -1.14, 05 +0.93, 06 -2.05, 07 +0.95, 08 +1.94, 09 +0.92, 10 +1.96 → **10/14 months positive**.
Real MNQ 15m (2026-08-06..10-15): 17 trades, 65 % WR, +0.28R, PF 2.70.

Same signal at RR 0.75: year 102 tr, 63.7 % WR (IS 66.7 / OOS 60.4), +0.10R, PF 1.23 (IS 1.47 / OOS 1.08), 8/14 months.

## Runner-ups
- 15m london+ny, mf 0.5, edge, RR 0.75: 139 tr/yr, WR IS 63 % / OOS 61 %, exp IS +0.09 / OOS +0.06R, PF IS 1.27 / OOS 1.05, 11/14 months, maxDD $3,354. Closest to the "60 % WR both halves" wish, but OOS PF only 1.05.
- 15m london, mf 0.5, edge, RR 1.0 (top IS score but only 71 tr/yr): IS 61 % +0.21R PF 1.55, OOS 57 % +0.12R PF 1.29, 8/14 months.
- 30m london+ny, mf 0.3, sweep, RR 1.0: IS 60 % / OOS 62 %, OOS PF 2.31 — but only 72 tr/yr and IS PF 1.17 (not chosen on IS).

## Findings
- Lowering RR to 0.75-1.0 does buy ~60-67 % WR, but expectancy shrinks to +0.05..+0.17R and costs eat a bigger share: OOS PF drops to ~1.05-1.2. Every config with IS WR >= 63 % lost most of its edge OOS (London+NY RR 0.75: IS 66 % / PF 1.43 → OOS 56 % / PF 0.89).
- Timeframe: 15m is the only TF with enough trades and a positive IS edge; 10m is worse (more noise, cost drag); 20m/30m have weak IS; 1h is the most positive in both halves (median exp ~+0.29R) but has only 15-60 trades/year.
- Asia alone and NY AM alone are weak/negative IS; London is the core edge; adding NY doubles trades but dilutes OOS.
- Sweep-first filter: halves trades, slightly higher median OOS expectancy, did not raise WR robustly; best sweep configs fell to OOS PF < 1.
- Goal (58-62 % WR both IS and OOS, PF >= 1.2, >= 80 trades, >= 10/14 months) **not met honestly**. Closest: the IS-chosen 15m London RR 1.0 (57 % year WR, OOS 54 %, OOS PF 1.18, 10/14 months), or the same at RR 0.75 for ~64 % WR at PF 1.23 (OOS PF 1.08).

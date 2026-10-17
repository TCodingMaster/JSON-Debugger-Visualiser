# SMC search: LuxAlgo structure + liquidity tools, fixed 2R

Data: Yahoo Finance MNQ/MGC 1/2/3/5/15m (Aug 6 – Oct 15 2026). 5,760 combinations
(4 liquidity sources × 2 structures × 4 entries × 6 sessions × 3 filters × 10 datasets) plus a random control.

* Variants with ≥ 30 trades: 204 (random: 100)
* Win rate ≥ 65 %: **0**, ≥ 60 %: **0**; highest 53.3% (random's highest 53.3%)
* Confirmed out-of-sample: 10% (random: 17%); FDR survivors: 0

## Pooled per combination (all sessions, no filter, all datasets)

| Liquidity | Structure | Entry | Trades | Win rate | Avg R |
|---|---|---|---|---|---|
| lux_sweeps5 | any | fvg_limit | 335 | 39.1% | +0.082 |
| lux_sweeps5 | choch | fvg_respect | 186 | 39.8% | +0.082 |
| lux_sweeps5 | choch | fvg_limit | 298 | 38.9% | +0.082 |
| random | - | seed1 | 585 | 37.4% | +0.060 |
| lux_swings14 | choch | fvg_respect | 153 | 37.3% | +0.008 |
| lux_sweeps5 | any | fvg_respect | 216 | 37.0% | +0.007 |
| hunter10 | any | fvg_limit | 231 | 36.4% | +0.001 |
| lux_swings14 | choch | fvg_limit | 254 | 35.8% | -0.006 |
| lux_swings14 | any | fvg_limit | 265 | 35.5% | -0.014 |
| random | - | seed2 | 587 | 34.8% | -0.023 |
| lux_sweeps5 | any | fvg_respect_sl20 | 360 | 34.2% | -0.026 |
| hunter10 | choch | fvg_limit | 211 | 35.1% | -0.032 |
| lux_swings14 | any | fvg_respect | 159 | 35.2% | -0.046 |
| lux_sweeps5 | choch | fvg_respect_sl20 | 321 | 33.0% | -0.062 |
| hunter10 | choch | fvg_respect | 128 | 35.2% | -0.063 |
| lux_sweeps5 | choch | ob_limit | 403 | 34.0% | -0.076 |
| lux_swings14 | choch | fvg_respect_sl20 | 291 | 32.6% | -0.082 |
| hunter10 | any | fvg_respect | 143 | 34.3% | -0.088 |
| lux_swings14 | choch | ob_limit | 364 | 33.5% | -0.090 |
| lux_sweeps5 | any | ob_limit | 447 | 33.3% | -0.092 |
| lux_swings14 | any | ob_limit | 376 | 33.2% | -0.095 |
| lux_swings14 | any | fvg_respect_sl20 | 304 | 31.9% | -0.104 |
| hunter10 | any | ob_limit | 338 | 32.8% | -0.107 |
| hunter10 | choch | ob_limit | 313 | 32.6% | -0.122 |
| eqhl | any | fvg_respect_sl20 | 153 | 30.1% | -0.172 |
| eqhl | choch | ob_limit | 204 | 31.4% | -0.185 |
| eqhl | any | ob_limit | 235 | 29.8% | -0.208 |
| eqhl | choch | fvg_limit | 120 | 30.8% | -0.217 |
| eqhl | choch | fvg_respect_sl20 | 136 | 28.7% | -0.218 |
| eqhl | any | fvg_limit | 135 | 30.4% | -0.218 |
| hunter10 | any | fvg_respect_sl20 | 253 | 26.9% | -0.241 |
| hunter10 | choch | fvg_respect_sl20 | 227 | 26.0% | -0.266 |
| eqhl | choch | fvg_respect | 73 | 28.8% | -0.272 |
| eqhl | any | fvg_respect | 84 | 27.4% | -0.300 |

Conclusion: no LuxAlgo/SMC combination reaches 60–70 % at a fixed 2R; the best are ~39 % (+0.08R), the same band as random entries.
The Sweep Hunter source is an approximation of BigBeluga's indicator, not its exact code.

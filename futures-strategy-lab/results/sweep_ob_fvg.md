# Liquidity sweep + order block + FVG respected (NY 10:00-13:00, Asia 20:00-04:00 ET)

Yahoo Finance 2m, 5m, 15m bars, last 60d (front-month continuous).

Fixed 2R, 2 MNQ / 1 MGC, commissions + 1 tick slippage on stop/market fills. Brackets are 95 % confidence intervals. Rows where the interval for expectancy stays above 0 are marked ✅. Max 2 trades per day (your plan), so frequent signals are capped at the first two each day.

## Pooled by combination (all markets, timeframes and windows)

| Combo | Trades | Win rate | Expectancy | Rows positive |
|---|---|---|---|---|
| Liquidity sweep only | 1261 | 30.5% | -0.179R | 1/18 |
| FVG respected only | 1315 | 37.8% | +0.059R | 11/18 |
| Sweep + FVG (no order block) | 534 | 33.5% | -0.048R | 6/18 |
| Sweep + order block + FVG, entry at FVG 50% | 418 | 32.8% | -0.063R | 5/18 |
| Sweep + order block + FVG, entry at order block | 409 | 31.1% | -0.133R | 6/18 |
| Random entries (control) | 1032 | 32.1% | -0.100R | 5/18 |

Rows overlap (the same days on 2m, 5m and 15m), so the pooled numbers are a summary, not independent samples.

## MGC · 2m · asia_20_04 (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 25% [15%–38%] | -0.39R [-0.74, -0.03] | 0.76 | -217 |
| FVG respected only | 52 | 10.0 | 42% [30%–56%] | +0.20R [-0.15, +0.62] | 1.36 | 441 |
| Sweep + FVG (no order block) | 42 | 8.1 | 36% [23%–51%] | +0.01R [-0.42, +0.45] | 1.07 | 89 |
| Sweep + order block + FVG, entry at FVG 50% | 38 | 7.3 | 39% [26%–55%] | +0.13R [-0.34, +0.61] | 1.11 | 136 |
| Sweep + order block + FVG, entry at order block | 36 | 6.9 | 44% [30%–60%] | +0.27R [-0.23, +0.78] | 1.46 | 384 |
| Random entries (control) | 52 | 10.0 | 35% [23%–48%] | -0.04R [-0.44, +0.37] | 0.89 | -128 |

## MGC · 2m · both (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 25% [15%–38%] | -0.39R [-0.74, -0.03] | 0.76 | -217 |
| FVG respected only | 52 | 10.0 | 42% [30%–56%] | +0.20R [-0.15, +0.62] | 1.36 | 441 |
| Sweep + FVG (no order block) | 47 | 9.0 | 34% [22%–48%] | -0.03R [-0.42, +0.41] | 0.91 | -153 |
| Sweep + order block + FVG, entry at FVG 50% | 43 | 8.3 | 37% [24%–52%] | +0.07R [-0.36, +0.49] | 0.97 | -46 |
| Sweep + order block + FVG, entry at order block | 42 | 8.1 | 40% [27%–56%] | +0.15R [-0.28, +0.58] | 1.17 | 194 |
| Random entries (control) | 52 | 10.0 | 27% [17%–40%] | -0.27R [-0.62, +0.09] | 0.70 | -395 |

## MGC · 2m · ny_10_13 (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 27% [17%–40%] | -0.33R [-0.69, +0.08] | 0.65 | -391 |
| FVG respected only | 51 | 9.8 | 33% [22%–47%] | -0.05R [-0.46, +0.36] | 1.01 | 28 |
| Sweep + FVG (no order block) | 23 | 4.4 | 35% [19%–55%] | -0.06R [-0.64, +0.54] | 1.06 | 53 |
| Sweep + order block + FVG, entry at FVG 50% | 14 | 2.7 | 29% [12%–55%] | -0.19R [-0.85, +0.46] | 1.11 | 61 |
| Sweep + order block + FVG, entry at order block | 13 | 2.5 | 31% [13%–58%] | -0.13R [-0.84, +0.58] | 1.27 | 135 |
| Random entries (control) | 47 | 9.0 | 26% [15%–40%] | -0.29R [-0.68, +0.09] | 0.59 | -672 |

## MGC · 5m · asia_20_04 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 100 | 10.0 | 26% [18%–35%] | -0.31R [-0.57, -0.05] | 0.71 | -878 |
| FVG respected only | 100 | 10.0 | 39% [30%–49%] | +0.13R [-0.14, +0.41] | 1.13 | 582 |
| Sweep + FVG (no order block) | 42 | 4.2 | 33% [21%–48%] | -0.03R [-0.46, +0.40] | 0.99 | -25 |
| Sweep + order block + FVG, entry at FVG 50% | 32 | 3.2 | 28% [16%–45%] | -0.19R [-0.66, +0.28] | 0.79 | -366 |
| Sweep + order block + FVG, entry at order block | 34 | 3.4 | 26% [15%–43%] | -0.25R [-0.69, +0.20] | 0.75 | -456 |
| Random entries (control) | 87 | 8.7 | 28% [19%–38%] | -0.23R [-0.50, +0.05] | 0.82 | -582 |

## MGC · 5m · both (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 100 | 10.0 | 26% [18%–35%] | -0.31R [-0.57, -0.05] | 0.71 | -878 |
| FVG respected only | 100 | 10.0 | 39% [30%–49%] | +0.13R [-0.14, +0.41] | 1.13 | 582 |
| Sweep + FVG (no order block) | 53 | 5.3 | 32% [21%–45%] | -0.07R [-0.41, +0.27] | 0.87 | -365 |
| Sweep + order block + FVG, entry at FVG 50% | 37 | 3.7 | 30% [17%–46%] | -0.14R [-0.55, +0.35] | 0.88 | -262 |
| Sweep + order block + FVG, entry at order block | 38 | 3.8 | 29% [17%–45%] | -0.17R [-0.57, +0.30] | 0.90 | -189 |
| Random entries (control) | 99 | 9.9 | 32% [24%–42%] | -0.10R [-0.37, +0.18] | 0.83 | -659 |

## MGC · 5m · ny_10_13 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 84 | 8.4 | 25% [17%–35%] | -0.35R [-0.61, -0.06] | 0.61 | -1,312 |
| FVG respected only | 84 | 8.4 | 38% [28%–49%] | +0.05R [-0.25, +0.35] | 1.02 | 103 |
| Sweep + FVG (no order block) | 15 | 1.5 | 33% [15%–58%] | -0.03R [-0.63, +0.77] | 0.85 | -157 |
| Sweep + order block + FVG, entry at FVG 50% | 6 | 0.6 | 50% [19%–81%] | +0.47R [-0.53, +1.48] | 1.47 | 171 |
| Sweep + order block + FVG, entry at order block | 6 | 0.6 | 50% [19%–81%] | +0.46R [-0.56, +1.48] | 2.62 | 322 |
| Random entries (control) | 56 | 5.6 | 32% [21%–45%] | -0.10R [-0.44, +0.28] | 0.85 | -439 |

## MGC · 15m · asia_20_04 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 81 | 8.1 | 33% [24%–44%] | -0.06R [-0.37, +0.24] | 1.15 | 460 |
| FVG respected only | 84 | 8.4 | 35% [25%–45%] | +0.01R [-0.28, +0.33] | 1.02 | 103 |
| Sweep + FVG (no order block) | 18 | 1.8 | 28% [12%–51%] | -0.19R [-0.85, +0.48] | 0.85 | -256 |
| Sweep + order block + FVG, entry at FVG 50% | 11 | 1.1 | 36% [15%–65%] | +0.07R [-0.75, +0.89] | 1.07 | 66 |
| Sweep + order block + FVG, entry at order block | 12 | 1.2 | 33% [14%–61%] | -0.02R [-0.77, +0.73] | 1.06 | 61 |
| Random entries (control) | 49 | 4.9 | 35% [23%–49%] | +0.01R [-0.42, +0.44] | 1.09 | 234 |

## MGC · 15m · both (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 91 | 9.1 | 32% [23%–42%] | -0.14R [-0.40, +0.13] | 1.05 | 158 |
| FVG respected only | 95 | 9.5 | 34% [25%–44%] | -0.04R [-0.31, +0.25] | 0.94 | -403 |
| Sweep + FVG (no order block) | 23 | 2.3 | 22% [10%–42%] | -0.31R [-0.76, +0.22] | 0.63 | -830 |
| Sweep + order block + FVG, entry at FVG 50% | 15 | 1.5 | 27% [11%–52%] | -0.14R [-0.76, +0.51] | 0.73 | -380 |
| Sweep + order block + FVG, entry at order block | 16 | 1.6 | 31% [14%–56%] | -0.18R [-0.79, +0.48] | 0.81 | -275 |
| Random entries (control) | 57 | 5.7 | 33% [22%–46%] | -0.08R [-0.43, +0.29] | 0.84 | -577 |

## MGC · 15m · ny_10_13 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 32 | 3.2 | 28% [16%–45%] | -0.35R [-0.75, +0.08] | 0.55 | -830 |
| FVG respected only | 38 | 3.8 | 37% [23%–53%] | -0.22R [-0.55, +0.13] | 1.04 | 104 |
| Sweep + FVG (no order block) | 5 | 0.5 | 0% [0%–43%] | -0.76R [-1.03, -0.42] | 0.00 | -574 |
| Sweep + order block + FVG, entry at FVG 50% | 4 | 0.4 | 0% [0%–49%] | -0.70R [-1.03, -0.28] | 0.00 | -446 |
| Sweep + order block + FVG, entry at order block | 4 | 0.4 | 25% [5%–70%] | -0.66R [-1.04, -0.22] | 0.02 | -337 |
| Random entries (control) | 18 | 1.8 | 39% [20%–61%] | +0.02R [-0.53, +0.65] | 0.97 | -30 |

## MNQ · 2m · asia_20_04 (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 33% [22%–46%] | -0.13R [-0.49, +0.28] | 0.74 | -414 |
| FVG respected only | 52 | 10.0 | 33% [22%–46%] | -0.08R [-0.43, +0.33] | 0.74 | -644 |
| Sweep + FVG (no order block) | 42 | 8.1 | 36% [23%–51%] | +0.03R [-0.40, +0.46] | 0.83 | -398 |
| Sweep + order block + FVG, entry at FVG 50% | 40 | 7.7 | 30% [18%–45%] | -0.14R [-0.59, +0.31] | 0.70 | -763 |
| Sweep + order block + FVG, entry at order block | 35 | 6.7 | 26% [14%–42%] | -0.28R [-0.71, +0.15] | 0.54 | -930 |
| Random entries (control) | 52 | 10.0 | 35% [23%–48%] | -0.16R [-0.65, +0.32] | 1.03 | 57 |

## MNQ · 2m · both (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 33% [22%–46%] | -0.13R [-0.49, +0.28] | 0.74 | -414 |
| FVG respected only | 52 | 10.0 | 33% [22%–46%] | -0.08R [-0.43, +0.33] | 0.74 | -644 |
| Sweep + FVG (no order block) | 49 | 9.4 | 37% [25%–51%] | +0.06R [-0.36, +0.43] | 0.89 | -323 |
| Sweep + order block + FVG, entry at FVG 50% | 48 | 9.2 | 31% [20%–45%] | -0.09R [-0.47, +0.29] | 0.78 | -702 |
| Sweep + order block + FVG, entry at order block | 44 | 8.5 | 30% [18%–44%] | -0.16R [-0.54, +0.28] | 0.72 | -671 |
| Random entries (control) | 52 | 10.0 | 27% [17%–40%] | -0.24R [-0.59, +0.14] | 0.67 | -735 |

## MNQ · 2m · ny_10_13 (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 23% [14%–36%] | -0.37R [-0.71, -0.02] | 0.65 | -1,003 |
| FVG respected only | 51 | 9.8 | 39% [27%–53%] | +0.15R [-0.20, +0.56] | 1.13 | 609 |
| Sweep + FVG (no order block) | 20 | 3.8 | 30% [15%–52%] | -0.11R [-0.71, +0.50] | 0.71 | -507 |
| Sweep + order block + FVG, entry at FVG 50% | 16 | 3.1 | 31% [14%–56%] | -0.07R [-0.76, +0.66] | 0.83 | -219 |
| Sweep + order block + FVG, entry at order block | 16 | 3.1 | 38% [18%–61%] | +0.11R [-0.61, +0.84] | 1.17 | 135 |
| Random entries (control) | 47 | 9.0 | 30% [19%–44%] | -0.14R [-0.52, +0.25] | 0.71 | -1,119 |

## MNQ · 5m · asia_20_04 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 97 | 9.7 | 34% [25%–44%] | -0.07R [-0.35, +0.24] | 0.89 | -428 |
| FVG respected only | 99 | 9.9 | 41% [32%–51%] | +0.20R [-0.10, +0.48] | 1.46 | 2,646 |
| Sweep + FVG (no order block) | 51 | 5.1 | 35% [24%–49%] | +0.02R [-0.39, +0.44] | 1.18 | 637 |
| Sweep + order block + FVG, entry at FVG 50% | 39 | 3.9 | 36% [23%–52%] | +0.05R [-0.42, +0.51] | 1.16 | 483 |
| Sweep + order block + FVG, entry at order block | 37 | 3.7 | 22% [11%–37%] | -0.38R [-0.78, +0.06] | 0.51 | -1,409 |
| Random entries (control) | 89 | 8.9 | 30% [22%–41%] | -0.12R [-0.40, +0.17] | 0.84 | -802 |

## MNQ · 5m · both (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 100 | 10.0 | 35% [26%–45%] | -0.04R [-0.31, +0.26] | 0.91 | -344 |
| FVG respected only | 100 | 10.0 | 41% [32%–51%] | +0.19R [-0.11, +0.47] | 1.42 | 2,463 |
| Sweep + FVG (no order block) | 59 | 5.9 | 34% [23%–47%] | -0.07R [-0.41, +0.27] | 0.92 | -375 |
| Sweep + order block + FVG, entry at FVG 50% | 45 | 4.5 | 33% [21%–48%] | -0.07R [-0.44, +0.37] | 0.87 | -550 |
| Sweep + order block + FVG, entry at order block | 44 | 4.4 | 20% [11%–35%] | -0.45R [-0.77, -0.09] | 0.34 | -2,820 |
| Random entries (control) | 96 | 9.6 | 36% [28%–46%] | +0.04R [-0.25, +0.34] | 1.00 | -3 |

## MNQ · 5m · ny_10_13 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 73 | 7.3 | 32% [22%–43%] | -0.17R [-0.46, +0.14] | 0.63 | -2,013 |
| FVG respected only | 85 | 8.5 | 34% [25%–45%] | -0.09R [-0.36, +0.19] | 0.87 | -1,363 |
| Sweep + FVG (no order block) | 11 | 1.1 | 27% [10%–57%] | -0.52R [-1.02, +0.06] | 0.20 | -1,129 |
| Sweep + order block + FVG, entry at FVG 50% | 8 | 0.8 | 25% [7%–59%] | -0.48R [-1.02, +0.26] | 0.15 | -1,052 |
| Sweep + order block + FVG, entry at order block | 10 | 1.0 | 20% [6%–51%] | -0.61R [-1.02, -0.01] | 0.33 | -1,100 |
| Random entries (control) | 57 | 5.7 | 28% [18%–41%] | -0.18R [-0.50, +0.18] | 0.68 | -2,236 |

## MNQ · 15m · asia_20_04 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 76 | 7.6 | 33% [23%–44%] | -0.06R [-0.38, +0.29] | 0.68 | -1,815 |
| FVG respected only | 82 | 8.2 | 39% [29%–50%] | +0.15R [-0.15, +0.48] | 1.38 | 3,100 |
| Sweep + FVG (no order block) | 15 | 1.5 | 40% [20%–64%] | +0.18R [-0.62, +0.98] | 1.29 | 472 |
| Sweep + order block + FVG, entry at FVG 50% | 9 | 0.9 | 33% [12%–65%] | -0.02R [-0.69, +0.98] | 0.73 | -343 |
| Sweep + order block + FVG, entry at order block | 9 | 0.9 | 44% [19%–73%] | +0.31R [-0.69, +1.31] | 1.86 | 653 |
| Random entries (control) | 47 | 4.7 | 34% [22%–48%] | -0.00R [-0.39, +0.45] | 1.05 | 223 |

## MNQ · 15m · both (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 86 | 8.6 | 35% [26%–45%] | -0.01R [-0.29, +0.30] | 0.71 | -1,794 |
| FVG respected only | 95 | 9.5 | 40% [31%–50%] | +0.09R [-0.19, +0.36] | 1.15 | 1,564 |
| Sweep + FVG (no order block) | 17 | 1.7 | 41% [22%–64%] | +0.10R [-0.54, +0.81] | 1.16 | 295 |
| Sweep + order block + FVG, entry at FVG 50% | 11 | 1.1 | 36% [15%–65%] | -0.10R [-0.82, +0.71] | 0.64 | -520 |
| Sweep + order block + FVG, entry at order block | 11 | 1.1 | 45% [21%–72%] | +0.18R [-0.64, +1.00] | 1.61 | 577 |
| Random entries (control) | 57 | 5.7 | 40% [29%–53%] | +0.14R [-0.24, +0.52] | 1.21 | 1,182 |

## MNQ · 15m · ny_10_13 (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 29 | 2.9 | 52% [34%–69%] | +0.50R [-0.02, +1.03] | 1.43 | 812 |
| FVG respected only | 43 | 4.3 | 37% [24%–52%] | -0.26R [-0.54, +0.03] | 0.52 | -3,797 |
| Sweep + FVG (no order block) | 2 | 0.2 | 50% [9%–91%] | -0.47R [-1.02, +0.07] | 0.16 | -177 |
| Sweep + order block + FVG, entry at FVG 50% | 2 | 0.2 | 50% [9%–91%] | -0.47R [-1.02, +0.07] | 0.16 | -177 |
| Sweep + order block + FVG, entry at order block | 2 | 0.2 | 50% [9%–91%] | -0.38R [-1.02, +0.27] | 0.59 | -76 |
| Random entries (control) | 18 | 1.8 | 39% [20%–61%] | +0.05R [-0.47, +0.66] | 1.06 | 134 |

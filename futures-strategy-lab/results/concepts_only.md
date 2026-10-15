# Concepts only: sweep (S), rejection block (R), FVG respected (F)

Yahoo Finance 2m, 5m, 15m bars, last 60d (front-month continuous).

Fixed 2R, 2 MNQ / 1 MGC, commissions + 1 tick slippage on stop/market fills. Brackets are 95 % confidence intervals. Rows where the interval for expectancy stays above 0 are marked ✅. Max 2 trades per day (your plan), so frequent signals are capped at the first two each day.

## Pooled by combination (all markets, timeframes and windows)

| Combo | Trades | Win rate | Expectancy | Rows positive |
|---|---|---|---|---|
| Liquidity sweep only | 802 | 31.4% | -0.162R | 1/12 |
| Rejection block only | 861 | 31.4% | -0.125R | 4/12 |
| FVG respected only | 791 | 37.9% | +0.042R | 8/12 |
| Sweep + rejection | 622 | 28.0% | -0.243R | 1/12 |
| Sweep + FVG | 233 | 36.1% | -0.059R | 6/12 |
| Rejection + FVG | 336 | 37.8% | +0.009R | 7/12 |
| Sweep + rejection + FVG (full) | 167 | 34.1% | -0.129R | 3/12 |
| Random entries (control) | 564 | 31.2% | -0.119R | 3/12 |

Rows overlap (the same days on 2m, 5m and 15m), so the pooled numbers are a summary, not independent samples.

## MGC · 2m · extended (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 35% [23%–48%] | -0.12R [-0.52, +0.30] | 1.29 | 200 |
| Rejection block only | 52 | 10.0 | 29% [18%–42%] | -0.22R [-0.57, +0.14] | 0.62 | -481 |
| FVG respected only | 52 | 10.0 | 42% [30%–56%] | +0.20R [-0.21, +0.61] | 1.70 | 760 |
| Sweep + rejection | 52 | 10.0 | 27% [17%–40%] | -0.31R [-0.67, +0.09] | 0.74 | -237 |
| Sweep + FVG | 39 | 7.5 | 38% [25%–54%] | +0.07R [-0.39, +0.54] | 0.92 | -113 |
| Rejection + FVG | 50 | 9.6 | 34% [22%–48%] | -0.06R [-0.44, +0.34] | 0.94 | -112 |
| Sweep + rejection + FVG (full) | 34 | 6.5 | 38% [24%–55%] | +0.06R [-0.42, +0.55] | 0.88 | -170 |
| Random entries (control) | 52 | 10.0 | 33% [22%–46%] | -0.09R [-0.44, +0.31] | 0.77 | -327 |

## MGC · 2m · ny_am (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 50 | 9.6 | 24% [14%–37%] | -0.41R [-0.77, -0.01] | 0.46 | -703 |
| Rejection block only | 50 | 9.6 | 18% [10%–31%] | -0.52R [-0.83, -0.22] | 0.38 | -1,154 |
| FVG respected only | 51 | 9.8 | 35% [24%–49%] | +0.01R [-0.35, +0.43] | 1.02 | 37 |
| Sweep + rejection | 41 | 7.9 | 15% [7%–28%] | -0.65R [-0.94, -0.28] | 0.29 | -915 |
| Sweep + FVG | 10 | 1.9 | 40% [17%–69%] | +0.04R [-0.74, +0.94] | 1.14 | 63 |
| Rejection + FVG | 14 | 2.7 | 29% [12%–55%] | -0.27R [-0.83, +0.47] | 0.51 | -380 |
| Sweep + rejection + FVG (full) | 5 | 1.0 | 20% [4%–62%] | -0.70R [-1.05, -0.00] | 0.23 | -235 |
| Random entries (control) | 41 | 7.9 | 17% [9%–31%] | -0.54R [-0.84, -0.17] | 0.34 | -1,144 |

## MGC · 5m · extended (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 100 | 10.0 | 31% [23%–41%] | -0.17R [-0.44, +0.10] | 0.71 | -887 |
| Rejection block only | 99 | 9.9 | 28% [20%–38%] | -0.20R [-0.45, +0.07] | 0.65 | -1,462 |
| FVG respected only | 100 | 10.0 | 38% [29%–48%] | +0.08R [-0.19, +0.37] | 1.03 | 114 |
| Sweep + rejection | 95 | 9.5 | 23% [16%–33%] | -0.38R [-0.63, -0.10] | 0.54 | -1,699 |
| Sweep + FVG | 37 | 3.7 | 43% [29%–59%] | +0.26R [-0.21, +0.73] | 1.32 | 663 |
| Rejection + FVG | 51 | 5.1 | 37% [25%–51%] | +0.01R [-0.35, +0.39] | 0.86 | -448 |
| Sweep + rejection + FVG (full) | 26 | 2.6 | 42% [26%–61%] | +0.21R [-0.34, +0.79] | 1.17 | 248 |
| Random entries (control) | 90 | 9.0 | 39% [29%–49%] | +0.09R [-0.19, +0.39] | 1.13 | 472 |

## MGC · 5m · ny_am (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 76 | 7.6 | 25% [17%–36%] | -0.33R [-0.61, -0.03] | 0.69 | -993 |
| Rejection block only | 79 | 7.9 | 35% [26%–46%] | -0.01R [-0.32, +0.32] | 0.99 | -37 |
| FVG respected only | 69 | 6.9 | 38% [27%–49%] | +0.04R [-0.27, +0.37] | 0.96 | -181 |
| Sweep + rejection | 57 | 5.7 | 25% [15%–37%] | -0.34R [-0.68, -0.01] | 0.51 | -1,418 |
| Sweep + FVG | 8 | 0.8 | 50% [22%–78%] | +0.47R [-0.66, +1.61] | 2.66 | 524 |
| Rejection + FVG | 18 | 1.8 | 33% [16%–56%] | +0.01R [-0.64, +0.64] | 1.06 | 73 |
| Sweep + rejection + FVG (full) | 7 | 0.7 | 43% [16%–75%] | +0.26R [-0.61, +1.55] | 1.64 | 204 |
| Random entries (control) | 36 | 3.6 | 42% [27%–58%] | +0.22R [-0.28, +0.72] | 1.32 | 540 |

## MGC · 15m · extended (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 84 | 8.4 | 31% [22%–41%] | -0.19R [-0.46, +0.09] | 0.87 | -544 |
| Rejection block only | 89 | 8.9 | 37% [28%–47%] | +0.06R [-0.24, +0.35] | 0.93 | -392 |
| FVG respected only | 83 | 8.3 | 29% [20%–39%] | -0.22R [-0.47, +0.07] | 0.97 | -211 |
| Sweep + rejection | 56 | 5.6 | 32% [21%–45%] | -0.12R [-0.47, +0.23] | 0.72 | -981 |
| Sweep + FVG | 12 | 1.2 | 42% [19%–68%] | -0.12R [-0.63, +0.51] | 1.48 | 402 |
| Rejection + FVG | 21 | 2.1 | 38% [21%–59%] | +0.07R [-0.39, +0.57] | 1.51 | 564 |
| Sweep + rejection + FVG (full) | 10 | 1.0 | 30% [11%–60%] | -0.22R [-0.80, +0.46] | 1.23 | 196 |
| Random entries (control) | 52 | 5.2 | 23% [14%–36%] | -0.33R [-0.63, +0.00] | 0.57 | -1,687 |

## MGC · 15m · ny_am (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 35 | 3.5 | 31% [19%–48%] | -0.26R [-0.65, +0.17] | 0.91 | -179 |
| Rejection block only | 53 | 5.3 | 30% [20%–44%] | -0.19R [-0.54, +0.18] | 0.82 | -688 |
| FVG respected only | 32 | 3.2 | 31% [18%–49%] | -0.31R [-0.66, +0.07] | 0.83 | -564 |
| Sweep + rejection | 14 | 1.4 | 50% [27%–73%] | +0.21R [-0.50, +0.91] | 1.24 | 207 |
| Sweep + FVG | 5 | 0.5 | 40% [12%–77%] | -0.05R [-0.70, +0.68] | 1.10 | 39 |
| Rejection + FVG | 6 | 0.6 | 50% [19%–81%] | +0.53R [-0.18, +1.28] | 3.30 | 541 |
| Sweep + rejection + FVG (full) | 4 | 0.4 | 25% [5%–70%] | -0.11R [-0.86, +0.81] | 0.96 | -14 |
| Random entries (control) | 13 | 1.3 | 23% [8%–50%] | -0.33R [-1.02, +0.37] | 0.47 | -666 |

## MNQ · 2m · extended (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 33% [22%–46%] | -0.14R [-0.53, +0.22] | 1.03 | 38 |
| Rejection block only | 52 | 10.0 | 31% [20%–44%] | -0.14R [-0.49, +0.22] | 0.89 | -243 |
| FVG respected only | 52 | 10.0 | 38% [26%–52%] | +0.11R [-0.29, +0.51] | 0.95 | -156 |
| Sweep + rejection | 52 | 10.0 | 33% [22%–46%] | -0.10R [-0.50, +0.30] | 1.09 | 141 |
| Sweep + FVG | 45 | 8.7 | 27% [16%–41%] | -0.22R [-0.60, +0.19] | 0.72 | -1,119 |
| Rejection + FVG | 46 | 8.8 | 33% [21%–47%] | -0.05R [-0.45, +0.40] | 0.72 | -1,208 |
| Sweep + rejection + FVG (full) | 28 | 5.4 | 29% [15%–47%] | -0.21R [-0.68, +0.30] | 0.76 | -500 |
| Random entries (control) | 52 | 10.0 | 29% [18%–42%] | -0.18R [-0.53, +0.22] | 0.70 | -921 |

## MNQ · 2m · ny_am (26 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 52 | 10.0 | 44% [32%–58%] | +0.27R [-0.13, +0.68] | 1.30 | 766 |
| Rejection block only | 52 | 10.0 | 19% [11%–32%] | -0.46R [-0.75, -0.11] | 0.46 | -2,650 |
| FVG respected only | 52 | 10.0 | 40% [28%–54%] | +0.19R [-0.21, +0.59] | 1.12 | 629 |
| Sweep + rejection | 39 | 7.5 | 28% [17%–44%] | -0.19R [-0.58, +0.27] | 0.90 | -262 |
| Sweep + FVG | 11 | 2.1 | 36% [15%–65%] | +0.07R [-0.75, +0.89] | 1.36 | 452 |
| Rejection + FVG | 18 | 3.5 | 33% [16%–56%] | +0.03R [-0.53, +0.70] | 1.01 | 10 |
| Sweep + rejection + FVG (full) | 3 | 0.6 | 0% [0%–56%] | -1.03R [-1.03, -1.03] | 0.00 | -386 |
| Random entries (control) | 41 | 7.9 | 29% [18%–44%] | -0.15R [-0.59, +0.29] | 0.83 | -614 |

## MNQ · 5m · extended (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 100 | 10.0 | 33% [25%–43%] | -0.11R [-0.39, +0.18] | 0.90 | -547 |
| Rejection block only | 100 | 10.0 | 36% [27%–46%] | +0.04R [-0.23, +0.32] | 0.99 | -49 |
| FVG respected only | 100 | 10.0 | 36% [27%–46%] | +0.05R [-0.22, +0.35] | 0.90 | -858 |
| Sweep + rejection | 97 | 9.7 | 33% [24%–43%] | -0.08R [-0.35, +0.20] | 0.72 | -2,001 |
| Sweep + FVG | 43 | 4.3 | 26% [15%–40%] | -0.36R [-0.67, -0.01] | 0.47 | -2,936 |
| Rejection + FVG | 60 | 6.0 | 43% [32%–56%] | +0.13R [-0.23, +0.50] | 1.39 | 2,482 |
| Sweep + rejection + FVG (full) | 33 | 3.3 | 27% [15%–44%] | -0.38R [-0.73, +0.01] | 0.49 | -1,947 |
| Random entries (control) | 88 | 8.8 | 27% [19%–37%] | -0.24R [-0.50, +0.05] | 0.75 | -1,942 |

## MNQ · 5m · ny_am (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 71 | 7.1 | 31% [21%–42%] | -0.16R [-0.45, +0.16] | 0.71 | -2,248 |
| Rejection block only | 87 | 8.7 | 22% [14%–32%] | -0.40R [-0.64, -0.14] | 0.46 | -6,687 |
| FVG respected only | 77 | 7.7 | 34% [24%–45%] | -0.06R [-0.37, +0.22] | 0.95 | -570 |
| Sweep + rejection | 44 | 4.4 | 30% [18%–44%] | -0.21R [-0.59, +0.17] | 0.71 | -1,607 |
| Sweep + FVG | 11 | 1.1 | 27% [10%–57%] | -0.51R [-1.01, +0.08] | 0.44 | -1,147 |
| Rejection + FVG | 23 | 2.3 | 52% [33%–71%] | +0.31R [-0.22, +0.83] | 1.98 | 2,752 |
| Sweep + rejection + FVG (full) | 8 | 0.8 | 38% [14%–69%] | -0.32R [-0.87, +0.44] | 0.81 | -219 |
| Random entries (control) | 35 | 3.5 | 49% [33%–64%] | +0.41R [-0.08, +0.90] | 1.81 | 2,366 |

## MNQ · 15m · extended (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 84 | 8.4 | 31% [22%–41%] | -0.15R [-0.43, +0.14] | 0.61 | -3,857 |
| Rejection block only | 93 | 9.3 | 39% [29%–49%] | +0.08R [-0.20, +0.37] | 1.08 | 754 |
| FVG respected only | 86 | 8.6 | 49% [39%–59%] | +0.29R [-0.00, +0.57] | 1.25 | 2,738 |
| Sweep + rejection | 54 | 5.4 | 26% [16%–39%] | -0.28R [-0.61, +0.06] | 0.53 | -3,779 |
| Sweep + FVG | 8 | 0.8 | 62% [31%–86%] | +0.19R [-0.53, +1.02] | 1.51 | 432 |
| Rejection + FVG | 21 | 2.1 | 38% [21%–59%] | -0.19R [-0.64, +0.30] | 0.59 | -1,482 |
| Sweep + rejection + FVG (full) | 6 | 0.6 | 50% [19%–81%] | -0.09R [-0.84, +0.78] | 1.14 | 121 |
| Random entries (control) | 51 | 5.1 | 33% [22%–47%] | -0.11R [-0.44, +0.25] | 0.87 | -853 |

## MNQ · 15m · ny_am (50 sessions)

| Combo | Trades | /week | Win rate [95% CI] | Expectancy [95% CI] | PF | Net $ |
|---|---|---|---|---|---|---|
| Liquidity sweep only | 46 | 4.6 | 30% [19%–45%] | -0.18R [-0.55, +0.20] | 0.46 | -3,986 |
| Rejection block only | 55 | 5.5 | 44% [31%–57%] | +0.19R [-0.17, +0.55] | 1.02 | 182 |
| FVG respected only | 37 | 3.7 | 46% [31%–62%] | -0.04R [-0.38, +0.31] | 0.90 | -586 |
| Sweep + rejection | 21 | 2.1 | 29% [14%–50%] | -0.23R [-0.73, +0.34] | 0.49 | -2,074 |
| Sweep + FVG | 4 | 0.4 | 75% [30%–95%] | -0.04R [-0.74, +0.57] | 0.74 | -127 |
| Rejection + FVG | 8 | 0.8 | 38% [14%–69%] | -0.54R [-0.88, -0.07] | 0.14 | -1,394 |
| Sweep + rejection + FVG (full) | 3 | 0.3 | 67% [21%–94%] | -0.07R [-1.01, +0.74] | 0.67 | -160 |
| Random entries (control) | 13 | 1.3 | 15% [4%–42%] | -0.55R [-1.02, +0.14] | 0.29 | -1,889 |

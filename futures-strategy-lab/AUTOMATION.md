# Automating FVG Pro Leto (paper first)

Chain: TradingView strategy (FVG Pro L) → webhook alert on every **order fill** → TradersPost →
Tradovate **demo** account. The broker mirrors every fill of the TradingView strategy, so the partial
exit (½ at 1R, stop to break-even, runner to 3R, 8-bar time stop, 15:55 flatten) runs exactly as in the
Strategy Tester. The script's own `alert()` webhook option ("Pošiljaj naročila prek alert()") stays OFF.

## Requirements
- TradingView Premium (webhooks need a paid plan) + two-factor authentication enabled.
- Tradovate demo account (free), TradersPost account (trial, then paid).

## Steps
1. TradersPost: connect the Tradovate **demo/paper** account, create a Strategy, copy its webhook URL.
   In the strategy settings allow futures, set quantity "use signal quantity".
2. TradingView: chart MNQ1! 15m, strategy settings exactly as tested
   (min FVG 0.3, Edge, ne lovi cene 1, Delni TP: TP1 1R, preostanek 3R, 8 barov; contracts 2).
3. Create alert → Condition: **FVG Pro L → "Order fills only"**, Expiration: open-ended,
   Notifications: Webhook URL = TradersPost URL, Message:
   ```json
   {"ticker": "{{ticker}}", "action": "{{strategy.order.action}}", "sentiment": "{{strategy.market_position}}", "quantity": "{{strategy.order.contracts}}", "price": "{{close}}", "time": "{{timenow}}"}
   ```
   If TradersPost does not map the continuous symbol, replace `{{ticker}}` with the front contract,
   e.g. `"MNQZ2026"` (roll before expiry).
4. Gold (optional): same on MGC1! 15m (session auto = COMEX 08:20–10:30 NY, contracts 2, commission 0.82).
5. First week: compare every TradingView fill with the TradersPost signal log and the Tradovate demo fills.

## Notes
- Entries are mirrored as market orders the moment TradingView's simulated limit order fills, so expect
  about 1 tick of slippage per side versus the backtest.
- The chart/browser does not need to stay open: TradingView alerts run on its servers.
- Alerts on lower plans expire; recreate them when they do.

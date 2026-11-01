# Candidate strategies (to test on the recordings)

Every strategy is the same four steps. Each number below is a starting guess that the backtest tunes on the first
half of the data, then checks on the second half. Costs in every test: ~1% pump.fun fee each way, Solana network +
priority fee (~0.001 SOL per trade), entry 3 s after the signal at the price then, plus our own price impact on the
curve. Size: fixed 0.2 SOL (~EUR 30) per trade, so impact stays small.

Shared safety checks (the "Rina" step) for all strategies:
- creator (dev) has not sold any of their tokens yet
- no single wallet besides the curve holds more than ~10% (we can rebuild holdings from the trades)
- creator's earlier launches in our data did not rug (serial-rugger list builds up as we record)
- at least N different buyers (not one wallet buying repeatedly)

## A. Early momentum ("before trending", like the screenshots)
- Scan: coins 1-5 minutes old.
- Check: unique buyers per minute rising (e.g. 20 -> 40+), buy volume > 2x sell volume over the last minute,
  market cap still under ~60 SOL, safety checks pass.
- Buy: 0.2 SOL.
- Sell: half at 2x (gets the stake back, like "entry recovered"), trailing stop 30% on the rest; out at once if the dev
  sells or buyers per minute halve; time limit 20 min.

## B. Curve progress / migration run-up
- Scan: coins whose bonding curve is 40-70% full (market cap ~ 150-300 SOL... tuned from data).
- Check: curve filled that far within X minutes (fast), many unique buyers, no big holder, safety checks pass.
- Buy: 0.2 SOL.
- Sell: just before or at migration (curve 95-100%), trailing stop 25%, time limit 30 min.
- Idea: buyers chase coins that are about to "graduate"; question is whether they dump at migration.

## C. First dip after the first pump
- Scan: coins that went 3x+ from launch within 10 minutes.
- Check: pulled back 40-60% from the high, buying still active (unique buyers > sellers in the last 2 min), dev holds.
- Buy: 0.2 SOL when the next 30 s are up again (bounce confirmed).
- Sell: back to the old high or +50%, stop 25% below entry, time limit 15 min.

## D. Baseline (to compare against)
- Buy every launch at second 5, sell after 10 minutes. Shows what "random" earns after costs (expected: badly negative).

## Expected
Most memecoins die within minutes, so most trades of any strategy lose; a strategy only works if the few runners pay
for all the losers after costs. Judge by total SOL / EUR profit on the holdout weeks, not win rate.
If nothing beats costs on the holdout, the answer is "no", and we stop there.

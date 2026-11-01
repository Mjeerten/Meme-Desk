# Results

## Round 1: free pumpdata.fun day, 2026-10-15 (backtest-hf.yml, run 41322701011)
33,072 coins, 3.5 M curve trades in their first hour. Train = first 19,843 coins (by launch time), holdout = last
13,229. 0.2 SOL per trade, fee 1.25%/side, 2 s latency on entry and exit, curve-exact fills.
3,717 rule combinations with 30+ train trades; only 18 (0.5%) made money on train, about what luck alone gives.

| family | best rule on train | train trades / SOL | holdout trades / SOL | holdout per trade | holdout 95% range (SOL) |
|---|---|---|---|---|---|
| dip after first pump | 3x pump, 45-60% pullback, all safety checks, sell after 10 min | 215 / +8.58 | 125 / -2.48 | -9.9% | -8.1 to +4.3 |
| dip (5x pump variant, no creator check) | | 111 / +5.97 | 47 / +1.40 | +14.8% (15% wins) | -6.1 to +13.9 |
| early momentum | 20 new buyers/30 s, buys 3x sells, mcap < 60 SOL, dev holds | 50 / -0.25 | 32 / -0.42 | -6.5% | |
| curve progress | buy at 150 SOL mcap, 50 buyers, all checks, TP 2x / stop 30% | 53 / -1.56 | 22 / -1.14 | -25.8% | |
| copy trading | top 20 training wallets, coin < 1 min old | 7,948 / -76.5 | 5,066 / -15.5 to -32.9 | -1.5 to -3.3% | |
| fast flip | buy at 2-5 s, sell 5-15 s later | 18,271 / -162 | 12,107 / -102 to -121 | -4 to -5% | |
| baseline | buy every coin at 5 s, sell after 10 min | 18,271 / -281 | 12,107 / -254 | -10.5% | |

Conclusion: nothing makes money after costs. Copy trading loses even on the coins its wallets were picked from.
The only family positive on train is "dip after the first pump", and it fails the holdout (best variant -2.5 SOL;
one variant +1.4 SOL on 47 trades with a range that includes big losses: luck, not proof).
Next: the same test on our own recordings (from 2026-11-01) as a second, independent check, with "dip" as the one
candidate to watch. If it fails there too, stop.

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

## Round 1b: copy trading in depth (meme/copytest.py, same day, run on backtest-hf.yml script=copytest)
**Winners do keep winning:** the top 10 wallets on the training coins (10+ coins) made +6,246 SOL on the later
coins, all 10 in profit; top 50: +7,407 SOL, 88% in profit (rank correlation train -> holdout 0.26-0.35).
**But they can't be copied:** 56% of the top 50 are the coins' own creators, median hold 4 seconds, 70% hold under 30 s
(creators, bundlers, same-block snipers). Their edge is being first / being the insider; a copier buys after them,
into their selling.

Copy simulation on the holdout (0.2 SOL, fees, curve fills, sell when the wallet sells or after 30 min):

| wallets followed | delay 0 s | 1 s | 2 s | 5 s |
|---|---|---|---|---|
| top 50 by profit (7,072 trades) | -6.1% | -5.1% | -4.8% | -6.9% per trade (-68 to -97 SOL) |
| copyable top 50 (10+ coins, win >= 50%, hold >= 30 s, not creator; 445 trades) | -4.9% | -5.4% | -6.1% | -9.0% |
| copyable top 200 (848 trades) | -4.8% | -4.8% | -4.9% | -7.3% |
| most consistent (20+ coins, win >= 60%, hold >= 60 s; 440 trades) | -6.3% | -7.0% | -7.9% | -7.8% |

Even with zero delay every copy variant loses ~5-8% per trade. Conclusion: the people who make money on pump.fun
are mostly creators and the fastest bots; copying them is the losing side of their trade.

## Round 1c: what coin creators make (meme/creators.py, same day)
33,072 coins, 2.67% completed the curve. Creator's own wallet only (bundled side wallets invisible), first hour,
0.02 SOL creation cost, creator fee share assumed 0.3% of curve volume (estimate):
- realized + fees: median -0.006 SOL per coin, mean -0.36 SOL, 47% in profit; 90th pct +0.91, 99th pct +6.4 SOL.
- creators who never sold (25%): median fee income 0.011 SOL (about EUR 1.50).
- creators who put in 1+ SOL: 71% in profit but mean -1.83 SOL (a few big losses).
So an honest launch earns about nothing; the profitable creator pattern is buy-early-sell-to-followers
(pump-and-dump / rug), which is not something we will do.

## Round 2: funding-rate carry (carry/funding.py, Binance funding history 2020 -> Oct 2026)
Long spot + short perp, 0.30% round-trip cost. Train 2020-2023, holdout 2024+. %/yr on position size
(on capital ~ divide by 1.5):

| | train %/yr | holdout %/yr | holdout on capital | worst holdout month |
|---|---|---|---|---|
| BTC always on | 14.9 | 6.9 | 4.6 | -0.18% |
| ETH always on | 18.5 | 6.9 | 4.6 | -0.31% |
| best rule (rotate to highest funding, N21, in > 0.005%/8h) | 20.8 | 6.5 | 4.3 | -0.20% |

Funding by year (BTC): 2021 30.6%, 2022 4.2%, 2023 7.9%, 2024 11.9%, 2025 5.1%, 2026 3.1%.
Last 12 months: BTC 3.5%, ETH 2.5%, SOL -0.3% if always collected, i.e. ~2% on capital: savings-account level,
with exchange risk on top. Smart rules add nothing over "always on". Not worth doing now; only interesting when
funding is high again (bull markets, like 2021 / 2024).

## Round 3: memecoins on an exchange (meme/bigcoins.py + meme/listings.py, round3.yml, Binance public data)
**3a, big memecoins, daily** (DOGE, SHIB, PEPE, FLOKI, BONK, WIF, BOME, MEME, PEOPLE, TURBO, NEIRO, PNUT, ACT, TRUMP ...
each from its listing, equal weight, Bitvavo cost 0.25% a side; 2019-23 vs 2024+, %/yr compounded):
| | 2019-23 | 2024+ | worst drop 2024+ | 2024 / 2025 / 2026 |
|---|---|---|---|---|
| hold the meme basket | +108 | -12 | -91% | +271 / -79 / -13 |
| BTC hold | +62 | +24 | -53% | +121 / -6 / -11 |
| BTC alone, Donchian 20/10 | +46 | +22 | -29% | +66 / +8 / -3 |
| memes, Donchian 20/10 (in on a 20-day high, out on a 10-day low) | +142 | +41 | -39% | +181 / -9 / +3 |
| same + only while BTC > its 50-day average | +122 | +49 | -35% | +160 / +13 / +5 |
- Trend rules (Donchian / above the 20-day average) beat holding memes on both periods; dip buying and momentum
  rotation fail the holdout. But the 2019-23 numbers are DOGE/SHIB in 2021 and the holdout is mostly 2024: outside
  those two bull runs the trend rules make about 0 (2025 -9 to +13, 2026 +3 to +5). Real but rests on rare manias,
  -35 to -55% drops; better than holding memes, about BTC-trend quality per unit of risk. List chosen in 2026 (hindsight).
**3b, new Binance perpetual listings** (912 since 2020, 63 memes): 64% are lower 30 days after the first close
(median -11%, memes -22%). Shorting all listings: +1 to +4% per trade on 2024+, weak. Shorting new MEME listings:
+5 to +10% per trade on 2024+ (53 trades) but only 10 trades before 2024 to tune on, and the tails kill it: worst
trade -587% without a stop (squeeze), and with stops the result swings from -0.6% to +10% depending on the setting.
Not robust, and Binance futures are not offered to Dutch retail clients anyway.

## Videos (1 Nov 2026, via video.yml)
- runitbankexe "Grok Bot night shift" (28 Oct): $1,500 -> $7,858 overnight, 47 trades / 41 wins. Staged: the BNB/BTC/ETH
  lock-screen prices (755.29 / 81,527.60 / 2,372.69) and the 96% battery never change from 00:06 to 06:04. Ad.
- runitbankexe "FOMO x GROK" (23 Sep): the screen shows +44% for the shift ($11,451 -> $16,508); "16.49x in five days" is
  only in the caption. The log is Polymarket/Kalshi bets (Musk tweet counts, esports, football, Kalshi-vs-Polymarket gaps)
  plus the $CATE token, not pump.fun. Same "subscription covered by P&L" upsell. No wallet shown.
- el3mentss: ICT 4-step prop-firm setup (daily sweep of PDH/PDL -> 4h FVG -> 1h swing -> CISD entry, 2R). Close to the
  day desk's rounds 10/13 (IFVG, HTF + zones + BOS: no edge); this exact chain not tested yet.

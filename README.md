# Meme Desk

Memecoin research for Maarten, kept apart from the Nasdaq day desk (private repo day-trading-desk).
Question: can a scan -> check -> buy -> sell bot on new pump.fun coins make money after fees, delay and rugs?

**Stage 1: recording (now).** `.github/workflows/record.yml` runs `meme/record.py` around the clock in chained
6 h runs: every new pump.fun launch, its first 60 minutes of bonding-curve trades, and migrations, from PumpPortal's
free data feed. Each run uploads one artifact (`pumpfun-<run id>`, gzipped CSV, kept 90 days).
Stop or extend with `RECORD_UNTIL` in the workflow. Check a file with `python -m meme.stats data/*.csv.gz`.

**Stage 2: backtest (after ~2 weeks of data).** First half to tune, second half as the holdout.
Costs: pump.fun fee ~1% each way, Solana fees, entry a few seconds after the signal at the price then, our own price impact.
Judge by profit, not win rate.

No wallet, no real money here. Only after a holdout pass and weeks of paper trading, and only if Maarten decides.

Tests: `python -m pytest -q`.

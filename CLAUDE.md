# Meme Desk — notes for Claude

Memecoin (pump.fun, Solana) research for Maarten (Amsterdam). Separate from the Nasdaq day desk (repo day-trading-desk).
Be token-frugal. Claude's container cannot reach PumpPortal, pump.fun, DexScreener, GMGN, GeckoTerminal, Birdeye,
Solana RPC or ntfy: everything that needs market data runs on GitHub Actions; read the job logs.

- Stage 1, recording: `meme/record.py` via `.github/workflows/record.yml` (chained 6 h runs, 24/7 until `RECORD_UNTIL`).
  Every launch + first 60 min of bonding-curve trades + migrations, PumpPortal free feed. One artifact per run.
  Summary: `python -m meme.stats data/*.csv.gz` (also printed at the end of each run's log).
- Stage 2, backtest scan -> check -> buy -> sell on the recordings: first half to tune, second half holdout.
  Costs: ~1% pump.fun fee each way + Solana fees, entry a few seconds after the signal, own price impact on the curve.
  Maarten judges by profit (EUR, %), not win rate.
- Stage 3, paper trading only while Maarten watches: a workflow he starts himself, runs a set time, pushes paper
  trades to his phone, then stops. No wallet, no real money unless Maarten explicitly decides after a holdout pass.
- Tests: `python -m pytest -q`.

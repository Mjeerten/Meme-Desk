# Meme Desk — notes for Claude

Memecoin (pump.fun, Solana) research for Maarten (Amsterdam). Separate from the Nasdaq day desk (repo day-trading-desk).
Be token-frugal. Claude's container cannot reach PumpPortal, pump.fun, DexScreener, GMGN, GeckoTerminal, Birdeye,
Solana RPC or ntfy: everything that needs market data runs on GitHub Actions; read the job logs.

- Stage 1, recording (free sources only): `meme/record.py` via `.github/workflows/record.yml` (chained ~6 h runs, 24/7
  until `RECORD_UNTIL`, 6-hourly watchdog). Launches + migrations from PumpPortal's free feed; every pump.fun
  bonding-curve trade decoded from the free public Solana RPC (logsSubscribe, TradeEvent in 'Program data').
  Public RPC drops every 10-30 s, so two copies (a, b) run on different runners; merge + de-duplicate.
  Not usable: PumpPortal trade streams (need a key funded with 0.02 SOL), swap-api.pump.fun (Cloudflare blocks GitHub).
  One artifact per copy per run. Summary: `python -m meme.stats data` (also at the end of each run's log).
- Stage 2, backtest: `meme/backtest.py` via `.github/workflows/backtest.yml` (downloads all recordings). Curve-exact
  fills from the recorded reserves, latency, fees; families baseline, fast flip, momentum, curve progress, dip,
  copy trading, x safety filters x exits; first 60% of coins to tune, last 40% holdout. Candidates: `STRATEGIES.md`.
  Prior art: github.com/apchhui/pump-research (26k coins, every family lost on its holdout).
  Costs: ~1% pump.fun fee each way + Solana fees, entry a few seconds after the signal, own price impact on the curve.
  Maarten judges by profit (EUR, %), not win rate.
- Stage 3, paper trading only while Maarten watches: a workflow he starts himself, runs a set time, pushes paper
  trades to his phone, then stops. No wallet, no real money unless Maarten explicitly decides after a holdout pass.
- Tests: `python -m pytest -q`.

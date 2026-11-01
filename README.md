# Meme Desk

Memecoin research for Maarten, kept apart from the Nasdaq day desk (private repo day-trading-desk).
Question: can a scan -> check -> buy -> sell bot on new pump.fun coins make money after fees, delay and rugs?

**Stage 1: recording (now, free sources only).** `.github/workflows/record.yml` runs `meme/record.py` around the
clock in chained ~6 h runs: every new pump.fun launch and migration (PumpPortal free feed) and every bonding-curve trade
(free public Solana RPC, decoded on the fly). Two copies run side by side because the public RPC drops often.
Stop or extend with `RECORD_UNTIL` in the workflow. Check data with `python -m meme.stats data`.

**Stage 2: backtest (after ~4-7 days of data).** `.github/workflows/backtest.yml` -> `meme/backtest.py`.
First 60% of coins to tune, last 40% as the holdout. Costs: pump.fun fee 1.25% each way, network fees, fills on the
curve 2 s after the signal including our own price impact. Judge by profit, not win rate. See `STRATEGIES.md`.

**Stage 3: paper trading while Maarten watches** (only if something passes the holdout): a workflow he starts himself.

No wallet, no real money here.

Tests: `python -m pytest -q`.

## Video analysis
Moved to the Toolbox repo (Mjeerten/Toolbox).

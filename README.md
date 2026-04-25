# cuddly-fishstick

A personal quantitative equity factor model. Runs on iPhone (Pythonista) or any Python 3 environment. Pulls fundamentals and prices from FMP, computes Value/Quality/Momentum factor scores, and constructs a sector-capped, vol-targeted portfolio.

Currently in Phase 2 of a ground-up rebuild. Phase 1 (cache layer) and Phase 2 (math layer) complete. Phase 3 (HTML report) and Phase 4 (paper-trade tracker) pending.

## Setup

1. Create `mysecrets.py` in the project root:
   ```python
   API_KEY = "your_fmp_api_key_here"
   ```
2. Run `cache.py` and choose mode 1 (Full). This populates `data/cache.db` with ~3 years of prices and quarterly fundamentals for the test universe.
3. Run `db.py` — should print 11 self-tests passing.
4. Run `shared.py` — should print the factor table, residual momentum diagnostic table, and 6 self-tests passing.

## Files

- **`cache.py`** — Cache maintainer. Only file that fetches from FMP. Writes to SQLite. Has interactive menu: full / prices / financials / status.
- **`db.py`** — Read-only loaders. All other scripts read the cache through this. Self-tests on direct run.
- **`shared.py`** — Math layer. Factor model, residual momentum (long-window beta, alpha dropped), portfolio construction with sector cap and vol targeting. Self-tests on direct run.
- **`mysecrets.py`** — Local-only. Not committed. Holds `API_KEY`.
- **`data/`** — Local-only. Not committed. Holds `cache.db` and its backups.

## Architecture

```
FMP API → cache.py → cache.db
                     ↑
                     │ (read-only)
                     │
                  db.py ← shared.py ← (future viewers)
```

`cache.py` is the only writer. `db.py` owns the schema. `shared.py` is pure math. Future scripts (report, paper-trade, ticker deep-dive) read from `db.py` and `shared.py` and produce output.

## Model spec

**Universe**: 8 names + SPY for Phase 1 testing. Will scale to S&P 500 in production.

**Value** (4 components, equal-weighted z-scores): EBIT/EV, FCF/EV, Book/Market, Sales/EV.

**Quality** (3 components): GP/Assets, Operating Margin, −NetDebt/Assets.

**Momentum** (2 components): residual t-stat over 12m-1m and 6m windows.
- Beta estimated on the 504 days *before* the measurement window (no overlap).
- No intercept (alpha dropped) — the residual is `r_stock − β·r_market`.
- t-stat = `sum(residuals) / std(residuals)` per window.

**Standardization**: winsorize 5/95 at sub-component level, then 80% sector + 20% global blend, modulated by sector size (`α_s = n_s / max_n_s'`).

**Composite**: raw mean of Value/Quality/Momentum, no top-level winsorize/z (uncapped).

**Portfolio construction**: top 30 by composite. Weights = 50% equal + 25% inv-vol + 25% min-var (long-only). 25% sector cap with proportional redistribution. EWMA covariance (λ=0.94). Vol-targeted to 20% annual.

## Status

- ✅ Phase 1 — Cache maintainer (`cache.py`)
- ✅ Phase 2A — Read-only loaders (`db.py`)
- ✅ Phase 2B — Math layer (`shared.py`)
- ⬜ Phase 3 — HTML report (`report.py`)
- ⬜ Phase 4 — Paper-trade tracker (`paper.py`)
- ⬜ Phase 5 — Scale universe to S&P 500

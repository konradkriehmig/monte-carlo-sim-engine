I ran a monte carlo simulation to show different ways of speeding it up and determining an optimal infrastructure to run on. This assumes that a simulation will not run once but multiple times for different options contracts and maybe even used for some automatic trades.

The program is determining fair prices for European options. It makes no sense from a business perspective, since you would just use the Black-Scholes formula. However, a similar program would make sense to price exotic options with different parameters. I just use European options in this project for simplicity since the underlying compute logic is fairly the same.

---

## MA Crossover Backtester (existing)

The original module runs Moving Average crossover backtests on crypto price
data at scale on Azure infrastructure:

- **`data fetcher`** — downloads raw price data into Azure Blob Storage.
- **`logic`** — core backtesting logic (MA crossover signals, P&L).
- **`push_jobs.py`** — enqueues all parameter combinations to an Azure Queue.
- **`worker.py`** — VMSS worker: pulls jobs, runs backtests, saves results.
- **`infra/`** — ARM templates and infrastructure-as-code.

---

## ETF Fair Value Monte Carlo Engine (`etf_fairvalue/`)

Estimates the **fair value of the XLK ETF** by running correlated Geometric
Brownian Motion (GBM) simulations across all ~70 constituents using a
Cholesky-decomposed covariance matrix.  Designed to run at scale on a
Kubernetes (AKS) cluster via the Indexed Job pattern — 100 worker pods ×
10,000 paths = **1,000,000 simulated NAV values**.

### Architecture

```
┌──────────────────┐       ┌───────────────────────────────────────┐
│  Step 1           │       │  Step 2 — K8s Indexed Job             │
│  fetch.py         │──────▶│  100 worker pods × 10,000 paths       │
│  (runs locally)   │ config│  each: Cholesky → correlated GBM      │
│                   │ bundle│  output: results/batch_{id}.parquet   │
└──────────────────┘       └────────────────┬──────────────────────┘
                                            │
                            ┌───────────────▼──────────────────────┐
                            │  aggregate.py                        │
                            │  Combine 1M NAV values               │
                            │  → summary stats + distribution plot │
                            └──────────────────────────────────────┘
```

### File structure

```
etf_fairvalue/
├── __init__.py
├── fetch.py          # Step 1: Data fetch & config bundle
├── worker.py         # Step 2: Monte Carlo simulation worker
├── aggregate.py      # Aggregate results & produce report
├── Dockerfile        # Container image for K8s workers
└── k8s/
    └── worker-job.yaml   # K8s Indexed Job manifest (100 workers)
requirements-etf.txt      # Python dependencies
```

### Installation

```bash
pip install -r requirements-etf.txt
```

### Step 1 — Fetch data & build config bundle (run once locally)

```bash
python -m etf_fairvalue.fetch
```

This pulls XLK holdings from yfinance (falls back to `data/xlk_holdings.csv`
if unavailable), downloads 1 year of daily adjusted closes for all
constituents, computes the annualised covariance matrix / drift / volatility
and saves:

- `config/config_bundle.npz` — numpy arrays (weights, prices, μ, σ, Σ)
- `config/config_meta.json`  — metadata (tickers, XLK market price, timestamp)

### Step 2 — Run a local simulation worker (single batch)

```bash
python -m etf_fairvalue.worker \
    --batch-id 0 \
    --num-paths 10000 \
    --horizon-days 5 \
    --seed 42
```

Output: `results/batch_0.parquet` (10,000 simulated NAV values).

### Step 3 — Aggregate results

```bash
python -m etf_fairvalue.aggregate
```

Reads all `results/batch_*.parquet` files and produces:

- `results/summary_stats.json`      — mean, median, std, percentiles, premium/discount
- `results/nav_distribution.png`    — histogram + KDE with mean / market-price lines

### Deploy to Kubernetes (AKS)

1. **Build & push the Docker image**

   ```bash
   docker build -f etf_fairvalue/Dockerfile -t <YOUR_REGISTRY>/etf-mc-worker:latest .
   docker push <YOUR_REGISTRY>/etf-mc-worker:latest
   ```

2. **Copy the config bundle onto the shared PVC** (e.g. via a `kubectl cp` or
   an init container that runs `fetch.py`).

3. **Submit the Indexed Job**

   ```bash
   kubectl apply -f etf_fairvalue/k8s/worker-job.yaml
   ```

   This launches 100 pods (20 in parallel), each processing 10,000 paths.
   Results land in `results/` on the shared PVC.

4. **Aggregate** once all pods complete:

   ```bash
   python -m etf_fairvalue.aggregate
   ```

### Key constants

| Constant | Value |
|---|---|
| `TRADING_DAYS_PER_YEAR` | 252 |
| Default `horizon_days` | 5 trading days |
| Default `num_paths` per worker | 10,000 |
| Default number of workers | 100 |
| Total paths | 1,000,000 |

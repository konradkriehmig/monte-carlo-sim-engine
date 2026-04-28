"""
Step 2 — Monte Carlo Simulation Worker
Runs inside each K8s pod (Indexed Job).

Loads the config bundle produced by fetch.py, Cholesky-decomposes the
annualised covariance matrix and runs correlated Geometric Brownian Motion
(GBM) simulations over a multi-day horizon for all ETF constituents.
Writes the array of simulated NAV values as a Parquet file.

Usage (standalone):
    python -m etf_fairvalue.worker \
        --batch-id 0 \
        --num-paths 10000 \
        --horizon-days 5 \
        --seed 42 \
        --config-dir config \
        --results-dir results
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from etf_fairvalue.logging_config import setup_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRADING_DAYS_PER_YEAR = 252
DT = 1.0 / TRADING_DAYS_PER_YEAR  # one trading day in year fraction


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_dir: Path) -> dict:
    """
    Load the config bundle written by fetch.py.

    Returns a dict with keys:
        tickers, weights, current_prices, mu, sigma, cov_matrix,
        xlk_market_price, n_tickers, nav_scale_factor
    """
    npz_path = config_dir / "config_bundle.npz"
    meta_path = config_dir / "config_meta.json"

    data = np.load(npz_path)
    with open(meta_path) as fh:
        meta = json.load(fh)

    weights = data["weights"]
    current_prices = data["current_prices"]
    xlk_market_price = meta["xlk_market_price"]

    # ---------------------------------------------------------------------------
    # FIX: Compute scaling factor to anchor weighted-average prices to ETF price.
    #
    # weights @ current_prices gives a weighted average of raw stock prices,
    # but the ETF share price reflects total portfolio value / shares outstanding.
    # This scale factor bridges the two so simulated NAV is in ETF-price units.
    # ---------------------------------------------------------------------------
    raw_nav = np.dot(weights, current_prices)
    nav_scale_factor = xlk_market_price / raw_nav
    logger.info(
        "NAV scale factor: %.6f (raw weighted avg = $%.2f, XLK = $%.2f)",
        nav_scale_factor, raw_nav, xlk_market_price,
    )

    return {
        "tickers": meta["tickers"],
        "xlk_market_price": xlk_market_price,
        "n_tickers": meta["n_tickers"],
        "generated_utc": meta.get("generated_utc"),
        "weights": weights,
        "current_prices": current_prices,
        "mu": data["mu"],
        "sigma": data["sigma"],
        "cov_matrix": data["cov_matrix"],
        "nav_scale_factor": nav_scale_factor,
    }


# ---------------------------------------------------------------------------
# Cholesky helper
# ---------------------------------------------------------------------------

def cholesky_decompose(cov_matrix: np.ndarray) -> np.ndarray:
    """
    Return lower-triangular Cholesky factor L such that L @ L.T == cov_matrix.

    If the matrix is not numerically positive-definite a small nugget is added
    to the diagonal to regularise it.
    """
    try:
        L = np.linalg.cholesky(cov_matrix)
    except np.linalg.LinAlgError:
        n = cov_matrix.shape[0]
        nugget = 1e-8 * np.trace(cov_matrix) / n
        logger.warning(
            "Covariance matrix not positive-definite; adding nugget=%.2e for regularisation",
            nugget,
        )
        L = np.linalg.cholesky(cov_matrix + nugget * np.eye(n))
    return L


# ---------------------------------------------------------------------------
# Simulation — loop-based (clarity reference)
# ---------------------------------------------------------------------------

def simulate_nav(
    *,
    current_prices: np.ndarray,
    weights: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
    L: np.ndarray,
    horizon_days: int,
    num_paths: int,
    rng: np.random.Generator,
    nav_scale_factor: float = 1.0,
) -> np.ndarray:
    """
    Loop-based GBM simulation. Provided for clarity; not the default.

    For each path:
      - Walk each stock forward *horizon_days* steps using correlated GBM
      - Compute NAV = scale * Σ weight_i * S_i(T)

    Returns array of shape (num_paths,) with simulated NAV values.
    """
    n = len(current_prices)
    nav_values = np.empty(num_paths, dtype=float)

    for path_idx in range(num_paths):
        prices = current_prices.copy()

        for _ in range(horizon_days):
            z_ind = rng.standard_normal(n)          # (n,) independent normals
            z_cor = L @ z_ind                        # (n,) correlated normals
            drift = (mu - 0.5 * sigma ** 2) * DT
            diffusion = sigma * np.sqrt(DT) * z_cor
            prices = prices * np.exp(drift + diffusion)

        nav_values[path_idx] = np.dot(weights, prices) * nav_scale_factor

    return nav_values


# ---------------------------------------------------------------------------
# Simulation — vectorised (default, processes all paths simultaneously)
# ---------------------------------------------------------------------------

def simulate_nav_vectorised(
    *,
    current_prices: np.ndarray,
    weights: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
    L: np.ndarray,
    horizon_days: int,
    num_paths: int,
    rng: np.random.Generator,
    nav_scale_factor: float = 1.0,
) -> np.ndarray:
    """
    Vectorised GBM simulation using numpy broadcasting.
    Processes all *num_paths* simultaneously — much faster than the loop version.

    Shape guide:
        n            = number of tickers
        prices       (num_paths, n)   — broadcast from (n,)
        z_ind        (num_paths, n)   — independent normals
        z_cor        (num_paths, n)   — correlated via L
        drift        (n,)             — broadcast across paths
        diffusion    (num_paths, n)
        nav_values   (num_paths,)
    """
    n = len(current_prices)
    # Start every path at current prices; shape (num_paths, n)
    prices = np.tile(current_prices, (num_paths, 1))

    drift = (mu - 0.5 * sigma ** 2) * DT           # (n,) — pre-compute once

    for _ in range(horizon_days):
        # Draw independent standard normals for all paths at once
        z_ind = rng.standard_normal((num_paths, n))  # (num_paths, n)
        # Correlate: z_cor[p] = L @ z_ind[p]  →  z_ind @ L.T
        z_cor = z_ind @ L.T                          # (num_paths, n)
        diffusion = sigma * np.sqrt(DT) * z_cor      # (num_paths, n)
        prices = prices * np.exp(drift + diffusion)

    # NAV = weighted sum across tickers for each path, scaled to ETF price
    nav_values = (prices @ weights) * nav_scale_factor  # (num_paths,)
    return nav_values


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_results(nav_values: np.ndarray, results_dir: Path, batch_id: int) -> Path:
    """Save nav_values array to results/batch_{batch_id}.parquet."""
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"batch_{batch_id}.parquet"
    df = pd.DataFrame({"nav": nav_values})
    df.to_parquet(out_path, index=False)
    return out_path


def log_summary(nav_values: np.ndarray, batch_id: int, elapsed: float) -> None:
    """Log summary statistics for this batch."""
    p5, p25, p50, p75, p95 = np.percentile(nav_values, [5, 25, 50, 75, 95])
    logger.info(
        "batch=%d | n=%s paths | mean=%.4f | median=%.4f | std=%.4f | "
        "p5=%.4f | p95=%.4f | elapsed=%.2fs",
        batch_id, f"{len(nav_values):,}",
        nav_values.mean(), p50, nav_values.std(), p5, p95, elapsed,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ETF Fair Value Monte Carlo worker"
    )
    parser.add_argument("--batch-id", type=int, default=0,
                        help="Batch index (JOB_COMPLETION_INDEX in K8s)")
    parser.add_argument("--num-paths", type=int, default=10_000,
                        help="Number of simulation paths for this worker")
    parser.add_argument("--horizon-days", type=int, default=5,
                        help="Simulation horizon in trading days")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed (uses batch-id if omitted)")
    parser.add_argument("--config-dir", type=Path, default=Path("config"),
                        help="Directory containing config bundle")
    parser.add_argument("--results-dir", type=Path, default=Path("results"),
                        help="Directory for output parquet files")
    parser.add_argument("--use-loop", action="store_true",
                        help="Use loop-based simulation instead of vectorised")
    parser.add_argument("--log-level", default="info",
                        choices=["debug", "info", "warning", "error"],
                        help="Logging verbosity (default: info)")
    parser.add_argument("--log-file", type=Path, default=None,
                        help="Optional file path for log output (appended)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    setup_logging(level=args.log_level, log_file=args.log_file)

    # Allow K8s JOB_COMPLETION_INDEX to override batch-id / seed
    k8s_index = os.environ.get("JOB_COMPLETION_INDEX")
    if k8s_index is not None:
        args.batch_id = int(k8s_index)

    # Default seed = batch_id so each worker produces deterministic,
    # non-overlapping random streams without requiring an explicit --seed flag.
    seed = args.seed if args.seed is not None else args.batch_id
    rng = np.random.default_rng(seed)

    logger.info(
        "Starting batch=%d | paths=%s | horizon=%dd | seed=%s",
        args.batch_id, f"{args.num_paths:,}", args.horizon_days, seed,
    )

    # 1. Load config
    cfg = load_config(args.config_dir)
    logger.info(
        "Config loaded: %d tickers, XLK=$%.2f (generated %s)",
        cfg["n_tickers"], cfg["xlk_market_price"], cfg.get("generated_utc", "unknown"),
    )

    # 2. Cholesky decomposition (once per worker)
    L = cholesky_decompose(cfg["cov_matrix"])
    logger.info("Cholesky decomposition complete — L shape %s", L.shape)

    # 3. Simulate
    t0 = time.perf_counter()
    simulate_fn = simulate_nav if args.use_loop else simulate_nav_vectorised
    nav_values = simulate_fn(
        current_prices=cfg["current_prices"],
        weights=cfg["weights"],
        mu=cfg["mu"],
        sigma=cfg["sigma"],
        L=L,
        horizon_days=args.horizon_days,
        num_paths=args.num_paths,
        rng=rng,
        nav_scale_factor=cfg["nav_scale_factor"],
    )
    elapsed = time.perf_counter() - t0

    # 4. Log summary
    log_summary(nav_values, args.batch_id, elapsed)

    # 5. Write output
    out_path = write_results(nav_values, args.results_dir, args.batch_id)
    logger.info("Results written → %s", out_path)


if __name__ == "__main__":
    main()

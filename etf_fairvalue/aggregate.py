"""
Aggregation script
Combines all batch Parquet files produced by the workers, computes summary
statistics, compares against the XLK market price and generates a
histogram / density plot.

Usage:
    python -m etf_fairvalue.aggregate \\
        [--results-dir results] \\
        [--config-dir config]
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PERCENTILES = [5, 25, 75, 95]
PLOT_FILENAME = "nav_distribution.png"
STATS_FILENAME = "summary_stats.json"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_all_batches(results_dir: Path) -> np.ndarray:
    """Read every batch_*.parquet in *results_dir* and return a single NAV array."""
    parquet_files = sorted(results_dir.glob("batch_*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(
            f"No batch_*.parquet files found in {results_dir}. "
            "Run the worker first."
        )
    frames = [pd.read_parquet(p) for p in parquet_files]
    all_data = pd.concat(frames, ignore_index=True)
    print(f"[aggregate] Loaded {len(parquet_files)} batch files, "
          f"{len(all_data):,} total NAV values")
    return all_data["nav"].values


def load_xlk_price(config_dir: Path) -> float | None:
    """Read the XLK market price from the config metadata, or return None."""
    meta_path = config_dir / "config_meta.json"
    if not meta_path.exists():
        return None
    with open(meta_path) as fh:
        meta = json.load(fh)
    return meta.get("xlk_market_price")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_summary(nav_values: np.ndarray, xlk_price: float | None) -> dict:
    """Compute summary statistics and premium/discount vs. XLK market price."""
    mean_nav = float(np.mean(nav_values))
    median_nav = float(np.median(nav_values))
    std_nav = float(np.std(nav_values))

    pcts = {f"p{p}": float(np.percentile(nav_values, p)) for p in PERCENTILES}

    summary: dict = {
        "n_paths": int(len(nav_values)),
        "mean_nav": mean_nav,
        "median_nav": median_nav,
        "std_nav": std_nav,
        **pcts,
    }

    if xlk_price is not None:
        premium_pct = (mean_nav - xlk_price) / xlk_price * 100.0
        summary["xlk_market_price"] = xlk_price
        summary["premium_discount_pct"] = round(premium_pct, 4)

    return summary


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_distribution(
    nav_values: np.ndarray,
    summary: dict,
    out_path: Path,
) -> None:
    """Generate a histogram + KDE density plot of the NAV distribution."""
    mean_nav = summary["mean_nav"]
    p5 = summary["p5"]
    p95 = summary["p95"]
    xlk_price = summary.get("xlk_market_price")

    fig, ax = plt.subplots(figsize=(12, 6))

    # Histogram
    ax.hist(
        nav_values,
        bins=120,
        density=True,
        color="#4C72B0",
        alpha=0.55,
        label="Simulated NAV distribution",
    )

    # Optional KDE overlay
    try:
        from scipy.stats import gaussian_kde  # type: ignore[import-untyped]

        kde = gaussian_kde(nav_values)
        x_grid = np.linspace(nav_values.min(), nav_values.max(), 500)
        ax.plot(x_grid, kde(x_grid), color="#4C72B0", linewidth=2)
    except Exception:
        pass  # scipy optional; fall back to histogram only

    # Vertical lines
    ax.axvline(mean_nav, color="#DD8452", linewidth=2, linestyle="-",
                label=f"Mean NAV = ${mean_nav:.2f}")
    ax.axvline(p5, color="#55A868", linewidth=1.5, linestyle="--",
                label=f"5th pct = ${p5:.2f}")
    ax.axvline(p95, color="#55A868", linewidth=1.5, linestyle="--",
                label=f"95th pct = ${p95:.2f}")

    if xlk_price is not None:
        ax.axvline(xlk_price, color="#C44E52", linewidth=2, linestyle="-.",
                   label=f"XLK market price = ${xlk_price:.2f}")

    ax.set_xlabel("Simulated NAV ($)", fontsize=13)
    ax.set_ylabel("Density", fontsize=13)
    ax.set_title("XLK Fair Value — Monte Carlo NAV Distribution", fontsize=15)
    ax.legend(fontsize=11)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("$%.2f"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.4f"))

    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[aggregate] Plot saved → {out_path}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(summary: dict) -> None:
    """Print a formatted summary report to stdout."""
    print()
    print("=" * 60)
    print("  XLK FAIR VALUE — MONTE CARLO SUMMARY REPORT")
    print("=" * 60)
    print(f"  Simulated paths  : {summary['n_paths']:>12,}")
    print(f"  Mean NAV         : ${summary['mean_nav']:>11.4f}")
    print(f"  Median NAV       : ${summary['median_nav']:>11.4f}")
    print(f"  Std Dev          : ${summary['std_nav']:>11.4f}")
    print(f"  5th  percentile  : ${summary['p5']:>11.4f}")
    print(f"  25th percentile  : ${summary['p25']:>11.4f}")
    print(f"  75th percentile  : ${summary['p75']:>11.4f}")
    print(f"  95th percentile  : ${summary['p95']:>11.4f}")
    if "xlk_market_price" in summary:
        prem = summary["premium_discount_pct"]
        direction = "premium" if prem >= 0 else "discount"
        print(f"  XLK market price : ${summary['xlk_market_price']:>11.4f}")
        print(f"  Mean vs market   : {abs(prem):.2f}% {direction}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate ETF Monte Carlo results"
    )
    parser.add_argument("--results-dir", type=Path, default=Path("results"),
                        help="Directory with batch_*.parquet files")
    parser.add_argument("--config-dir", type=Path, default=Path("config"),
                        help="Directory with config_meta.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # 1. Load all batch results
    nav_values = load_all_batches(args.results_dir)

    # 2. Load XLK market price (optional)
    xlk_price = load_xlk_price(args.config_dir)
    if xlk_price is not None:
        print(f"[aggregate] XLK market price from config: ${xlk_price:.2f}")

    # 3. Compute summary stats
    summary = compute_summary(nav_values, xlk_price)

    # 4. Save stats JSON
    stats_path = args.results_dir / STATS_FILENAME
    with open(stats_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"[aggregate] Summary stats → {stats_path}")

    # 5. Plot
    plot_path = args.results_dir / PLOT_FILENAME
    plot_distribution(nav_values, summary, plot_path)

    # 6. Print report
    print_report(summary)


if __name__ == "__main__":
    main()

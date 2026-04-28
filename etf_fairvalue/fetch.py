"""
Step 1 — Data Fetch
Runs once locally (NOT in K8s).

Fetches XLK holdings/weights, 1 year of daily adjusted closes,
computes annualised covariance / drift / volatility, fetches the current
XLK market price and saves everything as a config bundle:

    config/config_bundle.npz   – numpy arrays
    config/config_meta.json    – metadata (tickers, price, timestamp, …)

Usage:
    python -m etf_fairvalue.fetch
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRADING_DAYS_PER_YEAR = 252
XLK_TICKER = "XLK"
LOOKBACK_PERIOD = "1y"
CONFIG_DIR = Path("config")

# Fallback CSV path if yfinance cannot supply holdings
HOLDINGS_CSV = Path("data") / "xlk_holdings.csv"


# ---------------------------------------------------------------------------
# Holdings helpers
# ---------------------------------------------------------------------------

def _holdings_from_yfinance() -> pd.DataFrame:
    """Return DataFrame with columns [ticker, weight] from yfinance."""
    ticker = yf.Ticker(XLK_TICKER)
    holdings = ticker.funds_data.top_holdings  # type: ignore[attr-defined]
    if holdings is None or holdings.empty:
        raise ValueError("yfinance returned empty holdings")
    df = holdings.reset_index()
    # Column names vary by yfinance version; normalise them
    df.columns = [c.lower() for c in df.columns]
    # Possible column name combos: ('symbol','holdingpercent'), ('ticker','weight')
    rename_map: dict[str, str] = {}
    for col in df.columns:
        if col in ("symbol", "ticker", "holding"):
            rename_map[col] = "ticker"
        elif col in ("holdingpercent", "holding percent", "weight", "pct"):
            rename_map[col] = "weight"
    df = df.rename(columns=rename_map)
    df = df[["ticker", "weight"]].dropna()
    df["weight"] = df["weight"].astype(float)
    return df

def _holdings_from_csv(path: Path) -> pd.DataFrame:
    """Load holdings from a local CSV file with columns: ticker,weight."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "ticker" not in df.columns or "weight" not in df.columns:
        raise ValueError(f"CSV at {path} must have 'ticker' and 'weight' columns")
    df = df[["ticker", "weight"]].dropna()
    df["weight"] = df["weight"].astype(float)
    return df

def get_holdings() -> pd.DataFrame:
    """Return DataFrame[ticker, weight], trying yfinance first then CSV fallback."""
    try:
        df = _holdings_from_yfinance()
        print(f"[fetch] Loaded {len(df)} holdings from yfinance")
        return df
    except Exception as exc:
        print(f"[fetch] yfinance holdings failed ({exc}); falling back to CSV at {HOLDINGS_CSV}")
        return _holdings_from_csv(HOLDINGS_CSV)

# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------

def fetch_price_history(tickers: list[str]) -> pd.DataFrame:
    """
    Download 1 year of daily adjusted closes for *tickers*.
    Returns a DataFrame with tickers as columns and dates as index.
    Drops any ticker for which no data was returned.
    """
    print(f"[fetch] Downloading 1y of daily closes for {len(tickers)} tickers …")
    raw = yf.download(
        tickers,
        period=LOOKBACK_PERIOD,
        auto_adjust=True,
        progress=False,
    )
    # yf.download returns MultiIndex columns when >1 ticker
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
    closes = closes.dropna(axis=1, how="all")
    missing = set(tickers) - set(closes.columns)
    if missing:
        print(f"[fetch] Warning: no data for {missing}; dropping from universe")
    return closes


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def compute_stats(
    closes: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """
    From a closes DataFrame compute:
        mu       – annualised drift   (n,)
        sigma    – annualised vol     (n,)
        cov_ann  – annualised cov     (n, n)
        tickers  – ordered ticker list
    """
    log_returns = np.log(closes / closes.shift(1)).dropna()
    tickers = list(log_returns.columns)
    n = len(tickers)

    daily_mean = log_returns.mean().values          # (n,)
    daily_cov = log_returns.cov().values            # (n, n)

    mu = daily_mean * TRADING_DAYS_PER_YEAR         # annualised
    cov_ann = daily_cov * TRADING_DAYS_PER_YEAR     # annualised
    sigma = np.sqrt(np.diag(cov_ann))               # annualised vol

    print(f"[fetch] Computed stats for {n} tickers; "
          f"avg μ={mu.mean():.4f}, avg σ={sigma.mean():.4f}")
    return mu, sigma, cov_ann, tickers


# ---------------------------------------------------------------------------
# Current prices
# ---------------------------------------------------------------------------

def fetch_current_prices(tickers: list[str]) -> np.ndarray:
    """Return array of latest available closing prices for each ticker."""
    print("[fetch] Fetching latest prices …")
    raw = yf.download(tickers, period="5d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
    prices = closes.ffill().iloc[-1]
    return prices.reindex(tickers).values.astype(float)


def fetch_xlk_market_price() -> float:
    """Return the latest available XLK closing price."""
    raw = yf.download(XLK_TICKER, period="5d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
    price = float(closes.ffill().iloc[-1].values[0])
    print(f"[fetch] XLK market price: ${price:.2f}")
    return price


# ---------------------------------------------------------------------------
# Save config bundle
# ---------------------------------------------------------------------------

def save_config_bundle(
    *,
    tickers: list[str],
    weights: np.ndarray,
    current_prices: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
    cov_matrix: np.ndarray,
    xlk_market_price: float,
    config_dir: Path = CONFIG_DIR,
) -> None:
    """Persist all arrays + metadata to *config_dir*."""
    config_dir.mkdir(parents=True, exist_ok=True)

    npz_path = config_dir / "config_bundle.npz"
    np.savez(
        npz_path,
        weights=weights,
        current_prices=current_prices,
        mu=mu,
        sigma=sigma,
        cov_matrix=cov_matrix,
    )
    print(f"[fetch] Saved arrays → {npz_path}")

    meta = {
        "tickers": tickers,
        "xlk_market_price": xlk_market_price,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(tickers),
    }
    meta_path = config_dir / "config_meta.json"
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[fetch] Saved metadata → {meta_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    start = time.time()

    # 1. Holdings
    holdings_df = get_holdings()
    holdings_df = holdings_df.set_index("ticker")
    tickers_raw = holdings_df.index.tolist()

    # 2. Price history
    closes = fetch_price_history(tickers_raw)
    available_tickers = list(closes.columns)

    # Re-align weights to available tickers
    weights_series = holdings_df["weight"].reindex(available_tickers).fillna(0.0)
    total_w = weights_series.sum()
    if total_w > 0:
        weights_series = weights_series / total_w  # re-normalise
    weights = weights_series.values.astype(float)

    # 3. Compute stats
    mu, sigma, cov_matrix, tickers = compute_stats(closes[available_tickers])

    # 4. Current prices
    current_prices = fetch_current_prices(tickers)

    # 5. XLK market price
    xlk_market_price = fetch_xlk_market_price()

    # 6. Save bundle
    save_config_bundle(
        tickers=tickers,
        weights=weights,
        current_prices=current_prices,
        mu=mu,
        sigma=sigma,
        cov_matrix=cov_matrix,
        xlk_market_price=xlk_market_price,
    )

    elapsed = time.time() - start
    print(f"[fetch] Done in {elapsed:.1f}s. Config bundle written to {CONFIG_DIR}/")


if __name__ == "__main__":
    main()

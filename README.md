## ETF Fair Value Monte Carlo Engine

Estimates the **fair value of the XLK ETF** by running correlated Geometric
Brownian Motion (GBM) simulations across all ~70 stocks using a
Cholesky-decomposed covariance matrix.  Designed to run at scale in parallel on a
Kubernetes (AKS) cluster via Indexed Job pattern, where the number of simulated NAVs equals the number of pos times the number of paths on each pod.

### Workflow

1) fetch XLK constituents data locally from yahoo finance api
2) run the jobs on worker containers and receive a parquet as output
3) aggregate NAVs and evaluate with summary stats and plots

### Architecture

<img width="892" height="897" alt="image" src="https://github.com/user-attachments/assets/06288147-901e-4096-bf9e-22d6b9305b50" />



Got to the setup guide: https://github.com/konradkriehmig/monte-carlo-sim-engine/blob/main/K8S_SETUP_AND_USER_GUIDE.md

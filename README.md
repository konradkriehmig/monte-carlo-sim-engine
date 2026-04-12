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

### Results

<img width="885" height="437" alt="image" src="https://github.com/user-attachments/assets/690bd7b6-460a-4234-a5d6-0f6bad3035a2" />

The **key takeaway** from the model is the spread prediction. Obtaining a spread based on historical constituents' prices and their correlations to each other can be useful for participating in valatility trading. I.e., the modeled spread represents a realistic benchmark for volatility trading (e.g. straddles).

The drift leading to the estimated NAV of XLK is based on historical trend and does not take into account any variables from outside the world of its 70 constituents. For example, an anouncement of a new technology of a private Chinese company (deepseek moment) could significantly impact the forecast. 

The XLK spread is also vulnerable to external shocks but less so than the expected value. Spreads are in the short-term highly affected by the correlations among and the volatility of its constituents. Volatility trends are historically more persistent than the drift [1](http://rama.cont.perso.math.cnrs.fr/pdf/clustering.pdf).

Got to the setup guide: https://github.com/konradkriehmig/monte-carlo-sim-engine/blob/main/K8S_SETUP_AND_USER_GUIDE.md

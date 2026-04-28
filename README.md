## System to run Monte Carlo simulations estimating the NAV of the XLK ETF

Estimates the **fair value of the XLK ETF** by running correlated Geometric
Brownian Motion (GBM) simulations across all ~70 stocks using a
Cholesky-decomposed covariance matrix.  Designed to run at scale in parallel on a
Kubernetes (AKS) cluster via Indexed Job pattern, where the number of simulated NAVs equals the number of pods times the number of paths on each pod.
[Note: I did not build the model myself, I just focused on building the underlying infrastructure in this project.]

### Workflow

1) fetch XLK constituents data locally from yahoo finance api
2) run the jobs on worker containers and receive a parquet as output
3) aggregate NAVs and evaluate with summary stats and plots

### Architecture

<img width="892" height="897" alt="image" src="https://github.com/user-attachments/assets/06288147-901e-4096-bf9e-22d6b9305b50" />

### Results

<img width="885" height="437" alt="image" src="https://github.com/user-attachments/assets/690bd7b6-460a-4234-a5d6-0f6bad3035a2" />

The **key takeaway** from the model is the spread prediction. Obtaining a spread based on historical constituents' prices and their correlations to each other can be useful for participating in volatility trading. I.e., the modeled spread represents a realistic benchmark for volatility trading (e.g. straddles).

The drift leading to the estimated NAV of XLK is based on historical trends and does not take into account any variables from outside the world of its 70 constituents. For example, an announcement of a new technology of a private Chinese company (deepseek moment) could significantly impact the forecast. 

The XLK spread is also vulnerable to external shocks but less so than the expected value. Spreads are in the short-term highly affected by the correlations among and volatility of its constituents. Volatility levels are historically more persistent than the drift [1](http://rama.cont.perso.math.cnrs.fr/pdf/clustering.pdf).

### Performance

I initially wanted to create a system that handles tasks in the cloud faster than on my laptop. However, I am using a decently powerful laptop with 12 amd cores and I have limited access to SKUs (only to D series for regular daily work). Therefore, I was not able to speed up the parallelism on my local laptop using cloud resources. 

This operation is handled well by my laptop even with a pathsize of 1M. Transferring parallel tasks like this to the cloud, spread across clusters increases complexity and hurts performance. While multiple continuous tasks make sense to deploy on AKS clusters, such a simple parallel task would be better executed on a monolithic system. 

Go to the setup guide: https://github.com/konradkriehmig/distributed-simulation-k8s/blob/main/K8S_SETUP_AND_USER_GUIDE.md

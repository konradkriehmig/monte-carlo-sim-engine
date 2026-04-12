# ETF Fair Value Monte Carlo Engine — Azure K8s Guide

## Architecture Overview

<img width="839" height="1144" alt="image" src="https://github.com/user-attachments/assets/4785ad50-00e2-4df0-b531-59f691398888" />

---

## Part A — Setup Guide (one-time)

### A1. Install local tools

1. **Docker Desktop** — download from https://www.docker.com/products/docker-desktop
   - After installing, open it and make sure it shows "Running" (green) in the bottom left
   - Verify in PowerShell: `docker --version`

2. **Azure CLI** — download the MSI installer from https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows
   - Verify: `az --version`
   - Log in: `az login`

3. **kubectl** — installed via Azure CLI:
   ```powershell
   az aks install-cli
   ```

### A2. Create Azure Container Registry (ACR)

In the Azure portal:

1. Search **"Container registries"** → Create
2. Settings:
   - Resource group: create or use an existing one (e.g. `rg-monte-carlo-sim-ngin`)
   - Registry name: e.g. `montecarloengine` (lowercase, no dashes)
   - Location: pick one close to you (e.g. `UK West`)
   - SKU: Standard
3. Click Create

### A3. Build and push the Docker image

From PowerShell, navigate to your project root (where the `Dockerfile` sits):

```powershell
cd C:\path\to\monte-carlo-sim-engine

# Build the image for Linux (AKS nodes run Linux)
docker build --platform linux/amd64 -t etf-mc-worker:latest .

# Log in to your ACR
az acr login --name <your-acr-name>

# Tag and push
docker tag etf-mc-worker:latest <your-acr-name>.azurecr.io/etf-mc-worker:latest
docker push <your-acr-name>.azurecr.io/etf-mc-worker:latest
```

> **Important:** Always include `--platform linux/amd64` when building. Your Windows
> machine builds Windows/ARM images by default, but AKS nodes run Linux.

### A4. Create the AKS cluster

In the Azure portal:

1. Search **"Kubernetes services"** → Create
2. **Basics tab:**
   - Resource group: same as ACR
   - Cluster name: e.g. `aks-cluster-gbm-workers`
   - Region: same as ACR
   - Node pools: keep the default `agentpool` (System) and add a `userpool` (User)
     - Node size: `Standard_D2s_v3` (2 vCPU, 8 GB RAM)
     - Node count: 2–3
3. **Integrations tab:**
   - Container registry: select your ACR from the dropdown
4. Click Create (takes ~5-10 minutes)

### A5. Attach ACR to AKS (if not done via portal)

If you skipped the Integrations tab or it didn't take effect:

```powershell
az aks update --resource-group <your-rg> --name <your-cluster> --attach-acr <your-acr-name>
```

Verify:

```powershell
az aks check-acr --resource-group <your-rg> --name <your-cluster> --acr <your-acr-name>.azurecr.io
```

You should see: `Your cluster can pull images from <acr>.azurecr.io!`

### A6. Connect kubectl to your cluster

```powershell
az aks get-credentials --resource-group <your-rg> --name <your-cluster>
```

Verify:

```powershell
kubectl get nodes
```

You should see your nodes listed with status `Ready`.

---

## Part B — User Guide (daily workflow)

### B1. Generate the config bundle

Run the data fetch step locally. This downloads XLK holdings, price history, and computes the covariance matrix:

```powershell
python -m etf_fairvalue.fetch
```

Output: `config/config_bundle.npz` and `config/config_meta.json`

### B2. Upload config to K8s

Delete any old config and create a fresh one:

```powershell
kubectl delete configmap config-bundle --ignore-not-found
kubectl create configmap config-bundle --from-file=config/config_bundle.npz --from-file=config/config_meta.json
```

Verify:

```powershell
kubectl get configmap config-bundle
```

Should show `DATA: 2`.

### B3. Submit the simulation job

```powershell
kubectl apply -f k8s/job.yaml
```

### B4. Monitor progress

```powershell
# Overall progress
kubectl get job etf-mc-job

# Watch individual pods
kubectl get pods --watch

# Check logs of a specific worker
kubectl logs etf-mc-job-0-<pod-suffix>
```

Wait until `COMPLETIONS` shows `100/100`.

### B5. Retrieve results

Since results are stored in emptyDir (temporary pod storage), you need to pull them before cleanup. From a running or completed pod:

```powershell
# List completed pods
kubectl get pods --field-selector=status.phase=Succeeded

# Copy results from a pod (while it still exists)
kubectl cp <pod-name>:/data/results ./results
```

> **Note:** emptyDir volumes are lost when pods are deleted. Pull results
> promptly after the job completes.

### B6. Aggregate results locally

```powershell
python -m etf_fairvalue.aggregate
```

Output:
- `results/summary_stats.json` — mean, median, std, percentiles, premium/discount
- `results/nav_distribution.png` — histogram with KDE overlay

### B7. Clean up the job

After retrieving results, delete the job to free resources:

```powershell
kubectl delete job etf-mc-job
```

---

## Quick Reference

| Command | What it does |
|---|---|
| `docker build --platform linux/amd64 -t etf-mc-worker:latest .` | Build container image |
| `docker push <acr>.azurecr.io/etf-mc-worker:latest` | Push image to registry |
| `kubectl get nodes` | Check cluster nodes |
| `kubectl get job etf-mc-job` | Check job progress |
| `kubectl get pods --watch` | Watch pods live |
| `kubectl logs <pod-name>` | View worker output |
| `kubectl delete job etf-mc-job` | Clean up finished job |
| `kubectl delete configmap config-bundle` | Remove old config |

## Key Concepts

- **Docker image** — a portable snapshot of your code + dependencies. Built once, runs identically everywhere.
- **ACR** — Azure Container Registry. A private library where your images are stored.
- **AKS** — Azure Kubernetes Service. Manages VMs (nodes) and schedules containers onto them.
- **Node pool** — a group of VMs. System pool runs K8s internals, User pool runs your work.
- **Indexed Job** — K8s runs N containers, each getting a unique index (0 to N-1) via `JOB_COMPLETION_INDEX`.
- **ConfigMap** — small files stored in K8s, mounted into containers as if they were local files.
- **emptyDir** — temporary storage that exists for the lifetime of a pod.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ErrImagePull` | AKS can't pull from ACR | Run `az aks update --attach-acr` and resubmit |
| `no match for platform in manifest` | Image built for wrong OS/arch | Rebuild with `--platform linux/amd64` |
| `ImagePullBackOff` | Same as ErrImagePull, just K8s backing off retries | Fix the pull error, delete job, resubmit |
| Pods stuck in `Pending` | Not enough resources on nodes | Reduce `parallelism` or add nodes |
| `CrashLoopBackOff` | Worker code is crashing | Check `kubectl logs <pod>` for Python errors |

### Key constants

| Constant | Value |
|---|---|
| `TRADING_DAYS_PER_YEAR` | 252 |
| Default `horizon_days` | 5 trading days |
| Default `num_paths` per worker | 10,000 |
| Default number of workers | 100 |
| Total paths | 1,000,000 |

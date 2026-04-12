## User Guide (after installation)

- make sure cluster is running
- fetch data
- Upload config to K8s
- navigate to project folder
- login to Azure on your terminal
- connect AKS cluster to access confing file
```
az aks get-credentials --resource-group <resource-group-name> --name <aks-cluster-name>
```
- reupload the config bundle with the newly fetched data
```
kubectl delete configmap config-bundle --ignore-not-found
kubectl create configmap config-bundle --from-file=config/config_bundle.npz --from-file=config/config_meta.json
```
- delete old job and push the new one to the workers
```
kubectl delete job etf-mc-worker --ignore-not-found
kubectl apply -f etf_fairvalue/k8s/worker-job.yaml
```
- monitor progress
```
kubectl get job etf-mc-job
#or
kubectl get pods --watch
```

### B5. Retrieve results

Results should be stored in Azure File Share. Pull them to your local laptop:
´´´
az storage file download-batch --destination ./results --source results --account-name samontecarloengine --account-key <your-key>
´´´




Output:
- `results/summary_stats.json` — mean, median, std, percentiles, premium/discount
- `results/nav_distribution.png` — histogram with KDE overlay

### B7. Clean up the job

After retrieving results, delete the job to free resources:

```powershell
kubectl delete job etf-mc-job
```

## User Guide (after installation)

### Run workers
- make sure cluster is running
- fetch data
- Upload config to K8s
- navigate to project folder
- login to Azure on your terminal
- skip this next step if you haven't made changes to the worker file:
```
docker build --platform linux/amd64 -t etf-mc-worker:latest .
az acr login --name <acr-name>
docker tag etf-mc-worker:latest <acr-name>.azurecr.io/etf-mc-worker:latest
docker push <acr-name>.azurecr.io/etf-mc-worker:latest
```

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
kubectl apply -f k8s/job.yaml
```
- monitor progress
```
kubectl get job etf-mc-job
#or
kubectl get pods --watch
```

### Retrieve results
Results should be stored in Azure File Share. Pull them to your local laptop:
```
az storage file download-batch --destination ./results --source results --account-name samontecarloengine --account-key <your-key>
```

Output:
- `results/summary_stats.json` — mean, median, std, percentiles, premium/discount
- `results/nav_distribution.png` — histogram with KDE overlay

Delete job to free capacity:
```
kubectl delete job etf-mc-job
```

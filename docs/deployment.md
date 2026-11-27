# Deployment: Claims & Policy Copilot

The service runs as an Azure Container App in UK South. It was deployed from the command line on 27 Nov 2026. Everything here uses synthetic data only.

## Architecture in one paragraph
Source code lives in GitHub. A container image is built in Azure Container Registry from the `Dockerfile`. Azure Container Apps runs the image behind a public HTTPS address. The app calls Microsoft Foundry (chat and embedding models) using its own managed identity, so no model key is stored anywhere. Console output, including one `AUDIT` line per answered question, goes to the Log Analytics workspace created with the environment.

## Resources (resource group `rg-cpc-dev-uks`, UK South)
| Resource | Name | Purpose |
|---|---|---|
| Foundry resource and project | `foundry-cpc-dev-471` / `claims-copilot` | Chat model `gpt-4.1-mini`, embedding model `text-embedding-3-small` |
| Container registry (Basic) | `crcpcdev471` | Stores the image `claims-copilot:<tag>` |
| Container Apps environment | `cae-cpc-dev` | Shared hosting space and log workspace |
| Container app | `ca-cpc-dev` | Runs the API; scales 0 to 2 replicas |

## Security decisions
- **No model keys.** The app's system-assigned identity holds the roles "Azure AI User" and "Cognitive Services OpenAI User" on the Foundry resource.
- **API key on `/ask`.** The key is stored as a Container Apps secret (`api-key`) and read by the app as `API_KEY`. `/health` and `/docs` are open; only `/ask`, which spends model budget, needs the key.
- **No settings baked into the image.** Endpoint and deployment names are environment variables.
- **Registry pull uses the app identity**, not a registry password.
- Open item: `/docs` is public. Disable it or protect it before any real use.

## First deployment (commands used)
```
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry

az acr create --name crcpcdev471 --resource-group rg-cpc-dev-uks --location uksouth --sku Basic
az containerapp env create --name cae-cpc-dev --resource-group rg-cpc-dev-uks --location uksouth

az acr build --registry crcpcdev471 --image claims-copilot:v1 .

az containerapp create --name ca-cpc-dev --resource-group rg-cpc-dev-uks \
  --environment cae-cpc-dev --image crcpcdev471.azurecr.io/claims-copilot:v1 \
  --registry-server crcpcdev471.azurecr.io --registry-identity system --system-assigned \
  --target-port 8000 --ingress external --min-replicas 0 --max-replicas 2 --cpu 0.5 --memory 1.0Gi \
  --secrets "api-key=<generated key>" \
  --env-vars "FOUNDRY_PROJECT_ENDPOINT=<project endpoint>" "CHAT_DEPLOYMENT=gpt-4.1-mini" \
             "EMBED_DEPLOYMENT=text-embedding-3-small" "API_KEY=secretref:api-key"

# let the app identity use Foundry
az role assignment create --assignee-object-id <app principal id> --assignee-principal-type ServicePrincipal \
  --role "Azure AI User" --scope <foundry resource id>
az role assignment create --assignee-object-id <app principal id> --assignee-principal-type ServicePrincipal \
  --role "Cognitive Services OpenAI User" --scope <foundry resource id>
```

## Release a new version
```
az acr build --registry crcpcdev471 --image claims-copilot:v2 .
az containerapp update --name ca-cpc-dev --resource-group rg-cpc-dev-uks --image crcpcdev471.azurecr.io/claims-copilot:v2
```

## Roll back
Redeploy the previous tag:
```
az containerapp update --name ca-cpc-dev --resource-group rg-cpc-dev-uks --image crcpcdev471.azurecr.io/claims-copilot:v1
```
Each update also creates a numbered revision (`az containerapp revision list ...`).

## Check health and logs
```
Invoke-RestMethod https://<app address>/health
az containerapp logs show --name ca-cpc-dev --resource-group rg-cpc-dev-uks --tail 50
```
Audit lines start with `AUDIT` and contain the request id, question, question type, clauses used, answer and seconds. With real customer data these would need redaction, access control and a retention period.

## Known behaviour
- **Cold start:** with minimum replicas set to 0, the first request after idle takes longer (observed up to roughly 30 s is expected; measure and record).
- **Latency:** the first live `/ask` call took 4.77 s.
- **Cost:** consumption billing; the registry (Basic) has a small monthly charge. A budget alert is configured. To stop all charges at the end of the project, delete the resources, or the whole resource group (this also deletes the Foundry project).

## Next
GitHub Actions: run tests on pull requests; on merge to `main` build the image tagged with the commit id and update the app, logging in to Azure with OIDC (no stored secrets).

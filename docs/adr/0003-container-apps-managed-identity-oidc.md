# ADR 0003: Azure Container Apps, managed identity and OIDC deployment

- **Status:** Accepted
- **Date:** 27 November 2026

## Context

The service is a small stateless API with bursty, low traffic. It must call Foundry without keys in code, protect its endpoint, deploy automatically after tests pass, and cost almost nothing when idle.

## Decision

- **Hosting:** Azure Container Apps (UK South) running a Docker image from Azure Container Registry, scaling to zero when idle.
- **Access to Foundry:** the app's system-assigned **managed identity**, with a role assignment on the Foundry resource. The code uses `DefaultAzureCredential`, which uses `az login` locally and the managed identity in Azure.
- **Access to the registry:** the same identity pulls the image, so there are no registry passwords.
- **Endpoint protection:** `/ask` requires an `X-API-Key` header. The key is a Container Apps secret, referenced with `secretref`, and compared in constant time.
- **Deployment:** GitHub Actions deploys on merge to `main`. It logs in with **OIDC** (a federated credential that trusts only `refs/heads/main` of this repository), builds with `az acr build` tagged with the commit ID, updates the app, and checks `/health`. The deploy identity has Contributor on one resource group only.

## Alternatives considered

| Option | Why not |
|---|---|
| App Service | Fine for this workload, but does not scale to zero on common plans, so idle cost is higher. |
| AKS | Far more operational work than a single small API justifies. |
| Azure Functions | Possible, but a container keeps local, test and production environments identical and keeps the API a normal FastAPI app. |
| API keys for the model in app settings | Keys can leak and need rotation. Managed identity avoids storing them at all. |
| A service principal secret stored in GitHub | A long-lived secret that can leak. OIDC issues short-lived tokens and stores nothing. |

## Consequences

- Idle cost is close to zero, but the first request after a quiet period waits for a cold start (20 to 40 seconds seen in practice).
- No model keys or registry passwords exist to rotate or leak.
- Every running version maps to a commit, so rollback means activating an earlier revision.
- **Known gaps:** `/docs` is public, and a single shared API key gives no per-user control. A production version would use Entra ID authentication, a private endpoint, and a separate production environment with manual approval before deploy.
- Using a GitHub `environment:` in the deploy job would change the token subject and require a second federated credential. This was avoided for now.

# 13: Deployment + CI/CD (HITL — needs Azure access)

- **Type:** HITL
- **Spec:** SPEC.md §2, deployment topology
- **Blocked by:** #01–#12

## What to build

Production infrastructure and pipelines.

1. Dockerfiles: web (FastAPI) + worker (Celery) + beat (same image, different command).
2. Provision: Azure Container Apps (web + worker + beat), Azure Database for PostgreSQL Flexible Server (with `pgvector`), Azure Cache for Redis, Azure Blob Storage, Azure Key Vault.
3. Entra ID app registration for SSO (#10).
4. GitHub Actions: build image → push ACR → deploy Container Apps; run `pytest`/`mypy`/`ruff` on PR.
5. Environments: dev + prod.

## Acceptance criteria

- [ ] Web + worker + beat deployed to Container Apps
- [ ] Postgres (pgvector) + Redis reachable from the app
- [ ] Secrets in Key Vault (not in code/repo)
- [ ] CI runs tests + type check + lint on PR
- [ ] Dev and prod environments both deployable

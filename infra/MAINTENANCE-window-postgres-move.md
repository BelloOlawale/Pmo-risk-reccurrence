# Maintenance window — move PostgreSQL into the app region

**Status:** prepared, not executed
**Tooling:** `infra/move-postgres-region.sh` + `infra/copy_postgres.py` (validated against local Postgres 16 + pgvector)
**Estimated window:** ~20–30 minutes; user-visible disruption limited to the cutover redeploy (~2–5 min, zero-downtime roll).

---

## 1. Why

The Container Apps run in **East US**; the PostgreSQL flexible server lives in
**UK South**. Every query crosses regions — measured from inside the web
container:

```
connect_ms 595      # fresh connection
query_ms   154 76 76 77 77   # steady-state round-trip
```

In-region this is a few ms. Co-locating the database removes the source of the
lag on every page. (Web/DB CPU are both near-idle, so this is pure latency.)

**Reproduce the baseline before you start:**

```bash
bash infra/check-db-latency.sh dev
```

---

## 2. Scope and impact

| Item | Detail |
|---|---|
| Create | New PostgreSQL flexible server in **East US** (`riskapp-dev-postgres-eastus`) |
| Copy | All application tables (272 risks / 21 projects + audit/notifications/issues) |
| Repoint | `RISKAPP_DATABASE_URL` secret on `web`, `worker`, `beat` |
| Not touched | Blob storage, Redis, Entra config, frontend |
| Rollback | Restore the backed-up `deploy.dev.env` and redeploy apps (old server left running) |
| Downtime | Cutover only; Container Apps rolls revisions, so it is near zero. Background jobs pause briefly. |

**Approval / owner:** _<fill in>_

---

## 3. Pre-requisites

- [ ] Windows maintenance window agreed with the PMO stakeholders.
- [ ] `az login` as an account with Contributor on `rg-riskapp-dev`.
- [ ] Backend venv active with `alembic` installed (`pip install -e "backend[dev]"`).
- [ ] Choose the new server's admin password and export it (never committed):
      `export PG_ADMIN_PASSWORD='...'`
- [ ] Confirm no one is mid-data-entry (the copy is a point-in-time snapshot).

---

## 4. Window steps

### T+0 — Baseline and safety
```bash
cd app
bash infra/check-db-latency.sh dev          # record connect_ms / query_ms
git status --short                          # tree should be clean
cp infra/deploy.dev.env "infra/deploy.dev.env.manual-bak"   # belt-and-braces
```

### T+2 — Create target server and copy data (production untouched)
```bash
bash infra/move-postgres-region.sh dev --yes
```
This: creates `riskapp-dev-postgres-eastus` (East US, Burstable B2s, PG 16,
public access = Azure services), applies `alembic upgrade head`, copies every
table in FK order, resets identity sequences, and **verifies row counts match**.
The script refuses to copy into a non-empty target.

Expected: server create 5–10 min, migrations <1 min, copy <1 min.
The source server and the live app keep serving throughout.

### T+12 — Verify the copy
```bash
# Row counts on both sides (uses the copy tool's own check — re-running is safe
# because it refuses a populated target, so use a direct comparison instead)
```
Compare a few counts manually with `psql`/your client, or trust the tool's
"Copy complete; row counts match." confirmation. Spot-check in the target:
users, projects, risks, issues, and that `risks.embedding` has 1536 dims.

### T+15 — Cutover
```bash
bash infra/move-postgres-region.sh dev --yes --cutover
```
This backs up `deploy.dev.env` (timestamped), rewrites the DB host to the East
US server, and redeploys `web,worker,beat` (Bicep `apps` stage). Web runs
`alembic upgrade head` on start (no-op — already at head) before serving.

### T+20 — Post-window verification
```bash
bash infra/check-db-latency.sh dev          # expect query_ms single digits
curl -fsS https://riskapp-dev-web.lemonsand-ee3845bc.eastus.azurecontainerapps.io/health
for a in web worker beat; do
  az containerapp revision list -g rg-riskapp-dev -n riskapp-dev-$a \
    --query "[?properties.active].{r:name,h:properties.healthState}" -o tsv | tail -1
done
```
Then smoke-test the app: sign in, open a register, open a dashboard, add a risk.

---

## 5. Rollback (any time)

The old server is left running and untouched.

```bash
cp infra/deploy.dev.env.bak.<timestamp>      infra/deploy.dev.env
bash infra/deploy-service.sh dev --service web,worker,beat --stage apps
```

Any data written to the new server during the window would need to be copied
back — only relevant if you cut over and then roll back. Keep the window short
and low-traffic to minimise this.

---

## 6. Post-window cleanup

- [ ] Watch the app for a day; confirm latency stays low and no errors.
- [ ] Decommission the old server:
      `az postgres flexible-server delete -g rg-riskapp-dev -n riskapp-dev-postgres --yes`
- [ ] Delete stale `deploy.dev.env.bak.*` files.
- [ ] Rotate the database admin password (it has appeared in diagnostic output
      during troubleshooting) and update `deploy.dev.env`.
- [ ] Note the outcome in `infra/RUNBOOK.md §7`.

---

## 7. Appendix — what the tooling does

- `infra/move-postgres-region.sh` — orchestrates create → migrate → copy → cutover,
  with preflights (az/python/alembic present, `PG_ADMIN_PASSWORD` set, DB URL
  parseable) and a dry run when `--yes` is omitted.
- `infra/copy_postgres.py` — copies `riskapp.models.Base.metadata.sorted_tables`
  (FK order) via SQLAlchemy, resets identity sequences, and fails if row counts
  differ or the target is already populated.
- `infra/check-db-latency.sh` — measures connect + query round-trips from inside
  the running web container.

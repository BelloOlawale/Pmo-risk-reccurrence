# PMO Risk Recurrence Predictor — Architecture

> Authoritative architecture overview. Complements `SPEC.md` (the product/spec
> decisions) and `README.md` (quickstart). This document explains *how the
> system is put together*, with a deep dive on authentication and authorization.

---

## 1. Purpose

A **standalone web application** that automates project risk management:

1. A PM onboards a project.
2. The system **suggests recurring risks** from historical registers (hybrid
   search + LLM analysis with grounded citations).
3. Risks are captured, scored, monitored on SLA deadlines, escalated on breach,
   resolved, and closed — feeding learnings back so future suggestions improve.

Explicitly **not** used: SharePoint, Power Apps, Power BI, Power Automate.

---

## 2. High-level architecture

```
                         ┌───────────────────────────────────────────────┐
                         │                    Azure (prod)               │
                         │  ┌────────────────────┐  ┌─────────────────┐  │
  ┌──────────┐  HTTPS    │  │  Container Apps     │  │  Container Apps │  │
  │  Browser │──────────▶│  │  (web: FastAPI +   │  │  (Celery worker │  │
  │  (React  │   MSAL    │  │   serve static SPA)│  │   + Beat)       │  │
  │   SPA)   │  redirect │  └─────────┬──────────┘  └────────┬────────┘  │
  └──────────┘            │           │                        │          │
       │                  │           ▼                        ▼          │
       │  Entra ID        │  ┌─────────────────────────────────────────┐  │
       └── login ────────▶│  │  PostgreSQL Flexible Server + pgvector  │  │
                          │  │  Redis (broker/result backend)          │  │
                          │  │  Blob Storage (registers, citations)    │  │
                          │  │  Azure OpenAI (chat + embeddings)       │  │
                          │  │  Azure Communication Services (email)   │  │
                          │  │  Key Vault (secrets)                    │  │
                          │  └─────────────────────────────────────────┘  │
                          └───────────────────────────────────────────────┘

  Local (dev): the same components, but Postgres runs as a pgvector Docker
  container, Celery/Redis optional, and auth has a header-based dev mode.
```

**Runtime topology**

| Concern | Choice |
|---|---|
| Backend | Python + FastAPI (single modular monolith) |
| Frontend | React + TypeScript (Vite), charts via Apache ECharts |
| Database | PostgreSQL (Azure Flexible Server) + **pgvector** |
| Background jobs | Celery + Redis + Celery Beat |
| File storage | Azure Blob Storage (uploaded registers, citation links) |
| Email | Azure Communication Services |
| LLM | Azure OpenAI (GPT-4o-mini chat, text-embedding-3-small) |
| Auth | Entra ID (M365) SSO via OIDC |
| Secrets | Azure Key Vault (prod) / `.env` (dev) |
| CI/CD | GitHub Actions → ACR → Container Apps |

---

## 3. Repository layout

```
app/
├── backend/
│   ├── src/riskapp/
│   │   ├── main.py            # FastAPI app + all HTTP endpoints
│   │   ├── auth.py            # Entra token validation, roles, row-level scoping
│   │   ├── models.py          # SQLAlchemy ORM models (schema)
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── services.py        # business operations (create/accept/dismiss, …)
│   │   ├── suggestions.py     # hybrid retrieval + suggestion lifecycle
│   │   ├── domain/            # pure, side-effect-free logic (no DB/HTTP)
│   │   │   ├── scoring.py     # 3×3 rating matrix
│   │   │   ├── status.py      # lifecycle state machine
│   │   │   ├── sla.py         # deadlines, warning windows, activity detection
│   │   │   ├── retrieval.py   # merge/dedupe/rank candidates
│   │   │   └── similarity.py  # cosine fallback (SQLite dev only)
│   │   ├── vector_store.py    # pgvector semantic search (<=> cosine, HNSW)
│   │   ├── embeddings.py      # Azure OpenAI embeddings client
│   │   ├── llm/               # chat client, prompts, citation audit
│   │   ├── import_pipeline/   # Excel parse → field map → import
│   │   ├── notifications.py   # ACS email + in-app notifications
│   │   ├── scheduler.py       # Celery Beat schedule
│   │   ├── tasks.py           # Celery tasks (SLA monitor, emails, …)
│   │   ├── audit.py           # append-only audit logging helper
│   │   ├── config.py          # pydantic-settings (RISKAPP_* env vars)
│   │   └── db.py              # engine + session factory
│   ├── migrations/            # Alembic migrations
│   ├── tests/                 # pytest suite (275+ tests)
│   ├── scripts/seed_demo_risks.py
│   └── docker-compose.yml     # local pgvector Postgres
├── frontend/
│   └── src/
│       ├── main.tsx / App.tsx      # entry + routes
│       ├── auth/                   # MSAL config, AuthContext, auth store
│       ├── api/                    # fetch client + TypeScript types
│       ├── components/             # Layout, charts (ECharts), RiskTable, …
│       ├── pages/                  # registers, onboard, project, risk, portfolio
│       ├── utils/                  # formatting, aggregations, colors, status
│       └── hooks/useApi.ts
├── SPEC.md               # authoritative product/spec decisions
├── ARCHITECTURE.md       # this document
└── README.md             # quickstart
```

---

## 4. Backend (FastAPI monolith)

FastAPI serves **both** the JSON API and (in production) the built React SPA.
In development the two run separately (Vite dev server proxies `/api`).

The code is split into:

- **`domain/`** — pure, deterministic, exhaustively unit-tested logic with **no
  I/O**. This is the deepest, most stable layer (scoring, status machine, SLA,
  retrieval ranking).
- **`services.py`** — orchestrates the ORM models and domain logic.
- **`main.py`** — thin HTTP layer: parses requests, calls services, returns
  schemas. Authorization is enforced here (and in `auth.py`).
- **`auth.py`** — identity, roles, and row-level scoping (see §6).

---

## 5. Data model

Hierarchy (mirrors the `Project/<DEPARTMENT>/<PROJECT TYPE>/` folder layout):

```
department ──< project_type ──< project ──< risk ──< risk_audit_log (append-only)
```

| Entity | Purpose |
|---|---|
| `department` | Top org axis (e.g. "Digital Advisory"). Portfolio = across departments. |
| `project_type` | Lookup (~20 values), not an enum. |
| `project` | A client engagement (code, name, customer, dept, type, PM, dates, stage, status). |
| `risk` | Current-state record (all fields below). |
| `risk_audit_log` | **Append-only, immutable.** Every mutation writes a row. Source of truth for history. |
| `user` | Entra identity (upn, display_name) + local id. |
| `practice_lead` | department → person (notification CC). |
| `setting` | key/value config (PMO Lead email, thresholds). |
| `suggestion_dismissal` | per-project exclusions (dismissed/accepted suggestions never reappear). |
| `notification` | in-app notification (bell + unread). |

**Risk fields** (the important ones): `risk_code`, `description`, `category` /
`subcategory`, `risk_source`, `likelihood` / `impact` / `risk_rating`, `status`,
`source`, `source_file_name` / `source_file_url` / `source_risk_id`
(traceability), `llm_analysis`, `embedding` (`vector(1536)`), `sla_deadline` /
`sla_acknowledged` / `sla_manual_override`, `risk_start_date` / `risk_end_date`,
`owner_user_id`, closure fields (`root_cause`, `what_worked`,
`resolution_category`), and lifecycle timestamps.

---

## 6. Authentication & authorization (deep dive)

### 6.1 Two modes

| | **Production (Entra)** | **Development** |
|---|---|---|
| Trigger | `RISKAPP_ENTRA_TENANT_ID` is set | `RISKAPP_ENTRA_TENANT_ID` is empty |
| Identity | Entra OIDC bearer token | `X-User-Id` / `X-User-Role` headers |
| Frontend | MSAL redirect sign-in | sidebar role/user switcher |
| Default | — | System Admin (sees everything) |

The switch is **purely config-driven** — no code changes.

### 6.2 Production flow (Entra ID OIDC)

```
 ┌────────┐  1. loginRedirect()      ┌───────────────┐
 │  SPA   │ ───────────────────────▶ │  Microsoft    │
 │ (MSAL) │                          │  login (M365) │
 └────────┘                          └───────┬───────┘
     ▲  2. redirect back w/ auth code       │
     │  3. acquireTokenSilent → id + access │
     │     token (scopes: openid, profile,  │
     │     email, {clientId}/.default)      │
     │                                      ▼
 ┌────┴─────┐  4. Authorization: Bearer ┌─────────┐
 │  API     │ ─────────────────────────▶│ FastAPI │
 │  client  │                           │ backend │
 └──────────┘                           └────┬────┘
                                             │ 5. validate JWT (RS256, JWKS from
                                             │    {tenant}/discovery/v2.0/keys,
                                             │    aud = client_id,
                                             │    iss = {tenant}/v2.0)
                                             │ 6. roles  ← groups claim → group map
                                             │ 7. user_id ← upn → get_or_create_user
                                             ▼
                                      Principal(user_id, upn, roles)
```

1. **Frontend MSAL** (`@azure/msal-react`) is configured with the client id +
   tenant id from `VITE_ENTRA_CLIENT_ID` / `VITE_ENTRA_TENANT_ID`.
2. The API client (`src/api/client.ts`) attaches `Authorization: Bearer <token>`
   to every request.
3. **Backend** (`auth.py` → `get_principal`) validates the token against the
   tenant's JWKS (cached), checking signature, issuer, and audience.
4. **Roles** are resolved from the token's `groups` claim via the
   `RISKAPP_ENTRA_ROLE_GROUP_IDS` mapping (JSON: role name → group object id).
5. **Identity** is resolved by UPSERTING the `upn` into `users`
   (`get_or_create_user`), returning a stable local `user_id`.

### 6.3 UPN → user assignment

This is the wiring that makes row-level scoping work under Entra:

```python
# auth.py (simplified)
upn = token["preferred_username"] or token["upn"]
user = get_or_create_user(db, upn, display_name)   # upsert by upn
db.commit()                                          # stable id across requests
principal = Principal(user_id=user.id, upn=upn, roles=roles)
```

`principal.user_id` then flows into:

- **Project creation** — `POST /api/projects` assigns `pm_user_id` from an
  explicit `pm_upn` (resolved to a user id) or from the authenticated creator.
- **Risk accept** — `accept_risk` defaults the owner to `project.pm_user_id`.
- **Row-level scoping** — see §6.4.

### 6.4 Roles & row-level scoping

Three permission roles (mapped to Entra security groups):

| Role | Permissions |
|---|---|
| **System Admin** | everything: users, config, imports, all data |
| **PMO Lead** | portfolio, de-escalate, escalation handling, settings, import |
| **Project Manager** | create projects; full control of *own* projects' risks |

Record-level assignments (not permission roles): **Risk Owner** (per-risk) and
**Practice Lead** (department → notification recipient).

Enforcement (`auth.py`):

```python
can_access_project(principal, project):
    if principal.is_pmo_or_admin:  return True        # PMO Lead / Admin see all
    return principal.has_role(PROJECT_MANAGER)
           and principal.user_id is not None
           and project.pm_user_id == principal.user_id  # PM sees own projects

can_access_risk(principal, risk):
    if principal.is_pmo_or_admin:  return True
    if risk.owner_user_id == principal.user_id: return True   # owner
    return PM and risk.project.pm_user_id == principal.user_id # project PM
```

The API layer enforces these; the pure functions are unit-tested independently
of Entra.

---

## 7. Domain logic (pure)

- **Scoring** — `risk_rating = f(likelihood, impact)` via the 3×3 matrix (no
  Critical band, no 1–25, no 5 dimensions).
- **Status lifecycle** — `Suggested → Open → In Progress → Escalated → Event →
  Resolved → Closed`, plus `Dismissed` (terminal). Enforced transitions; every
  mutation is audit-logged.
- **SLA** — response windows (High 24h / Medium 48h / Low 120h), warning
  windows (4h / 12h / 24h). Deadline anchored at `risk_start_date` (midnight in
  the business timezone, `Africa/Lagos` default) or `created_at`. Activity
  (owner edit / status change / acknowledge) permanently satisfies the SLA.

---

## 8. Risk suggestions ("recurrence")

On project onboarding, the system suggests recurring risks:

1. **Exact** — same Department + ProjectType.
2. **Keyword** — category/subcategory/description token match.
3. **Semantic** — pgvector embedding similarity (`1 - (embedding <=> query)`,
   HNSW-accelerated).

Candidates are merged/deduped/ranked (exact → keyword → semantic), then Azure
OpenAI generates the landscape overview, per-risk analysis, and recommendations
with **grounded citations** (`[RiskID, file.xlsx]`). Every citation is audited
against the retrieved payload.

There are two suggestion surfaces:

- `POST /api/projects/{id}/suggest` — full LLM analysis (needs Azure OpenAI).
- `GET  /api/projects/{id}/suggestions` — **deterministic** exact+keyword list
  (no LLM/embeddings), used by the onboard → accept/dismiss flow. Accepting
  creates an Open risk (with source-file traceability); dismissing records a
  per-project exclusion so it never reappears.

---

## 9. Background jobs (Celery + Beat)

- Hourly SLA monitor (remind / escalate on breach).
- Daily start-date check (email owner when `risk_start_date` is today).
- Weekly summary (Mon 8 AM) to PM + PMO Lead.
- Async email sending.
- Async LLM suggestion generation.
- Admin bulk import.

---

## 10. Dashboards & reporting (React + ECharts)

- **Project dashboard** — KPI cards (total / high / escalated / SLA compliance
  %), donut (rating), stacked bar (status×rating), treemap (category), SLA
  countdown list, and a Risk Register table (conditional formatting, search,
  multi-column filters, sort, drill-through to risk detail).
- **Risk detail** — full info, status-history timeline (from the append-only
  audit log), source-file citation link, and Acknowledge / Accept / Dismiss /
  De-escalate / edit / status-transition actions.
- **Portfolio dashboard** (PMO Lead) — project×category heatmap, risk-by-project
  bar, escalation trend line, portfolio KPIs.

---

## 11. API surface

`/health`, then (all under `/api`):

- `departments`, `project-types` — create (lookup).
- `projects` — create/list/get; `projects/{id}/risks`.
- `risks` — create (Quick Add), get, patch, `acknowledge`, `accept`, `dismiss`,
  `de-escalate`, `history`.
- `projects/{id}/suggest`, `projects/{id}/suggestions`,
  `.../suggestions/accept`, `.../suggestions/dismiss`.
- `notifications` — list, mark-read.
- `imports` — initiate (upload xlsx), confirm (field mapping + run).

---

## 12. Deployment

- **dev** — local pgvector Postgres (`docker compose up -d`, port 5433), uvicorn
  on `:8000`, Vite on `:5173` (proxies `/api` → `:8000`).
- **prod** — GitHub Actions → build/push to Azure Container Registry → Azure
  Container Apps (web + Celery worker + Beat), secrets in Key Vault.

### Configuration (env vars, `RISKAPP_*` prefix)

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy connection string (Postgres + pgvector). |
| `AZURE_OPENAI_*` | endpoint, key, embedding/chat deployments, api-version. |
| `ENTRA_TENANT_ID` | Empty = dev mode; set = Entra OIDC validation. |
| `ENTRA_CLIENT_ID` | Audience for token validation. |
| `ENTRA_CLIENT_SECRET` | Stored for confidential-client flows (not used by JWKS validation). |
| `ENTRA_ROLE_GROUP_IDS` | JSON mapping role → Entra group object id. |
| `REDIS_URL` | Celery broker. |
| `ACS_*` | Azure Communication Services (email). |
| `BLOB_*` | Uploaded registers / citation links. |
| `APP_TIMEZONE` | Business timezone for SLA date anchors (default `Africa/Lagos`). |
| `CORS_ORIGINS` | Allowed SPA origins (default `http://localhost:5173`). |

Frontend (`VITE_*`): `VITE_API_BASE_URL` (empty = dev proxy), `VITE_ENTRA_CLIENT_ID`,
`VITE_ENTRA_TENANT_ID`.

---

## 13. Running it

```bash
# Backend (Entra mode is active when .env has the Entra vars)
cd app/backend
docker compose up -d                 # local pgvector Postgres
python -m uvicorn riskapp.main:app --reload --port 8000

# Frontend (MSAL sign-in when VITE_ENTRA_* are set)
cd app/frontend
npm install && npm run dev           # http://localhost:5173
```

**To switch back to dev mode** (header auth + sidebar role switcher): comment
out the `RISKAPP_ENTRA_*` lines in `backend/.env` and the `VITE_ENTRA_*` lines
in `frontend/.env`.

---

## 14. Security notes

- Tokens are validated server-side (RS256 + JWKS + audience + issuer) — the SPA
  never does authorization.
- Row-level scoping is enforced in the API layer, not trusted from the client.
- The audit log is append-only (rows never updated/deleted).
- LLM citations are audited for groundedness before display.
- Secrets live in Key Vault (prod) / `.env` (dev, gitignored). `.env` must never
  contain real secrets in version control.

### Azure portal prerequisites for SSO (one-time)

1. Register `http://localhost:5173` as a SPA redirect URI on the app registration.
2. Enable the **groups claim** (Token configuration → add group claims →
   SecurityGroup), otherwise the token won't carry `groups` and every user gets
   no role.

---

## 15. Current state

- **Done:** domain core, data model, audit trail, SLA, historical import (272
  risks / 21 projects), hybrid retrieval, pgvector, LLM suggestions + citation
  audit, accept/edit/dismiss + Quick Add, Celery scheduler, notifications,
  RBAC + Entra SSO + UPN→user wiring, admin import, and the full frontend
  (registers / onboard / dashboards / suggestions accept-dismiss).
- **Remaining (human/Azure):** deployment + CI/CD (#13), E2E validation + docs
  (#14), and generating the risk embeddings against Azure OpenAI.

# Codebase Design — Deep Modules and Refactor Plan

> **Status:** design artifact. No runtime behaviour changes.
> **Authored on:** `prod` at `2a715c7`.
> **Goal:** a target module design that can be applied to `main` later in small,
> behaviour-preserving steps.
>
> Read alongside `ARCHITECTURE.md` (how the system works today) and
> `docs/RISK_STATUS_MODEL.md` (authoritative lifecycle rules).

---

## 1. Executive summary

The application is already a sound modular monolith: a pure `domain/` core, a
FastAPI HTTP layer, SQLAlchemy persistence, Celery jobs, and a React SPA. The
weak point is not the technology split — it is that **too much behaviour leaks
into the HTTP module and into the service/scheduler call sites**.

Concretely:

- `main.py` is 1,428 lines and mixes routing, authorization, SQL, serialization,
  transactions, notifications, and provider wiring.
- `services.py` is 871 lines and both decides business rules and commits
  transactions; it also takes HTTP Pydantic models as command inputs.
- Authorization policy lives beside token verification in `auth.py`.
- Notifications are triggered from `main.py`, `scheduler.py`, and `services.py`,
  so a lifecycle change has to be made in several places.
- The frontend mirrors backend types and status rules by hand and calls raw
  `/api/...` paths from pages and components.

The target design is **not** a rewrite. It keeps the modular monolith and the
pure domain core, and deepens four modules:

1. **Risk lifecycle** — one application module owns every risk mutation,
   transition, audit row, Issue creation, and notification event.
2. **Authorization policy** — one declarative policy module, separate from
   identity/token adapters.
3. **Workflow modules** — suggestions, reporting, imports, and read models each
   expose a small interface and hide their queries, orchestration, and
   side effects.
4. **Frontend feature modules + generated contracts** — pages consume typed
   feature APIs, not raw endpoint strings; backend OpenAPI is the source of
   truth for types and status transitions.

The migration is phased so every step is independently reviewable, reversible,
and testable through the same interfaces callers already use.

---

## 2. Design principles

These use the vocabulary from the codebase-design skill.

- **Module** — anything with an interface and an implementation. A function,
  class, package, or slice. Not "component", "service", or "unit".
- **Interface** — everything a caller must know: types, invariants, ordering,
  errors, configuration, and performance expectations.
- **Depth** — leverage at the interface. A deep module hides a large amount of
  behaviour behind a small surface.
- **Seam** — the place where an interface lives and behaviour can be replaced.
- **Adapter** — a concrete implementation at a seam.
- **Locality** — one place to change, test, and reason about a rule.

Rules applied in this design:

1. **Put the seam where variation is real.** Do not add a repository port per
   model. The database has two adapters already (Postgres in production,
   in-memory SQLite in tests), so the persistence seam is the session/unit of
   work factory, not a dozen shallow repositories.
2. **The interface is the test surface.** Tests for a workflow call the workflow,
   not its private query helpers.
3. **Return results, don't emit hidden side effects.** Mutating workflows return
   a result plus domain events; the composition root dispatches notifications
   after commit.
4. **Accept dependencies, don't create them.** Workflows receive a unit-of-work
   factory, a clock, and ports. No module-level `build_notification_service()`
   calls.
5. **Keep the domain pure.** `domain/` continues to import only the standard
   library and its own modules.

---

## 3. Current-state assessment

### 3.1 What to keep

| Asset | Why it stays |
|---|---|
| `domain/scoring.py`, `status.py`, `sla.py`, `retrieval.py`, `similarity.py` | Pure, deterministic, unit-tested; no I/O. This is the deepest part of the codebase. |
| Append-only `risk_audit_log` | Correct source of truth for history; every mutation should continue to write it. |
| Provider protocols (`ChatProvider`, `EmbeddingProvider`, `BlobStorageProvider`, `EmailProvider`) | Real seams with production adapters and test fakes. Keep and apply the same pattern elsewhere. |
| `scheduler.py` with injected `today` and notifier | Excellent testability; Celery wrappers stay thin. |
| SQLite in-memory test suite with `TestClient` | Fast, deterministic; 89 tests already exercise the API. |
| Modular monolith deployment | One web app, one worker/Beat process. No operational reason to split services. |

### 3.2 Friction, with evidence

| Symptom | Evidence | Consequence |
|---|---|---|
| HTTP module is a god module | `backend/src/riskapp/main.py` — 1,428 lines; 36 direct `db.*` calls; 8 `commit()` calls; endpoints build notifications and serialize aggregates inline | Route changes touch business rules; workflows cannot be reused by Celery or tests without HTTP |
| Service layer mixes decisions and transactions | `services.py` — 871 lines; 13 `commit()` calls; functions accept `schemas.RiskCreate` / `RiskUpdate` | Callers cannot compose two operations in one transaction; HTTP contract changes ripple into business logic |
| Authorization is scattered | `auth.py` holds token validation plus `can_*` helpers; `main.py` re-checks action-specific rules in `patch_risk`, close, resolution, issue routes | Policy is hard to audit as a whole; easy to add an endpoint that misses a guard |
| Notification triggers are spread out | `build_notification_service()` / `notifier.notify` in `main.py` (6), `scheduler.py` (5), `tasks.py` (6), `reports.py` (2), `notifications.py` | One lifecycle event needs edits in multiple modules; DB commit and email ordering is inconsistent |
| Suggestion module has several jobs | `suggestions.py` — retrieval queries, LLM orchestration, citation audit, persistence, accept/dismiss lifecycle | Small changes require understanding the whole file; LLM failures and DB writes share one surface |
| Report aggregation and rendering are intertwined | `reports.py` — `build_weekly_report` plus 300+ lines of HTML/text rendering and delivery | Renderer changes can affect data assembly; hard to test a new format without the DB |
| HTTP contracts are one file | `schemas.py` — 507 lines for every feature | Merge conflicts; no ownership boundaries |
| Frontend endpoints and types are hand-maintained | `frontend/src/api/types.ts` mirrors backend by comment; 20+ raw `/api/...` literals across pages/components | Contract drift; status transitions mirrored in `utils/status.ts` |
| Large frontend pages own many concerns | `RiskDetailPage.tsx` 839 lines; `CreateRiskPage.tsx` 410; `RiskTable.tsx` 347 | Hard to test or reuse; UI and workflow changes collide |
| Caches are global and test-cleared | `cache.py` + module-level caches in `main.py`; `conftest.py` calls `clear_caches()` | Hidden coupling; invalidation is not owned by one module |

### 3.3 What is *not* wrong

This design deliberately does **not** claim the app needs microservices, event
sourcing, CQRS, or a repository per table. Those would add surface area without
leverage at this scale.

---

## 4. Target architecture

### 4.1 Dependency rule

```
                       ┌──────────────────────────────┐
  HTTP / Celery ─────▶ │  api/  (routers, deps)       │
                       └──────────────┬───────────────┘
                                      │ calls
                       ┌──────────────▼───────────────┐
                       │  application/ (workflows)    │
                       │  commands, ports, results    │
                       └──────┬───────────────┬───────┘
                              │ uses          │ defines
                       ┌──────▼──────┐  ┌─────▼───────────────────┐
                       │  domain/    │  │  ports (Protocols)      │
                       │  pure rules │  └─────▲───────────────────┘
                       └─────────────┘        │ implements
                       ┌──────────────────────┴───────────────────┐
                       │  adapters/ (DB, LLM, email, blob, auth)  │
                       └──────────────────────────────────────────┘
```

Allowed imports:

| From | May import |
|---|---|
| `domain/` | standard library, other `domain/` modules only |
| `application/` | `domain/`, its own command/result types, ports |
| `api/` | `application/` interfaces, HTTP contracts, FastAPI |
| `adapters/` | `domain/`, `application/` ports, third-party SDKs |
| `infrastructure/` | config, engine, Celery app; wires adapters in the composition root |

Forbidden after the migration:

- `api/` importing SQLAlchemy, ORM models, or `adapters/`.
- `application/` importing FastAPI, Pydantic HTTP schemas, or concrete adapters.
- `domain/` importing anything outside the standard library.
- `db.commit()` anywhere in `api/`.

### 4.2 Target backend layout

```
backend/src/riskapp/
├── api/
│   ├── app.py                 # create_app(), middleware, exception handlers
│   ├── deps.py                # Principal, UoW, provider dependencies
│   ├── errors.py              # domain error -> HTTP status mapping
│   └── routers/
│       ├── auth.py
│       ├── projects.py
│       ├── risks.py
│       ├── issues.py
│       ├── suggestions.py
│       ├── reports.py
│       ├── notifications.py
│       ├── imports.py
│       └── external.py
├── application/
│   ├── commands.py            # command/result dataclasses (no FastAPI/Pydantic HTTP)
│   ├── ports.py               # Clock, EmailPort, BlobPort, TokenVerifier, LLM ports
│   ├── risk_lifecycle.py      # create/update/transition/acknowledge/resolve/review
│   ├── risk_queries.py        # scoped read models for registers, detail, issues
│   ├── authorization.py       # policy: action + resource -> allow/deny
│   ├── suggestion_workflow.py # generate/list/accept/dismiss
│   ├── reporting.py           # build report data; renderer/sender ports
│   ├── notification_dispatch.py
│   ├── import_workflow.py
│   └── directory.py
├── domain/                    # existing pure modules + errors.py
├── adapters/
│   ├── persistence/
│   │   ├── models.py          # today's models.py (moved in cleanup phase)
│   │   ├── uow.py             # Session factory / transaction boundary
│   │   └── queries/           # feature query helpers if needed
│   ├── identity/
│   │   ├── entra.py
│   │   ├── local.py
│   │   └── headers.py
│   ├── llm/                   # today's llm/, embeddings.py, vector_store.py
│   ├── email/acs.py           # today's ACS adapter
│   ├── blob/azure.py
│   └── reporting/renderers.py # HTML + text renderers
├── contracts/                 # Pydantic schemas split by feature
│   ├── auth.py, projects.py, risks.py, issues.py, suggestions.py, …
├── infrastructure/
│   ├── config.py
│   ├── db.py
│   ├── celery_app.py
│   └── tasks.py
└── main.py                    # thin entrypoint: `app = create_app()`
```

The moves are mechanical and happen late. During the migration the old modules
stay as shims, so imports and tests keep working.

### 4.3 Target frontend layout

```
frontend/src/
├── app/
│   ├── App.tsx                # routes only
│   ├── providers.tsx          # auth + error boundary
│   └── routes.ts
├── features/
│   ├── auth/                  # session, sign-in, change-password
│   ├── projects/              # api.ts, hooks.ts, components/
│   ├── risks/                 # api.ts, hooks.ts, components/
│   ├── issues/
│   ├── suggestions/
│   ├── reports/
│   └── notifications/
├── shared/
│   ├── api/client.ts          # fetch + auth, no endpoint knowledge
│   ├── api/generated.ts       # generated from backend OpenAPI
│   ├── hooks/useApi.ts
│   ├── hooks/useMutation.ts
│   └── ui/                    # Badges, KpiCard, EChart, …
└── utils/                     # formatting/colors only
```

Each `features/<x>/api.ts` is the only place that knows endpoint paths and
response types. Pages compose hooks and presentational components; they do not
call `api.get('/api/...')` directly.

---

## 5. Deep modules and interfaces

The sketches below are the target interfaces. They are intentionally small;
the implementation behind them owns the complexity.

### 5.1 Identity vs authorization

Today `auth.py` does both token acquisition/validation and row-level policy.
Split it at the seam where variation is real:

- **Identity adapter** (`adapters/identity/*`): verifies a bearer token and
  returns an `Actor`. Three adapters exist: Entra, local password token, and
  test headers.
- **Authorization policy** (`application/authorization.py`): pure decisions over
  an `Actor` and a resource projection. No JWT, no HTTP, no ORM.

```python
# application/authorization.py
class Action(StrEnum):
    PROJECT_CREATE = "project:create"
    PROJECT_CLOSE = "project:close"
    RISK_UPDATE = "risk:update"
    RISK_ACKNOWLEDGE = "risk:acknowledge"
    RISK_REVIEW_RESOLUTION = "risk:review_resolution"
    RISK_CLOSE = "risk:close"
    RISK_DELETE = "risk:delete"
    ISSUE_VIEW = "issue:view"
    IMPORT_RUN = "import:run"

@dataclass(frozen=True)
class Actor:
    user_id: int | None
    roles: frozenset[Role]
    system: bool = False

class Policy:
    def require(self, actor: Actor, action: Action, resource: ResourceRef) -> None:
        """Raise Forbidden unless allowed. The only authorization entry point."""
```

`ResourceRef` is a small projection (`project_pm_user_id`, `risk_owner_user_id`,
`risk_status`, `project_status`) built by the workflow. Routes call the workflow
and never re-implement policy. `scheduler` uses `Actor(system=True)`.

**Why this is deep:** one table of actions and rules replaces scattered
`if` blocks, and the policy can be exhaustively tested as a matrix without
HTTP or a database.

### 5.2 Risk lifecycle

One application module owns every risk mutation. HTTP routes, external
acknowledgement links, suggestion acceptance, and scheduler jobs all call it.

```python
# application/risk_lifecycle.py
class RiskLifecycle:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        clock: Clock,
        policy: Policy,
    ) -> None: ...

    def create(self, command: CreateRisk, actor: Actor) -> LifecycleResult: ...
    def update(self, risk_id: int, command: UpdateRisk, actor: Actor) -> LifecycleResult: ...
    def transition(
        self,
        risk_id: int,
        target: RiskStatus,
        actor: Actor,
        detail: TransitionDetail | None = None,
    ) -> LifecycleResult: ...
    def acknowledge(self, risk_id: int, actor: Actor) -> LifecycleResult: ...
    def accept_suggestion(self, risk_id: int, command: AcceptSuggestion, actor: Actor) -> LifecycleResult: ...
    def dismiss_suggestion(self, risk_id: int, command: DismissSuggestion, actor: Actor) -> LifecycleResult: ...
    def submit_resolution(self, risk_id: int, command: SubmitResolution, actor: Actor) -> LifecycleResult: ...
    def review_resolution(self, risk_id: int, command: ReviewResolution, actor: Actor) -> LifecycleResult: ...
    def materialize(self, risk_id: int, actor: Actor) -> LifecycleResult: ...
```

`LifecycleResult` contains:

- a read-model snapshot of the risk (no lazy ORM objects),
- the domain events produced in the transaction,
- the list of audited field changes (for callers that need it).

Internally the module owns:

- transition validation (`domain/status.ensure_transition`),
- audit entries (`audit.record_change`),
- Issue creation / materialization (`ensure_issue_for_risk`),
- date/SLA validation and start-date activation,
- immutable-field and resolution-summary guards,
- one transaction boundary (commit/rollback),
- decision of *which* events occurred (not how they are delivered).

**Why this is deep:** callers learn six commands and one result. The rules,
queries, audit, and Issue side effects stay in one place. The duplicated
manual-vs-scheduled materialization logic disappears.

**Compatibility note:** keep `services.py` functions as thin wrappers around
`RiskLifecycle` during the migration so existing callers and tests do not break.

### 5.3 Risk queries and read models

Reads currently live in routes (`list_projects`, `list_risks`,
`_project_read`, issue serialization). Extract a query module that owns
scoping, eager loading, and projections:

```python
# application/risk_queries.py
class RiskQueries:
    def __init__(self, uow: Callable[[], UnitOfWork]) -> None: ...

    def list_visible(self, actor: Actor, filter: RiskFilter) -> list[RiskSummary]: ...
    def get_visible(self, actor: Actor, risk_id: int) -> RiskDetail: ...
    def project_register(self, actor: Actor, project_id: int) -> ProjectRegister: ...
    def project_issues(self, actor: Actor, project_id: int) -> list[IssueSummary]: ...
    def history(self, actor: Actor, risk_id: int) -> list[AuditEntry]: ...
```

The query module may use SQLAlchemy internally. It returns immutable projections,
not ORM objects. Authorization scoping is part of the interface, not something
each route remembers to apply.

### 5.4 Suggestion engine and workflow

Split the current `suggestions.py` into three responsibilities with one public
workflow interface:

```python
# application/suggestion_workflow.py
class SuggestionWorkflow:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        retrieval: RetrievalService,
        analyzer: SuggestionAnalyzer,   # owns LLM + citation audit
        lifecycle: RiskLifecycle,
        policy: Policy,
    ) -> None: ...

    def list(self, actor: Actor, project_id: int) -> list[SuggestedRisk]: ...
    def generate(self, actor: Actor, project_id: int) -> SuggestionBundle: ...
    def accept(self, actor: Actor, project_id: int, command: AcceptSuggestion) -> RiskDetail: ...
    def dismiss(self, actor: Actor, project_id: int, command: DismissSuggestion) -> None: ...
```

- `RetrievalService` hides exact/keyword/semantic queries, merge, dedupe, rank.
- `SuggestionAnalyzer` hides prompt construction, the LLM call, and citation
  auditing/provenance.
- Accept goes through `RiskLifecycle.create`, so risk codes, audit, and owner
  notifications cannot diverge from manual creation.

### 5.5 Notification dispatch

Replace service-locator calls with domain events and one dispatcher:

```python
# application/notification_dispatch.py
@dataclass(frozen=True)
class DomainEvent:
    kind: EventKind
    risk_id: int
    actor_user_id: int | None = None
    detail: Mapping[str, object] = field(default_factory=dict)

class NotificationDispatcher:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        recipients: RecipientResolver,
        renderer: EmailRenderer,
        email: EmailPort,
    ) -> None: ...

    def dispatch(self, events: Sequence[DomainEvent]) -> None:
        """Persist in-app notifications, then send email. Failures are logged/retried."""
```

Rules:

- Workflows **record events** in the result; they do not send email.
- The composition root (or UoW `after_commit` hook) calls `dispatch` **after**
  the database transaction commits. A failed email must not roll back a risk
  transition.
- Recipient resolution and template rendering live inside the dispatcher, not in
  routes. The existing `notifications.py` templates and ACS adapter can be
  retained behind the new interface.
- Start with in-process post-commit dispatch. If delivery guarantees become a
  requirement, add a transactional `notification_outbox` table drained by a
  Celery task. Do not build the outbox until then.

### 5.6 Reporting

Separate report assembly from rendering and delivery:

```python
# application/reporting.py
class WeeklyReportService:
    def __init__(self, uow: Callable[[], UnitOfWork], clock: Clock) -> None: ...
    def build(self, period: ReportPeriod) -> WeeklyReport: ...
    def send(self, report: WeeklyReport, recipients: Sequence[str]) -> None: ...

class ReportRenderer(Protocol):
    def render(self, report: WeeklyReport) -> str: ...
```

Adapters: `HtmlRenderer` and `TextRenderer` (two adapters, so a real seam).
`run_weekly_report` becomes a thin orchestration over `build`, `render`, and
`send`. The pure period/aggregation rules move to `domain/reporting.py` where
they can be tested without a DB.

### 5.7 Import workflow

`import_api.py` + `import_pipeline/` are already close to a deep module. Tighten
the interface:

```python
# application/import_workflow.py
class ImportWorkflow:
    def initiate(self, actor: Actor, upload: Upload) -> ImportJob: ...
    def suggest_mapping(self, actor: Actor, job_id: str) -> MappingSuggestion: ...
    def confirm(self, actor: Actor, job_id: str, mapping: FieldMapping) -> ImportReport: ...
```

The workflow owns job state, idempotency keys, parse/map/persist orchestration,
and audit. Excel parsing and field mapping remain pure helpers with their
existing tests.

### 5.8 Metadata and cache ownership

Today `main.py` owns two TTL caches and `conftest.py` clears globals. Move
caching into the module that owns the data:

```python
# application/risk_meta.py
class RiskMetaQueries:
    def __init__(self, uow: Callable[[], UnitOfWork], cache: TtlCache) -> None: ...
    def get(self) -> RiskMeta: ...
    def invalidate(self) -> None: ...
```

`RiskLifecycle` calls `invalidate()` when a project/department/type changes.
Tests construct a fresh instance instead of clearing a global. If a cache is not
demonstrably saving latency, delete it rather than generalize it.

### 5.9 Frontend feature modules and contracts

**Generated contracts.** Backend FastAPI already exposes OpenAPI. Generate
`frontend/src/shared/api/generated.ts` at build/dev time and check it in CI:

```bash
npm run generate:api   # openapi-typescript http://localhost:8000/openapi.json
```

Then `src/api/types.ts` disappears; feature APIs import generated types. This
removes the manual mirror that currently warns "see schemas.py".

**One source for lifecycle rules.** Add a small `GET /api/meta/risk-statuses`
(or extend `/api/risk-meta`) returning states, display labels, allowed
transitions, and role gates. `frontend/src/utils/status.ts` becomes a consumer
with no duplicated transition table. The backend remains authoritative; the UI
uses the metadata only to hide invalid actions.

**Feature API modules.** Example:

```ts
// features/risks/api.ts
export const risksApi = {
  list: (filter: RiskFilter) => client.get<RiskSummary[]>('/api/risks', { query: filter }),
  get: (id: number) => client.get<RiskDetail>(`/api/risks/${id}`),
  update: (id: number, body: RiskUpdate) => client.patch<RiskDetail>(`/api/risks/${id}`, body),
  acknowledge: (id: number) => client.post<RiskDetail>(`/api/risks/${id}/acknowledge`),
  history: (id: number) => client.get<AuditEntry[]>(`/api/risks/${id}/history`),
};
```

Pages and components import `risksApi`, never a raw path. This makes endpoint
changes one-file changes and gives each feature an obvious test surface.

**Page decomposition.** Do this only where it pays:

| Current file | Split into |
|---|---|
| `pages/RiskDetailPage.tsx` (839) | `useRiskDetail`, `RiskHeader`, `RiskEditForm`, `ResolutionPanel`, `RiskHistory`, `MaterializedIssueCard` |
| `pages/CreateRiskPage.tsx` (410) | `useCreateProject`, `ProjectForm`, `DepartmentField`, `SuggestionStep` |
| `pages/PortfolioDashboardPage.tsx` (356) | `usePortfolioMetrics`, `PortfolioCharts`, `PortfolioFilters` |
| `components/RiskTable.tsx` (347) | `useRiskTable` (filter/sort/search) + presentational `RiskTable` |
| `utils/aggregates.ts` (345) | `features/reports/aggregates.ts` with unit tests; move any business-critical rule to the backend |

**Data fetching.** Keep the in-house `useApi` for now; add a paired
`useMutation` that returns `{ run, loading, error }` and an `onSuccess` reload
hook. Do not add a server-state library until two or more features need shared
cache invalidation; the app currently has no cross-page cache to justify it.

---

## 6. Cross-cutting decisions

### 6.1 Transaction boundary

- One command = one transaction.
- `application` modules own commit/rollback; `api/` never commits.
- The unit of work is a small context manager/factory:

```python
class UnitOfWork(Protocol):
    session: Session          # implementation detail of the persistence adapter
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

Tests pass a factory backed by the in-memory SQLite session; production passes
`SessionLocal`. This is a local-substitutable dependency, so no repository port
per model is needed.

### 6.2 Errors

Move domain/application errors to `domain/errors.py` (or
`application/errors.py`):

- `NotFound`
- `Forbidden`
- `Conflict` (invalid transition)
- `ValidationFailed`
- `UpstreamUnavailable` (LLM/email/blob)

Register FastAPI exception handlers in `api/errors.py` to map them to 404/403/
409/422/503. Delete the repeated `try/except ValueError` blocks in routes.
HTTP-specific errors (`HTTPException`) stay in the router for request parsing
only.

### 6.3 Clock

Introduce a tiny `Clock` port (`now()`, `today(tz)`) and inject it into
`RiskLifecycle`, schedulers, and reporting. `scheduler.py` already accepts
`today`; keep that and use `Clock` for `create_risk`/`update_risk` timestamps
and `_next_project_code`. Tests provide a fixed clock.

### 6.4 Configuration

Continue with `pydantic-settings`, but inject the `Settings` instance from the
composition root rather than importing the global `settings` deep inside
modules. This is a low-priority cleanup; it becomes important once workflows are
unit-tested without environment variables.

### 6.5 Observability

- Log at workflow boundaries: command name, actor id, risk id, outcome, duration.
- Log notification delivery failures with event kind and risk id.
- Keep audit rows as the business record; logs are for operations.
- Add a health/readiness distinction later if the deployment needs it.

---

## 7. Seams and adapters

| Dependency | Category | Seam | Adapters | Test strategy |
|---|---|---|---|---|
| Database | Local-substitutable | `UnitOfWork` factory | `SessionLocal` / in-memory SQLite | Run workflow tests against SQLite; no mocks |
| LLM chat/embeddings | True external | `ChatProvider`, `EmbeddingProvider` | Azure OpenAI, test fakes | Inject fakes; assert prompts and citation audit |
| Email | True external | `EmailPort` | ACS, recording fake | Assert rendered message + recipients; no network |
| Blob storage | True external | `BlobStorageProvider` | Azure Blob, in-memory fake | Round-trip and missing-object cases |
| Identity | True external + local variation | `TokenVerifier` | Entra, local token, header (tests) | Table-driven verification tests |
| Clock | In-process / test | `Clock` | system, fixed | Fixed time in lifecycle tests |
| Report renderer | In-process variation | `ReportRenderer` | HTML, text | Golden-file tests per format |

**Do not add:** repository interfaces for every model, an event bus, or a
message broker. The only event mechanism is a list of domain events returned by
a command and dispatched after commit.

---

## 8. Test strategy

The migration must preserve behaviour. The test suite is the safety net, but it
must be aimed at the new interfaces.

### 8.1 Before refactoring (phase 0)

1. Add **characterization tests** for the highest-risk workflows that are not
   already covered end-to-end:
   - create → update → acknowledge → resolve → accept → close,
   - manual `Event` materialization and Issue idempotency,
   - external acknowledgement + resolution submission,
   - suggestion accept/dismiss,
   - project close guard,
   - scoped reads for PM / owner / PMO / admin / history.
2. Add an **OpenAPI snapshot** test or a generated-client check so contract
   changes are visible.
3. Record the current `pytest` count and runtime; CI must stay green throughout.

### 8.2 During refactoring

- New tests target the new interface (`RiskLifecycle`, `SuggestionWorkflow`,
  `AuthorizationPolicy`), not private helpers.
- Delete old unit tests for shallow modules once equivalent interface tests
  exist (replace, don't layer).
- Keep the HTTP-level tests: they verify the composition root, error mapping,
  and serialization.
- Use fakes for all external services. No test may reach Azure.
- Add an import-boundary test or `import-linter` contract:
  - `domain` must not import `fastapi`, `sqlalchemy`, or `adapters`.
  - `application` must not import `fastapi` or `adapters`.
  - `api` must not import `sqlalchemy` or `adapters`.

### 8.3 Definition of done for a refactor PR

- Behaviour unchanged; existing tests pass without modification (except
  intentional test moves).
- New interface tests cover the moved logic.
- No new `# type: ignore` unless justified.
- `ruff`, `mypy`, `pytest`, `npm run typecheck`, and `npm run build` pass.
- The PR is one phase/slice and revertible on its own.

---

## 9. Phased migration plan

Each phase is independently mergeable and can target `main` later.

### Phase 0 — Align branches and add safety net

- Merge/fast-forward `main` to `prod` (or confirm `prod` is the merge base) so
  the refactor does not have to be written twice.
- Add characterization tests and the OpenAPI snapshot.
- Add `docs/CODEBASE_DESIGN.md` (this document) to `main`.

**Exit:** `main` and `prod` have the same runtime code; new tests pass.

### Phase 1 — Split the HTTP shell (no behaviour change)

- Introduce `api/app.py` with `create_app()`.
- Move endpoints mechanically into routers by feature.
- Add `api/errors.py` exception handlers and remove repeated `try/except`
  mapping where it is purely mechanical.
- Leave `main.py` as `from riskapp.api.app import create_app; app = create_app()`.

**Exit:** `main.py` < 150 lines; all tests pass; route paths/response models
unchanged.

### Phase 2 — Extract RiskLifecycle

- Define `application/commands.py`, `Actor`, `Policy`, `RiskLifecycle`.
- Move risk mutation logic from `services.py` and the notification-triggering
  parts of `main.py`/`scheduler.py` behind it.
- Keep `services.py` functions as wrappers while callers migrate.
- Scheduler and external acknowledgement endpoints call `RiskLifecycle`.

**Exit:** routes and scheduler contain no risk transition/audit/Issue logic;
manual and scheduled materialization use the same command; all lifecycle tests
pass.

### Phase 3 — Notification events and dispatcher

- Have `RiskLifecycle` return domain events instead of sending notifications.
- Add `NotificationDispatcher`; call it after commit from the composition root.
- Keep in-app notification persistence in the transaction.
- Convert scheduler and report delivery to the same dispatcher where applicable.

**Exit:** no `build_notification_service()` calls in routes or lifecycle code;
email failure cannot roll back a DB mutation; notification payload tests pass.

### Phase 4 — Deepen suggestions, reporting, and imports

- Extract `SuggestionWorkflow`, `SuggestionAnalyzer`, `RetrievalService` from
  `suggestions.py`; route accept through `RiskLifecycle`.
- Split `reports.py` into `application/reporting.py`, `domain/reporting.py`, and
  renderer adapters.
- Extract `ImportWorkflow` from `import_api.py`.
- Move scoped reads into `RiskQueries`.

**Exit:** routers are thin; feature modules expose the interfaces in §5; no
        repeated row-level scoping in routes.

### Phase 5 — Backend package cleanup

- Move models/engine/Celery/config into `adapters/persistence` and
  `infrastructure` (or keep their current names with re-export shims).
- Split `contracts/` by feature.
- Move identity adapters out of `auth.py`.
- Remove compatibility wrappers once all callers use the new modules.

**Exit:** dependency rule enforced by lint; old modules deleted; docs updated.

### Phase 6 — Frontend feature modules

- Add generated types and the `generate:api` CI check.
- Add `GET /api/meta/risk-statuses`; delete the mirrored transition table.
- Introduce `features/*/api.ts` and migrate pages/components off raw paths.
- Decompose `RiskDetailPage`, `CreateRiskPage`, `PortfolioDashboardPage`, and
  `RiskTable` where the split has a clear seam.
- Move `utils/aggregates.ts` into `features/reports` and test it.

**Exit:** no `/api/` literals outside `features/*/api.ts`; typecheck/build pass;
generated types are current.

### Phase 7 — Guardrails

- Add import-boundary lint and a CI job for generated contracts.
- Document the module map in `ARCHITECTURE.md` and link this design.
- Measure the targets in §10 and remove temporary shims.

---

## 10. Guardrails and target metrics

| Metric | Target |
|---|---|
| `backend/src/riskapp/main.py` | ≤ 150 lines (entrypoint only) |
| Largest backend module | ≤ ~400 lines; no single module owns two features |
| `db.commit()` in `api/` | 0 |
| SQLAlchemy imports in `api/` | 0 |
| FastAPI imports in `domain/` or `application/` | 0 |
| Risk transition tables | 1 (backend); frontend consumes metadata |
| Raw `/api/` strings in frontend pages/components | 0 (only `features/*/api.ts`) |
| Hand-written duplicate API types | 0 (generated from OpenAPI) |
| Notification call sites | 1 dispatcher; workflows return events |
| Tests | all existing pass; new workflow tests cover each command and policy row |
| CI | pytest, ruff, mypy, typecheck, build, generated-contract check |

---

## 11. Applying this to `main`

The design is docs-first and the code phases are behaviour-preserving, so
`main` can absorb it without a risky big-bang merge.

### Recommended path

1. **Align the branches first.** `prod` currently contains two commits that
   `main` does not (`679b348`, `2a715c7`). Fast-forward `main` to `prod` (or merge
   `prod` into `main`) before starting Phase 1. Do not refactor a divergent
   branch.
2. **Land this document on `main`.** It is docs-only and conflict-free.
3. **Run phases 1–3 on short-lived branches** (`refactor/api-shell`,
   `refactor/risk-lifecycle`, `refactor/notifications`) and merge each to `main`
   after review.
4. **Port to `prod` by fast-forward/merge from `main`** once the refactor is
   stable, or cherry-pick the same commits if release ordering requires it.
5. **Keep `prod` deployable throughout.** No phase changes the database schema,
   so rollback is a revert, not a migration.

### If `main` must stay independent

- Cherry-pick this document now.
- Base each refactor branch on `main` and rebase on `prod` before merging.
- Expect conflicts in `main.py`, `services.py`, `auth.py`, `schemas.py`, and
  `tests/`; `docs/` is stable. Do Phase 1 (mechanical router split) first,
  because it shrinks the conflict surface for every later phase.

### Compatibility strategy

- Keep old imports working via re-export shims (`services.py` functions delegate
  to workflows; `auth.py` re-exports policy helpers) until Phase 5.
- Migrate callers one feature at a time.
- Do not rename HTTP routes or response fields during refactors; contract
  changes are a separate, versioned decision.
- Do not mix refactor PRs with feature work or migrations.

---

## 12. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Microservices split | Adds network, deployment, and failure modes with no scaling need. The modular monolith already deploys as separate web and worker containers. |
| Repository interface per model | Shallow indirection; SQLAlchemy + SQLite already provide the test seam. Add repositories only where a second real adapter exists. |
| Event sourcing / full CQRS | The append-only audit log already provides history. Domain events are a lightweight in-process mechanism, not a persistence model. |
| Full DDD bounded contexts | Useful vocabulary, but the app has one bounded context (PMO risk management). Splitting it would add ceremony. |
| Immediate transactional outbox | Valuable only if guaranteed email delivery becomes a requirement. Start with post-commit dispatch; add the outbox behind the dispatcher if needed. |
| Rewriting the frontend state layer | The app has no shared cross-page cache. A small `useApi`/`useMutation` pair is enough until proven otherwise. |
| Big-bang rewrite | High risk, no incremental verification, and it would block `prod`. The phased plan preserves deployability. |

---

## Appendix A — Interface sketches

### A.1 Command/result types (application layer)

```python
@dataclass(frozen=True)
class CreateRisk:
    project_id: int
    description: str
    likelihood: Likelihood
    impact: Impact
    category: str | None = None
    subcategory: str | None = None
    risk_source: RiskSource | None = None
    response_strategy: ResponseStrategy | None = None
    response_plan: str | None = None
    owner_user_id: int | None = None
    risk_start_date: date | None = None
    risk_end_date: date | None = None
    source: str | None = None
    identified_during: str | None = None
    status: RiskStatus = RiskStatus.OPEN

@dataclass(frozen=True)
class LifecycleResult:
    risk: RiskSnapshot
    events: tuple[DomainEvent, ...] = ()
```

### A.2 Router shape

```python
@router.patch("/{risk_id}", response_model=RiskRead)
def patch_risk(
    risk_id: int,
    payload: RiskUpdate,
    principal: PrincipalDep,
    lifecycle: LifecycleDep,
) -> RiskRead:
    result = lifecycle.update(risk_id, payload.to_command(), actor=principal.actor)
    return RiskRead.from_snapshot(result.risk)
```

The route has no SQL, no commit, no policy branch, and no notification call.

### A.3 Frontend feature API

```ts
// features/risks/hooks.ts
export function useRisk(id: number) {
  return useApi(() => risksApi.get(id), [id]);
}

export function useAcknowledgeRisk(id: number) {
  const mutation = useMutation((riskId: number) => risksApi.acknowledge(riskId));
  return { ...mutation, run: () => mutation.run(id) };
}
```

---

## Appendix B — Current module → target module map

| Current | Target | Phase |
|---|---|---|
| `main.py` endpoints | `api/routers/*` + `api/app.py` | 1 |
| `main.py` policy branches, `auth.py::can_*` | `application/authorization.py` | 2 |
| `services.py` mutations | `application/risk_lifecycle.py` | 2 |
| `main.py` read queries | `application/risk_queries.py` | 4 |
| `suggestions.py` | `application/suggestion_workflow.py` + retrieval/analyzer adapters | 4 |
| `reports.py` | `application/reporting.py` + `domain/reporting.py` + renderers | 4 |
| `import_api.py` + `import_pipeline/` | `application/import_workflow.py` + existing pure helpers | 4 |
| `notifications.py` call sites | `application/notification_dispatch.py` | 3 |
| `models.py`, `db.py`, `celery_app.py`, `config.py` | `adapters/persistence/*`, `infrastructure/*` | 5 |
| `schemas.py` | `contracts/*` | 5 |
| `auth.py` verifiers | `adapters/identity/*` | 5 |
| `frontend/src/api/types.ts` | `shared/api/generated.ts` | 6 |
| `frontend/src/utils/status.ts` | generated/meta-driven status model | 6 |
| raw API calls in pages/components | `features/*/api.ts` | 6 |
| `utils/aggregates.ts` | `features/reports/aggregates.ts` | 6 |

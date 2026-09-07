# #15 — Risk ⇄ Project Normalization — UML Data Model Diagrams

> **Status:** PLANNING ONLY — nothing implemented.
> **Companion to:** `Issues/15-risk-project-normalization-migration.md` (full impact
> assessment & migration plan).
> **Date:** 2026-09-02
>
> These UML class diagrams (Mermaid syntax) illustrate the **current** data model
> and the **target** data model for normalizing the `Risk → Project` relationship
> into a `Risk ↔ Risk_Project ↔ Project` junction model.

---

## 1. Current Data Model

```mermaid
classDiagram
    class Department {
        +int id PK
        +string name  «unique»
    }

    class ProjectType {
        +int id PK
        +string name  «unique»
    }

    class User {
        +int id PK
        +string upn  «unique»
        +string display_name
    }

    class Project {
        +int id PK
        +string project_code  «unique»
        +string name
        +string customer
        +int department_id FK
        +int project_type_id FK
        +int pm_user_id FK
        +date start_date
        +date end_date
        +string stage_gate
        +string status  «default "Active"»
    }

    class Risk {
        +int id PK
        +string risk_code  «unique»
        +int project_id FK  «NOT NULL»
        +string description
        +string category
        +string likelihood
        +string impact
        +string risk_rating
        +string response_strategy
        +int owner_user_id FK
        +string status  «default "Suggested"»
        +...  «SLA / traceability / closure fields»
    }

    class RiskAuditLog {
        +int id PK
        +int risk_id FK
        +int user_id FK
        +string action
        +string field
        +json old_value
        +json new_value
        +datetime created_at
    }

    Department "1" --> "0..*" Project : department_id
    ProjectType "1" --> "0..*" Project : project_type_id
    User "0..1" --> "0..*" Project : pm_user_id
    Project "1" --> "0..*" Risk : project_id «NOT NULL»
    Risk "1" --> "0..*" RiskAuditLog : risk_id
    User "0..1" --> "0..*" Risk : owner_user_id
```

**Key point:** `Risk` holds a required `project_id` FK directly. A risk cannot
exist without exactly one project. The relationship is strictly
**one Project → many Risk**.

---

## 2. Target Data Model

```mermaid
classDiagram
    class Department {
        +int id PK
        +string name  «unique»
    }

    class ProjectType {
        +int id PK
        +string name  «unique»
    }

    class Project {
        +int id PK
        +string project_code  «unique»
        +string name
        +string customer
        +int department_id FK
        +int project_type_id FK
        +int pm_user_id FK
        +string status  «Active / Closed»
    }

    class RiskProject {
        +int risk_id FK
        +int project_id FK
        +datetime created_at
    }

    class Risk {
        +int id PK
        +string risk_code  «unique»
        +string description
        +string category
        +string likelihood
        +string impact
        +string risk_rating
        +string response_strategy
        +int owner_user_id FK
        +string status  «Suggested..Closed»
        +...  «SLA / traceability / closure fields»
    }

    class RiskAuditLog {
        +int id PK
        +int risk_id FK
        +string action
        +json old_value
        +json new_value
    }

    Department "1" --> "0..*" Project : department_id
    ProjectType "1" --> "0..*" Project : project_type_id
    Project "1" --> "0..*" RiskProject : project_id
    Risk "1" --> "0..*" RiskProject : risk_id
    Risk "1" --> "0..*" RiskAuditLog : risk_id
```

**Key point:** `project_id` is removed from `Risk`. The association now lives in
the `RiskProject` junction table. A risk can exist **independently** and be
associated with project(s) through `RiskProject`.

---

## 3. Side-by-Side of the Change

| | Current | Target |
|---|---|---|
| Association lives in | `Risk.project_id` (FK column) | `RiskProject` (junction table) |
| Risk can exist without project? | **No** (NOT NULL FK) | **Yes** |
| Cardinality | Project `1 — *` Risk (one-to-many) | Project `1 — *` RiskProject `* — 1` Risk (many-to-many) |
| What's new | — | `RiskProject` table |
| What's removed | — | `Risk.project_id` |

> ⚠️ **Open question** (from §17 of the companion doc): the junction diagram
> implies **many-to-many**. If the intent is actually "one risk → one project, just
> normalized," constrain the `RiskProject` relationship to `1..1` on the risk side
> (unique `risk_id`) rather than `0..*`.

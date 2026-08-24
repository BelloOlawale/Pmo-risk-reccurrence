# AGENTS.md

> **Purpose:** Engineering playbook for implementing the  issues. Every PR is small, tested, and reviewable in under 10 minutes.
>
> **Audience:** AI coding agents and human contributors.
> **Date:** July 2026

---

## Golden Rules

1. **One PR = One Issue.** Never combine issues. Each PR maps 1:1 to an issue in `issues/`.
2. **PR under 200 lines.** If a PR grows beyond ~200 significant lines (excluding JSON configs, generated files), split the issue further.
3. **Tests before implementation.** Write the test, watch it fail, then write the code. Red → Green → Refactor.
4. **Vet dependencies with opensrc.** Run `opensrc fetch` on every new library so agents can inspect source code before trusting it. No unvetted code in the supply chain.
5. **Clean code, always.** Single-responsibility functions. Descriptive names. No comments that explain what — only why.
6. **Document progress and blockers.** After meaningful progress on any issue, update `docs/PROGRESS.md` (partitioned by issue). When a blocker is hit or resolved, record it in `docs/BLOCKERS.md` with symptom, root cause, and fix.

---

## Technology Stack

### What We Use (and Why)

| Layer | Technology | License | Why |
|---|---|---|---|
| Runtime | **Python 3.11+** | PSF | Azure Functions native. `extract_hierarchy.py` already written in it. |
| LLM | **Azure OpenAI (GPT-4o mini)** | Proprietary | Chat completions for suggestion + re-scan. Cheapest viable option ($0.15/1M tokens). |
| Embeddings | **Azure OpenAI (text-embedding-3-small)** | Proprietary | 1536-dim vectors for FAISS semantic search. $0.02/1M tokens — negligible at this scale. |
| Vector search | **faiss-cpu** | MIT | In-memory cosine similarity search. ~1.2 MB per 200 risks. Index stored in Azure Blob. |
| Blob storage | **azure-storage-blob** | MIT | Serialize/deserialize FAISS index to Azure Blob Storage. |
| HTTP client | **httpx** | BSD | Modern async HTTP for SharePoint REST API. Drop-in for `requests`. |
| Excel parsing | **openpyxl** | MIT | Already proven in `extract_hierarchy.py`. Handles .xlsx, .xlsm. |
| PDF inspection | **PyPDF2** or **pikepdf** | BSD / MPL | For the 3 PDF risk registers. Read-only metadata + text extraction. |
| Testing | **pytest** | MIT | Standard. Fast. Great fixtures + parametrization. |
| Mocking | **pytest-httpx** | MIT | Mock SharePoint REST API responses without a real tenant. |
| Linting | **ruff** | MIT | Fast. Replaces flake8 + isort + black in one tool. |
| Type checking | **mypy** | MIT | Catch type errors before runtime. Strict mode for new code. |
| Azure Functions | **azure-functions** | MIT | Python worker for Consumption plan. |
| Config | **python-dotenv** | BSD | Local `.env` for dev; Function app settings in Azure. |

### What We Don't Use

| Avoid | Why |
|---|---|
| `pandas` | Overkill for 200 rows. `openpyxl` row-by-row is simpler and faster for this scale. |
| `requests` | `httpx` has native async, better timeout handling, and a modern API. |
| `SQLAlchemy` / ORMs | Data store is SharePoint Lists (REST API), not a relational DB. No ORM needed. |
| `langchain` / `semantic-kernel` | Adds abstraction layers we don't need. Direct OpenAI API calls with structured prompts are simpler and more transparent. |
| `chromadb` / `pinecone` / vector DBs | FAISS runs in-process with zero infrastructure. No separate service to manage at this scale. |
| Any npm / Node dependency | Single-language stack. Everything is Python + M365 point-and-click. |

---

## TDD Workflow

Every issue follows the same rhythm:

```
1. READ the issue           Understand acceptance criteria
2. WRITE the test           pytest. Watch it FAIL (red).
3. WRITE the code           Minimal implementation. Watch tests PASS (green).
4. REFACTOR                 Clean up. Tests still pass.
5. SELF-REVIEW              Run ruff + mypy. Check line count.
6. COMMIT                   Conventional commit message. Open PR.
```

### Test file conventions

```
src/
  import_pipeline/
    excel_parser.py          ← implementation
    field_mapper.py
  function_app.py            ← Azure Function
tests/
  test_excel_parser.py       ← mirrors src/ structure
  test_field_mapper.py
  test_function_suggest.py
conftest.py                  ← shared fixtures (sample Excel data, mock SharePoint responses)
```

### What to test

| Test type | Example | When |
|---|---|---|
| **Unit** | `test_field_mapper_maps_hml_to_likelihood()` | Every function that transforms data |
| **Unit** | `test_risk_rating_computed_from_matrix()` | Every pure computation |
| **Integration** | `test_parse_punuka_file_returns_12_risks()` | Reading real Excel files from `tests/fixtures/` |
| **Integration** | `test_suggest_endpoint_returns_correct_schema()` | Azure Function HTTP trigger (mocked SharePoint) |
| **Contract** | `test_suggest_response_matches_flow1_schema()` | Integration contract between Function and Power Automate |

### What NOT to test

- SharePoint REST API itself (Microsoft's problem)
- Power Automate flow logic (visual, tested manually during E2E)
- Power BI visuals (tested manually during E2E)
- openpyxl internals (library's problem)

---

## PR Structure

### Branch naming

```
issue/01-foundation-lists     ← maps to issues/01-foundation-sharepoint-lists.md
issue/03-azure-function       ← maps to issues/03-azure-function-openai-suggestion.md
```

### Commit messages (Conventional Commits)

```
feat(import): parse PUNUKA Excel schema with 7-column layout
test(import): add field mapping test for H/M/L → High/Medium/Low
fix(mapper): handle empty RiskCategory column gracefully
refactor(function): extract citation linkifier into pure function
```

### PR description template

```markdown
Closes #X

## What
- [brief 1-2 line summary]

## Files changed
- `src/import_pipeline/excel_parser.py` (+45, -12)
- `tests/test_excel_parser.py` (+78)

## Test plan
- [ ] `pytest tests/` — all green
- [ ] `ruff check src/ tests/` — clean
- [ ] `mypy src/` — no errors

## E2E verification (if applicable)
- [ ] Run import against test fixture → verify row count
```

---

## Code Organization

```
risk_reccurrence_predictor/
│
├── src/
│   ├── import_pipeline/           # Issue #1: Historical data import
│   │   ├── __init__.py
│   │   ├── excel_parser.py        # Read .xlsx, detect headers, extract rows
│   │   ├── field_mapper.py        # Map Excel columns → canonical schema
│   │   ├── sharepoint_client.py   # SharePoint REST API wrapper (create/read/update)
│   │   └── importer.py            # Orchestrator: walk folders → parse → push
│   │
│   ├── function_app.py            # Azure Function: POST /api/suggest
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── prompts.py             # LLM prompt templates (suggestion + re-scan)
│   │   ├── citations.py           # Citation → clickable SharePoint URL
│   │   ├── openai_client.py       # Azure OpenAI API wrapper (chat + embeddings)
│   │   ├── vector_store.py        # FAISS index builder, loader, searcher
│   │   └── evaluation.py          # Post-LLM citation audit + groundedness scoring
│   │
│   └── shared/
│       ├── __init__.py
│       ├── config.py              # Env var loading, settings
│       ├── risk_rating.py         # 3×3 matrix computation
│       └── types.py               # TypedDict schemas matching canonical fields
│
├── tests/
│   ├── conftest.py                # Shared fixtures
│   ├── fixtures/                  # Sample Excel files for testing
│   │   ├── punuka_sample.xlsx     # Schema A (7 cols)
│   │   ├── wacl_sample.xlsx       # Schema B (10 cols)
│   │   ├── tnl_sample.xlsx        # Schema C (6 cols)
│   │   └── seamless_hr_sample.xlsx # Schema D (7 cols, zero-width chars)
│   ├── test_excel_parser.py
│   ├── test_field_mapper.py
│   ├── test_importer.py
│   ├── test_sharepoint_client.py
│   ├── test_function_suggest.py
│   ├── test_risk_rating.py
│   ├── test_prompts.py
│   ├── test_citations.py
│   ├── test_vector_store.py
│   └── test_evaluation.py
│
├── scripts/
│   └── extract_hierarchy.py       # Already built: walk & inspect Excel files
│
├── docs/
│   ├── pre-implementation-prerequisites.md
│   ├── prd.md
│   └── ...
│
├── issues/                        # 17 implementation tickets
│   ├── 01-foundation-sharepoint-lists.md
│   └── ...
│
├── tests/fixtures/                # Real Excel files (anonymized) for testing
├── .env.example                   # Template: SHAREPOINT_SITE_URL, TENANT_ID, etc.
├── .gitignore
├── pyproject.toml                 # Dependencies, ruff config, mypy config
├── README.md
├── CONTEXT.md                     # Domain vocabulary
└── AGENTS.md                      # This file
```

---

## Clean Code Conventions

### Functions

- **One thing.** If you need "and" in the function name, split it.
- **Under 20 lines.** Exceptions: orchestration functions that compose other functions.
- **Pure where possible.** Side effects (HTTP, file I/O) only at the edges.

```python
# GOOD: pure function, testable without mocks
def compute_risk_rating(likelihood: str, impact: str) -> str:
    """Compute RiskRating from the standard 3×3 matrix."""
    matrix = {
        ("High", "High"): "High",   ("High", "Medium"): "High",   ("High", "Low"): "Medium",
        ("Medium", "High"): "High", ("Medium", "Medium"): "Medium", ("Medium", "Low"): "Low",
        ("Low", "High"): "Medium",  ("Low", "Medium"): "Low",     ("Low", "Low"): "Low",
    }
    return matrix.get((likelihood, impact), "Medium")

# BAD: mixes I/O, transformation, and business logic
def process_excel_and_save_to_sharepoint(filepath, site_url):
    wb = openpyxl.load_workbook(filepath)
    for row in wb.active.iter_rows():
        # 50 lines of mixed concerns...
```

### Naming

- `parse_` prefix for functions that read and structure data
- `map_` prefix for field-to-field transformations
- `compute_` prefix for derived values (ratings, durations)
- `fetch_` / `push_` for SharePoint REST calls
- `build_` for constructing complex objects or prompts

### Types

Every public function has type hints. Use `TypedDict` for structured data:

```python
from typing import TypedDict

class RiskRecord(TypedDict, total=False):
    risk_description: str
    risk_category: str
    likelihood: str
    impact: str
    risk_rating: str
    source_file_name: str
    source_risk_id: str
    # ... all canonical fields
```

### Errors

- Fail fast with specific exceptions. Never `except Exception: pass`.
- SharePoint 401/403 → `AuthenticationError`
- SharePoint 404 → `ListNotFoundError`
- Excel file unreadable → `ParseError` with filename + sheet + row context
- LLM returns unexpected JSON shape → `LLMResponseError` with raw response

---

## Dependency Vetting with opensrc

`opensrc` fetches the actual source code of every dependency into a local cache so coding agents can read, audit, and understand it before the library enters the codebase. Use `pypi:<name>` for Python packages (not bare names — those default to npm).

```bash
# Fetch source for a Python dependency
opensrc fetch pypi:httpx

# Some packages lack a repo URL in PyPI metadata — use the GitHub slug directly
opensrc fetch encode/httpx

# See all cached dependency sources
opensrc list

# Get the path to cached source (agent can read it)
opensrc path pypi:httpx

# If it checks out, add to pyproject.toml
# If anything suspicious (obfuscation, telemetry, excessive network), reject it
```

**Rule:** No library enters `pyproject.toml` without `opensrc fetch` first. The agent must read at least the package's `__init__.py`, `pyproject.toml`, and any network-related modules before approving. For packages that `opensrc` can't fetch (no repo URL in PyPI metadata), manually clone from their GitHub repo.

Vetted (opensrc fetch run, source inspected ✅):
- `httpx` — `pypi:httpx` → `github.com/encode/httpx`
- `pytest` — `pypi:pytest` → `github.com/pytest-dev/pytest`
- `pikepdf` — `pypi:pikepdf` → `github.com/pikepdf/pikepdf`
- `python-dotenv` — `pypi:python-dotenv` → `github.com/theskumar/python-dotenv`
- `faiss-cpu` — `pypi:faiss-cpu` → `github.com/facebookresearch/faiss`

Still needs vetting before use:
- `openpyxl` — PyPI lacks repo URL. Fetch from `github.com/chronossc/openpyxl` manually.
- `ruff` — repo too large for opensrc clone. Trusted (Astral-maintained, industry standard).
- `mypy` — PyPI lacks repo URL. Fetch from `github.com/python/mypy` manually.
- `pytest-httpx` — not yet fetched
- `azure-functions` — Microsoft-maintained, required by the runtime
- `azure-storage-blob` — Microsoft-maintained, required for FAISS index persistence
- `numpy` — transitive dep of faiss-cpu, already trusted (NumPy is the standard)

## Dependency Rules

1. **opensrc before adding.** Run `opensrc fetch <package>` on every new dependency. Agent inspects source before approval.
2. **Pin versions.** `pyproject.toml` uses exact versions (`==X.Y.Z`), not ranges.
3. **Minimize dependencies.** Every new library must justify itself. Can we write it in 10 lines? Do that instead.
4. **Document why.** Add a comment above each dependency in `pyproject.toml` explaining what it's for.

```toml
[project]
dependencies = [
    "openpyxl==3.1.5",          # Excel parsing — proven in extract_hierarchy.py
    "httpx==0.28.1",            # Async HTTP for SharePoint REST API
    "pikepdf==9.5.1",           # PDF text extraction for risk registers
    "python-dotenv==1.1.0",     # Local .env config
    "faiss-cpu==1.9.0",         # In-memory vector similarity search (hybrid retrieval)
    "numpy==2.1.0",             # Required by FAISS (also used for vector normalization)
    "azure-storage-blob==12.24.0",  # FAISS index persistence in Blob Storage
]

[project.optional-dependencies]
dev = [
    "pytest==8.3.4",            # Testing framework
    "pytest-httpx==0.35.0",     # Mock HTTP for SharePoint API
    "ruff==0.11.0",             # Linter + formatter
    "mypy==1.14.0",             # Static type checking
]
```

---

## Issue-by-Issue Implementation Notes

### Issue #1: Foundation — SharePoint Lists + Import

**This is the biggest issue.** Break it into 4 sub-PRs:

| PR | What | Lines (est.) |
|---|---|---|
| 1a | `excel_parser.py` — read .xlsx, detect headers, extract rows | ~80 |
| 1b | `field_mapper.py` — map 4+ schemas to canonical fields + `risk_rating.py` | ~100 |
| 1c | `sharepoint_client.py` — REST API wrapper (auth, create item, upload file) | ~120 |
| 1d | `importer.py` — orchestrate walk → parse → map → push + create Projects list | ~80 |
| 1e | FAISS rebuild — after import finishes, embed all Historical Risks, build index, upload to Blob | ~60 |

**TDD approach:** 
- PR 1a: Tests against `tests/fixtures/punuka_sample.xlsx` — verify 12 rows extracted with correct header detection
- PR 1b: Pure function tests — `map_hml_to_likelihood("H") == "High"`, `compute_risk_rating("High", "Medium") == "High"`
- PR 1c: Mock SharePoint responses with `pytest-httpx` — test auth flow, item creation, file upload
- PR 1d: Integration test — run full import against fixture directory, verify row counts in mocked SharePoint

### Issue #3: Azure Function + OpenAI Suggestion

**Second most important issue.** Three sub-PRs:

| PR | What | Lines (est.) |
|---|---|---|
| 3a | `prompts.py` + `openai_client.py` — LLM prompt templates, Azure OpenAI wrapper (chat + embeddings) | ~120 |
| 3b | `vector_store.py` — FAISS index builder, loader (from Blob), search, rebuild trigger | ~100 |
| 3c | `function_app.py` + `citations.py` — HTTP trigger, hybrid search (SharePoint + FAISS), citation linkification | ~150 |

**TDD approach:**
- PR 3a: Test prompt construction — verify system prompt includes domain vocabulary from CONTEXT.md. Test OpenAI chat + embedding client with mocked responses.
- PR 3b: Test index build from fixture data, search returns correct top-k, load/save roundtrip to disk, graceful degradation when index file missing.
- PR 3c: Contract test — `POST /api/suggest` returns JSON with exact fields that Flow 1 expects. Test hybrid merge logic. Test citation audit produces correct groundedness_score. Mock SharePoint + OpenAI + FAISS.

### Issues #2, #4–#17

These are primarily SharePoint UI, Power Automate, and Power BI work — low-code configurations. They're documented in the issues but require the dev tenant. Code changes are minimal (mostly JSON view formatting and form configuration). Python code is limited to:
- Citation URL transformations (already covered in 3b)
- Any helper scripts for list schema export (simple)

---

## Development Setup

```bash
# 1. Install opensrc (dependency source fetcher for agents)
npm install -g opensrc

# 2. Clone + venv
git clone <repo-url>
cd risk_reccurrence_predictor
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# 3. Install dependencies (vet each with opensrc first)
pip install -e ".[dev]"

# 4. Configure
cp .env.example .env
# Edit .env with dev tenant values:
#   SHAREPOINT_SITE_URL=https://<dev>.sharepoint.com/sites/PMO
#   TENANT_ID=...
#   CLIENT_ID=...
#   CLIENT_SECRET=...
#   AZURE_OPENAI_ENDPOINT=...
#   AZURE_OPENAI_KEY=...

# 5. Verify
ruff check src/ tests/
mypy src/
pytest tests/ -v

# 6. Start coding
# Pick an issue from issues/, create a branch, follow TDD.
```

---

## Quick Reference

| Rule | Threshold |
|---|---|
| Max PR size | 200 significant lines |
| Max function length | 20 lines |
| Test coverage target | >90% on `src/` Python code |
| Ruff rules | All enabled. `pyproject.toml` is the source of truth. |
| Mypy mode | `strict = true` |
| Python version | 3.11+ (matches Azure Functions runtime) |
| Commit style | [Conventional Commits](https://www.conventionalcommits.org/) |
| PR review time target | <10 minutes |

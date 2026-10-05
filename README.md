# SnappCarFix Engine Oil Compatibility API

SnappCarFix researches the engine-oil requirements of stored vehicles, evaluates
the evidence, and matches accepted specifications to an engine-oil catalog. It
provides a FastAPI API, PostgreSQL persistence through SQLAlchemy 2, Alembic
migrations, import scripts, and single-vehicle and batch research commands.
Python 3.12 or newer is required.

Research provenance is retained: every attempt records its provider result,
sources, timing, derived engine specification, oil matches, and immutable
compatibility-history snapshots.

## Architecture

```text
HTTP API / command scripts
          |
          v
services (research, matching, compatibility)
          |
          +----> provider abstraction ----> Gemini / OpenRouter / OpenCode
          |
          v
repositories ----> SQLAlchemy models ----> PostgreSQL
```

- `backend/app/api`: FastAPI routes and response validation.
- `backend/app/services`: research orchestration, evidence evaluation,
  deterministic matching, and compatibility persistence.
- `backend/app/agents`: provider protocols, adapters, clients, prompts, result
  schemas, parsing, and source evaluation.
- `backend/app/repositories`: database access over SQLAlchemy models.
- `backend/app/models`: database table mappings.
- `backend/app/workers`: processing for queued `AgentJob` records.
- `backend/scripts`: imports, smoke tests, single research, and batch research.
- `backend/migrations`: Alembic schema history.

The standard CRUD and job routes are under `/api/v1`. The research audit route is:

```http
GET /api/v1/vehicles/{vehicle_id}/research-history
```

It returns the vehicle and its chronological research timeline. Each entry
contains the complete `ResearchRun`, structured evidence sources, associated
engine specs, matched oil records, and compatibility-history snapshots. An
unknown vehicle returns `404`; a known vehicle with no runs has an empty timeline.

## Provider abstraction

`ResearchProvider` defines the normal `research_vehicle_oil_spec(vehicle)`
contract. `CatalogResearchProvider` adds the experimental catalog-aware contract.
`create_research_provider(settings)` selects one implementation:

- `gemini`: `GeminiResearchAdapter` backed by the official Google SDK and Google
  Search grounding.
- `openrouter`: `ResearchAgent` backed by `OpenRouterClient` and web search.
- `opencode`: `OpenCodeResearchAgent` backed by the locally configured OpenCode
  CLI.

Provider output is normalized to the same `EngineOilResearchResult`, so source
evaluation, persistence, and deterministic matching do not depend on a specific
provider. Provider selection and matching strategy are separate settings. The
`provider_catalog` strategy is supported only by Gemini.

## Database tables

| Table | Purpose |
| --- | --- |
| `vehicles` | Vehicle identity, production years, engine code, displacement, and fuel type. |
| `engine_oils` | Product catalog with SAE, API, ACEA, base type, and OEM approvals. |
| `research_runs` | One research attempt, including provider/model, status, structured and raw output, grounding data, and timings. |
| `engine_specs` | Accepted oil requirements derived from research; linked to its research run. |
| `vehicle_engine_oil_compatibilities` | Current vehicle/oil match, score, reason, review status, and provenance links. The vehicle/oil pair is unique and later runs update it. |
| `compatibility_history` | Immutable snapshot written whenever research creates or updates a compatibility. |
| `agent_jobs` | State for asynchronous single-vehicle jobs processed by the lightweight worker. |

## Research and persistence flow

```text
Vehicle
  -> selected research provider
  -> normalized structured result and sources
  -> deterministic evidence evaluation
       -> uncertain: persist ResearchRun as NEEDS_REVIEW
       -> accepted: persist ResearchRun + EngineSpec
                    -> match catalog oils
                    -> upsert current compatibility
                    -> append compatibility history
```

Evidence is accepted when the result is `FOUND`, includes a recommended SAE,
meets `RESEARCH_MIN_CONFIDENCE`, has no source conflict, and is supported by an
official manual/manufacturer source or two independent credible secondary
domains. Uncertain evidence is retained as `NEEDS_REVIEW`. Provider,
configuration, and malformed-response failures fail the job or batch item.

Queued job states are:

```text
PENDING -> RESOLVING_SPEC -> MATCHING -> COMPLETED
                         \-> NEEDS_REVIEW
provider/application error ------------> FAILED
```

## Matching strategies

`MATCHING_STRATEGY=deterministic` is the default. The provider researches only
the required specification. The local matcher treats recommended SAE and minimum
API as hard requirements, considers alternative SAE, ACEA, and OEM approvals,
and calculates a score. Products explicitly sourced by research are added to the
catalog before matching and retain their originating research-run ID.

`MATCHING_STRATEGY=provider_catalog` is experimental and Gemini-only. It sends
the existing catalog in one grounded provider request and accepts only returned
catalog IDs. It does not run the deterministic candidate matcher.

## Configuration

Create `backend/.env` (or export the variables) and configure PostgreSQL plus the
provider you intend to use:

```env
DATABASE_URL=postgresql+psycopg://oil:oil@localhost:5432/engine_oil
RESEARCH_PROVIDER=gemini
MATCHING_STRATEGY=deterministic
RESEARCH_MIN_CONFIDENCE=0.80
RESEARCH_WEB_SEARCH_ENABLED=true

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_STAGE1_TIMEOUT_SECONDS=45
GEMINI_STAGE2_TIMEOUT_SECONDS=20
GEMINI_TOTAL_TIMEOUT_SECONDS=65
GEMINI_MAX_OUTPUT_TOKENS=3072
GEMINI_TEMPERATURE=0.1

OPENROUTER_API_KEY=
OPENROUTER_MODEL=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_TIMEOUT_SECONDS=90
OPENROUTER_MAX_RETRIES=2

OPENCODE_COMMAND=opencode
OPENCODE_AGENT=oil-research
OPENCODE_TIMEOUT_SECONDS=90
OPENCODE_MODEL=opencode/big-pickle
```

`RESEARCH_PROVIDER` accepts `gemini`, `openrouter`, or `opencode`.
`MATCHING_STRATEGY` accepts `deterministic` or `provider_catalog`. Invalid
provider/strategy combinations fail during configuration.

Gemini performs a grounded research call and, only when needed, one no-search
JSON repair call. A `FOUND` Gemini result is rejected unless grounding metadata
contains a search query or source. OpenCode authentication is managed by the
local CLI; the backend does not store OpenCode credentials.

## Setup and running commands

Run backend commands from `backend`:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Or start PostgreSQL and the API from the repository root:

```powershell
docker compose up --build
```

Run the offline test suite:

```powershell
pytest -q
```

Create and process a queued research job:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/agents/vehicles/1/run
python scripts/run_worker.py
```

Research one vehicle. The first command is a dry run; `--save` persists the
accepted research, specification, matches, and history:

```powershell
python scripts/research_vehicle.py 1
python scripts/research_vehicle.py 1 --save
python scripts/research_vehicle.py 1 --matching-strategy provider_catalog
```

Research every stored vehicle with a bounded async queue. Each worker owns its
own provider client and DB session. This command always persists results and can
incur one or more provider calls per vehicle:

```powershell
python scripts/research_all_vehicles.py --concurrency 3
```

Run provider smoke tests manually (they are not part of pytest):

```powershell
python scripts/test_gemini_research.py
python scripts/test_opencode_research.py
python scripts/test_openrouter_web.py
```

Read a vehicle's stored research history:

```powershell
curl.exe http://localhost:8000/api/v1/vehicles/1/research-history
```

## PostgreSQL migration validation

Start PostgreSQL and run the schema/drift checks from `backend`:

```powershell
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://oil:oil@localhost:5432/engine_oil"
uv run alembic upgrade head
uv run alembic check
$env:POSTGRES_TEST_DATABASE_URL = $env:DATABASE_URL
uv run pytest tests/integration/test_postgresql.py -q
```

Use a disposable database when validating `0003 -> head`: upgrade it to
`0003_research_provenance`, load representative legacy rows, then run
`uv run alembic upgrade head`. The migration preserves compatibility history
and fails explicitly on duplicate normalized vehicle identities or duplicate
research-run compatibility rows; it never merges records.

## JSON data import

The repository includes `data/vehicles.json` and `data/engine_oils_iran.json`.
Import scripts accept either a top-level array or an object containing the
expected collection key (`vehicles` or `engine_oils`). Explicit IDs are
preserved, existing IDs are skipped, invalid rows are reported, and `--dry-run`
validates without writing.

Vehicle example:

```json
{
  "vehicles": [
    {
      "id": 1,
      "manufacturer": "Peugeot",
      "model": "206",
      "trim_variant": null,
      "production_year_from": 2005,
      "production_year_to": 2012,
      "engine_code": "TU5",
      "engine_displacement": 1587,
      "fuel_type": "gasoline"
    }
  ]
}
```

Engine-oil example:

```json
{
  "engine_oils": [
    {
      "id": 1,
      "brand": "Example",
      "name": "Synthetic 10W-40",
      "sae_viscosity": "10W-40",
      "api_spec": "SN",
      "acea_spec": "A3/B4",
      "base_type": "Full Synthetic",
      "oem_approvals": ["PSA B71 2300"]
    }
  ]
}
```

Run imports from `backend`. The current import scripts target PostgreSQL on the
host at `localhost:5432`; adjust their `DATABASE_URL` constant if your database
uses a different host, port, database, or credentials.

```powershell
python scripts/import_vehicles.py ..\data\vehicles.json --dry-run
python scripts/import_vehicles.py ..\data\vehicles.json
python scripts/import_engine_oils.py ..\data\engine_oils_iran.json --dry-run
python scripts/import_engine_oils.py ..\data\engine_oils_iran.json
```

CSV is also supported. `oem_approvals` may be a JSON array or a `|`-separated
string.

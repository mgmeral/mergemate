# MergeMate

MergeMate is a Docker-based **local CI platform**. A developer picks a repo, a feature branch, a target branch, and a validation profile, and clicks Start. The system clones the repo into a **disposable, isolated Docker worker**, validates (merge-conflict check, incremental Maven build, tests, static analysis), reports, and destroys the worker. The developer's machine and repository are never touched.

## Safety model

- The user's working copy is **never used** — every validation clones fresh into an ephemeral container.
- SSH key is mounted **read-only**; no passwords, PATs, or stored credentials.
- A **git guard** enforces an argv-level allow-list; `push`, `commit`, `tag`, `rebase`, and all destructive operations are rejected at the policy layer before any subprocess is created.
- Workers are self-destructing; an **orphan reaper** cleans up containers by label even if the orchestrator crashes.

## Architecture

```
forge_planner/        Build Planner: POM parse → dep graph → changeset → ExecutionPlan
forge_worker/         Git Guard (allow-list) + Validation Lifecycle + hardened Dockerfile
forge_orchestrator/   Docker Worker, Orchestrator, orphan reaper
forge_api/            FastAPI REST API + SQLite repository
forge_spi/            ValidationStep ABC + Git and Maven reference plugins
forge_analysis/       Failure analysis: structured summary, root cause, confidence
web/                  React + Vite + TypeScript dashboard (dark mode)
```

## Build Planner

Pipeline: `changed files → changed modules → dependency graph → affected modules → execution plan → optimised Maven command`

- Discovers modules by recursively following `<modules>` from the root `pom.xml`
- Resolves groupId/version from `<parent>` elements
- Includes modules from active Maven profiles (`activeByDefault` or explicit)
- Strategy: **full build** if a global POM changed or impact ratio ≥ 60%; otherwise **incremental** (`mvn clean verify -pl :a,:b -am`)
- Labels each planned module: `changed` / `dependent` / `dependency`
- Duration estimate: transparent heuristic (30 s + 10 s per `*Test.java` / `*IT.java`), replaceable by historical data

CLI:
```
python -m forge_planner.cli <repo_root> <changed_file> [<changed_file> ...]
```

## API

```
POST /api/v1/validations          Start a validation
GET  /api/v1/validations/{run_id} Get a run (with execution plan + failure analysis)
GET  /api/v1/validations          List recent runs
GET  /api/v1/health               Health check
```

Persistence: SQLite (`MERGEMATE_DB_PATH` env var, default `mergemate.db`).

## Running

**Backend:**
```bash
pip install -e ".[dev]"
MERGEMATE_WORKER_IMAGE=mergemate-worker:latest \
MERGEMATE_SSH_KEY_PATH=~/.ssh/id_rsa \
python -m forge_api.main
```

**Worker image:**
```bash
docker build -t mergemate-worker:latest forge_worker/
```

**Frontend:**
```bash
cd web && npm install && npm run dev
# → http://localhost:5173 (proxies /api to localhost:8080)
```

## Tests

```bash
py -m pytest tests/ -v
```

**191 tests, all passing.** Covers: POM parsing and profile activation, dependency graph, changeset mapping, strategy selection, git guard allow/reject matrix (38 cases), lifecycle step ordering, Docker worker mocking, API endpoints, SQLite repository, plugin SPI, and failure analysis patterns.

## Status

All 7 slices are complete:

| Slice | What | Tests |
|-------|------|-------|
| 1 | Build Planner | 16 |
| 2 | Worker Safety Spine (git guard + lifecycle + Dockerfile) | +46 |
| 3 | Docker orchestration (Worker, Orchestrator, reaper) | +31 |
| 4 | FastAPI API + SQLite persistence | +28 |
| 5 | Plugin SPI (ValidationStep ABC + Git + Maven plugins) | +44 |
| 6 | React + Vite + TypeScript Web UI | (browser-tested) |
| 7 | Failure analysis (pattern matching, confidence, root cause) | +27 |

UI testing requires a running browser — TypeScript compiles in strict mode; run `cd web && npm install && tsc --noEmit` to verify types.

## Docs

- `docs/adr/001-scope-and-stack.md` — Scope and technology choices
- `docs/adr/002-ephemeral-worker-safety.md` — Safety model ADR
- `docs/build-planner-algorithm.md` — Build planner algorithm

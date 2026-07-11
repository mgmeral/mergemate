# Build Planner Algorithm

## Overview

The Build Planner (`forge_planner`) takes a Maven reactor root and a list of changed files, then produces a typed `ExecutionPlan` that tells you exactly which modules to build and with what Maven command.

The pipeline has five stages:

```
changed files
     │
     ▼
[1] POM Discovery  ──────────────────► reactor module map
     │                                  {artifactId → ModuleInfo}
     ▼
[2] Graph Build  ────────────────────► DependencyGraph
     │                                  (directed: B→A means A depends on B)
     ▼
[3] Changeset Mapping  ──────────────► {artifactId → files} + is_global flag
     │
     ▼
[4] Impact Analysis  ────────────────► [ImpactedModule]  (changed + dependents)
     │
     ▼
[5] Strategy Selection  ─────────────► ExecutionPlan (full or incremental)
```

---

## Stage 1: POM Discovery

Entry point: `pom_parser.discover_reactor(root_pom, active_profiles)`

Starting from the root `pom.xml`, the parser performs a breadth-first walk:

1. Parse `<modules>` elements to find child module directories.
2. Parse `<profiles>` — include profile modules when the profile is active.
3. Recurse into each child's `pom.xml`.

For each POM, the parser reads:
- `artifactId`, `groupId`, `version` (inheriting from `<parent>` when absent)
- `packaging` (default: `jar`)
- `<dependencies>` (all, not filtered by scope)
- Whether the POM has `<modules>` or `<dependencyManagement>` (used for global-change detection)

**Profile activation rules (implemented):**
- A profile is active if its `id` appears in `active_profiles`, OR if `<activeByDefault>true</activeByDefault>` is set.
- Property-based and OS-based activation are NOT evaluated (deferred to a future slice).

---

## Stage 2: Dependency Graph

Entry point: `dependency_graph.build_graph(modules)`

For each module, iterates its `<dependencies>` and adds an edge only if the dependency's `artifactId` exists in the reactor:

```
if dep.artifact_id in reactor_ids:
    graph.dependents[dep.artifact_id].add(this_module)
    graph.dependencies[this_module].add(dep.artifact_id)
```

Edge direction: `B → A` means "A depends on B, so B must be built first."  
`graph.dependents[B]` is the set of modules that need B to be built first.

---

## Stage 3: Changeset Mapping

Entry point: `changeset.changed_module_ids(changed_files, modules, repo_root)`

Each changed file is assigned to the module whose directory is its **deepest ancestor** (longest matching path). If no module directory qualifies, the file is assigned to a `_root_` sentinel.

**Global change detection:** A global change (triggering a mandatory full build) is detected when:
- Any file maps to the root sentinel (e.g., the root `pom.xml` itself), OR
- Any changed module has `packaging=pom` with child `<modules>` or `<dependencyManagement>` (it is an aggregator or BOM).

---

## Stage 4: Impact Analysis

Entry point: `impact.compute_impact(changed_ids, graph, include_upstream)`

```
affected = changed_ids ∪ transitive_dependents(changed_ids)
```

Uses a breadth-first traversal of `graph.dependents` from each changed module.

Labels:
- `"changed"` – the module directly contains changed files
- `"dependent"` – reachable via the dependents graph from a changed module
- `"dependency"` – an upstream module pulled in by `-am` (only when `include_upstream=True`)

---

## Stage 5: Strategy Selection

Entry point: `planner.plan(repo_root, changed_files, active_profiles)`

Decision tree:

```
empty changeset?  ──Yes──► full build ("no changed files")
      │
      No
      │
global change?    ──Yes──► full build ("global change detected")
      │
      No
      │
ratio = |affected| / |reactor|
      │
ratio ≥ 0.60?     ──Yes──► full build ("impact ratio ≥ 60%")
      │
      No
      │
                           incremental build
                           mvn clean verify -pl :m1,:m2 -am
```

**Buildable module count**: all modules discovered in the reactor (including the root aggregator). This intentionally uses a conservative denominator so that large reactors with many leaf changes still trigger full builds.

---

## Duration Estimation

Implemented in `planner.estimate_module_duration(module_dir)`.

**Heuristic** (transparent — clearly labeled as an estimate):

```
duration = 30s (base) + 10s × count(*Test.java, *IT.java under src/test/java/)
```

This interface is stable by design. Once historical build data is available in SQLite (a future slice), the implementation can be replaced without changing the calling code.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Directed graph B→A | Matches Maven's natural "build B before A" semantics and makes transitive-dependent queries O(reachable nodes) |
| Deepest-ancestor file mapping | Handles nested Maven modules correctly without ambiguity |
| 60% ratio threshold | Empirically, rebuilding >60% of a reactor is rarely faster than a full build (Maven parallel execution overhead offsets -pl savings) |
| stdlib-only implementation | Zero install friction; works in any Python 3.11+ environment |
| Profile activation without property/OS evaluation | MVP scope; property-based activation requires Maven property resolution which is complex |
| `_root_` sentinel | Keeps the changeset mapping pure (no special-casing in callers); sentinel propagates the global-change signal cleanly |

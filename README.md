# MergeMate

MergeMate is an intelligent local CI build planner for Maven multi-module projects. It analyses the dependency graph of your Maven reactor, maps changed files to their owning modules, and decides whether to run a full build or a targeted incremental build — producing a precise `mvn` command that rebuilds only what is needed, together with transparent duration estimates. The goal is to give developers fast, accurate feedback without requiring any external CI service or touching the repository under analysis.

MergeMate is designed as a read-only tool: it never modifies source files, never pushes to remote repositories, and never executes Maven itself. It reads POM files, walks the file tree for test-class counts, and emits a JSON execution plan that any CI harness or IDE plugin can consume.

## Status

**Slice 1 – Build Planner is complete.** The `forge_planner` Python package implements POM parsing (including Maven profile support), reactor dependency-graph construction, changeset-to-module mapping, transitive impact analysis, full-vs-incremental strategy selection, duration estimation, and a CLI entry point. All unit tests pass.
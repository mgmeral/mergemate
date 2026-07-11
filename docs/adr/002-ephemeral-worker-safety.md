# ADR 002 – Ephemeral Worker Safety Model

**Status:** Accepted  
**Date:** 2026-07-11  
**Author:** MergeMate Team

---

## Context

MergeMate must be safe to run against repositories that the operator does not own, and safe to deploy in shared CI environments where mistakes could corrupt other users' work.

---

## Decision

### No-touch policy on user repositories

MergeMate's analysis phase is strictly read-only with respect to the repository under analysis:

- It opens POM files and source-tree directories for reading only
- It never creates, modifies, or deletes files inside the analysed repository
- It never runs `git` commands that write to the repository (no commits, no resets, no checkouts)
- It never executes Maven or any build tool against the repository

The JSON execution plan it produces is an instruction set for a separate, human- or harness-controlled step.

### Read-only SSH / credential scope

When MergeMate is extended to fetch remote metadata (e.g., fetching POMs from an artefact repository to resolve external version ranges), it will use read-only SSH keys or read-only API tokens. Specifically:

- SSH keys must not have push access to the analysed repository
- API tokens must have the minimum required scope (read-only to package registries)
- Credentials are never written to the analysed repository's git config

### Guard allow-list

Any file-system path that MergeMate is permitted to write to (e.g., its own SQLite database, log files, cached plans) must appear in an explicit allow-list configured at startup. Writes to paths outside the allow-list raise an exception rather than silently succeeding. The default allow-list is:

- `~/.mergemate/` (user-level data directory)
- A path explicitly passed via `--data-dir` CLI flag

### Ephemeral worker isolation

When future slices run MergeMate inside containers or ephemeral CI workers:

- The repository is mounted read-only inside the container
- The container's writable layer is discarded after the plan is emitted
- No persistent credentials are baked into container images; secrets are injected at runtime via environment variables and are never logged

---

## Consequences

- MergeMate can be safely pointed at any repository without risk of data loss
- The no-touch policy is enforced by convention (pure-read code paths) in Slice 1; future slices that add write operations must obtain an explicit review against this ADR
- The allow-list mechanism provides a safety net for future write paths without blocking legitimate use cases

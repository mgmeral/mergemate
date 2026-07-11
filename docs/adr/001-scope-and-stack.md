# ADR 001 – Scope and Stack

**Status:** Accepted  
**Date:** 2026-07-11  
**Author:** MergeMate Team

---

## Context

MergeMate needs to deliver fast, reliable build plans for Maven multi-module projects without introducing complex infrastructure or third-party dependencies.

The core question is: what is the scope of the tool, what runtime environment does it target, and what persistence mechanism is appropriate?

---

## Decision

### Scope: local CI, no production deployment

MergeMate operates entirely on the developer's local machine (or a CI agent that already has access to the repository). It:

- Reads POM files and source trees in a read-only fashion
- Produces a JSON execution plan (the developer or CI harness decides whether to act on it)
- Does NOT deploy artefacts, push to registries, or interact with production systems

This constraint keeps the blast radius of any bug to "wrong build command emitted" rather than "production deployment corrupted."

### Backend: Python (stdlib-first)

Python 3.11+ is chosen for the backend because:

- Rich XML support via `xml.etree.ElementTree` (no external parser needed for POM files)
- Excellent path-manipulation utilities (`os.path`, `pathlib`)
- First-class dataclass support for typed plan structures
- Widely available in CI environments without additional installation steps
- Strong type-annotation support for stable interfaces

External runtime dependencies are intentionally kept to zero (dev tooling uses pytest only). This makes the tool easy to distribute as a single directory or zipapp.

### Persistence: SQLite

When MergeMate evolves beyond pure plan generation (e.g., storing historical build durations to improve duration estimates), SQLite is used because:

- Zero-dependency: ships with Python's `sqlite3` module
- File-based: no daemon, no port, no auth — safe for a local tool
- Sufficient for the expected data volumes (build history per project)
- Easy to inspect with standard tools; easy to back up (just copy the file)

---

## Consequences

- No network access is required at runtime
- The duration-estimation interface is designed to be swapped for historical-data queries once the SQLite store is populated
- Future slices that add server components or a database should create their own ADRs rather than expanding this one

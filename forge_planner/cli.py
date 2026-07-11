"""
cli.py

Command-line interface for the forge_planner build planner.

Usage:
    python -m forge_planner.cli <repo_root> <changed_file> [<changed_file> ...]

Prints the ExecutionPlan as JSON to stdout.

Optional environment variable:
    FORGE_ACTIVE_PROFILES  Comma-separated list of Maven profile ids to activate
                           (in addition to those with activeByDefault=true).
                           Example: FORGE_ACTIVE_PROFILES=extras,ci

Exit codes:
    0  Success
    1  Usage error or planning failure
"""

from __future__ import annotations

import json
import os
import sys

from forge_planner.planner import plan


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) < 1:
        print(
            "Usage: python -m forge_planner.cli <repo_root> [<changed_file> ...]",
            file=sys.stderr,
        )
        return 1

    repo_root = argv[0]
    changed_files = argv[1:]

    # Optional: active profiles via environment variable
    active_profiles_env = os.environ.get("FORGE_ACTIVE_PROFILES", "")
    active_profiles = [p.strip() for p in active_profiles_env.split(",") if p.strip()]

    try:
        execution_plan = plan(
            repo_root=repo_root,
            changed_files=changed_files,
            active_profiles=active_profiles,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(execution_plan.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Historical co-change analysis.

Examines git log to find which test files have historically been changed
in the same commit as a given set of production source files.

Used as an additional signal in test candidate scoring.
"""
from __future__ import annotations

import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class CoChangeMap:
    """
    Maps production file paths to test file paths with co-change counts.

    co_changes[prod_file][test_file] = number of commits where both changed.
    Only test files (path contains /test/ and ends with .java) are recorded.
    """
    co_changes: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    def test_files_for(self, prod_file: str) -> dict[str, int]:
        """Return {test_file: count} for a production file path."""
        return dict(self.co_changes.get(prod_file, {}))

    def co_change_count(self, prod_file: str, test_file: str) -> int:
        """Return how many commits changed both prod_file and test_file together."""
        return self.co_changes.get(prod_file, {}).get(test_file, 0)

    def is_empty(self) -> bool:
        return not self.co_changes


def analyze_cochange(
    repo_dir: str,
    prod_files: list[str],
    max_commits: int = 100,
    days: int = 90,
) -> CoChangeMap:
    """
    Analyse recent git history to find which test files co-change with prod_files.

    Runs one `git log` per production file, limiting to recent commits.
    Never raises — returns an empty CoChangeMap on any error.

    Args:
        repo_dir:    absolute path to the git repository root
        prod_files:  list of relative file paths (changed production files)
        max_commits: maximum number of commits to examine per file
        days:        look-back window in calendar days

    Returns:
        CoChangeMap with co-change counts populated.
    """
    result = CoChangeMap()
    if not prod_files or not os.path.isdir(repo_dir):
        return result

    # Normalise to forward-slash relative paths
    normalised = [p.replace("\\", "/") for p in prod_files]

    try:
        _fill_cochange(result, repo_dir, normalised, max_commits, days)
    except Exception:
        pass  # best-effort; never fails the pipeline

    return result


def _fill_cochange(
    result: CoChangeMap,
    repo_dir: str,
    prod_files: list[str],
    max_commits: int,
    days: int,
) -> None:
    """Internal: fill result.co_changes by running git log for each prod file."""
    for prod_file in prod_files:
        commits = _commits_touching_file(repo_dir, prod_file, max_commits, days)
        for commit_hash in commits:
            changed = _files_in_commit(repo_dir, commit_hash)
            for path in changed:
                norm = path.replace("\\", "/")
                if _is_java_test_file(norm) and norm != prod_file:
                    result.co_changes[prod_file][norm] += 1


def _commits_touching_file(
    repo_dir: str,
    file_path: str,
    max_commits: int,
    days: int,
) -> list[str]:
    """Return list of commit hashes that touched file_path in the last `days` days."""
    argv = [
        "git", "log",
        "--format=%H",
        f"--since={days}.days.ago",
        f"--max-count={max_commits}",
        "--",
        file_path,
    ]
    proc = subprocess.run(
        argv,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _files_in_commit(repo_dir: str, commit_hash: str) -> list[str]:
    """Return list of file paths changed in `commit_hash`.

    Uses diff-tree for merges/normal commits. Falls back to `git show` for
    root commits (which have no parent and diff-tree returns nothing).
    """
    argv = [
        "git", "diff-tree",
        "--no-commit-id",
        "-r",
        "--name-only",
        commit_hash,
    ]
    proc = subprocess.run(
        argv,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return []
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if files:
        return files

    # Root commit: diff-tree against the empty tree
    argv_root = [
        "git", "diff-tree",
        "--no-commit-id",
        "-r",
        "--name-only",
        "--root",
        commit_hash,
    ]
    proc2 = subprocess.run(
        argv_root,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc2.returncode != 0:
        return []
    return [line.strip() for line in proc2.stdout.splitlines() if line.strip()]


def _is_java_test_file(path: str) -> bool:
    """Return True if path looks like a Java test source file."""
    if not path.endswith(".java"):
        return False
    norm = path.replace("\\", "/")
    return "/test/" in norm or norm.startswith("test/")

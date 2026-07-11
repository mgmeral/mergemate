import subprocess
import os
from mergemate.domain.models import ChangedFile, GitChangeSet


def get_merge_base(repo_dir: str, source_ref: str, target_ref: str) -> str:
    """Run: git merge-base <source_ref> <target_ref>. Returns SHA."""
    result = subprocess.run(
        ["git", "merge-base", source_ref, target_ref],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def get_changed_files(repo_dir: str, merge_base: str, source_ref: str) -> list[ChangedFile]:
    """
    Run: git diff --name-status <merge_base>..<source_ref>
    Parse output into ChangedFile list.
    Status codes: A=added, M=modified, D=deleted, R=renamed, C=copied
    """
    result = subprocess.run(
        ["git", "diff", "--name-status", f"{merge_base}..{source_ref}"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    changed_files: list[ChangedFile] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if not parts:
            continue

        status_code = parts[0]

        if status_code.startswith("R"):
            # Rename: R100\told_path\tnew_path
            old_path = parts[1] if len(parts) > 1 else None
            new_path = parts[2] if len(parts) > 2 else parts[1]
            changed_files.append(
                ChangedFile(path=new_path, status="renamed", old_path=old_path)
            )
        elif status_code.startswith("C"):
            # Copy: C100\told_path\tnew_path
            old_path = parts[1] if len(parts) > 1 else None
            new_path = parts[2] if len(parts) > 2 else parts[1]
            changed_files.append(
                ChangedFile(path=new_path, status="copied", old_path=old_path)
            )
        elif status_code == "A":
            path = parts[1] if len(parts) > 1 else ""
            changed_files.append(ChangedFile(path=path, status="added"))
        elif status_code == "M":
            path = parts[1] if len(parts) > 1 else ""
            changed_files.append(ChangedFile(path=path, status="modified"))
        elif status_code == "D":
            path = parts[1] if len(parts) > 1 else ""
            changed_files.append(ChangedFile(path=path, status="deleted"))
        else:
            # Unknown status — treat as modified
            path = parts[1] if len(parts) > 1 else ""
            changed_files.append(ChangedFile(path=path, status="modified"))

    return changed_files


def build_changeset(
    repo_dir: str,
    source_ref: str = "HEAD",
    target_ref: str = "origin/main",
) -> GitChangeSet:
    """
    Build a complete GitChangeSet:
    1. Compute merge_base
    2. Get changed files
    3. Classify files into categories (java_production, java_test, pom, config, migration)
    Returns GitChangeSet.
    """
    merge_base = get_merge_base(repo_dir, source_ref, target_ref)
    changed_files = get_changed_files(repo_dir, merge_base, source_ref)

    changeset = GitChangeSet(
        source_ref=source_ref,
        target_ref=target_ref,
        merge_base=merge_base,
        changed_files=changed_files,
    )

    for cf in changed_files:
        category = _classify_file(cf)
        if category == "java_production":
            changeset.java_production_files.append(cf)
        elif category == "java_test":
            changeset.java_test_files.append(cf)
        elif category == "pom":
            changeset.pom_files.append(cf)
        elif category == "config":
            changeset.config_files.append(cf)
        elif category == "migration":
            changeset.migration_files.append(cf)

    return changeset


def _classify_file(cf: ChangedFile) -> str:
    """
    Return category: "java_production", "java_test", "pom", "config", "migration", "other"

    java_test: path contains /test/ AND ends in .java
    java_production: ends in .java AND NOT /test/
    pom: filename == "pom.xml"
    migration: path matches db/changelog/, flyway, liquibase, .sql under migration dirs
    config: ends in .yml, .yaml, .properties, .xml (but not pom.xml)
    """
    path = cf.path
    # Normalise path separators for cross-platform matching
    norm_path = path.replace("\\", "/")
    lower_path = norm_path.lower()
    filename = os.path.basename(norm_path)

    # pom.xml check
    if filename == "pom.xml":
        return "pom"

    # Java files
    if lower_path.endswith(".java"):
        # Use /test/ path segment check (case-insensitive)
        if "/test/" in norm_path or norm_path.startswith("test/"):
            return "java_test"
        return "java_production"

    # Migration files
    migration_indicators = [
        "db/changelog",
        "db/migration",
        "flyway",
        "liquibase",
    ]
    is_sql = lower_path.endswith(".sql")
    for indicator in migration_indicators:
        if indicator in lower_path:
            return "migration"
    if is_sql:
        # SQL files in migration-related paths
        path_parts = lower_path.split("/")
        migration_dirs = {"migration", "migrations", "changelog", "changelogs", "flyway", "liquibase", "db"}
        for part in path_parts[:-1]:  # exclude filename
            if part in migration_dirs:
                return "migration"

    # Config files
    config_extensions = (".yml", ".yaml", ".properties", ".xml")
    if any(lower_path.endswith(ext) for ext in config_extensions):
        return "config"

    return "other"

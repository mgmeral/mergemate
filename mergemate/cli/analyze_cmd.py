import json
import os
import sys
from mergemate.git.diff import build_changeset
from mergemate.maven.jdk import detect_jdk_requirement, detect_maven_runtime, check_jdk_compatibility
from mergemate.maven.wrapper import find_maven_executable
from mergemate.config.loader import load_config


def run_analyze(args):
    repo_dir = args.repo_dir or os.getcwd()
    config = load_config(repo_dir)

    target = args.target or config.target_branch
    if not target:
        print("Error: --target is required (or set targetBranch in .mergemate.yml)", file=sys.stderr)
        sys.exit(1)

    source = args.source
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()] if args.profiles else []

    print(f"MergeMate Impact Analysis\n")
    print(f"Source: {source}")
    print(f"Target: {target}")

    # Git diff
    changeset = build_changeset(repo_dir, source, target)
    print(f"Merge base: {changeset.merge_base[:8]}")
    print()

    # JDK detection
    root_pom = os.path.join(repo_dir, "pom.xml")
    maven_exe = find_maven_executable(repo_dir)

    if os.path.exists(root_pom):
        jdk_req = detect_jdk_requirement(root_pom)
        try:
            jdk_runtime = detect_maven_runtime(maven_exe)
            jdk_compat = check_jdk_compatibility(jdk_req, jdk_runtime)
            _print_jdk_section(jdk_req, jdk_runtime, jdk_compat)
            if not jdk_compat.compatible:
                print(f"\nERROR: {jdk_compat.message}")
                sys.exit(1)
        except Exception as e:
            print(f"JDK: Could not detect Maven runtime: {e}")

    # Changed files
    print(f"Changed files ({len(changeset.changed_files)}):")
    for cf in changeset.changed_files[:20]:
        print(f"  [{cf.status[0].upper()}] {cf.path}")
    if len(changeset.changed_files) > 20:
        print(f"  ... and {len(changeset.changed_files) - 20} more")

    print()
    print("Changed Java production files:")
    for cf in changeset.java_production_files:
        print(f"  {cf.path}")
    print()
    print("Changed POM files:")
    for cf in changeset.pom_files:
        print(f"  {cf.path}")

    if args.json:
        output = {
            "source": source,
            "target": target,
            "merge_base": changeset.merge_base,
            "changed_files": [{"path": f.path, "status": f.status} for f in changeset.changed_files],
            "java_production_files": [f.path for f in changeset.java_production_files],
            "java_test_files": [f.path for f in changeset.java_test_files],
            "pom_files": [f.path for f in changeset.pom_files],
        }
        print(json.dumps(output, indent=2))


def _print_jdk_section(req, runtime, compat):
    status = "yes" if compat.compatible else "NO (incompatible)"
    print(f"JDK:")
    print(f"  Required: {req.required_version or 'unknown'}")
    print(f"  Maven runtime: {runtime.java_version}")
    print(f"  Compatible: {status}")
    if req.detected_from:
        print(f"  Detected from: {req.detected_from}")

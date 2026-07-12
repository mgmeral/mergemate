"""
Console output formatter for MergeMate impact analysis.
"""
from __future__ import annotations

from mergemate.domain.models import ImpactAnalysis, GitChangeSet, ValidationPlan, ValidationExecution


def print_analyze_report(
    changeset: GitChangeSet,
    impact: ImpactAnalysis | None = None,
    plan: ValidationPlan | None = None,
    jdk_compat=None,
) -> None:
    """
    Print the full analyze report to stdout.

    Format:

    MergeMate Impact Analysis

    Source: HEAD
    Target: origin/premaster
    Merge base: abc1234

    JDK:
      Required: 17
      Maven runtime: 17.0.12
      Compatible: yes
      Detected from: root pom.xml -> maven.compiler.release

    Changed modules:
      order-service

    Affected modules:
      order-service       changed
      checkout-api        dependent
      shared-common       dependency

    Changed Java production files:
      services/order-service/src/main/java/.../OrderService.java

    Changed POM files:
      (none)

    Risk: MEDIUM
    Full validation recommended: NO

    Recommended Maven command:
      ./mvnw -pl :order-service,:checkout-api -am test
    """
    print("MergeMate Impact Analysis")
    print()
    print(f"Source: {changeset.source_ref}")
    print(f"Target: {changeset.target_ref}")
    print(f"Merge base: {changeset.merge_base[:8] if changeset.merge_base else 'unknown'}")
    print()

    # JDK section
    if jdk_compat is not None:
        req = jdk_compat.requirement
        rt = jdk_compat.runtime
        status = "yes" if jdk_compat.compatible else "NO (incompatible)"
        print("JDK:")
        print(f"  Required: {req.required_version or 'unknown'}")
        print(f"  Maven runtime: {rt.java_version}")
        print(f"  Compatible: {status}")
        if req.detected_from:
            print(f"  Detected from: {req.detected_from}")
        print()

    if impact is None:
        print("Changed files:")
        for cf in changeset.changed_files:
            print(f"  [{cf.status[0].upper()}] {cf.path}")
        return

    # Changed modules
    print("Changed modules:")
    if impact.changed_modules:
        for mod_id in impact.changed_modules:
            print(f"  {mod_id}")
    else:
        print("  (none)")
    print()

    # Affected modules
    print("Affected modules:")
    if impact.affected_modules:
        max_id_len = max(len(m.artifact_id) for m in impact.affected_modules)
        for mod_impact in impact.affected_modules:
            pad = " " * (max_id_len - len(mod_impact.artifact_id) + 4)
            print(f"  {mod_impact.artifact_id}{pad}{mod_impact.label}")
    else:
        print("  (none)")
    print()

    # Changed Java production files
    print("Changed Java production files:")
    if changeset.java_production_files:
        for cf in changeset.java_production_files:
            print(f"  {cf.path}")
    else:
        print("  (none)")
    print()

    # Changed POM files
    print("Changed POM files:")
    if changeset.pom_files:
        for cf in changeset.pom_files:
            print(f"  {cf.path}")
    else:
        print("  (none)")
    print()

    # Risk
    print(f"Risk: {impact.risk_level}")
    if impact.risk_reasons:
        for reason in impact.risk_reasons:
            print(f"  - {reason}")

    full_rec = "YES" if impact.full_build_recommended else "NO"
    print(f"Full validation recommended: {full_rec}")
    print()

    # Selected tests (Java analysis)
    if impact.test_candidates:
        print("Selected tests:")
        max_name_len = max(len(c.class_name) for c in impact.test_candidates)
        for candidate in impact.test_candidates:
            name_pad = " " * (max_name_len - len(candidate.class_name) + 2)
            conf_pad = " " * (6 - len(candidate.confidence) + 2)
            print(f"  {candidate.class_name}{name_pad}{candidate.confidence}{conf_pad}{candidate.score:.2f}")
        # Print reasons for HIGH confidence tests
        high_tests = [c for c in impact.test_candidates if c.confidence == "HIGH"]
        if high_tests:
            print()
            for candidate in high_tests:
                print(f"  Reasons ({candidate.class_name}):")
                for reason in candidate.reasons:
                    print(f"    - {reason}")
        print()

    # Maven command
    if plan is not None and plan.maven_command is not None:
        print("Recommended Maven command:")
        print(f"  {plan.maven_command.display_command}")
    elif impact.strategy == "full":
        print("Strategy: full build")
    else:
        print("Strategy: incremental")


def print_validation_result(execution: ValidationExecution) -> None:
    """
    Print the validation result summary after Maven completes.

    Format:
    Result: SUCCESS (42s)
    Report: .mergemate/runs/abc-123/report.json

    or:
    Result: TIMEOUT (1800s)
    Maven process was killed after timeout.
    """
    duration = int(execution.duration_seconds)
    status = execution.status.upper()
    print(f"Result: {status} ({duration}s)")

    if execution.timed_out:
        print("Maven process was killed after timeout.")

    if execution.report_dir:
        report_path = execution.report_dir.rstrip("/\\")
        print(f"Report: {report_path}/report.json")
        print(f"HTML:   {report_path}/report.html")

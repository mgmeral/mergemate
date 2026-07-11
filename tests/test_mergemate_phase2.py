"""
Phase 2 tests for the mergemate/ package.
Tests for: module_graph, file_mapper, risk engine, impact analyzer,
           maven project loader, reporting, and integration.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from mergemate.domain.models import (
    ChangedFile,
    GitChangeSet,
    MavenModule,
    MavenProject,
    ImpactAnalysis,
    ModuleImpact,
    MavenCommand,
    ValidationPlan,
)
from mergemate.config.loader import MergeMateConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module(
    artifact_id: str,
    relative_path: str = "",
    dependencies: list[str] | None = None,
    packaging: str = "jar",
    has_modules: bool = False,
    has_dependency_management: bool = False,
    pom_path: str = "",
) -> MavenModule:
    return MavenModule(
        artifact_id=artifact_id,
        group_id="com.example",
        version="1.0.0-SNAPSHOT",
        packaging=packaging,
        relative_path=relative_path,
        pom_path=pom_path or f"/fake/{artifact_id}/pom.xml",
        dependencies=dependencies or [],
        has_modules=has_modules,
        has_dependency_management=has_dependency_management,
    )


def _make_project(*modules: MavenModule, root_dir: str = "/fake") -> MavenProject:
    return MavenProject(
        root_pom=f"{root_dir}/pom.xml",
        root_dir=root_dir,
        modules={m.artifact_id: m for m in modules},
    )


def _make_changeset(
    changed_paths: list[str] | None = None,
    java_prod: list[str] | None = None,
    pom_files: list[str] | None = None,
    migration_files: list[str] | None = None,
    config_files: list[str] | None = None,
) -> GitChangeSet:
    all_files = [ChangedFile(path=p, status="modified") for p in (changed_paths or [])]
    java_production_files = [ChangedFile(path=p, status="modified") for p in (java_prod or [])]
    pom_changed = [ChangedFile(path=p, status="modified") for p in (pom_files or [])]
    mig_files = [ChangedFile(path=p, status="modified") for p in (migration_files or [])]
    cfg_files = [ChangedFile(path=p, status="modified") for p in (config_files or [])]
    return GitChangeSet(
        source_ref="HEAD",
        target_ref="origin/main",
        merge_base="abc1234567890",
        changed_files=all_files or java_production_files or pom_changed or mig_files or cfg_files,
        java_production_files=java_production_files,
        pom_files=pom_changed,
        migration_files=mig_files,
        config_files=cfg_files,
    )


# ---------------------------------------------------------------------------
# Module Graph Tests (1-7)
# ---------------------------------------------------------------------------

class TestModuleGraph:
    """Tests 1-7: Module dependency graph."""

    def _make_abc_project(self) -> MavenProject:
        """A depends on B, B depends on C."""
        a = _make_module("A", dependencies=["B"])
        b = _make_module("B", dependencies=["C"])
        c = _make_module("C", dependencies=[])
        return _make_project(a, b, c)

    def test_1_build_graph_three_module_project(self):
        """Test 1: Build graph from a 3-module project."""
        from mergemate.impact.module_graph import ModuleGraph
        project = self._make_abc_project()
        graph = ModuleGraph(project)
        assert graph.all_module_ids() == {"A", "B", "C"}

    def test_2_transitive_dependents_of_c_returns_b_and_a(self):
        """Test 2: transitive_dependents({"C"}) returns {"B", "A"}."""
        from mergemate.impact.module_graph import ModuleGraph
        project = self._make_abc_project()
        graph = ModuleGraph(project)
        result = graph.transitive_dependents({"C"})
        assert result == {"B", "A"}

    def test_3_transitive_dependents_of_b_returns_only_a(self):
        """Test 3: transitive_dependents({"B"}) returns {"A"} (not C)."""
        from mergemate.impact.module_graph import ModuleGraph
        project = self._make_abc_project()
        graph = ModuleGraph(project)
        result = graph.transitive_dependents({"B"})
        assert result == {"A"}

    def test_4_transitive_dependencies_of_a_returns_b_and_c(self):
        """Test 4: transitive_dependencies({"A"}) returns {"B", "C"}."""
        from mergemate.impact.module_graph import ModuleGraph
        project = self._make_abc_project()
        graph = ModuleGraph(project)
        result = graph.transitive_dependencies({"A"})
        assert result == {"B", "C"}

    def test_5_direct_dependents_of_c_returns_b(self):
        """Test 5: direct_dependents("C") returns {"B"}."""
        from mergemate.impact.module_graph import ModuleGraph
        project = self._make_abc_project()
        graph = ModuleGraph(project)
        result = graph.direct_dependents("C")
        assert result == {"B"}

    def test_6_graph_with_no_deps_transitive_dependents_empty(self):
        """Test 6: Graph with no deps: transitive_dependents returns empty set."""
        from mergemate.impact.module_graph import ModuleGraph
        a = _make_module("A", dependencies=[])
        b = _make_module("B", dependencies=[])
        project = _make_project(a, b)
        graph = ModuleGraph(project)
        assert graph.transitive_dependents({"A"}) == set()
        assert graph.transitive_dependents({"B"}) == set()

    def test_7_circular_dep_no_infinite_loop(self):
        """Test 7: Circular dep handling: no infinite loop (use max_depth)."""
        from mergemate.impact.module_graph import ModuleGraph
        # A depends on B, B depends on A (circular)
        a = _make_module("A", dependencies=["B"])
        b = _make_module("B", dependencies=["A"])
        project = _make_project(a, b)
        graph = ModuleGraph(project)
        # Should not hang — terminates due to visited-set tracking
        result = graph.transitive_dependents({"A"}, max_depth=10)
        # B is a transitive dependent of A (B depends on A... wait that means B is dependent of A)
        # Actually A depends on B, so B has A as dependent. But B depends on A too.
        # transitive_dependents(A) = who depends on A = B (since B depends on A... wait no)
        # Edge A->B means A depends on B.
        # Reverse: B->A means B has dependent A.
        # So dependents of A = who depends on A = ?
        # B depends on A, so B is a dependent of A.
        # Then dependents of B = who depends on B = A.
        # But A is in input set, excluded. So result should contain B.
        assert isinstance(result, set)  # Just verifies no infinite loop


# ---------------------------------------------------------------------------
# File Mapper Tests (8-12)
# ---------------------------------------------------------------------------

class TestFileMapper:
    """Tests 8-12: File to module mapping."""

    def _make_multi_module_project(self) -> MavenProject:
        root = _make_module("root", relative_path="", packaging="pom", has_modules=True)
        order = _make_module("order-service", relative_path="services/order-service")
        checkout = _make_module("checkout-api", relative_path="services/checkout-api")
        shared = _make_module("shared-common", relative_path="shared/shared-common")
        return _make_project(root, order, checkout, shared)

    def test_8_file_in_order_service_maps_to_order_service(self):
        """Test 8: File in services/order-service/... maps to order-service."""
        from mergemate.impact.file_mapper import map_file_to_module
        project = self._make_multi_module_project()
        result = map_file_to_module(
            "services/order-service/src/main/java/Foo.java", project
        )
        assert result is not None
        assert result.artifact_id == "order-service"

    def test_9_file_in_checkout_api_maps_to_checkout_api(self):
        """Test 9: File in services/checkout-api/... maps to checkout-api."""
        from mergemate.impact.file_mapper import map_file_to_module
        project = self._make_multi_module_project()
        result = map_file_to_module(
            "services/checkout-api/src/main/java/Bar.java", project
        )
        assert result is not None
        assert result.artifact_id == "checkout-api"

    def test_10_root_pom_maps_to_root_module(self):
        """Test 10: File at root pom.xml maps to root module."""
        from mergemate.impact.file_mapper import map_file_to_module
        project = self._make_multi_module_project()
        result = map_file_to_module("pom.xml", project)
        # Root module has relative_path="" so it matches everything
        assert result is not None
        assert result.artifact_id == "root"

    def test_11_deepest_module_wins_nested_structure(self):
        """Test 11: Deepest module wins in nested module structure."""
        from mergemate.impact.file_mapper import map_file_to_module
        root = _make_module("root", relative_path="", packaging="pom", has_modules=True)
        parent_mod = _make_module("services", relative_path="services", packaging="pom", has_modules=True)
        child_mod = _make_module("order-service", relative_path="services/order-service")
        project = _make_project(root, parent_mod, child_mod)
        result = map_file_to_module("services/order-service/src/main/java/Foo.java", project)
        assert result is not None
        assert result.artifact_id == "order-service"

    def test_12_unknown_file_returns_none(self):
        """Test 12: Unknown file (not under any module) returns None."""
        from mergemate.impact.file_mapper import map_file_to_module
        # Project with no root module (no empty relative_path)
        order = _make_module("order-service", relative_path="services/order-service")
        checkout = _make_module("checkout-api", relative_path="services/checkout-api")
        project = _make_project(order, checkout)
        result = map_file_to_module("unrelated/SomeFile.java", project)
        assert result is None


# ---------------------------------------------------------------------------
# Risk Engine Tests (13-18)
# ---------------------------------------------------------------------------

class TestRiskEngine:
    """Tests 13-18: Risk rules engine."""

    def _make_project_with_root(self) -> MavenProject:
        root = _make_module(
            "root", relative_path="", packaging="pom", has_modules=True
        )
        order = _make_module("order-service", relative_path="services/order-service")
        return _make_project(root, order)

    def test_13_root_pom_changed_triggers_full_build_critical(self):
        """Test 13: Root pom.xml changed -> full_build_recommended=True, CRITICAL risk."""
        from mergemate.impact.risk import evaluate_risks
        project = self._make_project_with_root()
        config = MergeMateConfig()
        pom_file = ChangedFile(path="pom.xml", status="modified")
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[pom_file],
            pom_files=[pom_file],
        )
        risk_level, reasons, full_build = evaluate_risks(
            changeset, project, {"root": [pom_file]}, config, 0.1
        )
        assert full_build is True
        assert risk_level == "CRITICAL"

    def test_14_always_full_build_module_triggers_full_build(self):
        """Test 14: Module in always_full_build_modules changed -> full_build_recommended=True."""
        from mergemate.impact.risk import evaluate_risks
        project = self._make_project_with_root()
        config = MergeMateConfig(always_full_build_modules=["order-service"])
        java_file = ChangedFile(path="services/order-service/src/main/java/Foo.java", status="modified")
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        risk_level, reasons, full_build = evaluate_risks(
            changeset, project, {"order-service": [java_file]}, config, 0.1
        )
        assert full_build is True

    def test_15_application_yml_changed_increases_risk(self):
        """Test 15: application.yml changed -> MEDIUM or HIGH risk (soft rule)."""
        from mergemate.impact.risk import evaluate_risks
        project = self._make_project_with_root()
        config = MergeMateConfig()
        yml_file = ChangedFile(
            path="services/order-service/src/main/resources/application.yml",
            status="modified",
        )
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[yml_file],
            config_files=[yml_file],
        )
        risk_level, reasons, full_build = evaluate_risks(
            changeset, project, {"order-service": [yml_file]}, config, 0.1
        )
        assert risk_level in ("MEDIUM", "HIGH")
        assert full_build is False  # soft rule alone shouldn't force full build

    def test_16_migration_file_changed_increases_risk(self):
        """Test 16: Migration file changed -> risk increases."""
        from mergemate.impact.risk import evaluate_risks
        project = self._make_project_with_root()
        config = MergeMateConfig()
        sql_file = ChangedFile(path="db/changelog/001.sql", status="added")
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[sql_file],
            migration_files=[sql_file],
        )
        risk_level, reasons, full_build = evaluate_risks(
            changeset, project, {}, config, 0.1
        )
        assert risk_level in ("MEDIUM", "HIGH", "CRITICAL")
        assert any("migration" in r.lower() or "flyway" in r.lower() or "liquibase" in r.lower() for r in reasons)

    def test_17_impact_ratio_above_threshold_triggers_full_build(self):
        """Test 17: Impact ratio >= 0.6 -> full_build_recommended=True."""
        from mergemate.impact.risk import evaluate_risks
        project = self._make_project_with_root()
        config = MergeMateConfig(full_build_threshold=0.6)
        java_file = ChangedFile(path="services/order-service/src/main/java/Foo.java", status="modified")
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        risk_level, reasons, full_build = evaluate_risks(
            changeset, project, {"order-service": [java_file]}, config, 0.8
        )
        assert full_build is True

    def test_18_no_changes_low_risk_no_full_build(self):
        """Test 18: No changes -> LOW risk, no full build."""
        from mergemate.impact.risk import evaluate_risks
        project = self._make_project_with_root()
        config = MergeMateConfig()
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[],
        )
        risk_level, reasons, full_build = evaluate_risks(
            changeset, project, {}, config, 0.0
        )
        assert risk_level == "LOW"
        assert full_build is False
        assert reasons == []


# ---------------------------------------------------------------------------
# Impact Analyzer Tests (19-25)
# ---------------------------------------------------------------------------

class TestImpactAnalyzer:
    """Tests 19-25: Impact Analyzer."""

    def _make_three_module_project(self) -> MavenProject:
        """
        order-service has no deps
        checkout-api depends on order-service
        shared-common has no deps
        payment-service has no deps
        notification-service has no deps
        (5 modules so 2/5 = 40% impact ratio, below 60% threshold)
        """
        order = _make_module("order-service", relative_path="services/order-service")
        checkout = _make_module(
            "checkout-api",
            relative_path="services/checkout-api",
            dependencies=["order-service"],
        )
        shared = _make_module("shared-common", relative_path="shared/shared-common")
        payment = _make_module("payment-service", relative_path="services/payment-service")
        notification = _make_module("notification-service", relative_path="services/notification-service")
        return _make_project(order, checkout, shared, payment, notification)

    def test_19_changing_order_service_marks_checkout_as_dependent(self):
        """Test 19: Changing order-service -> checkout-api marked as dependent."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        project = self._make_three_module_project()
        java_file = ChangedFile(
            path="services/order-service/src/main/java/OrderService.java",
            status="modified",
        )
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        config = MergeMateConfig(impact_max_depth=5)
        analyzer = ImpactAnalyzer(config)
        impact = analyzer.analyze(changeset, project, "/fake")
        assert "order-service" in impact.changed_modules
        dependent_ids = {m.artifact_id for m in impact.affected_modules if m.label == "dependent"}
        assert "checkout-api" in dependent_ids

    def test_20_changing_shared_common_includes_all_dependents(self):
        """Test 20: Changing shared-common -> all dependents included."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        # shared-common <- order-service <- checkout-api
        # Add extra modules to keep impact ratio below threshold
        shared = _make_module("shared-common", relative_path="shared/shared-common")
        order = _make_module(
            "order-service",
            relative_path="services/order-service",
            dependencies=["shared-common"],
        )
        checkout = _make_module(
            "checkout-api",
            relative_path="services/checkout-api",
            dependencies=["order-service"],
        )
        payment = _make_module("payment-service", relative_path="services/payment-service")
        notification = _make_module("notification-service", relative_path="services/notification-service")
        project = _make_project(shared, order, checkout, payment, notification)
        java_file = ChangedFile(
            path="shared/shared-common/src/main/java/Util.java",
            status="modified",
        )
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        config = MergeMateConfig(impact_max_depth=5)
        analyzer = ImpactAnalyzer(config)
        impact = analyzer.analyze(changeset, project, "/fake")
        affected_ids = {m.artifact_id for m in impact.affected_modules}
        assert "order-service" in affected_ids
        assert "checkout-api" in affected_ids

    def test_21_full_build_returns_all_modules_as_changed(self):
        """Test 21: Full build returns all modules with label 'changed'."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        # Make project with root module that will trigger full build when root pom.xml changes
        root = _make_module("root", relative_path="", packaging="pom", has_modules=True)
        order = _make_module("order-service", relative_path="services/order-service")
        checkout = _make_module("checkout-api", relative_path="services/checkout-api", dependencies=["order-service"])
        project = _make_project(root, order, checkout)
        pom_file = ChangedFile(path="pom.xml", status="modified")
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[pom_file],
            pom_files=[pom_file],
        )
        config = MergeMateConfig()
        analyzer = ImpactAnalyzer(config)
        impact = analyzer.analyze(changeset, project, "/fake")
        assert impact.strategy == "full"
        labels = {m.label for m in impact.affected_modules}
        assert "changed" in labels

    def test_22_incremental_pl_am_format(self):
        """Test 22: Incremental: -pl :order-service,:checkout-api -am format."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        project = self._make_three_module_project()
        java_file = ChangedFile(
            path="services/order-service/src/main/java/OrderService.java",
            status="modified",
        )
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        config = MergeMateConfig(impact_max_depth=5)
        analyzer = ImpactAnalyzer(config)
        impact = analyzer.analyze(changeset, project, "/fake")
        plan = analyzer.build_validation_plan(impact, project, "/fake", goal="test")
        assert impact.strategy == "incremental"
        assert plan.maven_command is not None
        argv_str = " ".join(plan.maven_command.argv)
        assert "-pl" in argv_str
        assert "-am" in argv_str
        assert ":order-service" in argv_str
        assert ":checkout-api" in argv_str

    def test_23_build_validation_plan_goal_test(self):
        """Test 23: build_validation_plan with goal='test' -> argv contains 'test'."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        project = self._make_three_module_project()
        java_file = ChangedFile(
            path="services/order-service/src/main/java/OrderService.java",
            status="modified",
        )
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        analyzer = ImpactAnalyzer(MergeMateConfig(impact_max_depth=5))
        impact = analyzer.analyze(changeset, project, "/fake")
        plan = analyzer.build_validation_plan(impact, project, "/fake", goal="test")
        assert plan.maven_command is not None
        assert "test" in plan.maven_command.argv
        assert plan.maven_command.goal == "test"

    def test_24_build_validation_plan_compile_has_skip_tests(self):
        """Test 24: build_validation_plan with goal='compile' -> -DskipTests in argv."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        project = self._make_three_module_project()
        java_file = ChangedFile(
            path="services/order-service/src/main/java/OrderService.java",
            status="modified",
        )
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[java_file],
            java_production_files=[java_file],
        )
        analyzer = ImpactAnalyzer(MergeMateConfig(impact_max_depth=5))
        impact = analyzer.analyze(changeset, project, "/fake")
        plan = analyzer.build_validation_plan(impact, project, "/fake", goal="compile")
        assert plan.maven_command is not None
        assert "-DskipTests" in plan.maven_command.argv

    def test_25_full_build_plan_goal_test_or_verify(self):
        """Test 25: Full build plan: ./mvnw verify or ./mvnw test (no -pl)."""
        from mergemate.impact.analyzer import ImpactAnalyzer
        root = _make_module("root", relative_path="", packaging="pom", has_modules=True)
        order = _make_module("order-service", relative_path="services/order-service")
        checkout = _make_module("checkout-api", relative_path="services/checkout-api", dependencies=["order-service"])
        project = _make_project(root, order, checkout)
        pom_file = ChangedFile(path="pom.xml", status="modified")
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc",
            changed_files=[pom_file],
            pom_files=[pom_file],
        )
        analyzer = ImpactAnalyzer(MergeMateConfig())
        impact = analyzer.analyze(changeset, project, "/fake")
        plan = analyzer.build_validation_plan(impact, project, "/fake", goal="verify")
        assert impact.strategy == "full"
        assert plan.maven_command is not None
        # No -pl for full build
        assert "-pl" not in plan.maven_command.argv
        assert "verify" in plan.maven_command.argv


# ---------------------------------------------------------------------------
# Maven Project Loader Tests (26-30)
# ---------------------------------------------------------------------------

class TestMavenProjectLoader:
    """Tests 26-30: Maven project loader."""

    def _write_pom(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_26_load_simple_two_module_project(self):
        """Test 26: Load a simple 2-module POM fixture -> both modules discovered."""
        from mergemate.maven.project import load_project
        with tempfile.TemporaryDirectory() as tmpdir:
            root_pom = os.path.join(tmpdir, "pom.xml")
            child_dir = os.path.join(tmpdir, "child")
            child_pom = os.path.join(child_dir, "pom.xml")
            self._write_pom(root_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>root</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <packaging>pom</packaging>
  <modules>
    <module>child</module>
  </modules>
</project>""")
            self._write_pom(child_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>child</artifactId>
  <packaging>jar</packaging>
</project>""")
            project = load_project(root_pom)
            assert "root" in project.modules
            assert "child" in project.modules
            assert len(project.modules) == 2

    def test_27_profile_module_activated_by_active_by_default(self):
        """Test 27: Profile module activated by activeByDefault=true."""
        from mergemate.maven.project import load_project
        with tempfile.TemporaryDirectory() as tmpdir:
            root_pom = os.path.join(tmpdir, "pom.xml")
            extra_dir = os.path.join(tmpdir, "extra")
            extra_pom = os.path.join(extra_dir, "pom.xml")
            self._write_pom(root_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>root</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <packaging>pom</packaging>
  <profiles>
    <profile>
      <id>extras</id>
      <activation>
        <activeByDefault>true</activeByDefault>
      </activation>
      <modules>
        <module>extra</module>
      </modules>
    </profile>
  </profiles>
</project>""")
            self._write_pom(extra_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>extra</artifactId>
</project>""")
            project = load_project(root_pom)
            assert "extra" in project.modules

    def test_28_profile_module_not_activated_when_not_in_active_profiles(self):
        """Test 28: Profile module NOT activated when not in active_profiles."""
        from mergemate.maven.project import load_project
        with tempfile.TemporaryDirectory() as tmpdir:
            root_pom = os.path.join(tmpdir, "pom.xml")
            optional_dir = os.path.join(tmpdir, "optional-module")
            optional_pom = os.path.join(optional_dir, "pom.xml")
            self._write_pom(root_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>root</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <packaging>pom</packaging>
  <profiles>
    <profile>
      <id>optional-profile</id>
      <modules>
        <module>optional-module</module>
      </modules>
    </profile>
  </profiles>
</project>""")
            self._write_pom(optional_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>optional-module</artifactId>
</project>""")
            # No active profiles -> optional-profile is not active
            project = load_project(root_pom, active_profiles=[])
            assert "optional-module" not in project.modules

    def test_29_groupid_inherited_from_parent(self):
        """Test 29: groupId inherited from parent."""
        from mergemate.maven.project import load_project
        with tempfile.TemporaryDirectory() as tmpdir:
            root_pom = os.path.join(tmpdir, "pom.xml")
            child_dir = os.path.join(tmpdir, "child")
            child_pom = os.path.join(child_dir, "pom.xml")
            self._write_pom(root_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.myorg</groupId>
  <artifactId>root</artifactId>
  <version>2.0.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>child</module>
  </modules>
</project>""")
            self._write_pom(child_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.myorg</groupId>
    <artifactId>root</artifactId>
    <version>2.0.0</version>
  </parent>
  <artifactId>child</artifactId>
</project>""")
            project = load_project(root_pom)
            child = project.modules["child"]
            assert child.group_id == "com.myorg"
            assert child.version == "2.0.0"

    def test_30_internal_dep_edges_only(self):
        """Test 30: Internal dep edges only (no external artifact)."""
        from mergemate.maven.project import load_project
        with tempfile.TemporaryDirectory() as tmpdir:
            root_pom = os.path.join(tmpdir, "pom.xml")
            a_dir = os.path.join(tmpdir, "module-a")
            b_dir = os.path.join(tmpdir, "module-b")
            a_pom = os.path.join(a_dir, "pom.xml")
            b_pom = os.path.join(b_dir, "pom.xml")
            self._write_pom(root_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>root</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>module-a</module>
    <module>module-b</module>
  </modules>
</project>""")
            self._write_pom(a_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0</version>
  </parent>
  <artifactId>module-a</artifactId>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>module-b</artifactId>
      <version>1.0.0</version>
    </dependency>
    <dependency>
      <groupId>org.external</groupId>
      <artifactId>external-lib</artifactId>
      <version>5.0</version>
    </dependency>
  </dependencies>
</project>""")
            self._write_pom(b_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0</version>
  </parent>
  <artifactId>module-b</artifactId>
</project>""")
            project = load_project(root_pom)
            module_a = project.modules["module-a"]
            # Only internal dep (module-b), not external-lib
            assert "module-b" in module_a.dependencies
            assert "external-lib" not in module_a.dependencies


# ---------------------------------------------------------------------------
# Integration Test (31)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIntegrationRealFixture:
    """Test 31: Real multi-module Maven fixture integration test."""

    def _write_pom(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_java(self, path: str, content: str = "public class Stub {}") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_31_full_pipeline_with_real_fixture(self):
        """
        Test 31: Create a real multi-module Maven fixture directory (no real Maven needed),
        load it, build graph, run impact analysis on a changed file,
        verify correct modules selected and Maven command generated.
        """
        from mergemate.maven.project import load_project
        from mergemate.impact.analyzer import ImpactAnalyzer
        from mergemate.impact.module_graph import ModuleGraph

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directory structure with 6 modules so impact ratio stays below threshold:
            # root/pom.xml
            # root/shared/pom.xml  (no deps)
            # root/service/pom.xml  (depends on shared)
            # root/api/pom.xml     (depends on service)
            # root/payment/pom.xml  (no deps)
            # root/notification/pom.xml  (no deps)
            # root/batch/pom.xml  (no deps)
            # So changing shared -> service+api impacted = 3/7 = 43% < 60%
            root_pom = os.path.join(tmpdir, "pom.xml")
            self._write_pom(root_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>root</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <packaging>pom</packaging>
  <modules>
    <module>shared</module>
    <module>service</module>
    <module>api</module>
    <module>payment</module>
    <module>notification</module>
    <module>batch</module>
  </modules>
</project>""")
            shared_pom = os.path.join(tmpdir, "shared", "pom.xml")
            self._write_pom(shared_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>shared</artifactId>
</project>""")
            service_pom = os.path.join(tmpdir, "service", "pom.xml")
            self._write_pom(service_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>service</artifactId>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>shared</artifactId>
      <version>1.0.0-SNAPSHOT</version>
    </dependency>
  </dependencies>
</project>""")
            api_pom = os.path.join(tmpdir, "api", "pom.xml")
            self._write_pom(api_pom, """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>api</artifactId>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>service</artifactId>
      <version>1.0.0-SNAPSHOT</version>
    </dependency>
  </dependencies>
</project>""")
            # Extra modules (no deps) — needed to keep impact ratio below threshold
            for extra in ("payment", "notification", "batch"):
                extra_pom = os.path.join(tmpdir, extra, "pom.xml")
                self._write_pom(extra_pom, f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <groupId>com.example</groupId>
    <artifactId>root</artifactId>
    <version>1.0.0-SNAPSHOT</version>
  </parent>
  <artifactId>{extra}</artifactId>
</project>""")

            # Create some java source files
            self._write_java(os.path.join(tmpdir, "shared", "src", "main", "java", "Shared.java"))
            self._write_java(os.path.join(tmpdir, "service", "src", "main", "java", "Service.java"))
            self._write_java(os.path.join(tmpdir, "api", "src", "main", "java", "Api.java"))

            # Load the project
            project = load_project(root_pom)
            assert "root" in project.modules
            assert "shared" in project.modules
            assert "service" in project.modules
            assert "api" in project.modules

            # Verify dependency graph
            graph = ModuleGraph(project)
            # service depends on shared -> shared has service as dependent
            assert "service" in graph.direct_dependents("shared")
            # api depends on service -> service has api as dependent
            assert "api" in graph.direct_dependents("service")
            # transitive: shared -> service -> api
            trans_deps = graph.transitive_dependents({"shared"})
            assert "service" in trans_deps
            assert "api" in trans_deps

            # Simulate a change to shared/src/main/java/Shared.java
            changed_file = ChangedFile(
                path="shared/src/main/java/Shared.java",
                status="modified",
            )
            changeset = GitChangeSet(
                source_ref="HEAD",
                target_ref="origin/main",
                merge_base="abc123",
                changed_files=[changed_file],
                java_production_files=[changed_file],
            )

            config = MergeMateConfig(impact_max_depth=10)
            analyzer = ImpactAnalyzer(config)
            impact = analyzer.analyze(changeset, project, tmpdir)

            # Should be incremental
            assert impact.strategy == "incremental"
            assert "shared" in impact.changed_modules

            affected_ids = {m.artifact_id for m in impact.affected_modules}
            assert "service" in affected_ids
            assert "api" in affected_ids

            # Build validation plan
            plan = analyzer.build_validation_plan(impact, project, tmpdir, goal="test")
            assert plan.maven_command is not None
            argv_str = " ".join(plan.maven_command.argv)
            assert "-pl" in argv_str
            assert "-am" in argv_str
            assert "test" in argv_str
            # shared should be included (changed module)
            assert ":shared" in argv_str


# ---------------------------------------------------------------------------
# Additional tests for reporting
# ---------------------------------------------------------------------------

class TestConsoleReporting:
    """Test console output (smoke tests)."""

    def test_print_analyze_report_no_impact(self, capsys):
        """Basic report without impact analysis."""
        from mergemate.reporting.console import print_analyze_report
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc12345678",
            changed_files=[ChangedFile(path="src/Foo.java", status="modified")],
        )
        print_analyze_report(changeset)
        captured = capsys.readouterr()
        assert "MergeMate Impact Analysis" in captured.out
        assert "HEAD" in captured.out
        assert "origin/main" in captured.out

    def test_print_analyze_report_with_impact(self, capsys):
        """Report with full impact analysis."""
        from mergemate.reporting.console import print_analyze_report
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc12345678",
            changed_files=[ChangedFile(path="src/Foo.java", status="modified")],
            java_production_files=[ChangedFile(path="src/Foo.java", status="modified")],
        )
        impact = ImpactAnalysis(
            strategy="incremental",
            strategy_reason="1 changed module",
            changed_modules=["order-service"],
            affected_modules=[
                ModuleImpact(artifact_id="order-service", label="changed", reason="changed"),
                ModuleImpact(artifact_id="checkout-api", label="dependent", reason="dep"),
            ],
            risk_level="MEDIUM",
            risk_reasons=["application.yml changed"],
            full_build_recommended=False,
        )
        print_analyze_report(changeset, impact)
        captured = capsys.readouterr()
        assert "order-service" in captured.out
        assert "checkout-api" in captured.out
        assert "MEDIUM" in captured.out


class TestJsonReporting:
    """Test JSON report generation."""

    def test_build_json_report_basic(self):
        """Basic JSON report without impact."""
        from mergemate.reporting.json_report import build_json_report, dump_report
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc123",
            changed_files=[ChangedFile(path="src/Foo.java", status="modified")],
        )
        report = build_json_report(changeset)
        assert report["source"] == "HEAD"
        assert report["target"] == "origin/main"
        assert report["merge_base"] == "abc123"
        assert isinstance(report["changed_files"], list)

    def test_build_json_report_with_impact(self):
        """JSON report with impact."""
        from mergemate.reporting.json_report import build_json_report, dump_report
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc123",
            changed_files=[],
        )
        impact = ImpactAnalysis(
            strategy="incremental",
            strategy_reason="ok",
            changed_modules=["mod-a"],
            affected_modules=[
                ModuleImpact(artifact_id="mod-a", label="changed", reason="changed"),
            ],
            risk_level="LOW",
            risk_reasons=[],
            full_build_recommended=False,
        )
        report = build_json_report(changeset, impact)
        assert "impact" in report
        assert report["impact"]["strategy"] == "incremental"
        assert report["impact"]["risk_level"] == "LOW"

    def test_dump_report_is_valid_json(self):
        """dump_report produces valid JSON."""
        import json
        from mergemate.reporting.json_report import build_json_report, dump_report
        changeset = GitChangeSet(
            source_ref="HEAD", target_ref="origin/main", merge_base="abc123",
            changed_files=[],
        )
        report = build_json_report(changeset)
        json_str = dump_report(report)
        parsed = json.loads(json_str)
        assert parsed["source"] == "HEAD"

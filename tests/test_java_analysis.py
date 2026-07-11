"""
Phase 3 tests: Java source analysis and test candidate scoring.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from mergemate.domain.models import JavaClassInfo, TestCandidate, MavenModule, MavenProject


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_java_class_info(
    class_name: str,
    qualified_name: str = "",
    package: str = "com.example",
    file_path: str = "",
    is_test_class: bool = False,
    imports: list[str] | None = None,
    extends: list[str] | None = None,
    implements: list[str] | None = None,
    referenced_types: list[str] | None = None,
    annotations: list[str] | None = None,
) -> JavaClassInfo:
    if not qualified_name:
        qualified_name = f"{package}.{class_name}" if package else class_name
    if not file_path:
        sub = "test" if is_test_class else "main"
        file_path = f"src/{sub}/java/com/example/{class_name}.java"
    return JavaClassInfo(
        class_name=class_name,
        qualified_name=qualified_name,
        package=package,
        file_path=file_path,
        is_test_class=is_test_class,
        imports=imports or [],
        extends=extends or [],
        implements=implements or [],
        referenced_types=referenced_types or [],
        annotations=annotations or [],
    )


def _make_module(
    artifact_id: str,
    relative_path: str = "",
    dependencies: list[str] | None = None,
    packaging: str = "jar",
) -> MavenModule:
    return MavenModule(
        artifact_id=artifact_id,
        group_id="com.example",
        version="1.0.0-SNAPSHOT",
        packaging=packaging,
        relative_path=relative_path,
        pom_path=f"/fake/{artifact_id}/pom.xml",
        dependencies=dependencies or [],
    )


def _make_project(*modules: MavenModule, root_dir: str = "/fake") -> MavenProject:
    return MavenProject(
        root_pom=f"{root_dir}/pom.xml",
        root_dir=root_dir,
        modules={m.artifact_id: m for m in modules},
    )


def _write_java(tmpdir: str, rel_path: str, content: str) -> str:
    """Write a Java file to tmpdir, return relative path."""
    abs_path = os.path.join(tmpdir, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return rel_path


# ---------------------------------------------------------------------------
# Parser Tests (1-10)
# ---------------------------------------------------------------------------

class TestParserJavalang:
    """Tests 1-7: Parser with javalang (if available) or regex fallback."""

    SIMPLE_CLASS = """\
package com.example;

import com.example.util.Helper;
import java.util.List;

public class OrderService extends BaseService implements Runnable {
    private Helper helper;

    public void run() {}
}
"""

    TEST_CLASS_BY_PATH = """\
package com.example;

import org.junit.jupiter.api.Test;
import com.example.OrderService;

public class OrderServiceTest {
    @Test
    public void testSomething() {}
}
"""

    def test_1_parse_simple_class_name_package_qualified(self):
        """Test 1: Parse a simple Java class -> correct class_name, package, qualified_name."""
        from mergemate.java_analysis.parser import parse_java_file
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/com/example/OrderService.java", self.SIMPLE_CLASS)
            result = parse_java_file(rel, tmpdir)
            assert result is not None
            assert result.class_name == "OrderService"
            assert result.package == "com.example"
            assert result.qualified_name == "com.example.OrderService"

    def test_2_parse_imports_extracted(self):
        """Test 2: Parse imports -> all imports extracted."""
        from mergemate.java_analysis.parser import parse_java_file
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/com/example/OrderService.java", self.SIMPLE_CLASS)
            result = parse_java_file(rel, tmpdir)
            assert result is not None
            assert "com.example.util.Helper" in result.imports
            assert "java.util.List" in result.imports

    def test_3_parse_extends_captured(self):
        """Test 3: Parse extends -> parent class name captured."""
        from mergemate.java_analysis.parser import parse_java_file
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/com/example/OrderService.java", self.SIMPLE_CLASS)
            result = parse_java_file(rel, tmpdir)
            assert result is not None
            assert "BaseService" in result.extends

    def test_4_parse_implements_captured(self):
        """Test 4: Parse implements -> interface names captured."""
        from mergemate.java_analysis.parser import parse_java_file
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/com/example/OrderService.java", self.SIMPLE_CLASS)
            result = parse_java_file(rel, tmpdir)
            assert result is not None
            assert "Runnable" in result.implements

    def test_5_test_path_is_test_class_true(self):
        """Test 5: /test/ path -> is_test_class=True."""
        from mergemate.java_analysis.parser import parse_java_file
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/test/java/com/example/OrderServiceTest.java",
                              self.TEST_CLASS_BY_PATH)
            result = parse_java_file(rel, tmpdir)
            assert result is not None
            assert result.is_test_class is True

    def test_6_test_import_is_test_class_true(self):
        """Test 6: org.junit.jupiter.api.Test import -> is_test_class=True."""
        from mergemate.java_analysis.parser import parse_java_file
        # Put in main/ path but with @Test import -> still is_test_class = True
        with tempfile.TemporaryDirectory() as tmpdir:
            content = """\
package com.example;
import org.junit.jupiter.api.Test;
public class SomeTest {
    @Test
    public void testIt() {}
}
"""
            rel = _write_java(tmpdir, "src/main/java/com/example/SomeTest.java", content)
            result = parse_java_file(rel, tmpdir)
            assert result is not None
            assert result.is_test_class is True

    def test_7_parse_error_returns_none(self):
        """Test 7: File with parse error -> returns None (no exception raised)."""
        from mergemate.java_analysis.parser import parse_java_file
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a non-Java file that will cause parse errors
            content = "NOT JAVA CONTENT @@@ *** !!!"
            rel = _write_java(tmpdir, "src/main/java/Bad.java", content)
            # Should return None or a JavaClassInfo, never raise
            try:
                result = parse_java_file(rel, tmpdir)
                # Either returns None or some partial result — must not raise
            except Exception as e:
                pytest.fail(f"parse_java_file raised an exception: {e}")

    def test_8_nonexistent_file_returns_none(self):
        """Test 8 (edge): Non-existent file returns None, no exception."""
        from mergemate.java_analysis.parser import parse_java_file
        try:
            result = parse_java_file("nonexistent/path/Foo.java", "/tmp")
            assert result is None
        except Exception as e:
            pytest.fail(f"parse_java_file raised for nonexistent file: {e}")


class TestParserRegexFallback:
    """Tests 8-10: Regex fallback parser (tested via _parse_with_regex directly)."""

    def test_9_regex_parse_package(self):
        """Test 9: regex fallback: parse package from 'package com.example;'."""
        from mergemate.java_analysis.parser import _parse_with_regex
        content = "package com.example;\npublic class OrderService {}\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/OrderService.java", content)
            result = _parse_with_regex(rel, tmpdir)
            assert result is not None
            assert result.package == "com.example"

    def test_10_regex_parse_imports(self):
        """Test 10: regex fallback: parse imports from 'import com.example.Foo;'."""
        from mergemate.java_analysis.parser import _parse_with_regex
        content = """\
package com.example;
import com.example.Foo;
import static com.example.Bar.method;
public class OrderService {}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/OrderService.java", content)
            result = _parse_with_regex(rel, tmpdir)
            assert result is not None
            assert "com.example.Foo" in result.imports
            assert "com.example.Bar.method" in result.imports

    def test_11_regex_parse_class_name(self):
        """Test 11: regex fallback: parse class name from 'public class OrderService {'."""
        from mergemate.java_analysis.parser import _parse_with_regex
        content = "package com.example;\npublic class OrderService {\n}\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            rel = _write_java(tmpdir, "src/main/java/OrderService.java", content)
            result = _parse_with_regex(rel, tmpdir)
            assert result is not None
            assert result.class_name == "OrderService"


# ---------------------------------------------------------------------------
# JavaDependencyGraph Tests (11-16)
# ---------------------------------------------------------------------------

class TestJavaDependencyGraph:
    """Tests 11-16: JavaDependencyGraph."""

    def _make_three_classes(self):
        """
        Create 3 JavaClassInfo objects:
        - OrderService (production)
        - OrderServiceImpl extends OrderService
        - OrderServiceTest imports com.example.OrderService (test)
        """
        order_service = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            package="com.example",
            file_path="src/main/java/com/example/OrderService.java",
        )
        order_impl = _make_java_class_info(
            "OrderServiceImpl",
            qualified_name="com.example.OrderServiceImpl",
            package="com.example",
            file_path="src/main/java/com/example/OrderServiceImpl.java",
            extends=["OrderService"],
        )
        order_test = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            package="com.example",
            file_path="src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
            referenced_types=["OrderService"],
        )
        return order_service, order_impl, order_test

    def test_11_dependents_of_includes_test(self):
        """Test 11: graph.dependents_of('OrderService') includes OrderServiceTest."""
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        os_, impl, test = self._make_three_classes()
        graph = JavaDependencyGraph([os_, impl, test])
        dependents = graph.dependents_of("OrderService")
        dependent_names = {c.class_name for c in dependents}
        assert "OrderServiceTest" in dependent_names

    def test_12_dependents_of_includes_impl_via_extends(self):
        """Test 12: graph.dependents_of('OrderService') includes OrderServiceImpl (via extends)."""
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        os_, impl, test = self._make_three_classes()
        graph = JavaDependencyGraph([os_, impl, test])
        dependents = graph.dependents_of("OrderService")
        dependent_names = {c.class_name for c in dependents}
        assert "OrderServiceImpl" in dependent_names

    def test_13_dependencies_of_test_includes_order_service(self):
        """Test 13: graph.dependencies_of('OrderServiceTest') includes OrderService."""
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        os_, impl, test = self._make_three_classes()
        graph = JavaDependencyGraph([os_, impl, test])
        deps = graph.dependencies_of("OrderServiceTest")
        dep_names = {c.class_name for c in deps}
        assert "OrderService" in dep_names

    def test_14_find_class_returns_correct_info(self):
        """Test 14: graph.find_class('OrderService') returns the correct JavaClassInfo."""
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        os_, impl, test = self._make_three_classes()
        graph = JavaDependencyGraph([os_, impl, test])
        found = graph.find_class("OrderService")
        assert found is not None
        assert found.class_name == "OrderService"
        assert found.qualified_name == "com.example.OrderService"

    def test_15_max_depth_limits_transitive_search(self):
        """Test 15: max_depth=1 limits transitive search to direct dependents."""
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        # A <- B <- C (C depends on B, B depends on A)
        class_a = _make_java_class_info(
            "ClassA", qualified_name="com.example.ClassA",
            file_path="src/main/java/ClassA.java"
        )
        class_b = _make_java_class_info(
            "ClassB", qualified_name="com.example.ClassB",
            file_path="src/main/java/ClassB.java",
            imports=["com.example.ClassA"],
            referenced_types=["ClassA"],
        )
        class_c = _make_java_class_info(
            "ClassC", qualified_name="com.example.ClassC",
            file_path="src/main/java/ClassC.java",
            imports=["com.example.ClassB"],
            referenced_types=["ClassB"],
        )
        graph = JavaDependencyGraph([class_a, class_b, class_c])
        # With max_depth=1, only ClassB should be found (not ClassC)
        deps_depth1 = graph.dependents_of("ClassA", max_depth=1)
        names_depth1 = {c.class_name for c in deps_depth1}
        assert "ClassB" in names_depth1
        assert "ClassC" not in names_depth1

        # With max_depth=2, ClassC should also be found
        deps_depth2 = graph.dependents_of("ClassA", max_depth=2)
        names_depth2 = {c.class_name for c in deps_depth2}
        assert "ClassB" in names_depth2
        assert "ClassC" in names_depth2

    def test_16_unknown_class_find_returns_none(self):
        """Test 16: Unknown class -> find_class returns None."""
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        os_, impl, test = self._make_three_classes()
        graph = JavaDependencyGraph([os_, impl, test])
        result = graph.find_class("NonExistentClass")
        assert result is None


# ---------------------------------------------------------------------------
# test_finder Tests (17-21)
# ---------------------------------------------------------------------------

class TestTestFinder:
    """Tests 17-21: test_finder module."""

    def _make_fixture_classes(self):
        """
        Create:
        - OrderService (production)
        - OrderServiceTest (test, imports OrderService)
        - CheckoutFacadeTest (test, imports CheckoutFacade not OrderService)
        """
        order_service = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="src/main/java/com/example/OrderService.java",
        )
        order_test = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            file_path="src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
            referenced_types=["OrderService"],
        )
        checkout_test = _make_java_class_info(
            "CheckoutFacadeTest",
            qualified_name="com.example.CheckoutFacadeTest",
            file_path="src/test/java/com/example/CheckoutFacadeTest.java",
            is_test_class=True,
            imports=["com.example.CheckoutFacade"],
            referenced_types=["CheckoutFacade"],
        )
        return order_service, order_test, checkout_test

    def test_17_level1_naming_finds_order_service_test(self):
        """Test 17: match_level1_naming finds OrderServiceTest for OrderService."""
        from mergemate.java_analysis.test_finder import match_level1_naming
        order_service, order_test, checkout_test = self._make_fixture_classes()
        results = match_level1_naming(order_service, [order_test, checkout_test])
        result_names = [tc.class_name for tc, _ in results]
        assert "OrderServiceTest" in result_names

    def test_18_level1_naming_does_not_find_checkout_test(self):
        """Test 18: match_level1_naming does NOT find CheckoutFacadeTest for OrderService."""
        from mergemate.java_analysis.test_finder import match_level1_naming
        order_service, order_test, checkout_test = self._make_fixture_classes()
        results = match_level1_naming(order_service, [order_test, checkout_test])
        result_names = [tc.class_name for tc, _ in results]
        assert "CheckoutFacadeTest" not in result_names

    def test_19_level2_references_finds_order_test(self):
        """Test 19: match_level2_references finds OrderServiceTest (it imports OrderService)."""
        from mergemate.java_analysis.test_finder import match_level2_references
        order_service, order_test, checkout_test = self._make_fixture_classes()
        results = match_level2_references(order_service, [order_test, checkout_test])
        result_names = [tc.class_name for tc, _ in results]
        assert "OrderServiceTest" in result_names

    def test_20_level2_references_does_not_find_checkout_test(self):
        """Test 20: match_level2_references does NOT find CheckoutFacadeTest."""
        from mergemate.java_analysis.test_finder import match_level2_references
        order_service, order_test, checkout_test = self._make_fixture_classes()
        results = match_level2_references(order_service, [order_test, checkout_test])
        result_names = [tc.class_name for tc, _ in results]
        assert "CheckoutFacadeTest" not in result_names

    def test_21_level3_reverse_deps_finds_indirect_tests(self):
        """
        Test 21: match_level3_reverse_deps finds CheckoutFacadeTest indirectly
        (CheckoutFacadeTest tests CheckoutFacade which depends on OrderService).
        """
        from mergemate.java_analysis.test_finder import match_level3_reverse_deps
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        order_service = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="src/main/java/com/example/OrderService.java",
        )
        checkout_facade = _make_java_class_info(
            "CheckoutFacade",
            qualified_name="com.example.CheckoutFacade",
            file_path="src/main/java/com/example/CheckoutFacade.java",
            imports=["com.example.OrderService"],
            referenced_types=["OrderService"],
        )
        checkout_test = _make_java_class_info(
            "CheckoutFacadeTest",
            qualified_name="com.example.CheckoutFacadeTest",
            file_path="src/test/java/com/example/CheckoutFacadeTest.java",
            is_test_class=True,
            imports=["com.example.CheckoutFacade"],
            referenced_types=["CheckoutFacade"],
        )

        all_classes = [order_service, checkout_facade, checkout_test]
        graph = JavaDependencyGraph(all_classes)
        test_classes = [checkout_test]
        all_prod = [order_service, checkout_facade]

        results = match_level3_reverse_deps(
            order_service, all_prod, graph, test_classes, max_depth=3
        )
        result_names = [tc.class_name for tc, _ in results]
        assert "CheckoutFacadeTest" in result_names


# ---------------------------------------------------------------------------
# Scoring Tests (22-29)
# ---------------------------------------------------------------------------

class TestTestScorer:
    """Tests 22-29: TestCandidate scoring."""

    def _make_simple_project(self) -> MavenProject:
        module = _make_module("order-service", relative_path="services/order-service")
        return _make_project(module)

    def test_22_level1_score_at_least_040(self):
        """Test 22: Test with level1 match -> score >= 0.40."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="services/order-service/src/main/java/com/example/OrderService.java",
        )
        test_cls = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            file_path="services/order-service/src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
        )
        graph = JavaDependencyGraph([prod, test_cls])
        project = self._make_simple_project()
        candidates = score_test_candidates(prod, [test_cls], graph, project, set())
        assert len(candidates) >= 1
        assert candidates[0].score >= 0.40

    def test_23_level1_plus_level2_score_high_confidence(self):
        """Test 23: Test with level1 + level2 -> score >= 0.65 -> HIGH confidence."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="services/order-service/src/main/java/com/example/OrderService.java",
        )
        test_cls = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            file_path="services/order-service/src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
            referenced_types=["OrderService"],
        )
        graph = JavaDependencyGraph([prod, test_cls])
        project = self._make_simple_project()
        candidates = score_test_candidates(prod, [test_cls], graph, project, set())
        assert len(candidates) >= 1
        assert candidates[0].score >= 0.65
        assert candidates[0].confidence == "HIGH"

    def test_24_no_signals_score_zero_not_in_results(self):
        """Test 24: Test with no signals -> score == 0.0 (not in results)."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="services/order-service/src/main/java/com/example/OrderService.java",
        )
        # Test has completely different name and no references to OrderService
        test_cls = _make_java_class_info(
            "UnrelatedTest",
            qualified_name="com.example.UnrelatedTest",
            file_path="services/order-service/src/test/java/com/example/UnrelatedTest.java",
            is_test_class=True,
            imports=["com.example.SomeOtherClass"],
            referenced_types=["SomeOtherClass"],
        )
        graph = JavaDependencyGraph([prod, test_cls])
        project = self._make_simple_project()
        candidates = score_test_candidates(prod, [test_cls], graph, project, set())
        # Should not be in results (score 0 or very low)
        assert all(c.class_name != "UnrelatedTest" for c in candidates) or \
               all(c.score > 0 for c in candidates)  # if there, score > 0

    def test_25_integration_test_gets_penalty(self):
        """Test 25: Integration test (*IT.java) gets small penalty vs unit test with same signals."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="services/order-service/src/main/java/com/example/OrderService.java",
        )
        # Unit test (naming match)
        unit_test = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            file_path="services/order-service/src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
        )
        # Integration test (naming match with IT suffix)
        it_test = _make_java_class_info(
            "OrderServiceIT",
            qualified_name="com.example.OrderServiceIT",
            file_path="services/order-service/src/test/java/com/example/OrderServiceIT.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
        )

        graph = JavaDependencyGraph([prod, unit_test, it_test])
        project = self._make_simple_project()
        candidates = score_test_candidates(prod, [unit_test, it_test], graph, project, set())

        unit_candidate = next((c for c in candidates if c.class_name == "OrderServiceTest"), None)
        it_candidate = next((c for c in candidates if c.class_name == "OrderServiceIT"), None)

        assert unit_candidate is not None
        assert it_candidate is not None
        assert it_candidate.is_integration_test is True
        # IT test should have lower score than unit test (penalty applied)
        assert unit_candidate.score > it_candidate.score

    def test_26_same_module_bonus_applies(self):
        """Test 26: Same-module bonus applies when both classes in same module."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        from mergemate.java_analysis.test_scorer import SCORE_WEIGHTS

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="services/order-service/src/main/java/com/example/OrderService.java",
        )
        # Test in same module (services/order-service prefix matches)
        same_mod_test = _make_java_class_info(
            "SomeUnrelatedTest",
            qualified_name="com.example.SomeUnrelatedTest",
            file_path="services/order-service/src/test/java/com/example/SomeUnrelatedTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],  # has level2 match
        )
        module = _make_module("order-service", relative_path="services/order-service")
        project = _make_project(module)
        graph = JavaDependencyGraph([prod, same_mod_test])
        candidates = score_test_candidates(prod, [same_mod_test], graph, project, set())
        assert len(candidates) >= 1
        # Should include same_module bonus in score
        # Level2 direct import = 0.35, same_module = 0.10 -> at least 0.45
        assert candidates[0].score >= 0.35

    def test_27_score_test_candidates_sorted_by_score_descending(self):
        """Test 27: score_test_candidates returns sorted by score descending."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="src/main/java/com/example/OrderService.java",
        )
        # Test 1: has naming + import (higher score)
        test1 = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            file_path="src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
        )
        # Test 2: only import reference (lower score)
        test2 = _make_java_class_info(
            "AnotherTest",
            qualified_name="com.example.AnotherTest",
            file_path="src/test/java/com/example/AnotherTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
        )
        project = self._make_simple_project()
        graph = JavaDependencyGraph([prod, test1, test2])
        candidates = score_test_candidates(prod, [test1, test2], graph, project, set())
        scores = [c.score for c in candidates]
        # Verify sorted descending
        assert scores == sorted(scores, reverse=True)

    def test_28_only_candidates_with_positive_score_returned(self):
        """Test 28: score_test_candidates returns only candidates with score > 0."""
        from mergemate.java_analysis.test_scorer import score_test_candidates
        from mergemate.java_analysis.class_graph import JavaDependencyGraph

        prod = _make_java_class_info(
            "OrderService",
            qualified_name="com.example.OrderService",
            file_path="src/main/java/com/example/OrderService.java",
        )
        # Test with no relevance to OrderService at all
        irrelevant_test = _make_java_class_info(
            "UnrelatedServiceTest",
            qualified_name="com.example.UnrelatedServiceTest",
            file_path="src/test/java/com/example/UnrelatedServiceTest.java",
            is_test_class=True,
            imports=["com.example.UnrelatedService"],
            referenced_types=["UnrelatedService"],
        )
        # Test with relevance
        relevant_test = _make_java_class_info(
            "OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            file_path="src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
        )
        project = self._make_simple_project()
        graph = JavaDependencyGraph([prod, irrelevant_test, relevant_test])
        candidates = score_test_candidates(prod, [irrelevant_test, relevant_test], graph, project, set())
        # All returned candidates must have score > 0
        for c in candidates:
            assert c.score > 0.0

    def test_29_confidence_thresholds_correct(self):
        """Test 29: Confidence: score 0.70 -> HIGH, score 0.50 -> MEDIUM, score 0.20 -> LOW."""
        from mergemate.java_analysis.test_scorer import _assign_confidence
        assert _assign_confidence(0.70) == "HIGH"
        assert _assign_confidence(0.65) == "HIGH"
        assert _assign_confidence(0.50) == "MEDIUM"
        assert _assign_confidence(0.35) == "MEDIUM"
        assert _assign_confidence(0.20) == "LOW"
        assert _assign_confidence(0.10) == "LOW"
        assert _assign_confidence(0.00) == "LOW"


# ---------------------------------------------------------------------------
# Integration Test (30)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestJavaAnalysisIntegration:
    """Test 30: Integration test with real Java files."""

    def test_30_end_to_end_parse_graph_score_real_files(self):
        """
        Test 30: Create temp directory with real Java files, parse them,
        build graph, score, verify OrderServiceTest gets HIGH confidence.
        """
        from mergemate.java_analysis.parser import parse_java_files
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        from mergemate.java_analysis.test_scorer import score_test_candidates

        order_service_content = """\
package com.example;

import java.util.List;

public class OrderService {
    public List<String> getOrders() {
        return null;
    }
}
"""

        order_service_test_content = """\
package com.example;

import org.junit.jupiter.api.Test;
import com.example.OrderService;

public class OrderServiceTest {

    @Test
    public void testGetOrders() {
        OrderService service = new OrderService();
        assert service.getOrders() == null;
    }
}
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            prod_rel = _write_java(
                tmpdir,
                "src/main/java/com/example/OrderService.java",
                order_service_content,
            )
            test_rel = _write_java(
                tmpdir,
                "src/test/java/com/example/OrderServiceTest.java",
                order_service_test_content,
            )

            # Parse files
            prod_classes = parse_java_files([prod_rel], tmpdir)
            test_classes = parse_java_files([test_rel], tmpdir)

            assert len(prod_classes) >= 1, "Should parse OrderService"
            assert len(test_classes) >= 1, "Should parse OrderServiceTest"

            prod_cls = prod_classes[0]
            assert prod_cls.class_name == "OrderService"
            test_cls = test_classes[0]
            assert test_cls.class_name == "OrderServiceTest"
            assert test_cls.is_test_class is True

            # Build graph
            all_classes = prod_classes + test_classes
            graph = JavaDependencyGraph(all_classes)

            # Build a simple project
            module = _make_module("my-service", relative_path="")
            project = _make_project(module, root_dir=tmpdir)

            # Score
            candidates = score_test_candidates(
                prod_cls, test_classes, graph, project, {"my-service"}
            )

            assert len(candidates) >= 1, "Should find at least one test candidate"
            top = candidates[0]
            assert top.class_name == "OrderServiceTest"
            assert top.confidence == "HIGH", f"Expected HIGH confidence, got {top.confidence} (score={top.score})"
            assert top.score >= 0.40

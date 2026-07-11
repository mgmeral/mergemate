"""
Phase 4 End-to-End Integration Tests.

These tests create real temporary git repositories with real Maven project structures
to validate the full analysis pipeline end-to-end.

Tests do NOT require Maven to be installed — only validates:
- Git diff + POM parsing + module graph + impact analysis
"""
from __future__ import annotations

import os
import subprocess
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: str) -> None:
    """Run a git command and check=True."""
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


def _write_file(path: str, content: str) -> None:
    """Create parent dirs and write file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))


def _create_maven_fixture(base: str) -> None:
    """
    Create a valid Maven multi-module project in base/:

    sample-parent/
      pom.xml               (root aggregator)
      shared-domain/
        pom.xml             (artifactId=shared-domain)
        src/main/java/com/example/domain/OrderId.java
      order-service/
        pom.xml             (artifactId=order-service, deps=[shared-domain])
        src/main/java/com/example/order/OrderService.java
        src/test/java/com/example/order/OrderServiceTest.java
      checkout-api/
        pom.xml             (artifactId=checkout-api, deps=[order-service, shared-domain])
        src/main/java/com/example/checkout/CheckoutFacade.java
        src/test/java/com/example/checkout/CheckoutFacadeTest.java
    """
    root = base

    # Root pom.xml
    _write_file(os.path.join(root, "pom.xml"), """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
            <modelVersion>4.0.0</modelVersion>
            <groupId>com.example</groupId>
            <artifactId>sample-parent</artifactId>
            <version>1.0-SNAPSHOT</version>
            <packaging>pom</packaging>
            <modules>
                <module>shared-domain</module>
                <module>order-service</module>
                <module>checkout-api</module>
            </modules>
        </project>
    """)

    # shared-domain/pom.xml
    _write_file(os.path.join(root, "shared-domain", "pom.xml"), """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
            <modelVersion>4.0.0</modelVersion>
            <parent>
                <groupId>com.example</groupId>
                <artifactId>sample-parent</artifactId>
                <version>1.0-SNAPSHOT</version>
            </parent>
            <artifactId>shared-domain</artifactId>
            <packaging>jar</packaging>
        </project>
    """)

    # shared-domain source
    _write_file(
        os.path.join(root, "shared-domain", "src", "main", "java", "com", "example", "domain", "OrderId.java"),
        """\
        package com.example.domain;

        public class OrderId {
            private final String value;
            public OrderId(String value) { this.value = value; }
            public String getValue() { return value; }
        }
        """
    )

    # order-service/pom.xml
    _write_file(os.path.join(root, "order-service", "pom.xml"), """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
            <modelVersion>4.0.0</modelVersion>
            <parent>
                <groupId>com.example</groupId>
                <artifactId>sample-parent</artifactId>
                <version>1.0-SNAPSHOT</version>
            </parent>
            <artifactId>order-service</artifactId>
            <packaging>jar</packaging>
            <dependencies>
                <dependency>
                    <groupId>com.example</groupId>
                    <artifactId>shared-domain</artifactId>
                    <version>1.0-SNAPSHOT</version>
                </dependency>
            </dependencies>
        </project>
    """)

    # order-service source
    _write_file(
        os.path.join(root, "order-service", "src", "main", "java", "com", "example", "order", "OrderService.java"),
        """\
        package com.example.order;

        import com.example.domain.OrderId;

        public class OrderService {
            public OrderId createOrder(String id) {
                return new OrderId(id);
            }
        }
        """
    )

    # order-service test
    _write_file(
        os.path.join(root, "order-service", "src", "test", "java", "com", "example", "order", "OrderServiceTest.java"),
        """\
        package com.example.order;

        import com.example.order.OrderService;
        import org.junit.Test;

        public class OrderServiceTest {
            @Test
            public void testCreateOrder() {
                OrderService svc = new OrderService();
            }
        }
        """
    )

    # checkout-api/pom.xml
    _write_file(os.path.join(root, "checkout-api", "pom.xml"), """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
            <modelVersion>4.0.0</modelVersion>
            <parent>
                <groupId>com.example</groupId>
                <artifactId>sample-parent</artifactId>
                <version>1.0-SNAPSHOT</version>
            </parent>
            <artifactId>checkout-api</artifactId>
            <packaging>jar</packaging>
            <dependencies>
                <dependency>
                    <groupId>com.example</groupId>
                    <artifactId>order-service</artifactId>
                    <version>1.0-SNAPSHOT</version>
                </dependency>
                <dependency>
                    <groupId>com.example</groupId>
                    <artifactId>shared-domain</artifactId>
                    <version>1.0-SNAPSHOT</version>
                </dependency>
            </dependencies>
        </project>
    """)

    # checkout-api source
    _write_file(
        os.path.join(root, "checkout-api", "src", "main", "java", "com", "example", "checkout", "CheckoutFacade.java"),
        """\
        package com.example.checkout;

        import com.example.order.OrderService;

        public class CheckoutFacade {
            private final OrderService orderService;
            public CheckoutFacade(OrderService orderService) {
                this.orderService = orderService;
            }
        }
        """
    )

    # checkout-api test
    _write_file(
        os.path.join(root, "checkout-api", "src", "test", "java", "com", "example", "checkout", "CheckoutFacadeTest.java"),
        """\
        package com.example.checkout;

        import com.example.checkout.CheckoutFacade;
        import org.junit.Test;

        public class CheckoutFacadeTest {
            @Test
            public void testCheckout() {
                // stub test
            }
        }
        """
    )


# ---------------------------------------------------------------------------
# E2E test 1: Full impact analysis pipeline
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_full_e2e_impact_analysis(tmp_path):
    """
    End-to-end: create real git repo + Maven project, make a change, run analysis.
    Validates: changeset, module impact, dependency propagation.
    Does NOT call Maven.
    """
    root = str(tmp_path)

    # 1. Create Maven fixture
    _create_maven_fixture(root)

    # 2. Init git repo and initial commit on main branch
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)
    _git(["add", "."], root)
    _git(["commit", "-m", "initial commit"], root)

    # 3. Create feature branch and modify OrderService.java
    _git(["checkout", "-b", "feature/change-order"], root)

    order_service_path = os.path.join(
        root, "order-service", "src", "main", "java",
        "com", "example", "order", "OrderService.java"
    )
    with open(order_service_path, "a") as f:
        f.write("\n// Added a comment to trigger change\n")

    # 4. Commit the change
    _git(["add", order_service_path], root)
    _git(["commit", "-m", "modify OrderService"], root)

    # 5. Run analysis pipeline directly (not CLI subprocess)
    from mergemate.git.diff import build_changeset
    from mergemate.maven.project import load_project
    from mergemate.impact.analyzer import ImpactAnalyzer

    root_pom = os.path.join(root, "pom.xml")

    changeset = build_changeset(root, "HEAD", "main")
    project = load_project(root_pom)
    impact = ImpactAnalyzer().analyze(changeset, project, root)

    # 6. Assertions on changeset
    assert changeset.merge_base != "", "merge_base should not be empty"
    assert any(
        f.path.endswith("OrderService.java")
        for f in changeset.java_production_files
    ), "OrderService.java should be in java_production_files"

    # 7. Assertions on impact
    assert "order-service" in impact.changed_modules, \
        f"order-service should be in changed_modules, got: {impact.changed_modules}"

    # checkout-api depends on order-service -> should be a dependent
    affected_ids = {m.artifact_id for m in impact.affected_modules}
    assert "checkout-api" in affected_ids, \
        f"checkout-api should be in affected_modules, got: {affected_ids}"

    # Verify checkout-api is labeled as "dependent"
    checkout_impact = next(
        (m for m in impact.affected_modules if m.artifact_id == "checkout-api"),
        None
    )
    assert checkout_impact is not None, "checkout-api should be in affected_modules"
    assert checkout_impact.label == "dependent", \
        f"checkout-api should be 'dependent', got: {checkout_impact.label}"

    # shared-domain is upstream (a dependency), not directly changed
    # It may appear as "dependency" label (added by -am) or not at all in incremental
    # But it should NOT be labeled "dependent" since nothing changed in it
    shared_impact = next(
        (m for m in impact.affected_modules if m.artifact_id == "shared-domain"),
        None
    )
    if shared_impact is not None:
        assert shared_impact.label != "dependent", \
            "shared-domain should not be 'dependent' — nothing in it changed"

    # 8. Maven command / strategy check
    if impact.strategy == "incremental":
        pl_modules = [
            m.artifact_id for m in impact.affected_modules
            if m.label in ("changed", "dependent")
        ]
        assert "order-service" in pl_modules
        # In incremental mode, checkout-api should be in the pl list (it's dependent)
        assert "checkout-api" in pl_modules


# ---------------------------------------------------------------------------
# E2E test 2: JDK detection from real fixture POM
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_jdk_detection_from_fixture(tmp_path):
    """
    Create a pom.xml with maven.compiler.release=17 and verify JDK detection.
    """
    pom_path = os.path.join(str(tmp_path), "pom.xml")
    _write_file(pom_path, """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
            <modelVersion>4.0.0</modelVersion>
            <groupId>com.example</groupId>
            <artifactId>test-project</artifactId>
            <version>1.0-SNAPSHOT</version>
            <properties>
                <maven.compiler.release>17</maven.compiler.release>
            </properties>
        </project>
    """)

    from mergemate.maven.jdk import detect_jdk_requirement

    req = detect_jdk_requirement(pom_path)

    assert req.required_version == "17", f"Expected version 17, got: {req.required_version}"
    assert req.detection_method == "property"
    assert "maven.compiler.release" in (req.detected_from or ""), \
        f"Expected 'maven.compiler.release' in detected_from, got: {req.detected_from}"


# ---------------------------------------------------------------------------
# E2E test 3: Worktree cleanup on exception
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_worktree_cleanup_on_exception(tmp_path):
    """
    Create a real git repo, create a TemporaryWorktree, simulate an exception
    inside the context, and verify the worktree directory is cleaned up.
    """
    root = str(tmp_path)

    # Create a simple git repo
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)

    # Write a file so we can commit
    readme = os.path.join(root, "README.txt")
    with open(readme, "w") as f:
        f.write("test repo\n")

    _git(["add", "."], root)
    _git(["commit", "-m", "initial"], root)

    from mergemate.git.worktree import TemporaryWorktree

    worktree_path = None
    exception_raised = False

    try:
        wt = TemporaryWorktree(root, "HEAD")
        worktree_path = wt.__enter__()

        # Verify worktree path exists inside the context
        assert os.path.isdir(worktree_path), \
            f"Worktree directory should exist inside context: {worktree_path}"

        # Simulate an exception in the context body
        raise RuntimeError("Simulated exception in context body")

    except RuntimeError:
        exception_raised = True
        # Clean up manually since we're not using the `with` statement
        wt.__exit__(None, None, None)

    assert exception_raised, "Expected exception to be raised"
    assert worktree_path is not None, "worktree_path should have been set"

    # After __exit__, the worktree directory should be cleaned up
    assert not os.path.isdir(worktree_path), \
        f"Worktree directory should be cleaned up after __exit__: {worktree_path}"


@pytest.mark.integration
def test_worktree_cleanup_with_context_manager(tmp_path):
    """
    Verify TemporaryWorktree cleans up via `with` statement on exception.
    """
    root = str(tmp_path)

    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "test@test.com"], root)
    _git(["config", "user.name", "Test"], root)

    readme = os.path.join(root, "README.txt")
    with open(readme, "w") as f:
        f.write("test repo\n")

    _git(["add", "."], root)
    _git(["commit", "-m", "initial"], root)

    from mergemate.git.worktree import TemporaryWorktree

    worktree_path = None
    try:
        with TemporaryWorktree(root, "HEAD") as wt_path:
            worktree_path = wt_path
            assert os.path.isdir(wt_path)
            raise ValueError("test exception")
    except ValueError:
        pass  # expected

    assert worktree_path is not None
    assert not os.path.isdir(worktree_path), \
        f"Worktree should be removed after exception: {worktree_path}"

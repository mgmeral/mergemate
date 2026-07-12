"""
tests/test_cochange.py

Tests for:
  - mergemate/git/cochange.py    (CoChangeMap, analyze_cochange)
  - test_scorer.py with cochange_map  (scoring signal integration)
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest.mock as mock
from collections import defaultdict

import pytest

_project_root = os.path.dirname(os.path.dirname(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mergemate.git.cochange import (
    CoChangeMap,
    analyze_cochange,
    _commits_touching_file,
    _files_in_commit,
    _is_java_test_file,
)
from mergemate.java_analysis.test_scorer import (
    score_test_candidates,
    SCORE_WEIGHTS,
    COCHANGE_HIGH_THRESHOLD,
    COCHANGE_MEDIUM_THRESHOLD,
)


# ---------------------------------------------------------------------------
# CoChangeMap unit tests
# ---------------------------------------------------------------------------

class TestCoChangeMap:
    def test_empty_map(self):
        m = CoChangeMap()
        assert m.is_empty()
        assert m.co_change_count("a.java", "b.java") == 0
        assert m.test_files_for("a.java") == {}

    def test_add_entry(self):
        m = CoChangeMap()
        m.co_changes["src/Foo.java"]["src/test/FooTest.java"] += 3
        assert not m.is_empty()
        assert m.co_change_count("src/Foo.java", "src/test/FooTest.java") == 3

    def test_multiple_entries(self):
        m = CoChangeMap()
        m.co_changes["prod.java"]["a_test.java"] += 5
        m.co_changes["prod.java"]["b_test.java"] += 2
        m.co_changes["prod2.java"]["a_test.java"] += 1

        assert m.co_change_count("prod.java", "a_test.java") == 5
        assert m.co_change_count("prod.java", "b_test.java") == 2
        assert m.co_change_count("prod2.java", "a_test.java") == 1
        assert m.co_change_count("prod.java", "c_test.java") == 0

    def test_test_files_for(self):
        m = CoChangeMap()
        m.co_changes["p.java"]["t1.java"] += 3
        m.co_changes["p.java"]["t2.java"] += 1
        result = m.test_files_for("p.java")
        assert result == {"t1.java": 3, "t2.java": 1}

    def test_test_files_for_unknown_prod(self):
        m = CoChangeMap()
        assert m.test_files_for("unknown.java") == {}


# ---------------------------------------------------------------------------
# _is_java_test_file
# ---------------------------------------------------------------------------

class TestIsJavaTestFile:
    def test_positive_cases(self):
        assert _is_java_test_file("src/test/java/FooTest.java")
        assert _is_java_test_file("module/src/test/java/com/example/BarIT.java")
        assert _is_java_test_file("test/java/BazTest.java")

    def test_negative_cases(self):
        assert not _is_java_test_file("src/main/java/Foo.java")
        assert not _is_java_test_file("src/test/resources/data.json")
        assert not _is_java_test_file("src/test/java/README.md")
        assert not _is_java_test_file("")


# ---------------------------------------------------------------------------
# analyze_cochange with mocked subprocess
# ---------------------------------------------------------------------------

class TestAnalyzeCochangeMocked:
    def test_empty_prod_files_returns_empty(self, tmp_path):
        result = analyze_cochange(str(tmp_path), [], max_commits=10, days=30)
        assert result.is_empty()

    def test_nonexistent_dir_returns_empty(self):
        result = analyze_cochange("/nonexistent/path", ["Foo.java"], max_commits=10, days=30)
        assert result.is_empty()

    def test_git_failure_returns_empty(self, tmp_path):
        with mock.patch("mergemate.git.cochange._commits_touching_file", return_value=[]):
            result = analyze_cochange(str(tmp_path), ["src/Foo.java"])
        assert result.is_empty()

    def test_finds_cochange(self, tmp_path):
        commits = ["abc123", "def456"]
        files_per_commit = {
            "abc123": [
                "src/main/java/Foo.java",
                "src/test/java/FooTest.java",
                "src/test/java/BarTest.java",
            ],
            "def456": [
                "src/main/java/Foo.java",
                "src/test/java/FooTest.java",
            ],
        }

        def mock_commits(repo_dir, file_path, max_commits, days):
            if "Foo.java" in file_path and "test" not in file_path:
                return commits
            return []

        def mock_files(repo_dir, commit_hash):
            return files_per_commit.get(commit_hash, [])

        with mock.patch("mergemate.git.cochange._commits_touching_file", side_effect=mock_commits):
            with mock.patch("mergemate.git.cochange._files_in_commit", side_effect=mock_files):
                result = analyze_cochange(str(tmp_path), ["src/main/java/Foo.java"])

        assert result.co_change_count("src/main/java/Foo.java", "src/test/java/FooTest.java") == 2
        assert result.co_change_count("src/main/java/Foo.java", "src/test/java/BarTest.java") == 1

    def test_non_test_files_not_counted(self, tmp_path):
        """Production files that co-change should not be recorded in the map."""
        commits = ["abc"]
        files = ["src/main/java/Foo.java", "src/main/java/Bar.java"]

        with mock.patch("mergemate.git.cochange._commits_touching_file", return_value=commits):
            with mock.patch("mergemate.git.cochange._files_in_commit", return_value=files):
                result = analyze_cochange(str(tmp_path), ["src/main/java/Foo.java"])

        # Bar.java is a production file, should NOT appear
        assert result.is_empty()

    def test_exception_in_pipeline_returns_empty(self, tmp_path):
        with mock.patch(
            "mergemate.git.cochange._commits_touching_file",
            side_effect=RuntimeError("git exploded")
        ):
            result = analyze_cochange(str(tmp_path), ["Foo.java"])
        assert result.is_empty()


# ---------------------------------------------------------------------------
# analyze_cochange with real git repo (integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestAnalyzeCochangeRealGit:
    def _setup_repo(self, tmp_path):
        """Create a tiny real git repo with commit history."""
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        }

        repo = tmp_path / "repo"
        repo.mkdir()

        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        def commit(msg, files: dict[str, str]):
            for path, content in files.items():
                fpath = repo / path
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content)
            subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(repo), capture_output=True, check=True, env=env
            )

        # Commit 1: co-change Foo.java + FooTest.java
        commit("initial", {
            "src/main/java/Foo.java": "class Foo {}",
            "src/test/java/FooTest.java": "class FooTest {}",
        })
        # Commit 2: co-change Foo.java + FooTest.java + ExtraTest.java
        commit("fix foo", {
            "src/main/java/Foo.java": "class Foo { void x(){} }",
            "src/test/java/FooTest.java": "class FooTest { void testX(){} }",
            "src/test/java/ExtraTest.java": "class ExtraTest {}",
        })
        # Commit 3: Bar.java alone
        commit("add bar", {
            "src/main/java/Bar.java": "class Bar {}",
        })

        return repo

    def test_cochange_counts_from_real_repo(self, tmp_path):
        repo = self._setup_repo(tmp_path)
        result = analyze_cochange(
            str(repo),
            ["src/main/java/Foo.java"],
            max_commits=10,
            days=365,
        )
        # FooTest appeared in 2 commits with Foo
        foo_test_count = result.co_change_count(
            "src/main/java/Foo.java",
            "src/test/java/FooTest.java",
        )
        assert foo_test_count == 2

        # ExtraTest appeared in 1 commit with Foo
        extra_count = result.co_change_count(
            "src/main/java/Foo.java",
            "src/test/java/ExtraTest.java",
        )
        assert extra_count == 1

    def test_unrelated_file_count_is_zero(self, tmp_path):
        repo = self._setup_repo(tmp_path)
        result = analyze_cochange(str(repo), ["src/main/java/Bar.java"], max_commits=10, days=365)
        # Bar was never committed with any test file
        assert result.is_empty()


# ---------------------------------------------------------------------------
# Test scorer integration with CoChangeMap
# ---------------------------------------------------------------------------

class TestScorerCoChangeIntegration:
    def _make_classes(self):
        from mergemate.domain.models import JavaClassInfo
        prod = JavaClassInfo(
            class_name="OrderService",
            qualified_name="com.example.OrderService",
            package="com.example",
            file_path="order-svc/src/main/java/com/example/OrderService.java",
            is_test_class=False,
            imports=[],
            extends=[],
            implements=[],
            referenced_types=[],
            annotations=[],
        )
        test1 = JavaClassInfo(
            class_name="OrderServiceTest",
            qualified_name="com.example.OrderServiceTest",
            package="com.example",
            file_path="order-svc/src/test/java/com/example/OrderServiceTest.java",
            is_test_class=True,
            imports=["com.example.OrderService"],
            extends=[],
            implements=[],
            referenced_types=["OrderService"],
            annotations=[],
        )
        test2 = JavaClassInfo(
            class_name="OtherTest",
            qualified_name="com.other.OtherTest",
            package="com.other",   # different package → no same_package signal
            file_path="other-svc/src/test/java/com/other/OtherTest.java",
            is_test_class=True,
            imports=[],
            extends=[],
            implements=[],
            referenced_types=[],
            annotations=[],
        )
        return prod, test1, test2

    def _make_project(self):
        from mergemate.domain.models import MavenProject, MavenModule
        mod = MavenModule(
            artifact_id="order-svc",
            group_id="com.example",
            version="1.0",
            packaging="jar",
            relative_path="order-svc",
            pom_path="order-svc/pom.xml",
        )
        return MavenProject(root_pom="pom.xml", root_dir=".", modules={"order-svc": mod})

    def _make_graph(self, prod, test1, test2):
        from mergemate.java_analysis.class_graph import JavaDependencyGraph
        return JavaDependencyGraph([prod, test1, test2])

    def test_no_cochange_map_uses_existing_signals_only(self):
        prod, test1, test2 = self._make_classes()
        project = self._make_project()
        graph = self._make_graph(prod, test1, test2)

        candidates = score_test_candidates(
            prod, [test1, test2], graph, project,
            affected_module_ids={"order-svc"},
            cochange_map=None,
        )
        # test1 should score, test2 should not (no signals)
        names = [c.class_name for c in candidates]
        assert "OrderServiceTest" in names
        # test2 has no signals → may or may not appear
        for c in candidates:
            assert "cochange" not in " ".join(c.reasons).lower()

    def test_cochange_high_boosts_score(self):
        prod, test1, test2 = self._make_classes()
        project = self._make_project()
        graph = self._make_graph(prod, test1, test2)

        # Give test2 (OtherTest) high co-change with OrderService
        cochange_map = CoChangeMap()
        cochange_map.co_changes[
            "order-svc/src/main/java/com/example/OrderService.java"
        ][
            "other-svc/src/test/java/com/other/OtherTest.java"
        ] = COCHANGE_HIGH_THRESHOLD  # >= 5

        candidates_without = score_test_candidates(
            prod, [test1, test2], graph, project,
            affected_module_ids={"order-svc"},
            cochange_map=None,
        )
        candidates_with = score_test_candidates(
            prod, [test1, test2], graph, project,
            affected_module_ids={"order-svc"},
            cochange_map=cochange_map,
        )

        # OtherTest should appear in candidates_with but not candidates_without
        without_names = {c.class_name for c in candidates_without}
        with_names = {c.class_name for c in candidates_with}
        assert "OtherTest" in with_names
        assert "OtherTest" not in without_names

        # OtherTest should have HIGH co-change in reasons
        other = next(c for c in candidates_with if c.class_name == "OtherTest")
        assert any("co-changed" in r.lower() for r in other.reasons)
        assert other.score >= SCORE_WEIGHTS["cochange_high"]

    def test_cochange_medium_gives_lower_boost(self):
        prod, test1, test2 = self._make_classes()
        project = self._make_project()
        graph = self._make_graph(prod, test1, test2)

        cochange_high = CoChangeMap()
        cochange_high.co_changes[
            "order-svc/src/main/java/com/example/OrderService.java"
        ]["other-svc/src/test/java/com/other/OtherTest.java"] = COCHANGE_HIGH_THRESHOLD

        cochange_medium = CoChangeMap()
        cochange_medium.co_changes[
            "order-svc/src/main/java/com/example/OrderService.java"
        ]["other-svc/src/test/java/com/other/OtherTest.java"] = COCHANGE_MEDIUM_THRESHOLD

        c_high = score_test_candidates(
            prod, [test2], graph, project, set(), cochange_map=cochange_high
        )
        c_medium = score_test_candidates(
            prod, [test2], graph, project, set(), cochange_map=cochange_medium
        )

        if c_high and c_medium:
            high_score = c_high[0].score
            medium_score = c_medium[0].score
            assert high_score > medium_score

    def test_cochange_low_gives_smallest_boost(self):
        prod, test1, test2 = self._make_classes()
        project = self._make_project()
        graph = self._make_graph(prod, test1, test2)

        cochange_one = CoChangeMap()
        cochange_one.co_changes[
            "order-svc/src/main/java/com/example/OrderService.java"
        ]["other-svc/src/test/java/com/other/OtherTest.java"] = 1

        candidates = score_test_candidates(
            prod, [test2], graph, project, set(), cochange_map=cochange_one
        )
        assert candidates
        assert candidates[0].score == pytest.approx(SCORE_WEIGHTS["cochange_low"], abs=0.001)
        assert any("1 commit" in r for r in candidates[0].reasons)

    def test_filename_fallback_matching(self):
        """_best_cochange_count uses filename fallback when paths differ."""
        prod, test1, test2 = self._make_classes()
        project = self._make_project()
        graph = self._make_graph(prod, test1, test2)

        # test1's file_path: "order-svc/src/test/java/com/example/OrderServiceTest.java"
        # Store under a slightly different prefix in cochange_map
        cochange_map = CoChangeMap()
        cochange_map.co_changes[
            "order-svc/src/main/java/com/example/OrderService.java"
        ][
            "src/test/java/com/example/OrderServiceTest.java"  # slightly different prefix
        ] = 3

        candidates = score_test_candidates(
            prod, [test1], graph, project,
            affected_module_ids={"order-svc"},
            cochange_map=cochange_map,
        )
        assert candidates
        # The co-change reason should appear because filename "OrderServiceTest.java" matches
        has_cochange = any("co-changed" in r.lower() for r in candidates[0].reasons)
        assert has_cochange

    def test_score_weights_registered(self):
        """Verify co-change weights are in SCORE_WEIGHTS."""
        assert "cochange_high" in SCORE_WEIGHTS
        assert "cochange_medium" in SCORE_WEIGHTS
        assert "cochange_low" in SCORE_WEIGHTS
        assert SCORE_WEIGHTS["cochange_high"] > SCORE_WEIGHTS["cochange_medium"] > SCORE_WEIGHTS["cochange_low"]

    def test_config_cochange_fields_default(self):
        from mergemate.config.loader import MergeMateConfig
        cfg = MergeMateConfig()
        assert cfg.cochange_max_commits == 100
        assert cfg.cochange_days == 90

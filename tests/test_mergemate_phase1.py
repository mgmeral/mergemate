"""
Phase 1 tests for the mergemate/ package.
"""
from __future__ import annotations

import os
import sys
import subprocess
import tempfile
import shutil
from dataclasses import fields
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1-5: Domain models
# ---------------------------------------------------------------------------

class TestChangedFile:
    def test_has_correct_fields(self):
        from mergemate.domain.models import ChangedFile
        cf = ChangedFile(path="src/main/java/Foo.java", status="modified")
        assert cf.path == "src/main/java/Foo.java"
        assert cf.status == "modified"
        assert cf.old_path is None

    def test_renamed_has_old_path(self):
        from mergemate.domain.models import ChangedFile
        cf = ChangedFile(path="new/Foo.java", status="renamed", old_path="old/Foo.java")
        assert cf.old_path == "old/Foo.java"


class TestGitChangeSet:
    def test_categorises_files_when_built_manually(self):
        from mergemate.domain.models import GitChangeSet, ChangedFile
        java_prod = ChangedFile(path="src/main/java/Foo.java", status="modified")
        java_test = ChangedFile(path="src/test/java/FooTest.java", status="added")
        pom = ChangedFile(path="pom.xml", status="modified")
        cs = GitChangeSet(
            source_ref="HEAD",
            target_ref="origin/main",
            merge_base="abc123",
            changed_files=[java_prod, java_test, pom],
            java_production_files=[java_prod],
            java_test_files=[java_test],
            pom_files=[pom],
        )
        assert cs.source_ref == "HEAD"
        assert cs.target_ref == "origin/main"
        assert cs.merge_base == "abc123"
        assert java_prod in cs.java_production_files
        assert java_test in cs.java_test_files
        assert pom in cs.pom_files


class TestJdkModels:
    def test_jdk_requirement_is_dataclass(self):
        from mergemate.domain.models import JdkRequirement
        req = JdkRequirement(required_version="17", detected_from="pom.xml", detection_method="property")
        assert req.required_version == "17"
        assert req.detected_from == "pom.xml"
        assert req.detection_method == "property"

    def test_jdk_runtime_is_dataclass(self):
        from mergemate.domain.models import JdkRuntime
        rt = JdkRuntime(
            java_version="17.0.12",
            java_major=17,
            java_home="/opt/jdk-17",
            maven_version="3.9.6",
            source="mvn -version output",
        )
        assert rt.java_version == "17.0.12"
        assert rt.java_major == 17

    def test_jdk_compatibility_has_compatible_and_message(self):
        from mergemate.domain.models import JdkRequirement, JdkRuntime, JdkCompatibility
        req = JdkRequirement(required_version="17", detected_from=None, detection_method="property")
        rt = JdkRuntime(java_version="17.0.12", java_major=17, java_home=None, maven_version="3.9.6", source="test")
        compat = JdkCompatibility(requirement=req, runtime=rt, compatible=True, message="ok")
        assert compat.compatible is True
        assert compat.message == "ok"

    def test_maven_command_has_argv_and_display_command(self):
        from mergemate.domain.models import MavenCommand
        cmd = MavenCommand(
            argv=["mvn", "test", "-pl", "my-module"],
            display_command="mvn test -pl my-module",
            goal="test",
        )
        assert cmd.argv == ["mvn", "test", "-pl", "my-module"]
        assert cmd.display_command == "mvn test -pl my-module"
        assert cmd.goal == "test"


# ---------------------------------------------------------------------------
# 6-14: Git diff (mocked subprocess)
# ---------------------------------------------------------------------------

class TestGetMergeBase:
    def test_returns_clean_sha(self):
        from mergemate.git.diff import get_merge_base
        mock_result = MagicMock()
        mock_result.stdout = "  abc123def456\n"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            sha = get_merge_base("/repo", "HEAD", "origin/main")
        assert sha == "abc123def456"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "merge-base", "HEAD", "origin/main"]

    def test_strips_whitespace(self):
        from mergemate.git.diff import get_merge_base
        mock_result = MagicMock()
        mock_result.stdout = "\ndeadbeef\n"
        with patch("subprocess.run", return_value=mock_result):
            sha = get_merge_base("/repo", "HEAD", "origin/main")
        assert sha == "deadbeef"


class TestGetChangedFiles:
    def test_parses_modified_java_file(self):
        from mergemate.git.diff import get_changed_files
        mock_result = MagicMock()
        mock_result.stdout = "M\tpath/to/File.java\n"
        with patch("subprocess.run", return_value=mock_result):
            files = get_changed_files("/repo", "merge_base_sha", "HEAD")
        assert len(files) == 1
        assert files[0].path == "path/to/File.java"
        assert files[0].status == "modified"

    def test_parses_rename(self):
        from mergemate.git.diff import get_changed_files
        mock_result = MagicMock()
        mock_result.stdout = "R100\told/path.java\tnew/path.java\n"
        with patch("subprocess.run", return_value=mock_result):
            files = get_changed_files("/repo", "abc", "HEAD")
        assert len(files) == 1
        assert files[0].path == "new/path.java"
        assert files[0].status == "renamed"
        assert files[0].old_path == "old/path.java"

    def test_parses_added_file(self):
        from mergemate.git.diff import get_changed_files
        mock_result = MagicMock()
        mock_result.stdout = "A\tsrc/main/java/New.java\n"
        with patch("subprocess.run", return_value=mock_result):
            files = get_changed_files("/repo", "abc", "HEAD")
        assert len(files) == 1
        assert files[0].status == "added"

    def test_parses_deleted_file(self):
        from mergemate.git.diff import get_changed_files
        mock_result = MagicMock()
        mock_result.stdout = "D\tsrc/main/java/Old.java\n"
        with patch("subprocess.run", return_value=mock_result):
            files = get_changed_files("/repo", "abc", "HEAD")
        assert len(files) == 1
        assert files[0].status == "deleted"

    def test_parses_copy(self):
        from mergemate.git.diff import get_changed_files
        mock_result = MagicMock()
        mock_result.stdout = "C100\tsrc/Original.java\tsrc/Copy.java\n"
        with patch("subprocess.run", return_value=mock_result):
            files = get_changed_files("/repo", "abc", "HEAD")
        assert len(files) == 1
        assert files[0].status == "copied"
        assert files[0].path == "src/Copy.java"
        assert files[0].old_path == "src/Original.java"


class TestBuildChangeset:
    def _make_mock_subprocess(self, merge_base_sha: str, diff_output: str):
        """Return a side_effect function that returns different mocks for consecutive calls."""
        calls = []

        def side_effect(argv, **kwargs):
            calls.append(argv)
            mock = MagicMock()
            if "merge-base" in argv:
                mock.stdout = merge_base_sha + "\n"
            else:
                mock.stdout = diff_output
            return mock

        return side_effect

    def test_classifies_java_production_files(self):
        from mergemate.git.diff import build_changeset
        diff_output = "M\tsrc/main/java/Service.java\n"
        side_effect = self._make_mock_subprocess("abc123", diff_output)
        with patch("subprocess.run", side_effect=side_effect):
            cs = build_changeset("/repo", "HEAD", "origin/main")
        assert len(cs.java_production_files) == 1
        assert cs.java_production_files[0].path == "src/main/java/Service.java"

    def test_classifies_java_test_files(self):
        from mergemate.git.diff import build_changeset
        diff_output = "A\tsrc/test/java/FooTest.java\n"
        side_effect = self._make_mock_subprocess("abc123", diff_output)
        with patch("subprocess.run", side_effect=side_effect):
            cs = build_changeset("/repo", "HEAD", "origin/main")
        assert len(cs.java_test_files) == 1
        assert cs.java_test_files[0].path == "src/test/java/FooTest.java"
        assert len(cs.java_production_files) == 0

    def test_classifies_pom_files(self):
        from mergemate.git.diff import build_changeset
        diff_output = "M\tpom.xml\n"
        side_effect = self._make_mock_subprocess("abc123", diff_output)
        with patch("subprocess.run", side_effect=side_effect):
            cs = build_changeset("/repo", "HEAD", "origin/main")
        assert len(cs.pom_files) == 1
        assert cs.pom_files[0].path == "pom.xml"

    def test_classifies_config_files(self):
        from mergemate.git.diff import build_changeset
        diff_output = "M\tsrc/main/resources/application.yml\n"
        side_effect = self._make_mock_subprocess("abc123", diff_output)
        with patch("subprocess.run", side_effect=side_effect):
            cs = build_changeset("/repo", "HEAD", "origin/main")
        assert len(cs.config_files) == 1
        assert cs.config_files[0].path == "src/main/resources/application.yml"

    def test_classifies_migration_files(self):
        from mergemate.git.diff import build_changeset
        diff_output = "A\tdb/changelog/001.sql\n"
        side_effect = self._make_mock_subprocess("abc123", diff_output)
        with patch("subprocess.run", side_effect=side_effect):
            cs = build_changeset("/repo", "HEAD", "origin/main")
        assert len(cs.migration_files) == 1
        assert cs.migration_files[0].path == "db/changelog/001.sql"


# ---------------------------------------------------------------------------
# 15-17: Maven wrapper
# ---------------------------------------------------------------------------

class TestMavenWrapper:
    def test_returns_mvnw_when_wrapper_exists_and_executable_unix(self):
        from mergemate.maven.wrapper import find_maven_executable
        with tempfile.TemporaryDirectory() as tmpdir:
            mvnw = os.path.join(tmpdir, "mvnw")
            with open(mvnw, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(mvnw, 0o755)
            with patch("sys.platform", "linux"):
                result = find_maven_executable(tmpdir)
            assert result == "./mvnw"

    def test_returns_mvn_when_no_wrapper(self):
        from mergemate.maven.wrapper import find_maven_executable
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sys.platform", "linux"):
                result = find_maven_executable(tmpdir)
        assert result == "mvn"

    def test_get_effective_maven_argv_prepends_executable(self):
        from mergemate.maven.wrapper import get_effective_maven_argv
        with tempfile.TemporaryDirectory() as tmpdir:
            # No wrapper
            with patch("sys.platform", "linux"):
                argv = get_effective_maven_argv(tmpdir, ["-pl", "module", "test"])
        assert argv[0] == "mvn"
        assert argv[1:] == ["-pl", "module", "test"]

    def test_get_effective_maven_argv_with_wrapper_windows(self):
        from mergemate.maven.wrapper import get_effective_maven_argv
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create mvnw.cmd
            wrapper = os.path.join(tmpdir, "mvnw.cmd")
            with open(wrapper, "w") as f:
                f.write("@echo off\n")
            with patch("sys.platform", "win32"):
                argv = get_effective_maven_argv(tmpdir, ["test"])
        assert argv[0] == "mvnw.cmd"
        assert argv[1:] == ["test"]


# ---------------------------------------------------------------------------
# 18-29: JDK detection
# ---------------------------------------------------------------------------

class TestJdkDetection:
    def _write_pom(self, tmpdir: str, content: str) -> str:
        pom_path = os.path.join(tmpdir, "pom.xml")
        with open(pom_path, "w", encoding="utf-8") as f:
            f.write(content)
        return pom_path

    def test_detects_maven_compiler_release_from_properties(self):
        from mergemate.maven.jdk import detect_jdk_requirement
        pom_content = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
  </properties>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom_path = self._write_pom(tmpdir, pom_content)
            result = detect_jdk_requirement(pom_path)
        assert result.required_version == "17"
        assert result.detection_method == "property"
        assert "maven.compiler.release" in result.detected_from

    def test_detects_java_version_from_properties(self):
        from mergemate.maven.jdk import detect_jdk_requirement
        pom_content = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <properties>
    <java.version>11</java.version>
  </properties>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom_path = self._write_pom(tmpdir, pom_content)
            result = detect_jdk_requirement(pom_path)
        assert result.required_version == "11"
        assert "java.version" in result.detected_from

    def test_detects_compiler_plugin_release(self):
        from mergemate.maven.jdk import detect_jdk_requirement
        pom_content = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <build>
    <plugins>
      <plugin>
        <artifactId>maven-compiler-plugin</artifactId>
        <configuration>
          <release>21</release>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom_path = self._write_pom(tmpdir, pom_content)
            result = detect_jdk_requirement(pom_path)
        assert result.required_version == "21"
        assert result.detection_method == "compiler-plugin"
        assert "maven-compiler-plugin" in result.detected_from

    def test_detects_maven_compiler_source_as_fallback(self):
        from mergemate.maven.jdk import detect_jdk_requirement
        pom_content = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <properties>
    <maven.compiler.source>1.8</maven.compiler.source>
    <maven.compiler.target>1.8</maven.compiler.target>
  </properties>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom_path = self._write_pom(tmpdir, pom_content)
            result = detect_jdk_requirement(pom_path)
        assert result.required_version == "1.8"
        assert "maven.compiler.source" in result.detected_from

    def test_follows_parent_pom_via_relative_path(self):
        from mergemate.maven.jdk import detect_jdk_requirement
        parent_pom = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
  </properties>
</project>"""
        child_pom = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <parent>
    <relativePath>../pom.xml</relativePath>
  </parent>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # parent pom is at tmpdir/pom.xml
            # child pom is at tmpdir/child/pom.xml
            # child's relativePath is ../pom.xml -> tmpdir/pom.xml  (the parent)
            child_dir = os.path.join(tmpdir, "child")
            os.makedirs(child_dir)
            parent_pom_path = os.path.join(tmpdir, "pom.xml")
            child_pom_path = os.path.join(child_dir, "pom.xml")
            with open(parent_pom_path, "w") as f:
                f.write(parent_pom)
            with open(child_pom_path, "w") as f:
                f.write(child_pom)
            result = detect_jdk_requirement(child_pom_path)
        assert result.required_version == "17"

    def test_returns_none_detection_method_when_no_jdk_version(self):
        from mergemate.maven.jdk import detect_jdk_requirement
        pom_content = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>my-project</artifactId>
  <version>1.0.0</version>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom_path = self._write_pom(tmpdir, pom_content)
            result = detect_jdk_requirement(pom_path)
        assert result.required_version is None
        assert result.detection_method == "none"
        assert result.detected_from is None

    def test_detect_maven_runtime_parses_output(self):
        from mergemate.maven.jdk import detect_maven_runtime
        mvn_output = (
            "Apache Maven 3.9.6 (bc0240f3c744dd6b6ec2920b3cd08dcc295161ae)\n"
            "Maven home: /opt/maven\n"
            "Java version: 17.0.12, vendor: Eclipse Adoptium, runtime: /opt/jdk-17\n"
            "Default locale: en_US, platform encoding: UTF-8\n"
            "OS name: \"linux\", version: \"5.15\", arch: \"amd64\", family: \"unix\"\n"
        )
        mock_result = MagicMock()
        mock_result.stdout = mvn_output
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            runtime = detect_maven_runtime("mvn")
        assert runtime.java_version == "17.0.12"
        assert runtime.java_major == 17
        assert runtime.maven_version == "3.9.6"
        assert runtime.source == "mvn -version output"

    def test_check_jdk_compatibility_matching_major(self):
        from mergemate.maven.jdk import check_jdk_compatibility
        from mergemate.domain.models import JdkRequirement, JdkRuntime
        req = JdkRequirement(required_version="17", detected_from=None, detection_method="property")
        rt = JdkRuntime(java_version="17.0.12", java_major=17, java_home=None, maven_version="3.9.6", source="test")
        compat = check_jdk_compatibility(req, rt)
        assert compat.compatible is True

    def test_check_jdk_compatibility_older_runtime_incompatible(self):
        from mergemate.maven.jdk import check_jdk_compatibility
        from mergemate.domain.models import JdkRequirement, JdkRuntime
        req = JdkRequirement(required_version="17", detected_from=None, detection_method="property")
        rt = JdkRuntime(java_version="11.0.20", java_major=11, java_home=None, maven_version="3.9.6", source="test")
        compat = check_jdk_compatibility(req, rt)
        assert compat.compatible is False
        assert "17" in compat.message
        assert "11" in compat.message

    def test_check_jdk_compatibility_newer_runtime_allowed(self):
        from mergemate.maven.jdk import check_jdk_compatibility
        from mergemate.domain.models import JdkRequirement, JdkRuntime
        req = JdkRequirement(required_version="17", detected_from=None, detection_method="property")
        rt = JdkRuntime(java_version="21.0.1", java_major=21, java_home=None, maven_version="3.9.6", source="test")
        compat = check_jdk_compatibility(req, rt, allow_newer_major=True)
        assert compat.compatible is True
        assert "21" in compat.message or "newer" in compat.message.lower()

    def test_check_jdk_compatibility_no_requirement(self):
        from mergemate.maven.jdk import check_jdk_compatibility
        from mergemate.domain.models import JdkRequirement, JdkRuntime
        req = JdkRequirement(required_version=None, detected_from=None, detection_method="none")
        rt = JdkRuntime(java_version="11.0.20", java_major=11, java_home=None, maven_version="3.9.6", source="test")
        compat = check_jdk_compatibility(req, rt)
        assert compat.compatible is True
        assert "No JDK" in compat.message

    def test_format_incompatibility_error_contains_requires_jdk_and_running_with(self):
        from mergemate.maven.jdk import format_incompatibility_error, check_jdk_compatibility
        from mergemate.domain.models import JdkRequirement, JdkRuntime
        req = JdkRequirement(
            required_version="17",
            detected_from="root pom.xml -> maven.compiler.release",
            detection_method="property",
        )
        rt = JdkRuntime(java_version="11.0.20", java_major=11, java_home="/opt/jdk-11", maven_version="3.9.6", source="test")
        compat = check_jdk_compatibility(req, rt, allow_newer_major=False)
        error_text = format_incompatibility_error(compat)
        assert "requires JDK" in error_text
        assert "running with" in error_text


# ---------------------------------------------------------------------------
# 30-33: Execution adapters
# ---------------------------------------------------------------------------

class TestCurrentWorkspaceAdapter:
    def test_prepare_returns_project_dir(self):
        from mergemate.execution.current_workspace import CurrentWorkspaceAdapter
        adapter = CurrentWorkspaceAdapter()
        result = adapter.prepare("/some/project", "HEAD")
        assert result == "/some/project"

    def test_execute_returns_execution_result(self):
        from mergemate.execution.current_workspace import CurrentWorkspaceAdapter
        from mergemate.execution.adapter import ExecutionResult
        adapter = CurrentWorkspaceAdapter()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "hello"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = adapter.execute(["echo", "hello"], working_dir="/tmp")
        assert isinstance(result, ExecutionResult)
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.timed_out is False

    def test_cleanup_is_noop(self):
        from mergemate.execution.current_workspace import CurrentWorkspaceAdapter
        adapter = CurrentWorkspaceAdapter()
        adapter.cleanup()  # Should not raise


class TestLocalWorktreeAdapter:
    def test_cleanup_called_even_when_execute_raises(self):
        from mergemate.execution.local_worktree import LocalWorktreeAdapter
        from mergemate.git.worktree import TemporaryWorktree

        cleanup_called = []

        class MockWorktree:
            def __init__(self, *a, **kw):
                pass
            def __enter__(self):
                return "/tmp/fake-worktree"
            def __exit__(self, *args):
                cleanup_called.append(True)

        with patch("mergemate.execution.local_worktree.TemporaryWorktree", MockWorktree):
            adapter = LocalWorktreeAdapter("/repo")
            adapter.prepare("/repo", "HEAD")
            try:
                with patch("subprocess.run", side_effect=RuntimeError("oops")):
                    adapter.execute(["mvn", "test"], working_dir="/tmp/fake-worktree")
            except RuntimeError:
                pass
            adapter.cleanup()

        assert len(cleanup_called) >= 1

    def test_execution_result_fields(self):
        from mergemate.execution.adapter import ExecutionResult
        result = ExecutionResult(
            exit_code=0,
            stdout="output",
            stderr="",
            timed_out=False,
            duration_seconds=1.5,
        )
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.timed_out is False
        assert result.duration_seconds == 1.5


# ---------------------------------------------------------------------------
# 34-35: Config loader
# ---------------------------------------------------------------------------

class TestConfigLoader:
    def test_returns_defaults_when_no_file(self):
        from mergemate.config.loader import load_config, MergeMateConfig
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(tmpdir)
        assert isinstance(config, MergeMateConfig)
        assert config.execution_mode == "worktree"
        assert config.use_maven_wrapper is True
        assert config.impact_max_depth == 3

    def test_reads_target_branch_from_yaml(self):
        from mergemate.config.loader import load_config
        try:
            import yaml
        except ImportError:
            pytest.skip("pyyaml not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, ".mergemate.yml")
            with open(config_path, "w") as f:
                f.write("targetBranch: origin/premaster\n")
                f.write("executionMode: workspace\n")
            config = load_config(tmpdir)
        assert config.target_branch == "origin/premaster"
        assert config.execution_mode == "workspace"


# ---------------------------------------------------------------------------
# 36: Integration test (real git)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIntegrationRealGit:
    def test_build_changeset_with_real_git_repo(self):
        """
        Create a temp git repo with two commits:
        - initial commit on 'main' branch
        - a new branch with a Java file added

        Then run build_changeset and verify the Java file is classified correctly.
        """
        from mergemate.git.diff import build_changeset

        tmpdir = tempfile.mkdtemp(prefix="mergemate-test-")
        try:
            # Init repo
            subprocess.run(["git", "init", "-b", "main", tmpdir], check=True, capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "config", "user.email", "test@test.com"], check=True, capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "config", "user.name", "Test"], check=True, capture_output=True)

            # Initial commit on main
            readme = os.path.join(tmpdir, "README.md")
            with open(readme, "w") as f:
                f.write("# Test\n")
            subprocess.run(["git", "-C", tmpdir, "add", "README.md"], check=True, capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "commit", "-m", "initial"], check=True, capture_output=True)

            # Create feature branch
            subprocess.run(["git", "-C", tmpdir, "checkout", "-b", "feature"], check=True, capture_output=True)

            # Add a Java file
            java_dir = os.path.join(tmpdir, "src", "main", "java")
            os.makedirs(java_dir, exist_ok=True)
            java_file = os.path.join(java_dir, "MyService.java")
            with open(java_file, "w") as f:
                f.write("public class MyService {}\n")
            subprocess.run(["git", "-C", tmpdir, "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", tmpdir, "commit", "-m", "add MyService"], check=True, capture_output=True)

            # build_changeset: feature -> main
            cs = build_changeset(tmpdir, "feature", "main")

            assert len(cs.java_production_files) == 1
            assert cs.java_production_files[0].path.replace("\\", "/").endswith("MyService.java")
            assert cs.java_production_files[0].status == "added"

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

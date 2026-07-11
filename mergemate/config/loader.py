import os
import warnings
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MergeMateConfig:
    target_branch: Optional[str] = None
    execution_mode: str = "worktree"      # "worktree", "workspace", "docker"
    use_maven_wrapper: bool = True

    # Impact settings
    impact_max_depth: int = 3
    full_build_threshold: float = 0.60

    # JDK settings
    jdk_strict: bool = True
    allow_newer_major_version: bool = True

    # Modules that always trigger full build
    always_full_build_modules: list[str] = field(default_factory=list)

    # File patterns that trigger full build
    full_build_file_patterns: list[str] = field(default_factory=list)

    # Timeout settings (seconds)
    timeout_analyze: int = 120
    timeout_test: int = 1800
    timeout_compile: int = 1800
    timeout_verify: int = 3600

    # Test patterns
    unit_test_patterns: list[str] = field(
        default_factory=lambda: ["**/*Test.java", "**/*Tests.java"]
    )
    integration_test_patterns: list[str] = field(
        default_factory=lambda: ["**/*IT.java", "**/*IntegrationTest.java"]
    )


def load_config(project_dir: str) -> MergeMateConfig:
    """
    Load .mergemate.yml from project_dir if it exists.
    Returns MergeMateConfig with defaults if file not found.
    Uses pyyaml if available, otherwise returns default config with a warning.
    """
    config_path = os.path.join(project_dir, ".mergemate.yml")
    if not os.path.isfile(config_path):
        return MergeMateConfig()

    try:
        import yaml  # type: ignore[import]
    except ImportError:
        warnings.warn(
            "pyyaml is not installed — .mergemate.yml will be ignored. "
            "Install it with: pip install pyyaml>=6",
            UserWarning,
            stacklevel=2,
        )
        return MergeMateConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        warnings.warn(
            f"Failed to parse .mergemate.yml: {e}. Using defaults.",
            UserWarning,
            stacklevel=2,
        )
        return MergeMateConfig()

    if not isinstance(data, dict):
        return MergeMateConfig()

    # Map YAML keys to config fields
    config = MergeMateConfig()

    _set_str(config, data, "targetBranch", "target_branch")
    _set_str(config, data, "executionMode", "execution_mode")
    _set_bool(config, data, "useMavenWrapper", "use_maven_wrapper")
    _set_int(config, data, "impactMaxDepth", "impact_max_depth")
    _set_float(config, data, "fullBuildThreshold", "full_build_threshold")
    _set_bool(config, data, "jdkStrict", "jdk_strict")
    _set_bool(config, data, "allowNewerMajorVersion", "allow_newer_major_version")
    _set_list(config, data, "alwaysFullBuildModules", "always_full_build_modules")
    _set_list(config, data, "fullBuildFilePatterns", "full_build_file_patterns")
    _set_int(config, data, "timeoutAnalyze", "timeout_analyze")
    _set_int(config, data, "timeoutTest", "timeout_test")
    _set_int(config, data, "timeoutCompile", "timeout_compile")
    _set_int(config, data, "timeoutVerify", "timeout_verify")
    _set_list(config, data, "unitTestPatterns", "unit_test_patterns")
    _set_list(config, data, "integrationTestPatterns", "integration_test_patterns")

    return config


def _set_str(config: MergeMateConfig, data: dict, yaml_key: str, attr: str) -> None:
    if yaml_key in data and isinstance(data[yaml_key], str):
        setattr(config, attr, data[yaml_key])


def _set_bool(config: MergeMateConfig, data: dict, yaml_key: str, attr: str) -> None:
    if yaml_key in data and isinstance(data[yaml_key], bool):
        setattr(config, attr, data[yaml_key])


def _set_int(config: MergeMateConfig, data: dict, yaml_key: str, attr: str) -> None:
    if yaml_key in data and isinstance(data[yaml_key], int):
        setattr(config, attr, data[yaml_key])


def _set_float(config: MergeMateConfig, data: dict, yaml_key: str, attr: str) -> None:
    if yaml_key in data and isinstance(data[yaml_key], (int, float)):
        setattr(config, attr, float(data[yaml_key]))


def _set_list(config: MergeMateConfig, data: dict, yaml_key: str, attr: str) -> None:
    if yaml_key in data and isinstance(data[yaml_key], list):
        setattr(config, attr, data[yaml_key])

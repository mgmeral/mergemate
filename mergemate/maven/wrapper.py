import os
import sys


def find_maven_executable(project_dir: str) -> str:
    """
    Find the Maven executable to use for this project.

    Priority:
    1. ./mvnw (Linux/macOS) or mvnw.cmd (Windows) in project_dir — if executable
    2. mvn on PATH

    Returns the command string (e.g. "./mvnw" or "mvnw.cmd" or "mvn").
    Never returns a full absolute path unless necessary — keep it short for display.

    On Windows, check for mvnw.cmd first, then mvnw.
    On Linux/macOS, check for mvnw.
    """
    if sys.platform == "win32":
        # On Windows check mvnw.cmd first, then mvnw
        for wrapper_name in ("mvnw.cmd", "mvnw"):
            wrapper_path = os.path.join(project_dir, wrapper_name)
            if os.path.isfile(wrapper_path):
                return wrapper_name
    else:
        wrapper_path = os.path.join(project_dir, "mvnw")
        if os.path.isfile(wrapper_path) and os.access(wrapper_path, os.X_OK):
            return "./mvnw"

    return "mvn"


def is_wrapper_available(project_dir: str) -> bool:
    """Return True if a Maven wrapper exists in project_dir."""
    if sys.platform == "win32":
        for wrapper_name in ("mvnw.cmd", "mvnw"):
            if os.path.isfile(os.path.join(project_dir, wrapper_name)):
                return True
        return False
    else:
        wrapper_path = os.path.join(project_dir, "mvnw")
        return os.path.isfile(wrapper_path) and os.access(wrapper_path, os.X_OK)


def get_effective_maven_argv(project_dir: str, args: list[str]) -> list[str]:
    """
    Return a complete argv list for running Maven with the given args.

    Example on Linux with wrapper:
        ["./mvnw"] + args
    Example on Windows with wrapper:
        ["mvnw.cmd"] + args  # (or full path if needed)
    Example without wrapper:
        ["mvn"] + args
    """
    executable = find_maven_executable(project_dir)
    return [executable] + args

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_seconds: float = 0.0


class ExecutionAdapter(ABC):
    @abstractmethod
    def prepare(self, project_dir: str, source_ref: str) -> str:
        """
        Prepare the execution environment.
        Returns the working directory where Maven should be run.
        """

    @abstractmethod
    def execute(
        self,
        argv: list[str],
        working_dir: str,
        timeout_s: int = 3600,
        env: Optional[dict] = None,
    ) -> ExecutionResult:
        """Run a command in the prepared environment."""

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up the environment (always called, even on error)."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()

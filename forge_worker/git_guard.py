"""
forge_worker/git_guard.py

Git Guard — allow-list enforcement at the argv level.

Receives an argv list (starting from 'git' or directly from the subcommand).
Pure Python, no subprocess, no shell.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    allowed: bool
    reason: str


# ---------------------------------------------------------------------------
# Policy tables
# ---------------------------------------------------------------------------

# Subcommands that are unconditionally rejected.
_REJECTED_SUBCOMMANDS: frozenset[str] = frozenset({
    "push",
    "commit",
    "tag",
    "rebase",
    "cherry-pick",
    "revert",
    "clean",
})

# Subcommands that are allowed (all others are rejected by default).
_ALLOWED_SUBCOMMANDS: frozenset[str] = frozenset({
    "clone",
    "fetch",
    "checkout",
    "merge",
    "diff",
    "log",
    "status",
    "rev-parse",
    "ls-files",
})

# Dangerous flags (prefix-match with '=' separator supported).
# These are rejected wherever they appear in argv.
_DANGEROUS_FLAG_PREFIXES: tuple[str, ...] = (
    "--upload-pack",
    "--receive-pack",
    "-c",
    "--config",
    "--exec",
    "--exec-path",
    "--git-dir",
)


def _is_dangerous_flag(token: str) -> bool:
    """Return True if *token* matches any dangerous flag prefix."""
    for prefix in _DANGEROUS_FLAG_PREFIXES:
        if token == prefix or token.startswith(prefix + "="):
            return True
    return False


# ---------------------------------------------------------------------------
# Main check function
# ---------------------------------------------------------------------------

def check(argv: list[str]) -> GuardResult:
    """
    Check whether an argv list is allowed by the guard policy.

    argv may start with 'git' or directly with the subcommand.
    Returns GuardResult(allowed=True, ...) or GuardResult(allowed=False, reason=...).
    """
    if not argv:
        return GuardResult(allowed=False, reason="empty argv")

    args = list(argv)

    # Strip leading 'git' if present.
    if args[0] == "git":
        args = args[1:]

    if not args:
        return GuardResult(allowed=False, reason="no subcommand provided")

    # ------------------------------------------------------------------
    # Step 1: Scan ALL tokens for dangerous flags (before subcommand
    # extraction, so they are caught regardless of position).
    # ------------------------------------------------------------------
    for token in args:
        if _is_dangerous_flag(token):
            return GuardResult(
                allowed=False,
                reason=f"dangerous flag rejected: {token}",
            )

    # ------------------------------------------------------------------
    # Step 2: Detect options BEFORE the subcommand.
    # The first non-flag token is the subcommand; anything flag-like
    # before it is rejected.
    # ------------------------------------------------------------------
    subcommand: str | None = None
    subcommand_index: int = 0

    for i, token in enumerate(args):
        if token.startswith("-"):
            # Still in the pre-subcommand options zone — reject.
            return GuardResult(
                allowed=False,
                reason=f"no options before subcommand: {token}",
            )
        else:
            subcommand = token
            subcommand_index = i
            break

    if subcommand is None:
        return GuardResult(allowed=False, reason="no subcommand found")

    # Remaining tokens after the subcommand.
    rest = args[subcommand_index + 1:]

    # ------------------------------------------------------------------
    # Step 3: Hard-reject specific subcommands.
    # ------------------------------------------------------------------
    if subcommand in _REJECTED_SUBCOMMANDS:
        return GuardResult(
            allowed=False,
            reason=f"subcommand not allowed: {subcommand}",
        )

    # ------------------------------------------------------------------
    # Step 4: Special handling for 'reset'.
    # Allowed only as `reset --soft` with no path operands.
    # `reset --hard` is always rejected.
    # ------------------------------------------------------------------
    if subcommand == "reset":
        if "--hard" in rest:
            return GuardResult(
                allowed=False,
                reason="reset --hard is not allowed",
            )
        if "--soft" in rest:
            # Verify no path operands: only --soft (and maybe a ref) are present.
            non_flags = [t for t in rest if not t.startswith("-")]
            # A single non-flag is acceptable (the ref), more than one → suspect.
            # We allow `reset --soft` and `reset --soft <ref>` but nothing else.
            flags = [t for t in rest if t.startswith("-")]
            # Only --soft is acceptable as a flag in this mode.
            bad_flags = [f for f in flags if f != "--soft"]
            if bad_flags:
                return GuardResult(
                    allowed=False,
                    reason=f"reset with disallowed flags: {bad_flags}",
                )
            if len(non_flags) > 1:
                return GuardResult(
                    allowed=False,
                    reason="reset --soft with multiple operands is not allowed",
                )
            return GuardResult(allowed=True, reason="reset --soft allowed")
        # Any other reset variant (no --soft) is rejected.
        return GuardResult(
            allowed=False,
            reason="reset requires --soft and no path operands",
        )

    # ------------------------------------------------------------------
    # Step 5: Special handling for 'remote'.
    # Reject `remote remove` and `remote set-url`.
    # ------------------------------------------------------------------
    if subcommand == "remote":
        if rest and rest[0] in ("remove", "set-url"):
            return GuardResult(
                allowed=False,
                reason=f"remote {rest[0]} is not allowed",
            )
        return GuardResult(
            allowed=False,
            reason="remote subcommand is not allowed",
        )

    # ------------------------------------------------------------------
    # Step 6: Special handling for 'config'.
    # Reject config with --global.
    # ------------------------------------------------------------------
    if subcommand == "config":
        if "--global" in rest:
            return GuardResult(
                allowed=False,
                reason="config --global is not allowed",
            )
        return GuardResult(
            allowed=False,
            reason="config subcommand is not allowed",
        )

    # ------------------------------------------------------------------
    # Step 7: Check against the allow-list.
    # ------------------------------------------------------------------
    if subcommand not in _ALLOWED_SUBCOMMANDS:
        return GuardResult(
            allowed=False,
            reason=f"subcommand not in allow-list: {subcommand}",
        )

    # ------------------------------------------------------------------
    # Step 8: Subcommand-specific rules.
    # ------------------------------------------------------------------

    if subcommand == "merge":
        # Special case: `merge --abort` is a safe operation — allow it.
        if rest == ["--abort"]:
            return GuardResult(allowed=True, reason="merge --abort allowed")

        # `--commit` is never allowed in merge (it overrides --no-commit).
        if "--commit" in rest:
            return GuardResult(
                allowed=False,
                reason="merge --commit is not allowed",
            )

        # merge MUST have --no-commit for safe conflict detection.
        if "--no-commit" not in rest:
            return GuardResult(
                allowed=False,
                reason="merge requires --no-commit",
            )

    # ------------------------------------------------------------------
    # All checks passed.
    # ------------------------------------------------------------------
    return GuardResult(allowed=True, reason=f"{subcommand} allowed")

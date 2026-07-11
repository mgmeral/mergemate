"""
tests/test_git_guard.py

Full rejection matrix tests for forge_worker.git_guard.

Covers every allow / reject case in the spec.
"""

from __future__ import annotations

import os
import sys

import pytest

_here = os.path.dirname(__file__)
_project_root = os.path.dirname(_here)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from forge_worker.git_guard import check, GuardResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed(argv: list[str]) -> bool:
    return check(argv).allowed


def rejected(argv: list[str]) -> bool:
    return not check(argv).allowed


def reason(argv: list[str]) -> str:
    return check(argv).reason


# ===========================================================================
# Allow tests (1–9)
# ===========================================================================

def test_allow_clone():
    """git clone https://example.com/repo.git /work/repo → allowed"""
    result = check(["git", "clone", "https://example.com/repo.git", "/work/repo"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_fetch():
    """git fetch origin main → allowed"""
    result = check(["git", "fetch", "origin", "main"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_checkout():
    """git checkout feature-branch → allowed"""
    result = check(["git", "checkout", "feature-branch"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_merge_no_commit():
    """git merge --no-commit origin/main → allowed (merge-check pattern)"""
    result = check(["git", "merge", "--no-commit", "origin/main"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_diff():
    """git diff --name-only HEAD origin/main → allowed"""
    result = check(["git", "diff", "--name-only", "HEAD", "origin/main"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_log():
    """git log --oneline -10 → allowed"""
    result = check(["git", "log", "--oneline", "-10"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_status():
    """git status → allowed"""
    result = check(["git", "status"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_rev_parse():
    """git rev-parse HEAD → allowed"""
    result = check(["git", "rev-parse", "HEAD"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_allow_ls_files():
    """git ls-files → allowed"""
    result = check(["git", "ls-files"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


# ===========================================================================
# Reject tests (10–29)
# ===========================================================================

def test_reject_push():
    """git push origin main → rejected"""
    result = check(["git", "push", "origin", "main"])
    assert not result.allowed
    assert "push" in result.reason.lower()


def test_reject_commit():
    """git commit -m 'msg' → rejected"""
    result = check(["git", "commit", "-m", "msg"])
    assert not result.allowed
    assert "commit" in result.reason.lower()


def test_reject_tag():
    """git tag v1.0 → rejected"""
    result = check(["git", "tag", "v1.0"])
    assert not result.allowed
    assert "tag" in result.reason.lower()


def test_reject_rebase():
    """git rebase origin/main → rejected"""
    result = check(["git", "rebase", "origin/main"])
    assert not result.allowed
    assert "rebase" in result.reason.lower()


def test_reject_cherry_pick():
    """git cherry-pick abc123 → rejected"""
    result = check(["git", "cherry-pick", "abc123"])
    assert not result.allowed
    assert "cherry-pick" in result.reason.lower()


def test_reject_revert():
    """git revert HEAD → rejected"""
    result = check(["git", "revert", "HEAD"])
    assert not result.allowed
    assert "revert" in result.reason.lower()


def test_reject_clean():
    """git clean -fdx → rejected"""
    result = check(["git", "clean", "-fdx"])
    assert not result.allowed
    assert "clean" in result.reason.lower()


def test_reject_reset_hard():
    """git reset --hard HEAD → rejected"""
    result = check(["git", "reset", "--hard", "HEAD"])
    assert not result.allowed
    assert "hard" in result.reason.lower() or "reset" in result.reason.lower()


def test_reject_remote_remove():
    """git remote remove origin → rejected"""
    result = check(["git", "remote", "remove", "origin"])
    assert not result.allowed
    assert "remove" in result.reason.lower() or "remote" in result.reason.lower()


def test_reject_remote_set_url():
    """git remote set-url origin https://evil.com → rejected"""
    result = check(["git", "remote", "set-url", "origin", "https://evil.com"])
    assert not result.allowed
    assert "set-url" in result.reason.lower() or "remote" in result.reason.lower()


def test_reject_config_global():
    """git config --global user.email x@x.com → rejected"""
    result = check(["git", "config", "--global", "user.email", "x@x.com"])
    assert not result.allowed
    assert "global" in result.reason.lower() or "config" in result.reason.lower()


def test_reject_merge_without_no_commit():
    """git merge origin/main (without --no-commit) → rejected"""
    result = check(["git", "merge", "origin/main"])
    assert not result.allowed
    assert "--no-commit" in result.reason or "no-commit" in result.reason.lower()


def test_reject_merge_with_commit_flag():
    """git merge --commit origin/main → rejected (--commit overrides --no-commit)"""
    result = check(["git", "merge", "--commit", "origin/main"])
    assert not result.allowed
    assert "--commit" in result.reason or "commit" in result.reason.lower()


def test_reject_option_before_subcommand_c_flag():
    """git -c http.proxy=evil merge --no-commit → rejected (options before subcommand / -c flag)"""
    result = check(["git", "-c", "http.proxy=evil", "merge", "--no-commit"])
    assert not result.allowed
    # Either caught as dangerous flag or as option before subcommand
    assert result.reason  # must have a meaningful reason


def test_reject_upload_pack_before_subcommand():
    """git --upload-pack=evil fetch origin → rejected"""
    result = check(["git", "--upload-pack=evil", "fetch", "origin"])
    assert not result.allowed
    assert "upload-pack" in result.reason.lower()


def test_reject_receive_pack_before_subcommand():
    """git --receive-pack=evil clone → rejected"""
    result = check(["git", "--receive-pack=evil", "clone"])
    assert not result.allowed
    assert "receive-pack" in result.reason.lower()


def test_reject_fetch_with_upload_pack():
    """git fetch --upload-pack=/bin/evil origin → rejected"""
    result = check(["git", "fetch", "--upload-pack=/bin/evil", "origin"])
    assert not result.allowed
    assert "upload-pack" in result.reason.lower()


def test_reject_fetch_with_config():
    """git fetch --config=evil origin → rejected"""
    result = check(["git", "fetch", "--config=evil", "origin"])
    assert not result.allowed
    assert "config" in result.reason.lower()


def test_reject_merge_with_exec():
    """git merge --no-commit --exec='evil' → rejected (--exec flag)"""
    result = check(["git", "merge", "--no-commit", '--exec=evil'])
    assert not result.allowed
    assert "exec" in result.reason.lower()


def test_reject_log_with_exec_path():
    """git log --exec-path=evil → rejected"""
    result = check(["git", "log", "--exec-path=evil"])
    assert not result.allowed
    assert "exec" in result.reason.lower()


# ===========================================================================
# Edge cases
# ===========================================================================

def test_allow_merge_abort():
    """git merge --abort → allowed (safe abort, no write)"""
    result = check(["git", "merge", "--abort"])
    assert result.allowed, f"Expected merge --abort to be allowed, got: {result.reason}"


def test_allow_argv_without_git_prefix():
    """argv starting directly with subcommand (no 'git') → works correctly"""
    result = check(["fetch", "origin", "main"])
    assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_reject_argv_without_git_prefix_push():
    """argv ['push', 'origin', 'main'] without 'git' prefix → still rejected"""
    result = check(["push", "origin", "main"])
    assert not result.allowed
    assert "push" in result.reason.lower()


def test_reject_empty_argv():
    """Empty argv → rejected"""
    result = check([])
    assert not result.allowed


def test_reject_just_git():
    """['git'] alone → rejected (no subcommand)"""
    result = check(["git"])
    assert not result.allowed


def test_reject_merge_commit_with_no_commit():
    """git merge --no-commit --commit origin/main → rejected (--commit present)"""
    result = check(["git", "merge", "--no-commit", "--commit", "origin/main"])
    assert not result.allowed
    assert "commit" in result.reason.lower()


def test_allow_reset_soft():
    """git reset --soft HEAD~1 → allowed"""
    result = check(["git", "reset", "--soft", "HEAD~1"])
    assert result.allowed, f"Expected reset --soft to be allowed, got: {result.reason}"


def test_reject_reset_no_flags():
    """git reset HEAD → rejected (no --soft)"""
    result = check(["git", "reset", "HEAD"])
    assert not result.allowed

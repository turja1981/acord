"""
Git Tools

Tools for Git operations during the upgrade workflow.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from langchain_core.tools import tool


class GitTool:
    """Git operations wrapper."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git", *args]
        return subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def is_repo(self) -> bool:
        """Check if path is a git repository."""
        try:
            self._run_git("rev-parse", "--git-dir")
            return True
        except subprocess.CalledProcessError:
            return False

    def init_repo(self) -> bool:
        """Initialize a git repository."""
        try:
            self._run_git("init")
            return True
        except subprocess.CalledProcessError:
            return False

    def get_current_branch(self) -> str:
        """Get current branch name."""
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def create_branch(self, branch_name: str, checkout: bool = True) -> bool:
        """Create a new branch."""
        try:
            self._run_git("checkout", "-b", branch_name)
            return True
        except subprocess.CalledProcessError:
            if checkout:
                self._run_git("checkout", branch_name)
            return False

    def checkout(self, branch_name: str) -> bool:
        """Checkout a branch."""
        try:
            self._run_git("checkout", branch_name)
            return True
        except subprocess.CalledProcessError:
            return False

    def add(self, paths: list[str] | str = ".") -> bool:
        """Stage files for commit."""
        try:
            if isinstance(paths, str):
                paths = [paths]
            self._run_git("add", *paths)
            return True
        except subprocess.CalledProcessError:
            return False

    def commit(self, message: str) -> Optional[str]:
        """Create a commit."""
        try:
            self._run_git("commit", "-m", message)
            result = self._run_git("rev-parse", "HEAD")
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def get_diff(self, staged: bool = False, file_path: Optional[str] = None) -> str:
        """Get git diff."""
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.extend(["--", file_path])

        result = self._run_git(*args, check=False)
        return result.stdout

    def get_status(self) -> dict[str, list[str]]:
        """Get git status."""
        result = self._run_git("status", "--porcelain")

        status = {
            "modified": [],
            "added": [],
            "deleted": [],
            "untracked": [],
        }

        for line in result.stdout.split("\n"):
            if not line:
                continue
            status_code = line[:2]
            file_path = line[3:]

            if status_code in ("M ", " M", "MM"):
                status["modified"].append(file_path)
            elif status_code in ("A ", "AM"):
                status["added"].append(file_path)
            elif status_code in ("D ", " D"):
                status["deleted"].append(file_path)
            elif status_code == "??":
                status["untracked"].append(file_path)

        return status

    def get_log(self, count: int = 10) -> list[dict[str, str]]:
        """Get commit log."""
        result = self._run_git(
            "log",
            f"-{count}",
            "--pretty=format:%H|%an|%ae|%s|%ci",
        )

        commits = []
        for line in result.stdout.split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "message": parts[3],
                    "date": parts[4],
                })

        return commits

    def stash(self, message: Optional[str] = None) -> bool:
        """Stash changes."""
        try:
            args = ["stash", "push"]
            if message:
                args.extend(["-m", message])
            self._run_git(*args)
            return True
        except subprocess.CalledProcessError:
            return False

    def stash_pop(self) -> bool:
        """Pop stashed changes."""
        try:
            self._run_git("stash", "pop")
            return True
        except subprocess.CalledProcessError:
            return False


# LangChain tool definitions

@tool
def create_branch(
    repo_path: str,
    branch_name: str,
    prefix: str = "upgrade/java-",
) -> dict[str, Any]:
    """
    Create a new git branch for the upgrade.

    Args:
        repo_path: Path to the git repository
        branch_name: Name for the new branch (will be prefixed)
        prefix: Branch name prefix

    Returns:
        Result of branch creation
    """
    try:
        git = GitTool(repo_path)

        if not git.is_repo():
            git.init_repo()

        full_branch_name = f"{prefix}{branch_name}"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        full_branch_name = f"{full_branch_name}-{timestamp}"

        created = git.create_branch(full_branch_name)

        return {
            "success": True,
            "branch_name": full_branch_name,
            "created_new": created,
            "current_branch": git.get_current_branch(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def commit_changes(
    repo_path: str,
    message: str,
    files: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Commit changes to git.

    Args:
        repo_path: Path to the git repository
        message: Commit message
        files: Specific files to commit (None for all changes)

    Returns:
        Commit result
    """
    try:
        git = GitTool(repo_path)

        # Stage files
        if files:
            git.add(files)
        else:
            git.add(".")

        # Check if there are changes to commit
        status = git.get_status()
        if not any(status.values()):
            return {
                "success": True,
                "message": "No changes to commit",
                "commit_hash": None,
            }

        # Commit
        commit_hash = git.commit(message)

        return {
            "success": commit_hash is not None,
            "commit_hash": commit_hash,
            "message": message,
            "files_committed": status,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def get_diff(
    repo_path: str,
    staged: bool = False,
    file_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Get git diff.

    Args:
        repo_path: Path to the git repository
        staged: Whether to show staged changes only
        file_path: Specific file to diff

    Returns:
        Diff content
    """
    try:
        git = GitTool(repo_path)
        diff = git.get_diff(staged=staged, file_path=file_path)

        return {
            "success": True,
            "diff": diff,
            "has_changes": bool(diff),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def get_git_status(repo_path: str) -> dict[str, Any]:
    """
    Get git repository status.

    Args:
        repo_path: Path to the git repository

    Returns:
        Repository status information
    """
    try:
        git = GitTool(repo_path)

        return {
            "success": True,
            "is_repo": git.is_repo(),
            "current_branch": git.get_current_branch() if git.is_repo() else None,
            "status": git.get_status() if git.is_repo() else {},
            "recent_commits": git.get_log(5) if git.is_repo() else [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@tool
def stash_changes(repo_path: str, message: Optional[str] = None) -> dict[str, Any]:
    """
    Stash current changes.

    Args:
        repo_path: Path to the git repository
        message: Optional stash message

    Returns:
        Stash result
    """
    try:
        git = GitTool(repo_path)
        success = git.stash(message)

        return {
            "success": success,
            "message": message or "Automatic stash",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }

import os
import subprocess

from .config import GithubConfig


def check_git_config():
    """Validate that git user.name and user.email are configured."""
    for key in ["user.name", "user.email"]:
        result = subprocess.run(
            ["git", "config", key],
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            raise RuntimeError(
                f"Git이 설정되지 않았습니다: '{key}' 없음.\n"
                f"  실행: git config --global {key} 'Your Value'"
            )


def sync_repo(github: GithubConfig, local_path: str):
    """Clone the repo if missing, otherwise pull the latest commit."""
    git_dir = os.path.join(local_path, ".git")

    if os.path.exists(git_dir):
        result = subprocess.run(
            ["git", "pull", "origin", github.branch],
            capture_output=True,
            text=True,
            cwd=local_path,
        )
    else:
        os.makedirs(local_path, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--branch", github.branch, "--single-branch",
             github.url, local_path],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"GitHub 레포 동기화 실패 ({github.url}, branch={github.branch}):\n"
            f"  {result.stderr.strip()}"
        )


def pull_repo(github: GithubConfig, local_path: str):
    """Pull the latest commit for an already-cloned repo. Raises on failure."""
    result = subprocess.run(
        ["git", "pull", "origin", github.branch],
        capture_output=True,
        text=True,
        cwd=local_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git pull 실패: {result.stderr.strip()}")

import subprocess
import os


def check_git_config():
    """Validate that git user.name and user.email are configured globally or locally."""
    for key in ["user.name", "user.email"]:
        result = subprocess.run(
            ["git", "config", key],
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            raise RuntimeError(
                f"Git is not configured: '{key}' is missing.\n"
                f"  Run: git config --global {key} 'Your Value'"
            )


def sync_repo(repo_url: str, branch: str, local_path: str):
    """Clone the repo if it doesn't exist, otherwise pull the latest commit."""
    git_dir = os.path.join(local_path, ".git")

    if os.path.exists(git_dir):
        result = subprocess.run(
            ["git", "pull", "origin", branch],
            capture_output=True,
            text=True,
            cwd=local_path,
        )
    else:
        os.makedirs(local_path, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch", repo_url, local_path],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to sync GitHub repo '{repo_url}' (branch: {branch}):\n"
            f"  {result.stderr.strip()}"
        )


def pull_repo(branch: str, local_path: str):
    """Pull the latest commit for an already-cloned repo. Raises on failure."""
    result = subprocess.run(
        ["git", "pull", "origin", branch],
        capture_output=True,
        text=True,
        cwd=local_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git pull failed: {result.stderr.strip()}")

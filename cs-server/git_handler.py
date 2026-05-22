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
    """Clone the repo if it doesn't exist, otherwise pull latest."""
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


def get_schema_context(local_path: str) -> str:
    """
    Walk the repo and collect SQL schema files and markdown documentation.
    Returns a concatenated string for use as Claude's context.
    """
    schema_parts = []
    target_extensions = {".sql", ".md"}

    for root, dirs, files in os.walk(local_path):
        dirs[:] = [d for d in dirs if d != ".git"]

        for filename in sorted(files):
            if not any(filename.endswith(ext) for ext in target_extensions):
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                if content:
                    rel_path = os.path.relpath(filepath, local_path)
                    schema_parts.append(f"### {rel_path}\n```\n{content}\n```")
            except Exception:
                pass

    if not schema_parts:
        return "스키마 파일을 찾을 수 없습니다. 레포지토리에 .sql 또는 .md 파일을 추가하세요."

    return "\n\n".join(schema_parts)

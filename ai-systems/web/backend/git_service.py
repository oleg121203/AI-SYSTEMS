"""
Git Service Proxy - This module attempts to import the real GitService class
from the actual git_service module. If that fails, it provides a placeholder
implementation with limited functionality.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Configure logging
logger = logging.getLogger(__name__)

# Try to import the real GitService
try:
    # Try a few different relative paths to find the original git_service module
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "../../git-service"),
        os.path.join(os.path.dirname(__file__), "../../../ai-systems/git-service"),
        os.path.join(os.path.dirname(__file__), "../../../git-service"),
    ]

    git_service_found = False
    original_git_service = None

    for path in possible_paths:
        if os.path.exists(path):
            sys.path.append(os.path.abspath(path))
            try:
                import git_service as original_git_service
                from git_service import GitService as OriginalGitService

                git_service_found = True
                logger.info(f"Found original git-service module at {path}")
                break
            except ImportError:
                logger.warning(
                    f"Found path {path} but could not import git_service module"
                )

    if git_service_found:
        # If we successfully imported the original, use it
        GitService = OriginalGitService
        logger.info("Using original GitService implementation")
    else:
        # If not, create a placeholder implementation
        raise ImportError("Could not import original GitService")

except ImportError as e:
    logger.warning(
        f"Could not import GitService: {e}. Using placeholder implementation."
    )

    class FileContent:
        """Model for file content"""

        def __init__(self, path: str, content: str):
            self.path = path
            self.content = content

        def dict(self):
            return {"path": self.path, "content": self.content}

    class GitService:
        """Placeholder implementation of GitService with limited functionality"""

        def __init__(self, repo_path=None):
            """Initialize the Git service"""
            self.repo_path = (
                repo_path
                or Path(os.path.expanduser("~")) / "workspace" / "AI-SYSTEMS-REPO"
            )
            logger.warning(
                f"Using placeholder GitService with repo path: {self.repo_path}"
            )

        def ensure_repo_exists(self):
            """Ensure the repository exists and is up to date"""
            if not os.path.exists(self.repo_path):
                logger.warning(f"Repository directory does not exist: {self.repo_path}")
                os.makedirs(self.repo_path, exist_ok=True)
                try:
                    self._run_command(["git", "init"], cwd=str(self.repo_path))
                    logger.info(f"Initialized new Git repository at {self.repo_path}")
                except Exception as e:
                    logger.error(f"Error initializing Git repository: {e}")

            # Configure Git user if possible
            try:
                git_user_name = os.getenv("GIT_USER_NAME", "AI-SYSTEMS")
                git_user_email = os.getenv("GIT_USER_EMAIL", "ai-systems@example.com")

                self._run_command(
                    ["git", "config", "user.name", git_user_name],
                    cwd=str(self.repo_path),
                )
                self._run_command(
                    ["git", "config", "user.email", git_user_email],
                    cwd=str(self.repo_path),
                )
            except Exception as e:
                logger.error(f"Error configuring Git user: {e}")

        def commit_file(self, file_path, content, commit_message, branch="main"):
            """Commit a single file to the repository"""
            try:
                # Ensure directory exists
                full_path = os.path.join(self.repo_path, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)

                # Write file content
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)

                # Add and commit
                self._run_command(["git", "add", file_path], cwd=str(self.repo_path))
                self._run_command(
                    ["git", "commit", "-m", commit_message], cwd=str(self.repo_path)
                )

                return True
            except Exception as e:
                logger.error(f"Error committing file: {e}")
                return False

        def commit_files(self, files, commit_message, branch="main"):
            """Commit multiple files to the repository"""
            try:
                for file in files:
                    path = file.path if hasattr(file, "path") else file.get("path")
                    content = (
                        file.content
                        if hasattr(file, "content")
                        else file.get("content")
                    )

                    # Ensure directory exists
                    full_path = os.path.join(self.repo_path, path)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)

                    # Write file content
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(content)

                    # Add file
                    self._run_command(["git", "add", path], cwd=str(self.repo_path))

                # Commit all files
                self._run_command(
                    ["git", "commit", "-m", commit_message], cwd=str(self.repo_path)
                )

                return True, "Files committed successfully"
            except Exception as e:
                logger.error(f"Error committing files: {e}")
                return False, f"Error: {str(e)}"

        def setup_github_actions(self):
            """Set up GitHub Actions workflows for testing"""
            workflows_dir = os.path.join(self.repo_path, ".github", "workflows")
            os.makedirs(workflows_dir, exist_ok=True)

            # Create a basic CI workflow for testing
            ci_workflow = """name: CI

on:
  push:
    branches: [ master, main ]
  pull_request:
    branches: [ master, main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
    - name: Run tests
      run: |
        if [ -d tests ]; then
          python -m unittest discover tests
        else
          echo "No tests directory found, skipping tests"
        fi
"""

            workflow_path = os.path.join(workflows_dir, "ci.yml")
            with open(workflow_path, "w") as f:
                f.write(ci_workflow)

            # Commit the workflow file
            try:
                self._run_command(
                    ["git", "add", ".github/workflows/ci.yml"], cwd=str(self.repo_path)
                )
                self._run_command(
                    ["git", "commit", "-m", "Set up GitHub Actions CI workflow"],
                    cwd=str(self.repo_path),
                )
                logger.info("Successfully set up GitHub Actions workflow")
                return True
            except Exception as e:
                logger.error(f"Error setting up GitHub Actions: {e}")
                return False

        def get_repo_info(self):
            """Get information about the repository"""
            try:
                # Get last commit
                last_commit = "None"
                try:
                    result = self._run_command(
                        ["git", "log", "-1", "--pretty=format:%h - %s"],
                        cwd=str(self.repo_path),
                        capture_output=True,
                    )
                    last_commit = result.stdout.decode().strip()
                except Exception:
                    pass

                # Count files
                file_count = 0
                for _, _, files in os.walk(self.repo_path):
                    file_count += len(files)

                return {
                    "repo_url": f"https://github.com/{os.getenv('GITHUB_REPO', 'ai-systems/repo')}",
                    "branch": os.getenv("MAIN_BRANCH", "main"),
                    "last_commit": last_commit,
                    "file_count": file_count,
                }
            except Exception as e:
                logger.error(f"Error getting repo info: {e}")
                return {
                    "repo_url": "unknown",
                    "branch": "unknown",
                    "last_commit": "unknown",
                    "file_count": 0,
                    "error": str(e),
                }

        def _run_command(self, command, cwd=None, capture_output=False):
            """Run a command in the given directory"""
            try:
                logger.info(f"Running command: {' '.join(command)}")
                result = subprocess.run(
                    command,
                    cwd=cwd or str(self.repo_path),
                    check=True,
                    capture_output=capture_output,
                    text=False,
                )
                return result
            except subprocess.CalledProcessError as e:
                logger.warning(f"Command failed: {' '.join(command)}, Error: {str(e)}")
                if capture_output:
                    logger.warning(
                        f"Stdout: {e.stdout.decode() if e.stdout else 'None'}"
                    )
                    logger.warning(
                        f"Stderr: {e.stderr.decode() if e.stderr else 'None'}"
                    )
                raise

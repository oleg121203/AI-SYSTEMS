import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

from config import load_config

# Configure logging
logger = logging.getLogger("github_integration")


class GitHubIntegration:
    """Handles integration with GitHub for repository operations and workflow automation"""

    def __init__(self, token: Optional[str] = None, repo: Optional[str] = None):
        """
        Initialize GitHub integration.

        Args:
            token: GitHub token with repo and workflow permissions. If None, uses GITHUB_TOKEN env var.
            repo: GitHub repository in format "owner/repo". If None, uses config.
        """
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            logger.warning("No GitHub token provided. GitHub integration disabled.")

        config = load_config()
        self.repo = repo or config.get("github_repo")
        if not self.repo:
            logger.warning(
                "No GitHub repository specified. GitHub integration disabled."
            )

        self.api_base_url = "https://api.github.com"
        self.enabled = bool(self.token and self.repo)
        self.check_interval = config.get("github_actions_check_interval", 60)  # seconds
        self.session = None

    async def initialize(self):
        """Initialize aiohttp session and validate GitHub connection"""
        if not self.enabled:
            logger.info("GitHub integration is disabled. Skipping initialization.")
            return False

        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "AI-SYSTEMS GitHub Integration",
            }
        )

        # Test connection
        try:
            await self.get_repo_info()
            logger.info(f"GitHub integration initialized successfully for {self.repo}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize GitHub integration: {e}")
            return False

    async def close(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_repo_info(self) -> Dict[str, Any]:
        """Get information about the repository"""
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        url = f"{self.api_base_url}/repos/{self.repo}"

        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_msg = await response.text()
                    logger.error(
                        f"Failed to get repo info: {response.status} - {error_msg}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": error_msg,
                    }
        except Exception as e:
            logger.error(f"Exception in get_repo_info: {e}")
            return {"error": str(e)}

    async def create_or_update_file(
        self, path: str, content: str, message: str, branch: str = "main"
    ) -> Dict[str, Any]:
        """
        Create or update a file in the repository

        Args:
            path: File path in the repository
            content: File content
            message: Commit message
            branch: Branch name

        Returns:
            Dict with API response or error information
        """
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        url = f"{self.api_base_url}/repos/{self.repo}/contents/{path}"

        # First check if file already exists
        sha = None
        try:
            async with self.session.get(f"{url}?ref={branch}") as response:
                if response.status == 200:
                    file_info = await response.json()
                    sha = file_info.get("sha")
        except Exception:
            # File probably doesn't exist, which is fine
            pass

        # Prepare request payload
        import base64

        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {"message": message, "content": encoded_content, "branch": branch}

        if sha:
            payload["sha"] = sha

        try:
            async with self.session.put(url, json=payload) as response:
                response_json = await response.json()
                if response.status in (200, 201):
                    logger.info(
                        f"Successfully {'updated' if sha else 'created'} file {path}"
                    )
                    return response_json
                else:
                    logger.error(
                        f"Failed to {'update' if sha else 'create'} file: {response.status} - {response_json}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": response_json,
                    }
        except Exception as e:
            logger.error(f"Exception in create_or_update_file: {e}")
            return {"error": str(e)}

    async def trigger_workflow(
        self,
        workflow_file: str,
        ref: str = "main",
        inputs: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Trigger a GitHub Actions workflow

        Args:
            workflow_file: The workflow file name (e.g., "ci.yml")
            ref: The git reference (branch, tag, commit)
            inputs: Optional workflow inputs

        Returns:
            Dict with API response or error information
        """
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        url = f"{self.api_base_url}/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches"

        payload = {"ref": ref}

        if inputs:
            payload["inputs"] = inputs

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status == 204:  # No content is the success response
                    logger.info(f"Successfully triggered workflow {workflow_file}")
                    run_id = await self._get_latest_workflow_run(workflow_file)
                    return {
                        "success": True,
                        "workflow": workflow_file,
                        "run_id": run_id,
                    }
                else:
                    error_msg = await response.text()
                    logger.error(
                        f"Failed to trigger workflow: {response.status} - {error_msg}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": error_msg,
                    }
        except Exception as e:
            logger.error(f"Exception in trigger_workflow: {e}")
            return {"error": str(e)}

    async def _get_latest_workflow_run(self, workflow_file: str) -> Optional[int]:
        """Get the ID of the latest workflow run for a specific workflow file"""
        if not self.enabled or not self.session:
            return None

        url = f"{self.api_base_url}/repos/{self.repo}/actions/workflows/{workflow_file}/runs"

        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data["workflow_runs"]:
                        return data["workflow_runs"][0]["id"]
                return None
        except Exception:
            return None

    async def get_workflow_run_status(self, run_id: int) -> Dict[str, Any]:
        """
        Get the status of a specific workflow run

        Args:
            run_id: The workflow run ID

        Returns:
            Dict with workflow run status information
        """
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        url = f"{self.api_base_url}/repos/{self.repo}/actions/runs/{run_id}"

        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_msg = await response.text()
                    logger.error(
                        f"Failed to get workflow run status: {response.status} - {error_msg}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": error_msg,
                    }
        except Exception as e:
            logger.error(f"Exception in get_workflow_run_status: {e}")
            return {"error": str(e)}

    async def wait_for_workflow_completion(
        self, run_id: int, timeout: int = 600
    ) -> Dict[str, Any]:
        """
        Wait for a workflow run to complete

        Args:
            run_id: The workflow run ID
            timeout: Maximum time to wait in seconds

        Returns:
            Dict with final workflow run status
        """
        start_time = time.time()
        logger.info(
            f"Waiting for workflow run {run_id} to complete (timeout: {timeout}s)"
        )

        while time.time() - start_time < timeout:
            status = await self.get_workflow_run_status(run_id)

            if "error" in status:
                logger.error(f"Error getting workflow status: {status['error']}")
                return status

            if status.get("status") == "completed":
                logger.info(
                    f"Workflow run {run_id} completed with conclusion: {status.get('conclusion')}"
                )
                return status

            # Wait before checking again
            logger.debug(
                f"Workflow run {run_id} is still in progress (status: {status.get('status')})"
            )
            await asyncio.sleep(self.check_interval)

        logger.warning(f"Timeout waiting for workflow run {run_id}")
        return {"error": "Timeout", "run_id": run_id}

    async def get_workflow_logs(self, run_id: int) -> Dict[str, Any]:
        """
        Get logs for a workflow run

        Args:
            run_id: The workflow run ID

        Returns:
            Dict with workflow logs or error information
        """
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        # First get the job IDs for this run
        jobs_url = f"{self.api_base_url}/repos/{self.repo}/actions/runs/{run_id}/jobs"

        try:
            async with self.session.get(jobs_url) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    logger.error(
                        f"Failed to get workflow jobs: {response.status} - {error_msg}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": error_msg,
                    }

                jobs_data = await response.json()

            # Get logs for each job
            logs = {}
            for job in jobs_data.get("jobs", []):
                job_id = job.get("id")
                job_name = job.get("name")

                if not job_id:
                    continue

                logs_url = (
                    f"{self.api_base_url}/repos/{self.repo}/actions/jobs/{job_id}/logs"
                )

                async with self.session.get(logs_url) as logs_response:
                    if logs_response.status == 200:
                        logs[job_name] = await logs_response.text()
                    else:
                        logs[job_name] = f"Error fetching logs: {logs_response.status}"

            return {"logs": logs}
        except Exception as e:
            logger.error(f"Exception in get_workflow_logs: {e}")
            return {"error": str(e)}

    async def create_pull_request(
        self, title: str, body: str, head: str, base: str = "main"
    ) -> Dict[str, Any]:
        """
        Create a pull request

        Args:
            title: PR title
            body: PR description
            head: Source branch
            base: Target branch

        Returns:
            Dict with API response or error information
        """
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        url = f"{self.api_base_url}/repos/{self.repo}/pulls"

        payload = {"title": title, "body": body, "head": head, "base": base}

        try:
            async with self.session.post(url, json=payload) as response:
                response_json = await response.json()
                if response.status == 201:
                    logger.info(f"Successfully created PR: {title}")
                    return response_json
                else:
                    logger.error(
                        f"Failed to create PR: {response.status} - {response_json}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": response_json,
                    }
        except Exception as e:
            logger.error(f"Exception in create_pull_request: {e}")
            return {"error": str(e)}

    async def create_ci_workflow(self) -> Dict[str, Any]:
        """
        Create a basic CI workflow for the project based on detected languages

        Returns:
            Dict with result of operation
        """
        if not self.enabled or not self.session:
            return {"error": "GitHub integration not enabled or initialized"}

        # First check languages in the repo
        url = f"{self.api_base_url}/repos/{self.repo}/languages"

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    logger.error(
                        f"Failed to get repo languages: {response.status} - {error_msg}"
                    )
                    return {
                        "error": f"API error: {response.status}",
                        "details": error_msg,
                    }

                languages = await response.json()

            # Generate appropriate workflow based on detected languages
            if "Python" in languages:
                return await self._create_python_workflow()
            elif "JavaScript" in languages or "TypeScript" in languages:
                return await self._create_node_workflow()
            else:
                return await self._create_generic_workflow()

        except Exception as e:
            logger.error(f"Exception in create_ci_workflow: {e}")
            return {"error": str(e)}

    async def _create_python_workflow(self) -> Dict[str, Any]:
        """Create a Python CI workflow"""
        workflow = """name: Python CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.8, 3.9, '3.10']

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
        pip install pytest pytest-cov flake8
    - name: Lint with flake8
      run: |
        flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
    - name: Test with pytest
      run: |
        pytest --cov=./ --cov-report=xml
    - name: Upload coverage report
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
"""

        return await self.create_or_update_file(
            path=".github/workflows/python-ci.yml",
            content=workflow,
            message="Add Python CI workflow",
        )

    async def _create_node_workflow(self) -> Dict[str, Any]:
        """Create a Node.js CI workflow"""
        workflow = """name: Node.js CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [14.x, 16.x, 18.x]

    steps:
    - uses: actions/checkout@v3
    - name: Use Node.js ${{ matrix.node-version }}
      uses: actions/setup-node@v3
      with:
        node-version: ${{ matrix.node-version }}
        cache: 'npm'
    - name: Install dependencies
      run: npm ci || npm install
    - name: Run linting
      run: npm run lint --if-present
    - name: Run tests
      run: npm test --if-present
    - name: Build
      run: npm run build --if-present
"""

        return await self.create_or_update_file(
            path=".github/workflows/node-ci.yml",
            content=workflow,
            message="Add Node.js CI workflow",
        )

    async def _create_generic_workflow(self) -> Dict[str, Any]:
        """Create a generic CI workflow"""
        workflow = """name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    - name: Run basic tests
      run: |
        echo "Running tests..."
        if [ -f "./run_tests.sh" ]; then
          chmod +x ./run_tests.sh
          ./run_tests.sh
        elif [ -d "./tests" ]; then
          find ./tests -name "test_*.py" -exec python {} \;
        else
          echo "No tests found"
        fi
"""

        return await self.create_or_update_file(
            path=".github/workflows/ci.yml",
            content=workflow,
            message="Add basic CI workflow",
        )


# Helper function to create a GitHub integration instance
async def setup_github_integration() -> GitHubIntegration:
    """Initialize and return a GitHub integration instance"""
    github = GitHubIntegration()
    await github.initialize()
    return github


# Example usage
if __name__ == "__main__":

    async def main():
        github = await setup_github_integration()
        try:
            repo_info = await github.get_repo_info()
            print(json.dumps(repo_info, indent=2))

            # Create a CI workflow for the repository
            workflow_result = await github.create_ci_workflow()
            print(json.dumps(workflow_result, indent=2))
        finally:
            await github.close()

    # Run the async main function
    asyncio.run(main())

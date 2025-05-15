import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class GitHubIntegration:
    def __init__(self):
        self.git_user_name = os.getenv("GIT_USER_NAME", "Oleg Kizyma")
        self.git_user_email = os.getenv("GIT_USER_EMAIL", "oleg1203@gmail.com")
        self.github_token = os.getenv("GITHUB_TOKEN", "")
        self.github_repo = os.getenv("GITHUB_REPO", "oleg121203/AI-SYSTEMS-REPO")
        self.repo_url = f"https://github.com/{self.github_repo}.git"
        self.main_branch = os.getenv("MAIN_BRANCH", "master")
        repo_path_env = os.getenv("REPOSITORY_PATH", "~/workspace/AI-SYSTEMS-REPO")
        self.repo_path = Path(os.path.expanduser(repo_path_env))

        # Ensure repo directory exists
        self.repo_path.mkdir(parents=True, exist_ok=True)

        # Initialize repository if not already initialized
        self._init_repo()

    def _init_repo(self) -> None:
        """Initialize the git repository if it doesn't exist."""
        try:
            if not (self.repo_path / ".git").exists():
                self._run_git_command(["init"])
                logger.info(f"Initialized git repository at {self.repo_path}")

            # Configure git
            self._run_git_command(["config", "user.name", self.git_user_name])
            self._run_git_command(["config", "user.email", self.git_user_email])

            # Check if remote origin exists
            result = self._run_git_command(["remote", "-v"], capture_output=True)
            if "origin" not in result.stdout.decode():
                self._run_git_command(["remote", "add", "origin", self.repo_url])
                logger.info(f"Added remote origin: {self.repo_url}")

        except Exception as e:
            logger.error(f"Error initializing repository: {str(e)}")
            raise

    def _run_git_command(
        self, args: List[str], capture_output: bool = False
    ) -> Optional[subprocess.CompletedProcess]:
        """Run a git command in the repository directory."""
        try:
            cmd = ["git"] + args
            logger.info(f"Running git command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd, cwd=self.repo_path, check=True, capture_output=capture_output
            )
            return result if capture_output else None
        except subprocess.CalledProcessError as e:
            logger.error(f"Git command failed: {' '.join(['git'] + args)}")
            logger.error(f"Error: {str(e)}")
            if capture_output:
                logger.error(f"Stdout: {e.stdout.decode() if e.stdout else 'None'}")
                logger.error(f"Stderr: {e.stderr.decode() if e.stderr else 'None'}")
            raise

    def commit_code(self, files: Dict[str, str], commit_message: str) -> Dict[str, Any]:
        """
        Commit generated code to the repository.

        Args:
            files: Dictionary mapping file paths (relative to repo root) to file content
            commit_message: Commit message

        Returns:
            Dict with status and details of the operation
        """
        try:
            # Pull latest changes
            try:
                self._run_git_command(["pull", "origin", self.main_branch])
            except Exception as e:
                logger.warning(f"Failed to pull from origin: {str(e)}")

            # Write files
            for file_path, content in files.items():
                full_path = self.repo_path / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)

                with open(full_path, "w") as f:
                    f.write(content)

                # Add file to git
                self._run_git_command(["add", str(file_path)])

            # Check if there are changes to commit
            status_output = self._run_git_command(
                ["status", "--porcelain"], capture_output=True
            )
            if status_output.stdout.strip():
                # Commit changes
                try:
                    self._run_git_command(["commit", "-m", commit_message])

                    # Push changes
                    if self.github_token:
                        # Use token for authentication if available
                        token_url = self.repo_url.replace(
                            "https://", f"https://x-access-token:{self.github_token}@"
                        )
                        self._run_git_command(["push", token_url, self.main_branch])
                    else:
                        self._run_git_command(["push", "origin", self.main_branch])
                except Exception as e:
                    logger.warning(f"Error during commit/push: {str(e)}")
                    # Continue execution even if commit fails
            else:
                logger.info("No changes to commit")
                # Return success even if there are no changes to commit

            return {
                "status": "success",
                "message": f"Successfully committed and pushed {len(files)} files",
                "files": list(files.keys()),
            }

        except Exception as e:
            logger.error(f"Error in commit_code: {str(e)}")
            return {"status": "error", "message": str(e)}

    def setup_repository(self, repo_name: str = None) -> Dict[str, Any]:
        """Set up the GitHub repository for the project
        
        Args:
            repo_name: Name of the repository in the format 'owner/repo'
            
        Returns:
            Dict with success status and message
        """
        if not repo_name:
            repo_name = self.github_repo
            
        try:
            logger.info(f"Setting up GitHub repository: {repo_name}")
            
            # Configure git user
            self._run_git_command(["config", "user.name", self.git_user_name])
            self._run_git_command(["config", "user.email", self.git_user_email])
            
            # Check if the repo already exists locally
            if (self.repo_path / ".git").exists():
                logger.info("Git repository already initialized")
                
                # Check if the remote exists
                result = self._run_git_command(["remote", "-v"], capture_output=True)
                if "origin" in result.stdout.decode():
                    logger.info("Remote 'origin' already exists")
                    # Update the remote URL if needed
                    self._run_git_command(["remote", "set-url", "origin", f"https://github.com/{repo_name}.git"])
                else:
                    # Add the remote
                    self._run_git_command(["remote", "add", "origin", f"https://github.com/{repo_name}.git"])
            else:
                # Initialize git repository
                self._run_git_command(["init"])
                
                # Add the remote
                self._run_git_command(["remote", "add", "origin", f"https://github.com/{repo_name}.git"])
            
            # Create a .gitignore file if it doesn't exist
            gitignore_path = self.repo_path / ".gitignore"
            if not gitignore_path.exists():
                with open(gitignore_path, "w") as f:
                    f.write("""
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Environment variables
.env

# Logs
logs/*.log

# Node.js
node_modules/

# System files
.DS_Store
.idea/
.vscode/
""")
                
                # Add .gitignore to git
                self._run_git_command(["add", ".gitignore"])
                self._run_git_command(["commit", "-m", "Add .gitignore file"])
            
            # Success
            return {"success": True, "message": "GitHub repository setup successfully"}
        except Exception as e:
            logger.error(f"Error setting up GitHub repository: {e}")
            return {"success": False, "message": str(e)}

    def get_repo_status(self) -> Dict[str, Any]:
        """Get the status of the repository."""
        try:
            # Check if repo exists and has remote
            has_remote = False
            try:
                result = self._run_git_command(["remote", "-v"], capture_output=True)
                has_remote = "origin" in result.stdout.decode()
            except Exception:
                pass

            # Get current branch
            branch = "unknown"
            try:
                result = self._run_git_command(
                    ["branch", "--show-current"], capture_output=True
                )
                branch = result.stdout.decode().strip()
            except Exception:
                pass

            # Get last commit
            last_commit = "None"
            try:
                result = self._run_git_command(
                    ["log", "-1", "--pretty=format:%h - %s"], capture_output=True
                )
                last_commit = result.stdout.decode().strip()
            except Exception:
                pass

            return {
                "status": "success",
                "repository": str(self.repo_path),
                "remote_url": self.repo_url,
                "has_remote": has_remote,
                "current_branch": branch,
                "last_commit": last_commit,
            }

        except Exception as e:
            logger.error(f"Error in get_repo_status: {str(e)}")
            return {"status": "error", "message": str(e)}


# Singleton instance
github_integration = GitHubIntegration()

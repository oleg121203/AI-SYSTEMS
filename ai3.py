import asyncio
import importlib
import json
import logging # Keep standard logging import
import os
import re
import subprocess
import time
from datetime import datetime # Ensure datetime is imported
from pathlib import Path
import shutil
import aiofiles # Add missing import
from typing import Dict, Optional # Import Optional for type hint

import aiohttp
from git import GitCommandError, Repo

from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import (
    apply_request_delay,
    setup_service_logger, # Import the setup function
    wait_for_service,
)

# Constants
DEFAULT_MCP_API_URL = "http://localhost:7860"
DEFAULT_REPO_DIR = "repo"
GITIGNORE_FILENAME = ".gitignore"
GITKEEP_FILENAME = ".gitkeep"
REPO_PREFIX = "repo/"

# Setup logger for AI3 using the utility function
logger = setup_service_logger("ai3")

config = load_config()
MCP_API_URL = config.get("mcp_api", DEFAULT_MCP_API_URL)
REPO_DIR = config.get("repo_dir", DEFAULT_REPO_DIR)


def _init_or_open_repo(repo_path: str) -> Repo:
    try:
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        repo = Repo(repo_path)
        logger.info(f"[AI3-Git] Opened existing repository at: {repo_path}")
        return repo
    except Exception:
        try:
            repo = Repo.init(repo_path)
            logger.info(f"[AI3-Git] Initialized new repository at: {repo_path}")
            gitignore_path = os.path.join(repo_path, GITIGNORE_FILENAME) # Use constant
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w") as f:
                    f.write("# Ignore OS-specific files\n.DS_Store\n")
                    f.write("# Ignore virtual environment files\nvenv/\n.venv/\n")
                    f.write("# Ignore IDE files\n.idea/\n.vscode/\n")
                    f.write("# Ignore log files\nlogs/\n*.log\n")
                try:
                    repo.index.add([GITIGNORE_FILENAME]) # Use constant
                    repo.index.commit("Add .gitignore")
                    logger.info("[AI3-Git] Added .gitignore and committed.")
                except GitCommandError as git_e:
                    logger.warning(
                        f"[AI3-Git] Warning: Failed to commit .gitignore: {git_e}"
                    )
            return repo
        except Exception as init_e:
            logger.critical(
                f"[AI3-Git] CRITICAL: Failed to initialize or open repository at {repo_path}: {init_e}"
            )
            raise


def _commit_changes(repo: Repo, file_paths: list, message: str):
    if not file_paths:
        return
    try:
        valid_paths = [
            os.path.relpath(p, repo.working_dir)
            for p in file_paths
            if os.path.exists(p)
        ]
        paths_to_add = [
            p
            for p in valid_paths
            if p in repo.untracked_files
            or p in [item.a_path for item in repo.index.diff(None)]
        ]

        if not paths_to_add and not repo.is_dirty(
            untracked_files=True, path=valid_paths
        ):
            logger.info(f"[AI3-Git] No changes detected in {valid_paths} to commit.")
            return

        if paths_to_add:
            repo.index.add(paths_to_add)

        if repo.is_dirty():
            repo.index.commit(message)
            logger.info(
                f"[AI3-Git] Committed changes for {len(paths_to_add)} file(s): {message}"
            )
        else:
            logger.info(f"[AI3-Git] No staged changes to commit for message: {message}")

    except GitCommandError as e:
        logger.error(
            f"[AI3-Git] Error committing changes: {message}. Files: {file_paths}. Error: {e}"
        )
    except Exception as e:
        logger.error(f"[AI3-Git] Unexpected error during commit: {e}")


async def generate_structure(target: str) -> Optional[Dict]: # Add target param, update return type
    # Load base prompt from configuration
    base_prompt_template = config.get("ai3_prompt", "Generate a JSON structure for a project with the target: \"{target}\".")
    base_prompt = base_prompt_template.format(target=target) # Format the target

    # System instructions added in code
    system_instructions = """
Respond ONLY with the JSON structure itself, enclosed in triple backticks (```json ... ```).
The structure should be a valid JSON object representing directories and files. Use null for files.
Use only Latin characters for all generated names (files, directories).
Example:
```json
{
  "src": {
    "main.py": null,
    "utils.py": null
  },
  "tests": {
    "test_main.py": null
  },
  "README.md": null,
  ".gitignore": null
}
```
Do not include any explanatory text before or after the JSON block. Ensure the JSON is well-formed.
"""
    # Combine base prompt and system instructions
    full_prompt = base_prompt + "\n" + system_instructions

    ai_config_base = config.get("ai_config", {})
    ai3_config = ai_config_base.get("ai3", {})
    if not ai3_config:
        logger.warning("[AI3] Warning: 'ai_config.ai3' section not found. Using defaults.")
        ai3_config = {"provider": "openai"}

    # Updated: Iterate over the list of providers from the configuration
    ai3_providers = ai3_config.get("providers", ["openai"])
    if not ai3_providers:
        logger.warning("[AI3] No providers configured. Defaulting to ['openai'].")
        ai3_providers = ["openai"]

    response_text = None
    for provider_name in ai3_providers:
        try:
            logger.info(f"[AI3] Attempting structure generation with provider: {provider_name}")
            provider: BaseProvider = ProviderFactory.create_provider(provider_name)
            try:
                await apply_request_delay("ai3")
                # Use the full prompt
                response_text = await provider.generate(
                    prompt=full_prompt, # Pass the combined prompt
                    model=ai3_config.get("model"),
                    max_tokens=ai3_config.get("max_tokens"),
                    temperature=ai3_config.get("temperature"),
                )
                if response_text:
                    logger.info(f"[AI3] Successfully generated structure with provider: {provider_name}")
                    break
            finally:
                if hasattr(provider, "close_session") and callable(provider.close_session):
                    await provider.close_session()
        except Exception as e:
            logger.error(f"[AI3] Error with provider '{provider_name}': {e}")

    if not response_text:
        logger.error("[AI3] All providers failed to generate a structure.")
        return None

    # Consider replacing with a more robust JSON extraction method if needed
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    json_structure_str = None
    if match:
        json_structure_str = match.group(1)
    else:
        # Try to find JSON directly if backticks are missing
        try:
            start_index = response_text.find('{')
            end_index = response_text.rfind('}')
            if start_index != -1 and end_index != -1 and start_index < end_index:
                potential_json = response_text[start_index:end_index+1]
                # Basic validation
                if potential_json.count('{') == potential_json.count('}'):
                    json_structure_str = potential_json
                    logger.warning("[AI3] Extracted JSON structure without backticks.")
                else:
                    raise ValueError("Mismatched braces")
            else:
                 raise ValueError("Could not find JSON object delimiters")
        except Exception as direct_extract_err:
            logger.error(
                f"[AI3] Failed to extract JSON structure from response (tried direct extraction after backtick failure: {direct_extract_err}). Response: {response_text[:500]}"
            )
            return None

    try:
        structure_obj = json.loads(json_structure_str)
        logger.info(f"[AI3] Successfully extracted structure: {json_structure_str[:200]}...")
        return structure_obj
    except json.JSONDecodeError as e:
        logger.error(f"[AI3] JSON decode error: {e}. JSON string: {json_structure_str[:200]}")
        return None
    except Exception as e:
        logger.error(f"[AI3] Unexpected error processing structure: {e}")
        return None


async def send_structure_to_api(structure_obj: dict):
    api_url = f"{MCP_API_URL}/structure"
    logger.info(f"[AI3 -> API] Sending structure object to {api_url}")
    async with aiohttp.ClientSession() as client_session:
        try:
            async with client_session.post(
                api_url, json={"structure": structure_obj}, timeout=30
            ) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info(
                        f"[AI3 -> API] Structure successfully sent. Response: {response_text}"
                    )
                    return True
                else:
                    logger.error(
                        f"[AI3 -> API] Error sending structure. Status: {resp.status}, Response: {response_text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"[AI3 -> API] Error sending structure: {str(e)}")
            return False


async def send_ai3_report(status: str, details: dict = None):
    api_url = f"{MCP_API_URL}/ai3_report"
    payload = {"status": status}
    if details:
        payload["details"] = details
    logger.info(f"[AI3 -> API] Sending report to {api_url}: {payload}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json=payload, timeout=15) as resp:
                response_text = await resp.text()
                logger.info(
                    f"[AI3 -> API] Report sent. Status: {resp.status}, Response: {response_text}"
                )
                return resp.status == 200
        except asyncio.TimeoutError:
            logger.warning(f"[AI3 -> API] Timeout sending report: {status}")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"[AI3 -> API] Connection error sending report: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"[AI3 -> API] Unexpected error sending report: {str(e)}")
            return False


async def initiate_collaboration(error: str, context: str):
    api_url = f"{MCP_API_URL}/ai_collaboration"
    collaboration_request = {"error": error, "context": context, "ai": "AI3"}
    logger.info(
        f"[AI3 -> API] Initiating collaboration via {api_url}: {collaboration_request}"
    )
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                api_url, json=collaboration_request, timeout=20
            ) as resp:
                response_text = await resp.text()
                logger.info(
                    f"[AI3 -> API] Collaboration request sent. Status: {resp.status}, Response: {response_text}"
                )
                return resp.status == 200
        except asyncio.TimeoutError:
            logger.warning("[AI3 -> API] Timeout initiating collaboration.") # Remove f-string
            return False
        except aiohttp.ClientError as e:
            logger.error(
                f"[AI3 -> API] Connection error initiating collaboration: {str(e)}"
            )
            return False
        except Exception as e:
            logger.error(
                f"[AI3 -> API] Unexpected error initiating collaboration: {str(e)}"
            )
            return False


async def create_files_from_structure(structure_obj: dict, repo: Repo):
    base_path = repo.working_dir
    created_files = []
    created_dirs = []

    async def _create_recursive(struct: dict, current_rel_path: str):
        for key, value in struct.items():
            sanitized_key = re.sub(r'[<>:"/\\|?*]', "_", key).strip()
            if not sanitized_key:
                logger.warning(
                    f"[AI3] Warning: Skipping empty or invalid name derived from '{key}'"
                )
                continue

            new_rel_path = os.path.join(current_rel_path, sanitized_key)
            full_path = os.path.join(base_path, new_rel_path)

            try:
                if isinstance(value, dict):
                    if not os.path.exists(full_path):
                        os.makedirs(full_path)
                        logger.info(f"[AI3] Created directory: {new_rel_path}")
                        created_dirs.append(full_path)
                        if not value:
                            gitkeep_path = os.path.join(full_path, GITKEEP_FILENAME) # Use constant
                            with open(gitkeep_path, "w") as f:
                                f.write("")
                            logger.info(
                                f"[AI3] Created .gitkeep in empty directory: {new_rel_path}"
                            )
                    await _create_recursive(value, new_rel_path)
                elif value is None or isinstance(value, str):
                    parent_dir = os.path.dirname(full_path)
                    if not os.path.exists(parent_dir):
                        os.makedirs(parent_dir)
                        logger.info(
                            f"[AI3] Created parent directory: {os.path.relpath(parent_dir, base_path)}"
                        )

                    if not os.path.exists(full_path):
                        initial_content = (
                            value
                            if isinstance(value, str)
                            else "# Initial empty file created by AI3\n"
                        )
                        with open(full_path, "w", encoding="utf-8") as f:
                            f.write(initial_content)
                        logger.info(f"[AI3] Created file: {new_rel_path}")
                        created_files.append(full_path)
                    else:
                        logger.info(
                            f"[AI3] File already exists, skipping creation: {new_rel_path}"
                        )
                else:
                    logger.warning(
                        f"[AI3] Warning: Unknown type in structure for key '{key}', skipping: {type(value)}"
                    )

            except OSError as e:
                logger.error(f"[AI3] Error creating file/directory {new_rel_path}: {e}")
            except Exception as e:
                logger.error(f"[AI3] Unexpected error processing {new_rel_path}: {e}")

    try:
        logger.info("[AI3] Starting file creation from structure...")
        await _create_recursive(structure_obj, "")
        files_to_commit = created_files + [
            os.path.join(d, GITKEEP_FILENAME) # Use constant
            for d in created_dirs
            if os.path.exists(os.path.join(d, GITKEEP_FILENAME)) # Use constant
        ]
        _commit_changes(
            repo, files_to_commit, "Created initial project structure from AI"
        )
        logger.info("[AI3] File creation process completed.")
        await send_ai3_report("structure_creation_completed")
        return True
    except Exception as e:
        logger.error(f"[AI3] Error in create_files_from_structure: {e}")
        await initiate_collaboration(str(e), "Failed to create files from structure")
        await send_ai3_report("structure_creation_failed", {"error": str(e)})
        return False


# Remove simple_log_monitor as its functionality is covered by monitor_system_errors and logging setup
# async def simple_log_monitor():
#     ...


# ...existing code...

class AI3:
    def __init__(self, config):
        self.config = config
        self.repo_dir = config.get("repo_dir", DEFAULT_REPO_DIR) # Use constant
        self.repo = self._init_or_open_repo(self.repo_dir)
        self.session = None
        self.target = config.get("target")
        self.monitoring_stats = {
            "idle_workers_detected": 0,
            "task_requests_sent": 0,
            "successful_requests": 0,
            "error_fixes_requested": 0,
        }
        self.last_check_time = time.time()

    def _init_or_open_repo(self, repo_path: str) -> Repo:
        """Initializes a new or opens an existing Git repository."""
        try:
            logger.info(f"[AI3-Git] Attempting to open repository at: {repo_path}")
            Path(repo_path).mkdir(parents=True, exist_ok=True)
            repo = Repo(repo_path)
            logger.info(f"[AI3-Git] Opened existing repository at: {repo_path}")
            return repo
        except Exception:
            try:
                logger.info(f"[AI3-Git] Repository not found, initializing new one at: {repo_path}")
                repo = Repo.init(repo_path)
                logger.info(f"[AI3-Git] Initialized new repository at: {repo_path}")
                gitignore_path = os.path.join(repo_path, GITIGNORE_FILENAME) # Use constant
                if not os.path.exists(gitignore_path):
                    with open(gitignore_path, "w") as f:
                        f.write("# Ignore OS-specific files\n.DS_Store\n")
                        f.write("# Ignore virtual environment files\nvenv/\n.venv/\n")
                        f.write("# Ignore IDE files\n.idea/\n.vscode/\n")
                        f.write("# Ignore log files\nlogs/\n*.log\n")
                    try:
                        repo.index.add([GITIGNORE_FILENAME]) # Use constant
                        repo.index.commit("Add .gitignore")
                        logger.info("[AI3-Git] Added .gitignore and committed.")
                    except GitCommandError as git_e:
                        logger.warning(
                            f"[AI3-Git] Warning: Failed to commit .gitignore: {git_e}"
                        )
                return repo
            except Exception as init_e:
                logger.critical(
                    f"[AI3-Git] CRITICAL: Failed to initialize or open repository at {repo_path}: {init_e}"
                )
                raise

    async def clear_and_init_repo(self):
        """Clears the existing repository and initializes a new one."""
        try:
            # Check if the repository exists
            if os.path.exists(self.repo_dir):
                # Remove the repository
                logger.info(f"[AI3-Git] Removing existing repository directory: {self.repo_dir}")
                shutil.rmtree(self.repo_dir)
                logger.info(f"[AI3-Git] Removed existing repository: {self.repo_dir}")

            # Create the repository directory and initialize Git
            logger.info(f"[AI3-Git] Creating new repository directory: {self.repo_dir}")
            os.makedirs(self.repo_dir, exist_ok=True)
            
            # Option 1: Use GitPython (recommended)
            try:
                self.repo = Repo.init(self.repo_dir)
                logger.info(f"[AI3-Git] Successfully initialized new repository at: {self.repo_dir}")
                
                # Add .gitignore
                gitignore_path = os.path.join(self.repo_dir, GITIGNORE_FILENAME) # Use constant
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write("**/__pycache__\n")
                    f.write("*.pyc\n")
                    f.write(".DS_Store\n")
                logger.info(f"[AI3-Git] Created .gitignore in {self.repo_dir}")
                
                # Configure Git user
                with self.repo.config_writer() as git_config:
                    git_config.set_value('user', 'email', 'ai3@example.com')
                    git_config.set_value('user', 'name', 'AI3 System')
                
                # Add and commit gitignore
                self.repo.git.add(gitignore_path)
                self.repo.git.commit('-m', 'Initial commit (gitignore)')
                logger.info("[AI3-Git] Added and committed .gitignore file")
                
            except Exception as git_err:
                logger.error(f"[AI3-Git] Error using GitPython: {git_err}")
                logger.info("[AI3-Git] Falling back to subprocess method")
                
                # Option 2: Use subprocess as a fallback
                init_result = subprocess.run(
                    ["git", "init"],
                    cwd=self.repo_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info(f"[AI3-Git] Initialized Git repository via subprocess: {init_result.stdout}")
                
                # Create .gitignore
                gitignore_path = os.path.join(self.repo_dir, GITIGNORE_FILENAME) # Use constant
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write("**/__pycache__\n")
                    f.write("*.pyc\n")
                    f.write(".DS_Store\n")
                
                # Configure Git user
                subprocess.run(["git", "config", "user.email", "ai3@example.com"], cwd=self.repo_dir, check=False)
                subprocess.run(["git", "config", "user.name", "AI3 System"], cwd=self.repo_dir, check=False)
                
                # Add and commit
                subprocess.run(["git", "add", GITIGNORE_FILENAME], cwd=self.repo_dir, check=True) # Use constant
                subprocess.run(["git", "commit", "-m", "Initial commit (gitignore)"], cwd=self.repo_dir, check=True)
                
                # Reassign the repo object for further use
                self.repo = Repo(self.repo_dir)
            
            logger.info("[AI3-Git] Repository successfully cleared and initialized.")
            await send_ai3_report("repo_cleared")
            return True

        except Exception as e:
            logger.error(f"[AI3-Git] Unexpected error clearing and initializing repository: {e}")
            await send_ai3_report("repo_clear_failed", {"error": str(e)})
            return False

    async def create_session(self):
        """Creates an aiohttp ClientSession if it does not already exist."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            logger.info("[AI3] Created new aiohttp ClientSession.")

    async def close_session(self):
        """Closes the aiohttp ClientSession if it exists."""
        if self.session and not self.session.closed: # Fix: 'и' -> 'and'
            await self.session.close()
            self.session = None
            logger.info("[AI3] Closed aiohttp ClientSession.")

    async def setup_structure(self):
        try:
            # Wait for MCP API to be available
            await wait_for_service(MCP_API_URL, timeout=60)
            
            # Initialize repository
            success = await self.clear_and_init_repo()
            if not success:
                logger.error("[AI3] Failed to initialize repository. Aborting structure setup.")
                return False
                
            # Generate structure (pass target)
            structure = await generate_structure(self.target) # Pass self.target
            if not structure:
                logger.error("[AI3] Failed to generate structure. Aborting structure setup.")
                return False
                
            # Send structure to MCP API
            await self.create_session()
            try:
                # Include target in the payload if MCP API expects it
                payload = {"structure": structure}
                if self.target: # Check if target exists before adding
                    payload["target"] = self.target
                
                async with self.session.post(
                    f"{MCP_API_URL}/structure",
                    json=payload, # Use the constructed payload
                ) as resp:
                    if resp.status == 200:
                        logger.info("[AI3] Structure sent to MCP API successfully")
                        structure_response = await resp.json()
                        logger.info(f"[AI3] MCP API response: {structure_response}")
                        # Create the structure in the repository
                        await self.create_file_structure(structure)
                        return True
                    else:
                        error_text = await resp.text()
                        logger.error(f"[AI3] Error sending structure to MCP API: {error_text}")
                        return False
            except Exception as e:
                logger.error(f"[AI3] Exception during structure API call: {e}")
                return False
        except Exception as e:
            logger.error(f"[AI3] Unexpected error in setup_structure: {e}")
            return False

    async def create_file_structure(self, structure, parent_path=""):
        try:
            repo_path = Path(self.repo_dir)
            created_files = []
            
            for name, content in structure.items():
                full_path = os.path.join(parent_path, name)
                abs_path = os.path.join(repo_path, full_path)
                
                if content is None:  # It's a file
                    # Create an empty file
                    Path(abs_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(abs_path).touch()
                    created_files.append(abs_path)
                    logger.info(f"[AI3] Created empty file: {full_path}")
                else:  # It's a directory
                    Path(abs_path).mkdir(parents=True, exist_ok=True)
                    logger.info(f"[AI3] Created directory: {full_path}")
                    # Recursively process the directory
                    child_files = await self.create_file_structure(content, full_path)
                    created_files.extend(child_files)
            
            # Commit changes only after creating the full structure
            if created_files:
                _commit_changes(self.repo, created_files, "Initial project structure")
                
            return created_files
        except Exception as e:
            logger.error(f"[AI3] Error creating file structure: {e}")
            return []

    async def start_monitoring(self):
        logger.info("[AI3] Starting monitoring service...")
        try:
            while True:
                try:
                    await asyncio.sleep(30)  # Check every 30 seconds
                    await self.check_worker_status()
                    await self.scan_logs_for_errors()
                except asyncio.CancelledError:
                    logger.info("[AI3] Monitoring task cancelled")
                    break
                except Exception as e:
                    logger.error(f"[AI3] Error in monitoring cycle: {e}")
                    await asyncio.sleep(5)  # Short delay before retrying
        except Exception as e:
            logger.critical(f"[AI3] Monitoring service crashed: {e}")
        finally:
            logger.info("[AI3] Monitoring service stopped")

    async def check_worker_status(self):
        await self.create_session()
        try:
            async with self.session.get(f"{MCP_API_URL}/worker_status") as resp:
                if resp.status == 200:
                    status_data = await resp.json()
                    idle_workers = []
                    
                    for worker, status in status_data.items():
                        if status.get("status") == "idle" and status.get("queue_empty", False):
                            idle_workers.append(worker)
                    
                    if idle_workers:
                        self.monitoring_stats["idle_workers_detected"] += len(idle_workers)
                        logger.info(f"[AI3] Detected idle workers: {', '.join(idle_workers)}")
                        
                        # Request tasks for idle workers
                        for worker in idle_workers:
                            await self.request_task_for_worker(worker)
                else:
                    logger.warning(f"[AI3] Failed to get worker status: {resp.status}")
        except Exception as e:
            logger.error(f"[AI3] Error checking worker status: {e}")

    async def request_task_for_worker(self, worker_name):
        self.monitoring_stats["task_requests_sent"] += 1
        await self.create_session()
        try:
            async with self.session.post(
                f"{MCP_API_URL}/request_task_for_idle_worker",
                json={"worker": worker_name},
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("success"):
                        self.monitoring_stats["successful_requests"] += 1
                        logger.info(f"[AI3] Successfully requested task for {worker_name}: {result}")
                    else:
                        logger.warning(f"[AI3] Failed to request task for {worker_name}: {result}")
                else:
                    logger.error(f"[AI3] Error response from API: {resp.status}")
        except Exception as e:
            logger.error(f"[AI3] Error requesting task for worker {worker_name}: {e}")

    async def scan_logs_for_errors(self):
        # Шукаємо помилки у файлах логів, спеціально фокусуючись на помилках пов'язаних з файлами в repo/
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return
            
        try:
            # Only scan logs that have been modified in the last check interval
            current_time = time.time()
            time_threshold = self.last_check_time
            self.last_check_time = current_time
            
            # Паттерни для ідентифікації реальних помилок, виключаючи системні повідомлення
            error_patterns = [
                r"Error in .*?repo/.*?:", # Помилки пов'язані з файлами в repo/
                r"Exception .* in .*?repo/", # Винятки що виникли під час роботи з файлами в repo/
                r"Failed to execute .* in .*?repo/", # Невдалі операції з файлами в repo/
                r"CRITICAL: .* repo/", # Критичні помилки пов'язані з репозиторієм
            ]
            
            # Шаблони для виключення - це повідомлення не є помилками
            exclude_patterns = [
                r"\[AI3\] Detected error", # Рекурсивні повідомлення про виявлення помилок
                r"\[AI3\] Error requesting error fix task", # Повідомлення про власні помилки AI3
                r"Active tasks list", # Список активних завдань
                r"Successfully", # Успішні операції
                r"Updating status", # Оновлення статусу
            ]
            
            compiled_error_patterns = [re.compile(pattern) for pattern in error_patterns]
            compiled_exclude_patterns = [re.compile(pattern) for pattern in exclude_patterns]
            
            errors_found = False
            error_summary = []
            
            for log_file in logs_dir.glob("*.log"):
                if log_file.stat().st_mtime >= time_threshold:
                    with open(log_file, "r", errors="replace") as f:
                        lines = f.readlines()
                        # Only check the last 100 lines for efficiency
                        for line in lines[-100:]:
                            # Перевіряємо, чи відповідає лінія одному з шаблонів помилок
                            is_error = any(pattern.search(line) for pattern in compiled_error_patterns)
                            
                            # Перевіряємо, чи не відповідає лінія одному з шаблонів виключень
                            is_excluded = any(pattern.search(line) for pattern in compiled_exclude_patterns)
                            
                            # Якщо це справжня помилка (і не виключення), додаємо її до списку
                            if is_error and not is_excluded: # Fix: '&&' -> 'and'
                                error_summary.append(f"{log_file.name}: {line.strip()}")
                                errors_found = True
                                if len(error_summary) >= 5:  # Limit to 5 errors per check
                                    break
                    
                    if len(error_summary) >= 5:
                        break
            
            if errors_found:
                logger.info(f"[AI3] Found {len(error_summary)} real errors in repo files")
                await self.request_error_fix(error_summary)
        except Exception as e:
            logger.error(f"[AI3] Error scanning logs: {e}")

    async def request_error_fix(self, error_summary):
        self.monitoring_stats["error_fixes_requested"] += 1
        await self.create_session()
        try:
            error_report = "\n".join(error_summary[:5])  # Limit to first 5 errors
            async with self.session.post(
                f"{MCP_API_URL}/task",  # Змінюємо ендпоінт з /request_error_fix на /task
                json={
                    "role": "executor", 
                    "prompt": f"Fix errors detected in logs:\n```\n{error_report}\n```\nAnalyze these errors and provide the corrected code.",
                    "priority": 1  # Високий пріоритет для виправлення помилок
                },
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    logger.info(f"[AI3] Error fix task request response: {result}")
                else:
                    logger.error(f"[AI3] Error fix task request failed: {resp.status} - {await resp.text()}")
        except Exception as e:
            logger.error(f"[AI3] Error requesting error fix task: {e}")

    async def update_file_and_commit(self, file_path_relative: str, content: str):
        """Updates a file in the repository and commits the changes."""
        repo_dir = DEFAULT_REPO_DIR # Use constant
        full_path = os.path.join(repo_dir, file_path_relative)

        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Write the file content
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Updated file: {full_path}")

            # Add the file to the Git index
            add_result = subprocess.run(
                ["git", "add", full_path],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if add_result.returncode != 0:
                logger.error(f"Error 'git add' for {full_path}: {add_result.stderr}")
                return  # Do not proceed if add failed

            logger.info(f"Added to Git index: {full_path}")

            # Commit the changes
            commit_message = f"AI3: Updated {file_path_relative}"
            # Use globally configured Git user (from new_repo.sh)
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if commit_result.returncode != 0:
                # Commit may fail if there are no changes (this is normal)
                if (
                    "nothing to commit, working tree clean" not in commit_result.stdout
                    and "no changes added to commit" not in commit_result.stderr
                ):
                    logger.error(
                        f"Error 'git commit' for {file_path_relative}: {commit_result.stderr}"
                    )
                else:
                    logger.info(f"No changes to commit in file: {file_path_relative}")

            else:
                logger.info(f"Committed file: {file_path_relative}")

        except FileNotFoundError:
            logger.error( # Remove f-string
                "Error: 'git' command not found. Ensure Git is installed and available in PATH."
            )
        except Exception as e:
            logger.error(
                f"Failed to update or commit file {file_path_relative}: {e}"
            )

    async def handle_ai2_output(self, data):
        # ... logic to extract file_path and content ...
        file_path = data.get("filename")  # Or another field containing the path
        content = data.get("code")  # Or another field containing the content

        if file_path and content is not None: # Fix: 'і' -> 'and'
            # Ensure file_path is a relative path inside 'repo/'
            if file_path.startswith(os.path.abspath(DEFAULT_REPO_DIR)): # Use constant
                file_path = os.path.relpath(file_path, DEFAULT_REPO_DIR) # Use constant

            await self.update_file_and_commit(file_path, content)
        else:
            logger.warning(
                f"Failed to extract file path or content from AI2 report: {data}"
            )

    async def monitor_github_actions(self):
        """Monitors GitHub Actions results and sends recommendations based on analysis.
        This function continuously checks the status of GitHub Actions via the GitHub API
        and processes the test results.
        """
        logger.info("[AI3] Starting GitHub Actions monitoring...")
        
        # GitHub API configuration
        github_token = os.getenv("GITHUB_TOKEN") # Read from env
        github_repo = os.getenv("GITHUB_REPO_TO_MONITOR") # Read from env
        
        if not github_token or not github_repo:
            logger.warning("[AI3] Warning: GITHUB_TOKEN or GITHUB_REPO_TO_MONITOR not configured in .env. Cannot monitor GitHub Actions.")
            return
        
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Main monitoring loop
        while True:
            try:
                await self.create_session()
                # Get the latest workflow runs
                async with self.session.get(
                    f"https://api.github.com/repos/{github_repo}/actions/runs", # Use github_repo variable
                    headers=headers
                ) as response:
                    if response.status == 200:
                        runs_data = await response.json()
                        workflow_runs = runs_data.get("workflow_runs", [])
                        
                        # Process only the latest completed workflow run
                        for run in workflow_runs:
                            run_id = run.get("id")
                            run_status = run.get("status")
                            run_conclusion = run.get("conclusion")
                            
                            if run_status == "completed":
                                # Save information about the completed run if we haven't processed it yet
                                if self._is_new_completed_run(run_id):
                                    logger.info(f"[AI3] Found completed GitHub Actions run: {run_id}, conclusion: {run_conclusion}")
                                    await self._analyze_workflow_run(run_id, run_conclusion, headers)
                                break  # Process only the latest completed run
                    else:
                        logger.warning(f"[AI3] Failed to fetch GitHub Actions runs: Status {response.status}")
                    
            except Exception as e:
                logger.error(f"[AI3] Error in GitHub Actions monitoring: {e}")
            
            # Wait before the next check
            await asyncio.sleep(config.get("github_actions_check_interval", 60))

    async def _analyze_workflow_run(self, run_id, run_conclusion, headers):
        """Analyzes the results of the workflow run (pytest + linters) and sends recommendations."""
        github_repo = os.getenv("GITHUB_REPO_TO_MONITOR")
        if not github_repo:
            logger.warning("[AI3] Warning: GITHUB_REPO_TO_MONITOR not configured in .env. Cannot analyze workflow run.")
            return

        failed_files = set() # Use set to avoid duplicates
        linting_errors_found = False
        pytest_errors_found = False
        job_logs = ""

        try:
            await self.create_session()
            # 1. Get the job ID for 'build-and-test'
            job_id = None
            async with self.session.get(
                f"https://api.github.com/repos/{github_repo}/actions/runs/{run_id}/jobs",
                headers=headers
            ) as response:
                if response.status == 200:
                    jobs_data = await response.json()
                    for job in jobs_data.get("jobs", []):
                        if job.get("name") == "build-and-test": # Our job name
                            job_id = job.get("id")
                            # Check the overall job conclusion, if it's 'failure'
                            if job.get("conclusion") == "failure":
                                # Not necessarily pytest, could be dependency installation failure, etc.
                                # Marking it as potential pytest error for simplicity, but log parsing logic is more important
                                pytest_errors_found = True
                                logger.warning(f"[AI3] Job 'build-and-test' (ID: {job_id}) failed overall.")
                            break
                else:
                    logger.error(f"[AI3] Error fetching jobs for run {run_id}: {response.status}")
                    return # Cannot proceed without job ID

            if not job_id:
                logger.warning(f"[AI3] Could not find job 'build-and-test' for run {run_id}.")
                # Maybe the workflow hasn't started yet or the job name is different
                # Return to try again later
                return

            # 2. Get the full logs for the job
            async with self.session.get(
                f"https://api.github.com/repos/{github_repo}/actions/jobs/{job_id}/logs",
                headers=headers
            ) as log_response:
                if log_response.status == 200:
                    job_logs = await log_response.text()
                    logger.info(f"[AI3] Successfully fetched logs for job {job_id} (run {run_id}). Length: {len(job_logs)} chars.")
                else:
                    logger.error(f"[AI3] Error fetching logs for job {job_id}: {log_response.status}. Status: {run_conclusion}")
                    # If logs are unavailable but overall conclusion is 'failure', assume there are errors
                    if run_conclusion == "failure":
                         pytest_errors_found = True # Assume pytest/linting error

        except Exception as e:
            logger.error(f"[AI3] Error fetching job details or logs for run {run_id}: {e}")
            # If there was an error fetching details but overall conclusion is 'failure', assume there are errors
            if run_conclusion == "failure":
                 pytest_errors_found = True # Assume pytest/linting error

        # 3. Log parsing (if available)
        if job_logs:
            log_lines = job_logs.splitlines()

            # Patterns to find errors (can be improved)
            # Pytest: Look for FAILURES or errors section
            pytest_failure_pattern = re.compile(r"=+ FAILURES =+")
            pytest_error_pattern = re.compile(r"=+ ERRORS =+")
            pytest_file_pattern = re.compile(r"____ (test_.*\.py) ____") # Finds test file with error

            # HTMLHint: Look for lines starting with file path and containing 'error'
            htmlhint_error_pattern = re.compile(r"^(repo/project/.*\.html): line \d+, col \d+, (.*) \((.*)\)$", re.IGNORECASE)

            # Stylelint: Look for lines with file path, line/column numbers, and rule name
            # Fix: Corrected cyrillic 'д' to latin 'd' and removed unnecessary brackets around ✖️
            stylelint_error_pattern = re.compile(r"^(repo/project/.*\.css)\s+(\d+:\d+)\s+✖️\s+(.*)$")

            # ESLint: Look for lines with file path, line/column numbers, and 'Error'/'Warning'
            eslint_error_pattern = re.compile(r"^(repo/project/.*\.js)\s+line (\d+), col (\d+),\s+(Error|Warning)\s+-(.*)$")

            in_pytest_failures_section = False
            in_pytest_errors_section = False

            for line in log_lines:
                # Pytest parsing
                if pytest_failure_pattern.search(line):
                    pytest_errors_found = True
                    in_pytest_failures_section = True
                    logger.warning(f"[AI3] Pytest FAILURES section detected in logs for run {run_id}.")
                elif pytest_error_pattern.search(line):
                     pytest_errors_found = True
                     in_pytest_errors_section = True
                     logger.warning(f"[AI3] Pytest ERRORS section detected in logs for run {run_id}.")
                elif line.strip().startswith("===") and (in_pytest_failures_section or in_pytest_errors_section):
                    # End of pytest errors section
                    in_pytest_failures_section = False
                    in_pytest_errors_section = False
                elif in_pytest_failures_section or in_pytest_errors_section:
                    match = pytest_file_pattern.search(line)
                    if match:
                        # Add the test file itself where the error occurred
                        failed_files.add(f"tests/{match.group(1)}") # Assume tests are in tests/

                # HTMLHint parsing
                html_match = htmlhint_error_pattern.search(line)
                if html_match:
                    linting_errors_found = True
                    file_path = html_match.group(1).replace(REPO_PREFIX, "") # Use constant
                    failed_files.add(file_path)
                    logger.warning(f"[AI3] HTMLHint error found in {file_path}: {html_match.group(2)}")

                # Stylelint parsing
                style_match = stylelint_error_pattern.search(line)
                if style_match:
                    linting_errors_found = True
                    file_path = style_match.group(1).replace(REPO_PREFIX, "") # Use constant
                    failed_files.add(file_path)
                    logger.warning(f"[AI3] Stylelint error found in {file_path}: {style_match.group(4)}")

                # ESLint parsing
                eslint_match = eslint_error_pattern.search(line)
                if eslint_match:
                    linting_errors_found = True
                    file_path = eslint_match.group(1).replace(REPO_PREFIX, "") # Use constant
                    failed_files.add(file_path)
                    logger.warning(f"[AI3] ESLint {eslint_match.group(4)} found in {file_path}: {eslint_match.group(5)}")

        # 4. Determine recommendation and context
        # Recommendation 'rework' if there are pytest errors OR linting errors OR overall conclusion is 'failure'
        if pytest_errors_found or linting_errors_found or run_conclusion == "failure":
            recommendation = "rework"
            logger.warning(f"[AI3] Recommendation for run {run_id}: rework (Pytest errors: {pytest_errors_found}, Linting errors: {linting_errors_found}, Run conclusion: {run_conclusion})")
        else:
            recommendation = "accept"
            logger.info(f"[AI3] Recommendation for run {run_id}: accept")

        context = {}
        if recommendation == "rework":
            # Add unique file names to context
            context["failed_files"] = list(failed_files)
            context["run_url"] = f"https://github.com/{github_repo}/actions/runs/{run_id}"
            context["job_logs_excerpt"] = job_logs[:2000] + "..." if job_logs else "Logs not available." # Add log excerpt

        # 5. Send recommendation to MCP API
        await self._send_test_recommendation(recommendation, context)

    async def _send_test_recommendation(self, recommendation: str, context: dict):
        """Sends a test recommendation to the MCP API."""
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL) # Use constant
        try:
            await self.create_session()
            # Assuming TestRecommendation is a Pydantic model or similar
            # recommendation_data = TestRecommendation(recommendation=recommendation, context=context)
            # Sending raw dict for now
            recommendation_data = {"recommendation": recommendation, "context": context}
            async with self.session.post(f"{mcp_api_url}/test_recommendation", json=recommendation_data) as response:
                if response.status == 200:
                    logger.info(f"[AI3] Successfully sent test recommendation '{recommendation}' to MCP API.")
                else:
                    logger.error(f"[AI3] Error sending test recommendation to MCP API: {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"[AI3] Failed to send test recommendation to MCP API: {e}")

    async def monitor_idle_workers(self):
        """Monitors idle AI2 workers."""
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL) # Use constant
        check_interval = self.config.get("idle_worker_check_interval", 30)
        logger.info("[AI3] Starting idle worker monitoring.")
        while True:
            try:
                await self.create_session()
                async with self.session.get(f"{mcp_api_url}/worker_status") as response:
                    if response.status == 200:
                        worker_statuses = await response.json()
                        # logger.debug(f"[AI3] Worker statuses: {worker_statuses}")
                        for role, status in worker_statuses.items():
                            if status == "idle":
                                logger.info(f"[AI3] Worker '{role}' is idle. Requesting new task.")
                                await self._request_task_for_idle_worker(role, mcp_api_url)
                    else:
                        logger.warning(f"[AI3] Error checking worker status: {response.status}. Falling back to log analysis.")
                        # Fallback: Analyze MCP API logs for empty queue messages
                        await self._check_logs_for_idle_workers()

            except aiohttp.ClientConnectorError as e:
                 logger.error(f"[AI3] Connection error while checking worker status: {e}. Falling back to log analysis.")
                 await self._check_logs_for_idle_workers() # Fallback
            except Exception as e:
                logger.error(f"[AI3] Error monitoring idle workers: {e}")

            await asyncio.sleep(check_interval)

    async def _request_task_for_idle_worker(self, role: str, mcp_api_url: str):
        """Requests a new task for an idle worker."""
        try:
            await self.create_session()
            async with self.session.post(f"{mcp_api_url}/request_task_for_idle_worker", json={"role": role}) as response:
                if response.status == 200:
                    logger.info(f"[AI3] Successfully requested new task for idle worker '{role}'.")
                elif response.status == 404: # No tasks available
                     logger.debug(f"[AI3] No tasks available for idle worker '{role}'.")
                else:
                    logger.error(f"[AI3] Error requesting task for idle worker '{role}': {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"[AI3] Failed to request task for idle worker '{role}': {e}")

    async def _check_logs_for_idle_workers(self):
        """Fallback method: analyzes MCP API log for empty queue messages."""
        # log_file variable was unused, removed it.
        # log_file = self.config.get("mcp_log_file", "logs/mcp_api.log")
        try:
            # Read the last N lines of the log
            # Implementing log reading can be complex in async mode,
            # for simplicity, you can use synchronous reading or specialized libraries
            # Here is just an example of the logic
            # logger.debug("[AI3] Fallback: Checking MCP logs for idle workers.")
            # ... log analysis logic ...
            pass # Skipping implementation for now
        except Exception as e:
            logger.error(f"[AI3] Error checking logs for idle workers: {e}")


    async def monitor_system_errors(self):
        """Monitors system log files for errors related to files in repo/,
        and reports them to AI1.""" # Updated description
        log_files = self.config.get("error_log_files", ["logs/mcp_api.log", "logs/ai1.log", "logs/ai2.log", "logs/ai3.log"])
        check_interval = self.config.get("error_check_interval", 60)
        # --- CHANGE: Modify error pattern to require REPO_PREFIX ---
        # Pattern looks for CRITICAL/ERROR + error keyword + file path in repo/
        error_pattern = re.compile(r"(CRITICAL|ERROR).*(failed|exception|crash|timeout).*" + re.escape(REPO_PREFIX), re.IGNORECASE)
        # ----------------------------------------------------------
        # --- CHANGE: Refine exclusion patterns further ---
        exclude_patterns = [
            re.compile(r"AI3 -> AI1\\\] Reporting system error"), # Ignore AI3's own reports (less strict start)
            re.compile(r"AI collaboration request received"), # Ignore MCP receiving reports
            re.compile(r"fatal: pathspec .*repo/\.gitignore.* did not match any files"), # Ignore specific GitPython error during init (more flexible)
            re.compile(r"AI3\\\] Detected repo-related critical error"), # Ignore AI3 detecting errors (less strict start)
            # Existing exclude patterns (ensure they are correct)
            re.compile(r"\[AI3\] Error requesting error fix task"), # Повідомлення про власні помилки AI3
            re.compile(r"Active tasks list"), # Список активних завдань
            re.compile(r"Successfully"), # Успішні операції
            re.compile(r"Updating status"), # Оновлення статусу
        ]
        # --- END CHANGE ---
        processed_errors = set() # Store hashes of processed errors
        max_errors_per_cycle = self.config.get("max_errors_per_cycle", 2) # Limit number of errors per cycle

        async def check_executor_queue_size():
            # ... (implementation remains the same) ...
            try:
                await self.create_session()
                async with self.session.get(f"{self.config.get('mcp_api_url', DEFAULT_MCP_API_URL)}/worker_status") as response:
                    if response.status == 200:
                        worker_status = await response.json()
                        queue_sizes = {}
                        for worker_name, status in worker_status.items():
                            queue_sizes[worker_name] = status.get("queue_size", 0)
                        return queue_sizes.get("executor", 0), queue_sizes
                    else:
                        logger.warning(f"[AI3] Failed to get worker status: {response.status}")
                        return 1000, {}
            except Exception as e:
                logger.error(f"[AI3] Error checking worker status: {e}")
                return 1000, {}

        logger.info("[AI3] Starting system error monitoring (repo/ files only, reporting to AI1).") # Updated log
        while True:
            try:
                executor_queue_size, all_queue_sizes = await check_executor_queue_size()
                queue_threshold = self.config.get("executor_queue_threshold", 10)

                if executor_queue_size >= queue_threshold:
                    logger.info(f"[AI3] Executor queue size ({executor_queue_size}) exceeds threshold ({queue_threshold}). Notifying AI1 for queue rebalancing.")
                    await self.send_queue_info_to_ai1(all_queue_sizes)
                    await asyncio.sleep(check_interval * 2)
                    continue

                errors_processed_this_cycle = 0
                for log_file in log_files:
                    if not os.path.exists(log_file):
                        continue

                    if errors_processed_this_cycle >= max_errors_per_cycle:
                        break

                    try:
                        async with aiofiles.open(log_file, mode='r', encoding='utf-8', errors='ignore') as f:
                             lines = await f.readlines()
                             for i, line in enumerate(lines[-100:]):
                                 if errors_processed_this_cycle >= max_errors_per_cycle:
                                     break

                                 # --- CHANGE: Use the updated error_pattern ---
                                 if error_pattern.search(line):
                                 # -------------------------------------------
                                     error_hash = hash(line)
                                     if error_hash not in processed_errors:
                                         logger.info(f"[AI3] Detected repo-related critical error in {log_file}: {line.strip()}") # Updated log
                                         context_lines = lines[max(0, len(lines) - 100 + i - 2) : min(len(lines), len(lines) - 100 + i + 3)]
                                         error_context = "".join(context_lines)
                                         await self._report_system_error_to_ai1(log_file, line.strip(), error_context)
                                         processed_errors.add(error_hash)
                                         errors_processed_this_cycle += 1
                                         self.monitoring_stats["error_fixes_requested"] += 1 # Keep stat, but rename if needed
                    except Exception as file_read_err:
                         logger.error(f"[AI3] Error reading log file {log_file}: {file_read_err}")


                if errors_processed_this_cycle > 0:
                    logger.info(f"[AI3] Reported {errors_processed_this_cycle} repo-related critical system errors to AI1 this cycle") # Updated log

            except Exception as e:
                logger.error(f"[AI3] Error monitoring system errors: {e}")

            await asyncio.sleep(check_interval)

    async def _report_system_error_to_ai1(self, log_file: str, error_line: str, context: str):
        """Sends a system error report to AI1 via MCP API."""
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        try:
            await self.create_session()
            payload = {
                "source": "AI3",
                "type": "system_error_report", # New type field
                "details": {
                    "log_file": log_file,
                    "error_line": error_line,
                    "context": context, # Include surrounding lines
                    "timestamp": datetime.now().isoformat()
                }
            }
            logger.info(f"[AI3 -> AI1] Reporting system error: {error_line[:100]}...")
            async with self.session.post(
                f"{mcp_api_url}/ai_collaboration", # Use the collaboration endpoint
                json=payload,
                timeout=15
            ) as response:
                if response.status == 200:
                    logger.info(f"[AI3 -> AI1] System error report sent successfully.")
                    return True
                else:
                    logger.error(f"[AI3 -> AI1] Error sending system error report: {response.status} - {await response.text()}")
                    return False
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Failed to send system error report: {e}")
            return False

    async def send_queue_info_to_ai1(self, queue_sizes):
        """Sends queue size information to AI1 for task redistribution."""
        # Since communication with AI1 happens via MCP API, use the collaboration endpoint
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        try:
            await self.create_session()
            
            payload = {
                "source": "AI3",
                "type": "queue_rebalance_request", # Changed field name to 'type' for consistency
                "details": { # Nest details under a 'details' key
                    "queue_sizes": queue_sizes,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            # Send data via ai_collaboration endpoint
            logger.info(f"[AI3 -> AI1] Sending queue info to AI1: {queue_sizes}") # Simplified log
            async with self.session.post(
                f"{mcp_api_url}/ai_collaboration", 
                json=payload,
                timeout=15
            ) as response:
                if response.status == 200:
                    logger.info(f"[AI3 -> AI1] Queue info sent successfully.") # Simplified log
                    return True
                else:
                    logger.error(f"[AI3 -> AI1] Error sending queue info: {response.status} - {await response.text()}") # Fix: resp -> response
                    return False
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Failed to send queue info: {e}") # Simplified log
            return False

    async def run(self):
        """Starts all background tasks for AI3."""
        logger.info("[AI3] Starting AI3 background tasks...")
        await self.create_session() # Create session before starting tasks
        tasks = [
            self.monitor_idle_workers(),
            self.monitor_system_errors(),
            self.monitor_github_actions()
        ]
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
             logger.critical(f"[AI3] An error occurred in AI3 main run loop: {e}")
        finally:
             await self.close_session() # Close session on completion
             logger.info("[AI3] AI3 background tasks stopped.")


async def main():
    config = load_config()
    ai3 = AI3(config)

    # --- CHANGE: Call setup_structure before run ---
    logger.info("[AI3] Starting structure setup...")
    setup_successful = await ai3.setup_structure()

    if setup_successful:
        logger.info("[AI3] Structure setup completed successfully. Starting background tasks.")
        await ai3.run()
    else:
        logger.error("[AI3] Structure setup failed. AI3 will not start background monitoring tasks.")
        # Optionally close the session if it was created during setup
        await ai3.close_session()
    # --- END CHANGE ---

if __name__ == "__main__":
    # Logger is already configured at the top level using setup_service_logger
    # Remove redundant logger setup here

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[AI3] AI3 stopped by user.")
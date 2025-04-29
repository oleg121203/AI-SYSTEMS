import asyncio
import importlib
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
import shutil  # Added import

import aiohttp
from git import GitCommandError, Repo

from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import (
    apply_request_delay,  # Import apply_request_delay
    log_message,
    logger,
    wait_for_service,
)

logger = logging.getLogger(__name__)  # Use logger correctly

config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")
REPO_DIR = config.get("repo_dir", "repo")
LOG_FILE_PATH = "logs/mcp_api.log"  # Змінюємо шлях до лог-файлу MCP API


def _init_or_open_repo(repo_path: str) -> Repo:
    try:
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        repo = Repo(repo_path)
        log_message(f"[AI3-Git] Opened existing repository at: {repo_path}")
        return repo
    except Exception:
        try:
            repo = Repo.init(repo_path)
            log_message(f"[AI3-Git] Initialized new repository at: {repo_path}")
            gitignore_path = os.path.join(repo_path, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w") as f:
                    f.write("# Ignore OS-specific files\n.DS_Store\n")
                    f.write("# Ignore virtual environment files\nvenv/\n.venv/\n")
                    f.write("# Ignore IDE files\n.idea/\n.vscode/\n")
                    f.write("# Ignore log files\nlogs/\n*.log\n")
                try:
                    repo.index.add([".gitignore"])
                    repo.index.commit("Add .gitignore")
                    log_message("[AI3-Git] Added .gitignore and committed.")
                except GitCommandError as git_e:
                    log_message(
                        f"[AI3-Git] Warning: Failed to commit .gitignore: {git_e}"
                    )
            return repo
        except Exception as init_e:
            log_message(
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
            log_message(f"[AI3-Git] No changes detected in {valid_paths} to commit.")
            return

        if paths_to_add:
            repo.index.add(paths_to_add)

        if repo.is_dirty():
            repo.index.commit(message)
            log_message(
                f"[AI3-Git] Committed changes for {len(paths_to_add)} file(s): {message}"
            )
        else:
            log_message(f"[AI3-Git] No staged changes to commit for message: {message}")

    except GitCommandError as e:
        log_message(
            f"[AI3-Git] Error committing changes: {message}. Files: {file_paths}. Error: {e}"
        )
    except Exception as e:
        log_message(f"[AI3-Git] Unexpected error during commit: {e}")


async def generate_structure(target: str) -> dict:
    prompt = f"""
Generate a JSON structure for a project with the target: "{target}".
Respond ONLY with the JSON structure itself, enclosed in triple backticks (```json ... ```).
The structure should be a valid JSON object representing directories and files. Use null for files.
Example:
```json
{{
  "src": {{
    "main.py": null,
    "utils.py": null
  }},
  "tests": {{
    "test_main.py": null
  }},
  "README.md": null,
  ".gitignore": null
}}
```
Do not include any explanatory text before or after the JSON block. Ensure the JSON is well-formed.
"""
    ai_config_base = config.get("ai_config", {})
    ai3_config = ai_config_base.get("ai3", {})
    if not ai3_config:
        log_message("[AI3] Warning: 'ai_config.ai3' section not found. Using defaults.")
        ai3_config = {"provider": "openai"}

    provider_name = ai3_config.get("provider", "openai")

    response_text = None
    primary_provider = None
    fallback_provider = None
    try:
        log_message(
            f"[AI3] Attempting structure generation with provider: {provider_name}"
        )
        primary_provider: BaseProvider = ProviderFactory.create_provider(provider_name)
        try:
            await apply_request_delay("ai3")  # Add delay before primary generation
            response_text = await primary_provider.generate(
                prompt=prompt,
                model=ai3_config.get("model"),
                max_tokens=ai3_config.get("max_tokens"),
                temperature=ai3_config.get("temperature"),
            )
            if isinstance(response_text, str) and response_text.startswith(
                "Ошибка генерации"
            ):
                raise Exception(
                    f"Primary provider '{provider_name}' failed: {response_text}"
                )
        finally:
            if hasattr(primary_provider, "close_session") and callable(
                primary_provider.close_session
            ):
                await primary_provider.close_session()

        log_message(
            f"[AI3] Raw response preview from '{provider_name}': {response_text[:200] if response_text else 'None'}"
        )

    except Exception as e:
        primary_provider_name_for_log = (
            primary_provider.name if primary_provider else provider_name
        )
        log_message(
            f"[AI3] Error calling primary provider '{primary_provider_name_for_log}': {e}"
        )
        fallback_provider_name = ai3_config.get("fallback_provider")
        if fallback_provider_name:
            log_message(f"[AI3] Attempting fallback provider: {fallback_provider_name}")
            try:
                fallback_provider: BaseProvider = ProviderFactory.create_provider(
                    fallback_provider_name
                )
                try:
                    await apply_request_delay("ai3")  # Add delay before fallback generation
                    response_text = await fallback_provider.generate(
                        prompt=prompt,
                        model=ai3_config.get("fallback_model"),
                        max_tokens=ai3_config.get("max_tokens"),
                        temperature=ai3_config.get("temperature"),
                    )
                finally:
                    if hasattr(fallback_provider, "close_session") and callable(
                        fallback_provider.close_session
                    ):
                        await fallback_provider.close_session()
            except Exception as fallback_e:
                log_message(
                    f"[AI3] Error calling fallback provider '{fallback_provider_name}': {fallback_e}"
                )
        else:
            log_message("[AI3] No fallback provider configured. Structure generation failed.")

    if not response_text:
        log_message(
            "[AI3] No response received from AI model for structure generation."
        )
        return None

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    json_structure_str = None
    if match:
        json_structure_str = match.group(1)
    else:
        log_message(
            f"[AI3] Failed to extract JSON structure from response. Response: {response_text[:500]}"
        )
        return None

    try:
        structure_obj = json.loads(json_structure_str)
        log_message(f"[AI3] Successfully extracted structure: {json_structure_str[:200]}...")
        return structure_obj
    except json.JSONDecodeError as e:
        log_message(f"[AI3] JSON decode error: {e}. JSON string: {json_structure_str[:200]}")
        return None
    except Exception as e:
        log_message(f"[AI3] Unexpected error processing structure: {e}")
        return None


async def send_structure_to_api(structure_obj: dict):
    api_url = f"{MCP_API_URL}/structure"
    log_message(f"[AI3 -> API] Sending structure object to {api_url}")
    async with aiohttp.ClientSession() as client_session:
        try:
            async with client_session.post(
                api_url, json={"structure": structure_obj}, timeout=30
            ) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    log_message(
                        f"[AI3 -> API] Structure successfully sent. Response: {response_text}"
                    )
                    return True
                else:
                    log_message(
                        f"[AI3 -> API] Error sending structure. Status: {resp.status}, Response: {response_text}"
                    )
                    return False
        except Exception as e:
            log_message(f"[AI3 -> API] Error sending structure: {str(e)}")
            return False


async def send_ai3_report(status: str, details: dict = None):
    api_url = f"{MCP_API_URL}/ai3_report"
    payload = {"status": status}
    if details:
        payload["details"] = details
    log_message(f"[AI3 -> API] Sending report to {api_url}: {payload}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json=payload, timeout=15) as resp:
                response_text = await resp.text()
                log_message(
                    f"[AI3 -> API] Report sent. Status: {resp.status}, Response: {response_text}"
                )
                return resp.status == 200
        except asyncio.TimeoutError:
            log_message(f"[AI3 -> API] Timeout sending report: {status}")
            return False
        except aiohttp.ClientError as e:
            log_message(f"[AI3 -> API] Connection error sending report: {str(e)}")
            return False
        except Exception as e:
            log_message(f"[AI3 -> API] Unexpected error sending report: {str(e)}")
            return False


async def initiate_collaboration(error: str, context: str):
    api_url = f"{MCP_API_URL}/ai_collaboration"
    collaboration_request = {"error": error, "context": context, "ai": "AI3"}
    log_message(
        f"[AI3 -> API] Initiating collaboration via {api_url}: {collaboration_request}"
    )
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                api_url, json=collaboration_request, timeout=20
            ) as resp:
                response_text = await resp.text()
                log_message(
                    f"[AI3 -> API] Collaboration request sent. Status: {resp.status}, Response: {response_text}"
                )
                return resp.status == 200
        except asyncio.TimeoutError:
            log_message(f"[AI3 -> API] Timeout initiating collaboration.")
            return False
        except aiohttp.ClientError as e:
            log_message(
                f"[AI3 -> API] Connection error initiating collaboration: {str(e)}"
            )
            return False
        except Exception as e:
            log_message(
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
                log_message(
                    f"[AI3] Warning: Skipping empty or invalid name derived from '{key}'"
                )
                continue

            new_rel_path = os.path.join(current_rel_path, sanitized_key)
            full_path = os.path.join(base_path, new_rel_path)

            try:
                if isinstance(value, dict):
                    if not os.path.exists(full_path):
                        os.makedirs(full_path)
                        log_message(f"[AI3] Created directory: {new_rel_path}")
                        created_dirs.append(full_path)
                        if not value:
                            gitkeep_path = os.path.join(full_path, ".gitkeep")
                            with open(gitkeep_path, "w") as f:
                                f.write("")
                            log_message(
                                f"[AI3] Created .gitkeep in empty directory: {new_rel_path}"
                            )
                    await _create_recursive(value, new_rel_path)
                elif value is None or isinstance(value, str):
                    parent_dir = os.path.dirname(full_path)
                    if not os.path.exists(parent_dir):
                        os.makedirs(parent_dir)
                        log_message(
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
                        log_message(f"[AI3] Created file: {new_rel_path}")
                        created_files.append(full_path)
                    else:
                        log_message(
                            f"[AI3] File already exists, skipping creation: {new_rel_path}"
                        )
                else:
                    log_message(
                        f"[AI3] Warning: Unknown type in structure for key '{key}', skipping: {type(value)}"
                    )

            except OSError as e:
                log_message(f"[AI3] Error creating file/directory {new_rel_path}: {e}")
            except Exception as e:
                log_message(f"[AI3] Unexpected error processing {new_rel_path}: {e}")

    try:
        log_message("[AI3] Starting file creation from structure...")
        await _create_recursive(structure_obj, "")
        files_to_commit = created_files + [
            os.path.join(d, ".gitkeep")
            for d in created_dirs
            if os.path.exists(os.path.join(d, ".gitkeep"))
        ]
        _commit_changes(
            repo, files_to_commit, "Created initial project structure from AI"
        )
        log_message("[AI3] File creation process completed.")
        await send_ai3_report("structure_creation_completed")
        return True
    except Exception as e:
        log_message(f"[AI3] Error in create_files_from_structure: {e}")
        await initiate_collaboration(str(e), "Failed to create files from structure")
        await send_ai3_report("structure_creation_failed", {"error": str(e)})
        return False


async def simple_log_monitor():
    log_message(f"[AI3] Starting simple log monitoring: {LOG_FILE_PATH}")
    position = 0
    if os.path.exists(LOG_FILE_PATH):
        try:
            position = os.path.getsize(LOG_FILE_PATH)
        except OSError:
            position = 0

    error_pattern = re.compile(r".*(ERROR|CRITICAL).*", re.IGNORECASE)

    while True:
        try:
            current_size = os.path.getsize(LOG_FILE_PATH)
            if current_size < position:
                position = 0

            if current_size > position:
                with open(LOG_FILE_PATH, "r", encoding="utf-8") as file:
                    file.seek(position)
                    new_content = file.read()
                    position = file.tell()

                    for line in new_content.splitlines():
                        if error_pattern.search(line):
                            log_message(
                                f"[AI3-Monitor] Detected potential error: {line}"
                            )
                            pass

        except FileNotFoundError:
            log_message(f"[AI3] Log file not found: {LOG_FILE_PATH}. Retrying...")
            position = 0
        except Exception as e:
            log_message(f"[AI3] Error in simple log monitor: {e}")

        await asyncio.sleep(config.get("ai3_log_monitor_interval", 10))


def install_missing_modules(module_name):
    try:
        importlib.import_module(module_name)
    except ImportError:
        print(f"{module_name} not found. Installing...")
        subprocess.check_call(["pip", "install", module_name])


class AI3:
    def __init__(self, repo_dir="repo"):
        self.repo_dir = repo_dir
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
        try:
            Path(repo_path).mkdir(parents=True, exist_ok=True)
            repo = Repo(repo_path)
            log_message(f"[AI3-Git] Opened existing repository at: {repo_path}")
            return repo
        except Exception:
            try:
                repo = Repo.init(repo_path)
                log_message(f"[AI3-Git] Initialized new repository at: {repo_path}")
                gitignore_path = os.path.join(repo_path, ".gitignore")
                if not os.path.exists(gitignore_path):
                    with open(gitignore_path, "w") as f:
                        f.write("# Ignore OS-specific files\n.DS_Store\n")
                        f.write("# Ignore virtual environment files\nvenv/\n.venv/\n")
                        f.write("# Ignore IDE files\n.idea/\n.vscode/\n")
                        f.write("# Ignore log files\nlogs/\n*.log\n")
                    try:
                        repo.index.add([".gitignore"])
                        repo.index.commit("Add .gitignore")
                        log_message("[AI3-Git] Added .gitignore and committed.")
                    except GitCommandError as git_e:
                        log_message(
                            f"[AI3-Git] Warning: Failed to commit .gitignore: {git_e}"
                        )
                return repo
            except Exception as init_e:
                log_message(
                    f"[AI3-Git] CRITICAL: Failed to initialize or open repository at {repo_path}: {init_e}"
                )
                raise

    async def clear_and_init_repo(self):
        try:
            # If the repo_dir exists, clear it completely
            repo_path = Path(self.repo_dir)
            if repo_path.exists():
                try:
                    # Try to delete the entire directory
                    shutil.rmtree(self.repo_dir)
                    log_message(f"[AI3-Git] Cleared existing repository: {self.repo_dir}")
                except Exception as e:
                    log_message(f"[AI3-Git] Error clearing repository: {e}")
                    
            # Create or initialize the repository
            self.repo = _init_or_open_repo(self.repo_dir)
            log_message(f"[AI3-Git] Repository initialized at: {self.repo_dir}")
            return True
        except Exception as e:
            log_message(f"[AI3-Git] Error initializing repository: {e}")
            return False

    async def create_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            log_message("[AI3] Created new aiohttp session")

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            log_message("[AI3] Closed aiohttp session")

    async def setup_structure(self):
        try:
            # Wait for MCP API to be available
            await wait_for_service(MCP_API_URL, max_retries=60, retry_delay=1)
            
            # Initialize repository
            success = await self.clear_and_init_repo()
            if not success:
                log_message("[AI3] Failed to initialize repository. Aborting structure setup.")
                return False
                
            # Generate structure based on target
            structure = await generate_structure(self.target)
            if not structure:
                log_message("[AI3] Failed to generate structure. Aborting structure setup.")
                return False
                
            # Send structure to MCP API
            await self.create_session()
            try:
                async with self.session.post(
                    f"{MCP_API_URL}/structure",
                    json={"structure": structure, "target": self.target},
                ) as resp:
                    if resp.status == 200:
                        log_message("[AI3] Structure sent to MCP API successfully")
                        structure_response = await resp.json()
                        log_message(f"[AI3] MCP API response: {structure_response}")
                        # Create the structure in the repository
                        await self.create_file_structure(structure)
                        return True
                    else:
                        error_text = await resp.text()
                        log_message(f"[AI3] Error sending structure to MCP API: {error_text}")
                        return False
            except Exception as e:
                log_message(f"[AI3] Exception during structure API call: {e}")
                return False
        except Exception as e:
            log_message(f"[AI3] Unexpected error in setup_structure: {e}")
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
                    log_message(f"[AI3] Created empty file: {full_path}")
                else:  # It's a directory
                    Path(abs_path).mkdir(parents=True, exist_ok=True)
                    log_message(f"[AI3] Created directory: {full_path}")
                    # Recursively process the directory
                    child_files = await self.create_file_structure(content, full_path)
                    created_files.extend(child_files)
            
            # Commit changes only after creating the full structure
            if created_files:
                _commit_changes(self.repo, created_files, "Initial project structure")
                
            return created_files
        except Exception as e:
            log_message(f"[AI3] Error creating file structure: {e}")
            return []

    async def start_monitoring(self):
        log_message("[AI3] Starting monitoring service...")
        try:
            while True:
                try:
                    await asyncio.sleep(30)  # Check every 30 seconds
                    await self.check_worker_status()
                    await self.scan_logs_for_errors()
                except asyncio.CancelledError:
                    log_message("[AI3] Monitoring task cancelled")
                    break
                except Exception as e:
                    log_message(f"[AI3] Error in monitoring cycle: {e}")
                    await asyncio.sleep(5)  # Short delay before retrying
        except Exception as e:
            log_message(f"[AI3] Monitoring service crashed: {e}")
        finally:
            log_message("[AI3] Monitoring service stopped")

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
                        log_message(f"[AI3] Detected idle workers: {', '.join(idle_workers)}")
                        
                        # Request tasks for idle workers
                        for worker in idle_workers:
                            await self.request_task_for_worker(worker)
                else:
                    log_message(f"[AI3] Failed to get worker status: {resp.status}")
        except Exception as e:
            log_message(f"[AI3] Error checking worker status: {e}")

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
                        log_message(f"[AI3] Successfully requested task for {worker_name}: {result}")
                    else:
                        log_message(f"[AI3] Failed to request task for {worker_name}: {result}")
                else:
                    log_message(f"[AI3] Error response from API: {resp.status}")
        except Exception as e:
            log_message(f"[AI3] Error requesting task for worker {worker_name}: {e}")

    async def scan_logs_for_errors(self):
        # Simplified log scanning - would be more sophisticated in a real implementation
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return
            
        try:
            # Only scan logs that have been modified in the last check interval
            current_time = time.time()
            time_threshold = self.last_check_time
            self.last_check_time = current_time
            
            error_patterns = [
                "Error", "Exception", "Failed", "Timeout", "CRITICAL"
            ]
            
            errors_found = False
            error_summary = []
            
            for log_file in logs_dir.glob("*.log"):
                if log_file.stat().st_mtime >= time_threshold:
                    with open(log_file, "r", errors="replace") as f:
                        lines = f.readlines()
                        # Only check the last 100 lines for efficiency
                        for line in lines[-100:]:
                            if any(pattern in line for pattern in error_patterns):
                                error_summary.append(f"{log_file.name}: {line.strip()}")
                                errors_found = True
                                if len(error_summary) >= 5:  # Limit to 5 errors per check
                                    break
                    
                    if len(error_summary) >= 5:
                        break
            
            if errors_found:
                log_message(f"[AI3] Found errors in logs: {len(error_summary)} issues")
                await self.request_error_fix(error_summary)
        except Exception as e:
            log_message(f"[AI3] Error scanning logs: {e}")

    async def request_error_fix(self, error_summary):
        self.monitoring_stats["error_fixes_requested"] += 1
        await self.create_session()
        try:
            error_report = "\n".join(error_summary[:5])  # Limit to first 5 errors
            async with self.session.post(
                f"{MCP_API_URL}/request_error_fix",
                json={"errors": error_report},
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    log_message(f"[AI3] Error fix request response: {result}")
                else:
                    log_message(f"[AI3] Error fix request failed: {resp.status}")
        except Exception as e:
            log_message(f"[AI3] Error requesting error fix: {e}")

    async def clear_and_init_repo(self):
        """Очищає репозиторій та ініціалізує новий."""
        try:
            # Перевірити, чи існує репозиторій
            if os.path.exists(self.repo_dir):
                # Видалити репозиторій
                shutil.rmtree(self.repo_dir)
                log_message(f"[AI3] Видалено існуючий репозиторій: {self.repo_dir}")

            # Створити каталог репозиторію
            os.makedirs(self.repo_dir, exist_ok=True)

            # Ініціалізувати новий Git репозиторій
            init_result = subprocess.run(
                ["git", "init"],
                cwd=self.repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            log_message(f"[AI3] Ініціалізовано новий Git репозиторій: {self.repo_dir}. Output: {init_result.stdout}")
            self.repo = Repo(self.repo_dir)  # Re-assign the repo object

            # Додати .gitignore
            gitignore_path = os.path.join(self.repo_dir, ".gitignore")
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write("**/__pycache__\n")
                f.write("*.pyc\n")
                f.write(".DS_Store\n")
            log_message(f"[AI3] Створено .gitignore у {self.repo_dir}")

            # Додати та закомітити .gitignore
            add_result = subprocess.run(
                ["git", "add", ".gitignore"],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            log_message(f"[AI3] git add .gitignore: {add_result.stdout}")

            # Налаштування користувача Git (важливо для коміту)
            subprocess.run(["git", "config", "user.email", "ai3@example.com"], cwd=self.repo_dir, check=False)
            subprocess.run(["git", "config", "user.name", "AI3 System"], cwd=self.repo_dir, check=False)

            commit_result = subprocess.run(
                ["git", "commit", "-m", "Initial commit (gitignore)"],
                cwd=self.repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            log_message(f"[AI3] git commit: {commit_result.stdout}")
            log_message("[AI3] Репозиторій успішно очищено та ініціалізовано.")
            await send_ai3_report("repo_cleared")  # Повідомити API

        except subprocess.CalledProcessError as e:
            log_message(f"[AI3] Помилка subprocess під час очищення/ініціалізації репо: {e.stderr}")
            await send_ai3_report("repo_clear_failed", {"error": str(e.stderr)})
        except Exception as e:
            log_message(f"[AI3] Неочікувана помилка при очищенні та ініціалізації репозиторію: {e}")
            await send_ai3_report("repo_clear_failed", {"error": str(e)})

    async def update_file_and_commit(self, file_path_relative: str, content: str):
        """Оновлює файл у репозиторії та комітить зміни."""
        repo_dir = "repo"
        full_path = os.path.join(repo_dir, file_path_relative)

        try:
            # Переконатися, що директорія існує
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Записати вміст файлу
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Оновлено файл: {full_path}")

            # Додати файл до індексу Git
            add_result = subprocess.run(
                ["git", "add", full_path],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if add_result.returncode != 0:
                logger.error(f"Помилка 'git add' для {full_path}: {add_result.stderr}")
                return  # Не продовжувати, якщо add не вдався

            logger.info(f"Додано до індексу Git: {full_path}")

            # Закомітити зміни
            commit_message = f"AI3: Оновлено {file_path_relative}"
            # Використовує глобально налаштованого користувача Git (з new_repo.sh)
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if commit_result.returncode != 0:
                # Можливо, коміт не вдався, бо не було змін (це нормально)
                if (
                    "nothing to commit, working tree clean" not in commit_result.stdout
                    and "no changes added to commit" not in commit_result.stderr
                ):
                    logger.error(
                        f"Помилка 'git commit' для {file_path_relative}: {commit_result.stderr}"
                    )
                else:
                    logger.info(f"Немає змін для коміту в файлі: {file_path_relative}")

            else:
                logger.info(f"Зроблено коміт для файлу: {file_path_relative}")

        except FileNotFoundError:
            logger.error(
                f"Помилка: команда 'git' не знайдена. Переконайтеся, що Git встановлено та доступний у PATH."
            )
        except Exception as e:
            logger.error(
                f"Не вдалося оновити або закомітити файл {file_path_relative}: {e}"
            )

    async def handle_ai2_output(self, data):
        # ... логіка для вилучення file_path та content ...
        file_path = data.get("filename")  # Або інше поле, що містить шлях
        content = data.get("code")  # Або інше поле, що містить вміст

        if file_path and content is not None:
            # Переконайтеся, що file_path є відносним шляхом всередині 'repo/'
            if file_path.startswith(os.path.abspath("repo")):
                file_path = os.path.relpath(file_path, "repo")

            await self.update_file_and_commit(file_path, content)
        else:
            logger.warning(
                f"Не вдалося вилучити шлях до файлу або вміст зі звіту AI2: {data}"
            )

    async def monitor_github_actions(self):
        """Моніторить результати GitHub Actions та надсилає рекомендації на основі аналізу.
        Ця функція безперервно перевіряє статус GitHub Actions через GitHub API
        та обробляє результати тестування.
        """
        log_message("[AI3] Starting GitHub Actions monitoring...")
        
        # Конфігурація GitHub API
        github_token = config.get("github_token")
        github_repo = config.get("github_repo")
        
        if not github_token or not github_repo:
            log_message("[AI3] Warning: GitHub token or repo not configured. Cannot monitor GitHub Actions.")
            return
        
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Основний цикл моніторингу
        while True:
            try:
                await self.create_session()
                # Отримуємо останні workflow runs
                async with self.session.get(
                    f"https://api.github.com/repos/{github_repo}/actions/runs",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        runs_data = await response.json()
                        workflow_runs = runs_data.get("workflow_runs", [])
                        
                        # Обробляємо тільки останній завершений workflow run
                        for run in workflow_runs:
                            run_id = run.get("id")
                            run_status = run.get("status")
                            run_conclusion = run.get("conclusion")
                            
                            if run_status == "completed":
                                # Зберігаємо інформацію про завершений run, якщо ми його ще не обробляли
                                if self._is_new_completed_run(run_id):
                                    log_message(f"[AI3] Found completed GitHub Actions run: {run_id}, conclusion: {run_conclusion}")
                                    await self._analyze_workflow_run(run_id, run_conclusion, headers)
                                break  # Обробляємо тільки останній завершений run
                    else:
                        log_message(f"[AI3] Failed to fetch GitHub Actions runs: Status {response.status}")
                    
            except Exception as e:
                log_message(f"[AI3] Error in GitHub Actions monitoring: {e}")
            
            # Чекаємо перед наступною перевіркою
            await asyncio.sleep(config.get("github_actions_check_interval", 60))

    def _is_new_completed_run(self, run_id):
        """Перевіряє, чи є завершений run новим (ще не обробленим)."""
        if not hasattr(self, "processed_run_ids"):
            self.processed_run_ids = set()
        
        if run_id in self.processed_run_ids:
            return False
        
        self.processed_run_ids.add(run_id)
        # Обмежуємо розмір множини, зберігаючи тільки останні N run_id
        max_stored_runs = 50
        if len(self.processed_run_ids) > max_stored_runs:
            self.processed_run_ids = set(list(self.processed_run_ids)[-max_stored_runs:])
        
        return True

    async def _analyze_workflow_run(self, run_id, run_conclusion, headers):
        """Аналізує результати виконання workflow та відправляє рекомендації."""
        try:
            await self.create_session()
            # Отримуємо деталі запуску, включаючи тести
            async with self.session.get(
                f"https://api.github.com/repos/{config.get('github_repo')}/actions/runs/{run_id}/jobs",
                headers=headers
            ) as response:
                if response.status != 200:
                    log_message(f"[AI3] Failed to fetch jobs for run {run_id}: Status {response.status}")
                    return
                
                jobs_data = await response.json()
                jobs = jobs_data.get("jobs", [])
                
                # Аналізуємо тестові завдання
                all_tests_passed = True
                failed_files = []
                
                for job in jobs:
                    job_name = job.get("name", "")
                    job_conclusion = job.get("conclusion", "")
                    
                    if "test" in job_name.lower():
                        log_message(f"[AI3] Found test job: {job_name}, conclusion: {job_conclusion}")
                        
                        if job_conclusion != "success":
                            all_tests_passed = False
                            
                            # Отримуємо кроки завдання, щоб знайти, які тести не пройшли
                            steps = job.get("steps", [])
                            for step in steps:
                                step_name = step.get("name", "")
                                step_conclusion = step.get("conclusion", "")
                                
                                if step_conclusion == "failure" and "test" in step_name.lower():
                                    # Спроба визначити, який файл викликав помилку на основі назви кроку
                                    # Це може потребувати додаткової логіки залежно від формату кроків
                                    file_patterns = ["test_", ".test.", "_test"]
                                    for pattern in file_patterns:
                                        if pattern in step_name:
                                            file_parts = step_name.split(pattern)
                                            if len(file_parts) > 1:
                                                file_guess = pattern + file_parts[1].split()[0]
                                                failed_files.append(file_guess)
                                    
                                    log_message(f"[AI3] Failed test step: {step_name}")
                
                # Формуємо рекомендацію
                recommendation = "accept" if all_tests_passed else "rework"
                
                # Збираємо контекст для рекомендації
                context = {}
                if not all_tests_passed:
                    context["failed_files"] = failed_files
                    context["run_url"] = f"https://github.com/{config.get('github_repo')}/actions/runs/{run_id}"
                
                # Відправляємо рекомендацію в MCP API
                await self._send_test_recommendation(recommendation, context)
                
        except Exception as e:
            log_message(f"[AI3] Error analyzing workflow run {run_id}: {e}")

    async def _send_test_recommendation(self, recommendation, context=None):
        """Відправляє рекомендацію на основі результатів тестів в MCP API."""
        api_url = f"{MCP_API_URL}/test_recommendation"
        payload = {
            "recommendation": recommendation,
            "context": context or {}
        }
        
        log_message(f"[AI3] Sending test recommendation to MCP API: {recommendation}")
        
        try:
            await self.create_session()
            async with self.session.post(api_url, json=payload) as response:
                if response.status == 200:
                    log_message(f"[AI3] Test recommendation sent successfully: {recommendation}")
                    return True
                else:
                    response_text = await response.text()
                    log_message(f"[AI3] Failed to send test recommendation. Status: {response.status}, Response: {response_text}")
                    return False
        except Exception as e:
            log_message(f"[AI3] Error sending test recommendation: {e}")
            return False


# Глобальний екземпляр AI3 для використання в API та main
ai3_instance = AI3()


async def main():
    install_missing_modules("together")
    install_missing_modules("mistralai")

    target = config.get("target")
    if not target:
        log_message("[AI3] CRITICAL: 'target' not found in config.json. Exiting.")
        return

    log_message(f"[AI3] Started with target: {target}")

    log_message(f"[AI3] Checking connection to MCP API at {MCP_API_URL}")
    if not await wait_for_service(MCP_API_URL, timeout=120):
        log_message(f"[AI3] CRITICAL: MCP API at {MCP_API_URL} not available. Exiting.")
        return

    repo = ai3_instance.repo  # Use instance's repo

    structure_obj = None
    try:
        api_url = f"{MCP_API_URL}/structure"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if (
                        data
                        and isinstance(data.get("structure"), dict)
                        and data["structure"]
                    ):
                        structure_obj = data["structure"]
                        log_message("[AI3] Found existing structure from API.")
    except Exception as e:
        log_message(f"[AI3] Could not check for existing structure: {e}")

    if not structure_obj:
        log_message("[AI3] Attempting to generate project structure...")
        structure_obj = await generate_structure(target)

        if structure_obj:
            log_message(
                "[AI3] Structure generated. Sending to API and creating files..."
            )
            if await send_structure_to_api(structure_obj):
                if not await create_files_from_structure(structure_obj, ai3_instance.repo):
                    log_message(
                        "[AI3] Failed to create files from structure. Continuing monitor."
                    )
                    await send_ai3_report("structure_creation_failed")
            else:
                log_message(
                    "[AI3] Failed to send structure to API. Cannot create files."
                )
                await send_ai3_report("structure_api_send_failed")
        else:
            log_message("[AI3] Failed to generate structure. Cannot create files.")
            await send_ai3_report("structure_generation_failed")

    log_message("[AI3] Starting monitoring tasks.")
    monitoring_task = None  # Моніторинг воркерів та логів
    github_actions_task = None  # Моніторинг GitHub Actions
    
    try:
        # Запускаємо одночасно всі моніторингові завдання
        monitoring_task = asyncio.create_task(ai3_instance.start_monitoring())
        github_actions_task = asyncio.create_task(ai3_instance.monitor_github_actions())
        
        log_message("[AI3] All monitoring tasks started.")
        
        # Головний цикл, що просто підтримує програму активною
        while True:
            await asyncio.sleep(3600)  # Перевірка раз на годину

    except asyncio.CancelledError:
        log_message("[AI3] Main task cancelled")
    except Exception as e:
        log_message(f"[AI3] Unexpected error in main task: {e}")
    finally:
        log_message("[AI3] Main task finishing. Cleaning up...")
        # Скасовуємо всі моніторингові завдання
        for task, name in [
            (monitoring_task, "Monitoring"),
            (github_actions_task, "GitHub Actions monitoring")
        ]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                    log_message(f"[AI3] {name} task cancelled successfully.")
                except asyncio.CancelledError:
                    log_message(f"[AI3] {name} task cancellation confirmed.")
                except Exception as e:
                    log_message(f"[AI3] Error during {name} task cancellation: {e}")
        
        # Закриваємо сесію
        await ai3_instance.close_session()
        log_message("[AI3] Exiting.")
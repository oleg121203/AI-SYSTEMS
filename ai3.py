import asyncio
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import aiofiles
import aiohttp
import git
import requests
from git import GitCommandError, Repo

import ai_communication as ai_comm
from config import load_config
from providers import BaseProvider, ProviderFactory  # Adding missing provider imports
from utils import (
    apply_request_delay,
    log_message,
    setup_service_logger,
    wait_for_service,
)

# Load configuration and set up logging
config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")
LOG_FILE = "logs/ai3.log"

# Define constants
DEFAULT_REPO_DIR = "repo"
DEFAULT_MCP_API_URL = "http://localhost:7860"
REPO_PREFIX = "repo/"  # All relative paths should be relative to repo dir

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/ai3.log"), logging.StreamHandler()],
)
logger = logging.getLogger("AI3")

# Load configuration
config = load_config()

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


# Define wait_for_service function before it's used
async def wait_for_service(service_url: str, timeout: int = 60) -> bool:
    """Wait for a service to become available by polling its URL.

    Args:
        service_url: The URL of the service to check
        timeout: Maximum time to wait in seconds

    Returns:
        bool: True if service became available, False if timeout occurred
    """
    logger.info(f"[AI3] Waiting for service at {service_url} (timeout: {timeout}s)")
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        while time.time() - start_time < timeout:
            try:
                async with session.get(service_url, timeout=5) as response:
                    if response.status == 200:
                        logger.info(f"[AI3] Service at {service_url} is available")
                        return True
                    else:
                        logger.debug(
                            f"[AI3] Service check: Status {response.status} from {service_url}"
                        )
            except (
                aiohttp.ClientConnectorError,
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ):
                pass  # Expected during startup, don't log each failure
            except Exception as e:
                logger.debug(f"[AI3] Error checking service: {e}")

            # Check every second
            await asyncio.sleep(1)

    logger.warning(
        f"[AI3] Timeout waiting for service at {service_url} after {timeout}s"
    )
    return False


def _init_or_open_repo(repo_path: str) -> Repo:
    """Initializes a new or opens an existing Git repository."""
    try:
        logger.info(f"[AI3-Git] Attempting to open repository at: {repo_path}")
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        repo = Repo(repo_path)
        logger.info(f"[AI3-Git] Opened existing repository at: {repo_path}")
        return repo
    except Exception:
        try:
            logger.info(
                f"[AI3-Git] Repository not found, initializing new one at: {repo_path}"
            )
            repo = Repo.init(repo_path)
            logger.info(f"[AI3-Git] Initialized new repository at: {repo_path}")
            gitignore_path = os.path.join(repo_path, GITIGNORE_FILENAME)
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write("# Ignore OS-specific files\n.DS_Store\n")
                    f.write("# Ignore virtual environment files\nvenv/\n.venv/\n")
                    f.write("# Ignore IDE files\n.idea/\n.vscode/\n")
                    f.write("# Ignore log files\nlogs/\n*.log\n")
                    f.write("# Ignore Python cache\n**/__pycache__/\n*.pyc\n")
                logger.info(f"[AI3-Git] Created .gitignore at {gitignore_path}")
                repo.index.add([GITIGNORE_FILENAME])
                repo.index.commit("Initial commit with .gitignore")
                logger.info(f"[AI3-Git] Initial commit successful: .gitignore")
            return repo
        except Exception as init_e:
            logger.critical(
                f"[AI3-Git] CRITICAL: Failed to initialize or open repository at {repo_path}: {init_e}"
            )
            raise


def _commit_changes(repo: Repo, file_paths: list, message: str):
    """Commits specified files to the Git repository."""
    if not file_paths:
        logger.info(f"[AI3-Git] No file paths provided for commit: {message}")
        return
    try:
        relative_paths = [
            os.path.relpath(p, repo.working_dir)
            for p in file_paths
            if os.path.exists(p) and p.startswith(repo.working_dir)
        ]

        if not relative_paths:
            logger.info(
                f"[AI3-Git] No valid files found to commit for message: {message}"
            )
            return

        paths_to_add = [
            p
            for p in relative_paths
            if p in repo.untracked_files
            or p in [item.a_path for item in repo.index.diff(None)]
        ]

        if not paths_to_add:
            logger.info(
                f"[AI3-Git] No new or modified files to add to index for commit: {message}"
            )
            return

        logger.info(f"[AI3-Git] Adding files to index: {paths_to_add}")
        repo.index.add(paths_to_add)

        is_empty_repo = not repo.head.is_valid()

        if is_empty_repo:
            logger.info(
                f"[AI3-Git] Empty repository detected. Performing initial commit: {message}"
            )
            repo.index.commit(message)
            logger.info(f"[AI3-Git] Initial commit successful: {message}")
        else:
            staged_diff = repo.index.diff("HEAD")
            if staged_diff:
                logger.info(
                    f"[AI3-Git] Committing {len(paths_to_add)} added/modified file(s): {message}"
                )
                repo.index.commit(message)
                logger.info(f"[AI3-Git] Commit successful: {message}")
            else:
                logger.info(
                    f"[AI3-Git] No staged changes to commit for message: {message}"
                )

    except GitCommandError as e:
        if "nothing to commit" in str(e) or "no changes added to commit" in str(e):
            logger.info(f"[AI3-Git] Git: Nothing to commit for message: {message}")
        else:
            logger.error(
                f"[AI3-Git] Error committing changes: {message}. Files: {relative_paths}. Error: {e}"
            )
    except Exception as e:
        logger.error(f"[AI3-Git] Unexpected error during commit: {e}", exc_info=True)


async def generate_structure(target: str) -> Optional[Dict]:
    """
    Generates initial project structure, refines it, and returns the result.
    Uses the 'structure_providers' list from AI3 configuration.
    """
    logger.info(f"[AI3] Starting structure generation for target: {target}")
    base_prompt = config.get("ai3_prompt", "Generate a project structure for:")
    system_instructions_initial = f"""
    Target Project: {target}
    Generate a detailed JSON structure representing the directories and files for this project.
    Include potential initial content placeholders or comments within the files where appropriate (use strings for content, null for empty files).
    Use only Latin characters for all generated names (files, directories).
    Output ONLY the JSON structure, enclosed in triple backticks (```json ... ```), without any introductory text or explanations.
    Example format:
    ```json
    {{
      "project_name": {{
        "src": {{
          "main.py": "# Main application entry point",
          "utils.py": null
        }},
        "tests": {{
          "test_main.py": "# Tests for main.py"
        }},
        "README.md": "# Project Readme"
      }}
    }}
    ```
    """
    full_prompt_initial = base_prompt + "\n" + system_instructions_initial

    ai_config_base = config.get("ai_config", {})
    ai3_config = ai_config_base.get("ai3", {})
    if not ai3_config:
        logger.warning(
            "[AI3] Warning: 'ai_config.ai3' section not found. Using defaults."
        )
        ai3_config = {}

    structure_providers = ai3_config.get("structure_providers")
    if not structure_providers:
        logger.warning(
            "[AI3] 'structure_providers' not found in ai3 config. Using default ['codestral2']."
        )
        structure_providers = ["codestral2"]

    logger.info(f"[AI3] Using structure_providers: {structure_providers}")

    initial_response_text = None
    selected_provider_name = None

    logger.info(
        f"[AI3] Starting Cycle 1: Initial structure generation using providers: {structure_providers}"
    )
    for provider_name in structure_providers:
        try:
            logger.info(
                f"[AI3] Cycle 1: Trying provider for initial generation: {provider_name}"
            )
            provider: BaseProvider = ProviderFactory.create_provider(provider_name)
            try:
                await apply_request_delay("ai3")
                initial_response_text = await provider.generate(
                    prompt=full_prompt_initial,
                    model=ai3_config.get("model"),
                    max_tokens=ai3_config.get("max_tokens", 4000),
                    temperature=ai3_config.get("temperature"),
                )
                if initial_response_text:
                    logger.info(
                        f"[AI3] Cycle 1: Successfully generated initial structure with provider: {provider_name}"
                    )
                    selected_provider_name = provider_name
                    break
                else:
                    logger.warning(
                        f"[AI3] Cycle 1: Provider {provider_name} returned empty response for initial generation."
                    )
            except Exception as e:
                logger.error(
                    f"[AI3] Cycle 1: Failed initial generation with provider {provider_name}: {str(e)}"
                )
            finally:
                if hasattr(provider, "close_session") and callable(
                    provider.close_session
                ):
                    await provider.close_session()
        except Exception as e:
            logger.error(
                f"[AI3] Cycle 1: Error initializing provider '{provider_name}' for initial generation: {e}"
            )

    if not initial_response_text:
        logger.error(
            "[AI3] Cycle 1: Failed to generate initial structure with all configured providers."
        )
        return None

    def clean_and_parse_json(response_str: str) -> Optional[Dict]:
        cleaned_str = (
            response_str.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        )
        if not cleaned_str:
            logger.warning("[AI3] Cleaned JSON string is empty.")
            return None
        try:
            return json.loads(cleaned_str)
        except json.JSONDecodeError as e:
            logger.error(
                f"[AI3] Failed to decode JSON structure: {e}. String: {cleaned_str[:200]}..."
            )
            return None
        except Exception as e:
            logger.error(f"[AI3] Unexpected error parsing JSON: {e}")
            return None

    initial_structure_json = clean_and_parse_json(initial_response_text)
    if not initial_structure_json:
        logger.error("[AI3] Failed to parse the initial JSON structure. Aborting.")
        return None

    logger.info("[AI3] Starting Cycle 2: Structure refinement...")
    refinement_prompt = f"""
    Review the following initial project structure JSON for the target '{target}'.
    Analyze its completeness, logical organization, and adherence to common practices for such a project.
    Consider typical files needed (e.g., config, tests, docs, main entry points, utility modules).
    If you identify areas for improvement (e.g., missing essential files/directories, better organization, incorrect file types),
    provide a refined version of the JSON structure.
    If the structure looks good and complete, return the original JSON structure.
    Use only Latin characters for all generated names (files, directories).
    Output ONLY the JSON structure, enclosed in triple backticks (```json ... ```), without any introductory text or explanations.

    Initial Structure:
    ```json
    {json.dumps(initial_structure_json, indent=2)}
    ```
    """

    refined_response_text = None
    providers_to_try_refinement = (
        [selected_provider_name] if selected_provider_name else structure_providers
    )

    for provider_name in providers_to_try_refinement:
        try:
            logger.info(
                f"[AI3] Cycle 2: Trying provider for refinement: {provider_name}"
            )
            provider: BaseProvider = ProviderFactory.create_provider(provider_name)
            try:
                await apply_request_delay("ai3")
                refined_response_text = await provider.generate(
                    prompt=refinement_prompt,
                    model=ai3_config.get("model"),
                    max_tokens=ai3_config.get("max_tokens", 4000),
                    temperature=ai3_config.get("temperature"),
                )
                if refined_response_text:
                    logger.info(
                        f"[AI3] Cycle 2: Successfully received refinement response with provider: {provider_name}"
                    )
                    break
                else:
                    logger.warning(
                        f"[AI3] Cycle 2: Provider {provider_name} returned empty response for refinement."
                    )
            except Exception as e:
                logger.error(
                    f"[AI3] Cycle 2: Failed refinement with provider {provider_name}: {str(e)}"
                )
            finally:
                if hasattr(provider, "close_session") and callable(
                    provider.close_session
                ):
                    await provider.close_session()
        except Exception as e:
            logger.error(
                f"[AI3] Cycle 2: Error initializing provider '{provider_name}' for refinement: {e}"
            )

    if refined_response_text:
        final_structure_json = clean_and_parse_json(refined_response_text)
        if final_structure_json:
            logger.info(
                "[AI3] Cycle 2: Structure refinement successful. Using refined structure."
            )
            return final_structure_json
        else:
            logger.warning(
                "[AI3] Cycle 2: Failed to parse refined JSON structure. Falling back to initial structure."
            )
            return initial_structure_json
    else:
        logger.warning(
            "[AI3] Cycle 2: Failed to get refinement response from providers. Using initial structure."
        )
        return initial_structure_json


async def send_structure_to_api(structure_obj: dict, target: Optional[str]):
    """Sends the final structure object to the MCP API."""
    api_url = f"{MCP_API_URL}/structure"
    payload = {"structure": structure_obj}
    if target:
        payload["target"] = target

    logger.info(f"[AI3 -> API] Sending final structure object to {api_url}")
    async with aiohttp.ClientSession() as client_session:
        try:
            async with client_session.post(api_url, json=payload, timeout=30) as resp:
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
        except asyncio.TimeoutError:
            logger.error(f"[AI3 -> API] Timeout sending structure to {api_url}.")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"[AI3 -> API] Connection error sending structure: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"[AI3 -> API] Unexpected error sending structure: {str(e)}")
            return False


async def send_ai3_report(status: str, details: dict = None):
    """Sends a status report from AI3 to the MCP API."""
    api_url = f"{MCP_API_URL}/ai3_report"
    payload = {"status": status}
    if details:
        payload["details"] = details
    logger.debug(f"[AI3 -> API] Sending report to {api_url}: Status={status}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json=payload, timeout=15) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.debug(f"[AI3 -> API] Report '{status}' sent successfully.")
                else:
                    logger.warning(
                        f"[AI3 -> API] Failed to send report '{status}'. Status: {resp.status}, Response: {response_text}"
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
    """Initiates collaboration with AI1 via MCP API for error handling."""
    api_url = f"{MCP_API_URL}/ai_collaboration"
    collaboration_request = {"error": error, "context": context, "ai": "AI3"}
    logger.info(
        f"[AI3 -> API] Initiating collaboration via {api_url} for error: {error[:100]}..."
    )
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                api_url, json=collaboration_request, timeout=20
            ) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info(
                        f"[AI3 -> API] Collaboration request sent successfully. Response: {response_text}"
                    )
                else:
                    logger.warning(
                        f"[AI3 -> API] Failed to send collaboration request. Status: {resp.status}, Response: {response_text}"
                    )
                return resp.status == 200
        except asyncio.TimeoutError:
            logger.warning("[AI3 -> API] Timeout initiating collaboration.")
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


async def create_files_from_structure(
    structure_obj: dict, repo: Repo
) -> Tuple[List[str], List[str]]:
    """Creates file structure from the JSON structure object."""
    base_path = repo.working_dir
    created_files = []
    skipped_files = []
    created_dirs = []

    async def _create_recursive(struct: dict, current_path: str):
        nonlocal created_files, skipped_files, created_dirs

        if not isinstance(struct, dict):
            logger.error(
                f"[AI3] Invalid structure object provided: Expected dict, got {type(struct)}"
            )
            return

        for key, value in struct.items():
            sanitized_key = re.sub(r'[<>:"/\\|?*]', "_", key).strip()
            sanitized_key = re.sub(r"\s+", "_", sanitized_key)
            if not sanitized_key:
                logger.warning(
                    f"[AI3] Skipping empty/invalid name: '{key}' in path '{current_path}'"
                )
                continue

            full_path = os.path.join(base_path, current_path, sanitized_key)
            rel_path = os.path.join(current_path, sanitized_key)

            try:
                parent_dir = os.path.dirname(full_path)
                if parent_dir != base_path and not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)
                    logger.info(
                        f"[AI3] Created parent directory: {os.path.relpath(parent_dir, base_path)}"
                    )

                if isinstance(value, dict):
                    if not os.path.exists(full_path):
                        os.makedirs(full_path, exist_ok=True)
                        created_dirs.append(full_path)
                        logger.info(f"[AI3] Created directory: {rel_path}")

                        if not value:
                            gitkeep_path = os.path.join(full_path, GITKEEP_FILENAME)
                            async with aiofiles.open(
                                gitkeep_path, "w", encoding="utf-8"
                            ) as f:
                                await f.write("")
                            created_files.append(gitkeep_path)
                            logger.info(
                                f"[AI3] Created .gitkeep in empty directory: {rel_path}"
                            )

                    await _create_recursive(value, rel_path)

                elif value is None or isinstance(value, str):
                    if not os.path.exists(full_path):
                        content = value if isinstance(value, str) else ""
                        if content and not content.endswith("\n"):
                            content += "\n"

                        async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                            await f.write(content)

                        created_files.append(full_path)
                        logger.info(f"[AI3] Created file: {rel_path}")
                    else:
                        skipped_files.append(full_path)
                        logger.info(f"[AI3] File already exists, skipping: {rel_path}")
                else:
                    logger.warning(
                        f"[AI3] Unknown data type '{type(value)}' for '{key}' in '{rel_path}'"
                    )

            except OSError as e:
                logger.error(f"[AI3] OS Error creating file/directory {rel_path}: {e}")
            except Exception as e:
                logger.error(f"[AI3] Error creating {rel_path}: {e}", exc_info=True)

    try:
        logger.info("[AI3] Starting file creation from structure...")
        await _create_recursive(structure_obj, "")

        if created_files:
            logger.info(f"[AI3] Committing {len(created_files)} created files...")
            _commit_changes(
                repo, created_files, "AI3: Created initial project structure"
            )
        else:
            logger.info("[AI3] No new files were created to commit.")

        logger.info(
            f"[AI3] File creation completed: {len(created_files)} files created, {len(skipped_files)} skipped"
        )
        await send_ai3_report(
            "structure_creation_completed",
            {"created_count": len(created_files), "skipped_count": len(skipped_files)},
        )
        return created_files, skipped_files
    except Exception as e:
        logger.error(f"[AI3] Error in create_files_from_structure: {e}", exc_info=True)
        await send_ai3_report("structure_creation_failed", {"error": str(e)})
        await initiate_collaboration(
            f"Failed during create_files_from_structure: {e}",
            f"Structure object keys: {list(structure_obj.keys()) if isinstance(structure_obj, dict) else 'Invalid structure'}",
        )
        return [], []


async def generate_initial_idea_md(
    target: str, ai3_config: Dict, provider_name: str
) -> Optional[str]:
    """Generates the initial detailed description for idea.md using an LLM."""
    logger.info(f"[AI3] Generating initial idea.md content for target: {target}")
    prompt = f'Based on the project target "{target}", create a detailed initial description for the project. This description will be stored in idea.md and used by other AI agents to understand the project goals and requirements. Describe the main features, target audience, and key functionalities. Be reasonably detailed but concise, as another AI will refine this later.'
    system_prompt = (
        "You are a helpful assistant tasked with creating project descriptions."
    )

    try:
        # Use the utility function to call the provider
        idea_content = await call_llm_provider(
            provider_name=provider_name,
            prompt=prompt,
            system_prompt=system_prompt,
            config=config,  # Pass the global config
            ai_config=ai3_config,  # Pass the specific AI config section
            service_name="ai3",  # Specify the service name for delay
        )

        if idea_content:
            logger.info("[AI3] Successfully generated initial idea.md content.")
            return idea_content
        else:
            logger.warning(
                "[AI3] LLM provider returned empty response for idea.md generation."
            )
            return None
    except Exception as e:
        logger.error(
            f"[AI3] Failed to generate initial idea.md content: {e}", exc_info=True
        )
        return None


class AI3:
    def __init__(self, config_data):
        self.config = config_data
        self.repo_dir = self.config.get("repo_dir", DEFAULT_REPO_DIR)
        self.target = self.config.get("target")
        logger.info(f"[AI3] Repository directory set to: {self.repo_dir}")
        logger.info(
            f"[AI3] Project Target: {self.target if self.target else 'Not specified'}"
        )
        self.repo = self._init_or_open_repo(self.repo_dir)
        self.session = None
        self.monitoring_stats = {
            "idle_workers_detected": 0,
            "task_requests_sent": 0,
            "successful_requests": 0,
            "error_fixes_requested": 0,
        }
        self.last_check_time = time.time()
        self._processed_run_ids = set()
        # Log Ollama configuration
        ollama_config = (
            self.config.get("ai_config", {})
            .get("ai3", {})
            .get("providers", ["ollama1"])[0]
        )
        endpoint = (
            self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
        )
        model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
        if endpoint and model:
            logger.info(
                f"[AI3-Ollama] Successfully initialized Ollama with endpoint '{endpoint}' and model '{model}'"
            )
        else:
            logger.error(
                "[AI3-Ollama] Failed to initialize Ollama: Configuration not found in config.json"
            )

    def _init_or_open_repo(self, repo_path: str) -> Repo:
        return _init_or_open_repo(repo_path)

    async def clear_and_init_repo(self):
        try:
            if os.path.exists(self.repo_dir):
                logger.info(
                    f"[AI3-Git] Removing existing repository directory: {self.repo_dir}"
                )
                shutil.rmtree(self.repo_dir)
                logger.info(f"[AI3-Git] Removed existing repository: {self.repo_dir}")

            # Create the directory before initializing Git repository
            logger.info(f"[AI3-Git] Creating new repository directory: {self.repo_dir}")
            os.makedirs(self.repo_dir, exist_ok=True)

            # Змінемо поточний каталог на self.repo_dir перед викликом Repo.init
            # щоб уникнути помилки "unable to get current working directory"
            current_dir = os.getcwd()
            os.chdir(self.repo_dir)

            try:
                self.repo = Repo.init(".")  # Ініціалізація в поточному каталозі
                logger.info(
                    f"[AI3-Git] Successfully initialized new repository at: {self.repo_dir}"
                )
            finally:
                # Повернення до попереднього робочого каталогу
                os.chdir(current_dir)

            gitignore_path = os.path.join(self.repo_dir, GITIGNORE_FILENAME)
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write("**/__pycache__/\n*.pyc\n.DS_Store\n")
                f.write("venv/\n.venv/\n")
                f.write(".idea/\n.vscode/\n")
                f.write("logs/\n*.log\n")
            logger.info(f"[AI3-Git] Created .gitignore at {gitignore_path}")

            _commit_changes(self.repo, [gitignore_path], "Initial commit (gitignore)")

            project_path = os.path.join(self.repo_dir, "project")
            if os.path.exists(project_path):
                logger.warning(
                    f"[AI3-Git] Found unexpected 'project/' directory at {project_path}. Removing it."
                )
                shutil.rmtree(project_path)

            await send_ai3_report("repo_cleared")
            return True
        except Exception as e:
            logger.error(
                f"[AI3-Git] Error clearing and initializing repository: {e}",
                exc_info=True,
            )
            await send_ai3_report("repo_clear_failed", {"error": str(e)})
            return False

    async def create_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            logger.info("[AI3] Created new aiohttp ClientSession.")

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
            logger.info("[AI3] Closed aiohttp ClientSession.")

    async def setup_structure(self):
        try:
            if not await wait_for_service(MCP_API_URL, timeout=60):
                logger.error(
                    "[AI3] MCP API did not become available. Aborting structure setup."
                )
                return False

            success = await self.clear_and_init_repo()
            if not success:
                logger.error(
                    "[AI3] Failed to initialize repository. Aborting structure setup."
                )
                return False

            logger.info("[AI3] Generating and refining project structure...")
            structure = await generate_structure(self.target)
            if not structure:
                logger.error(
                    "[AI3] Failed to generate structure. Aborting structure setup."
                )
                await send_ai3_report("structure_generation_failed")
                return False
            else:
                logger.info("[AI3] Structure generation/refinement successful.")

            created_files, skipped_files = await create_files_from_structure(
                structure, self.repo
            )

            if not created_files and not skipped_files:
                logger.warning(
                    "[AI3] No files were created or skipped from the generated structure. Structure might be empty or all files existed."
                )

            # --- NEW: Generate and commit idea.md ---
            logger.info("[AI3] Generating initial idea.md...")
            ai_config_base = self.config.get("ai_config", {})
            ai3_config = ai_config_base.get("ai3", {})
            # Use the first provider from structure_providers or a default
            structure_providers = ai3_config.get("structure_providers", ["codestral2"])
            provider_name_for_idea = (
                structure_providers[0] if structure_providers else "codestral2"
            )

            idea_content = await generate_initial_idea_md(
                self.target, ai3_config, provider_name_for_idea
            )
            idea_md_path = os.path.join(self.repo_dir, "idea.md")
            if idea_content:
                try:
                    async with aiofiles.open(idea_md_path, "w", encoding="utf-8") as f:
                        await f.write(idea_content)
                    logger.info(
                        f"[AI3] Successfully wrote initial content to {idea_md_path}"
                    )
                    _commit_changes(
                        self.repo, [idea_md_path], "AI3: Add initial idea.md"
                    )
                except Exception as e:
                    logger.error(
                        f"[AI3] Failed to write or commit idea.md: {e}", exc_info=True
                    )
                    # Decide if this is critical enough to abort
            else:
                logger.warning(
                    "[AI3] Failed to generate initial idea.md content. Proceeding without it."
                )
            # --- END NEW ---

            api_success = await send_structure_to_api(structure, self.target)
            if api_success:
                await send_ai3_report("structure_setup_completed")
                return True
            else:
                await send_ai3_report("structure_api_send_failed")
                return False

        except Exception as e:
            logger.error(f"[AI3] Error during structure setup: {e}", exc_info=True)
            await send_ai3_report("structure_setup_failed", {"error": str(e)})
            await self.close_session()  # Ensure session is closed on error
            return False

    async def start_monitoring(self):
        logger.info("[AI3] Starting AI3 monitoring service...")
        await self.create_session()
        tasks = [
            self.monitor_idle_workers(),
            self.monitor_system_errors(),
            self.monitor_github_actions(),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("[AI3] Monitoring tasks cancelled.")
        except Exception as e:
            logger.critical(f"[AI3] Monitoring service crashed: {e}", exc_info=True)
        finally:
            logger.info("[AI3] Monitoring service stopped.")
            await self.close_session()

    async def check_worker_status(self) -> Tuple[int, Dict[str, int]]:
        await self.create_session()
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        executor_queue_size = 0
        all_queue_sizes = {}
        try:
            async with self.session.get(
                f"{mcp_api_url}/worker_status", timeout=10
            ) as resp:
                if resp.status == 200:
                    status_data = await resp.json()
                    logger.debug(f"[AI3] Worker status received: {status_data}")
                    all_queue_sizes = status_data.get("queue_sizes", {})
                    executor_queue_size = all_queue_sizes.get("executor", 0)
                else:
                    logger.warning(
                        f"[AI3] Failed to get worker status: {resp.status} - {await resp.text()}"
                    )
        except asyncio.TimeoutError:
            logger.warning("[AI3] Timeout checking worker status.")
        except aiohttp.ClientError as e:
            logger.error(f"[AI3] Connection error checking worker status: {e}")
        except Exception as e:
            logger.error(f"[AI3] Error checking worker status: {e}", exc_info=True)
        return executor_queue_size, all_queue_sizes

    async def request_task_for_worker(self, worker_name: str):
        self.monitoring_stats["task_requests_sent"] += 1
        await self.create_session()
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        try:
            logger.info(f"[AI3 -> MCP] Requesting task for idle worker: {worker_name}")
            async with self.session.post(
                f"{mcp_api_url}/request_task_for_idle_worker",
                json={"worker": worker_name},
                timeout=15,
            ) as resp:
                if resp.status == 200:
                    response_data = await resp.json()
                    if response_data.get("task_assigned"):
                        self.monitoring_stats["successful_requests"] += 1
                        logger.info(
                            f"[AI3 -> MCP] Task successfully requested for worker: {worker_name}"
                        )
                    else:
                        logger.info(
                            f"[AI3 -> MCP] No suitable task found for worker: {worker_name}"
                        )
                elif resp.status == 404:
                    logger.warning(
                        f"[AI3 -> MCP] Worker '{worker_name}' not found or no tasks available."
                    )
                else:
                    logger.error(
                        f"[AI3 -> MCP] Error requesting task for worker {worker_name}: {resp.status} - {await resp.text()}"
                    )
        except asyncio.TimeoutError:
            logger.warning(
                f"[AI3 -> MCP] Timeout requesting task for worker {worker_name}."
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"[AI3 -> MCP] Connection error requesting task for worker {worker_name}: {e}"
            )
        except Exception as e:
            logger.error(
                f"[AI3 -> MCP] Error requesting task for worker {worker_name}: {e}",
                exc_info=True,
            )

    async def scan_logs_for_errors(self):
        """Scans configured log files for errors related to 'repo/' using Ollama."""
        logger.info("[AI3] Starting log scan for errors using Ollama")
        logs_dir = Path("logs")
        if not logs_dir.exists():
            logger.warning(
                "[AI3] Logs directory 'logs/' not found. Cannot scan for errors."
            )
            return

        try:
            ollama_config = (
                self.config.get("ai_config", {})
                .get("ai3", {})
                .get("providers", ["ollama1"])[0]
            )
            endpoint = (
                self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
            )
            model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
            if not endpoint or not model:
                logger.error(
                    "[AI3] Ollama configuration not found in config.json. Cannot proceed with log analysis."
                )
                return
            logger.info(
                f"[AI3] Ollama configured with endpoint '{endpoint}' and model '{model}'"
            )

            current_time = time.time()
            time_threshold = self.last_check_time
            self.last_check_time = current_time

            for log_file in logs_dir.glob("*.log"):
                if log_file.stat().st_mtime < time_threshold:
                    continue
                logger.info(f"[AI3] Scanning log file: {log_file.name}")
                try:
                    async with aiofiles.open(
                        log_file, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        lines = await f.readlines()
                    logger.info(f"[AI3] Read {len(lines)} lines from {log_file.name}")

                    lines_analyzed = 0
                    errors_detected = 0

                    for i, line in enumerate(lines):
                        line = line.strip()
                        if not line:
                            continue

                        lines_analyzed += 1

                        if i % 100 == 0:
                            logger.debug(
                                f"[AI3] Analyzing log line {i}/{len(lines)} in {log_file.name}"
                            )

                        prompt = (
                            f"Analyze this log line and determine if it indicates an error related to files in 'repo/':\n"
                            f"{line}\n"
                            f"Respond in JSON format: {{'is_error': bool, 'details': str}}"
                        )
                        analysis = await call_ollama(prompt, endpoint, model)
                        try:
                            result = json.loads(analysis)
                            if result.get("is_error", False):
                                errors_detected += 1
                                context_start = max(0, i - 3)
                                context_lines = [
                                    l.strip() for l in lines[context_start:i]
                                ]
                                context_str = "\n".join(context_lines)
                                logger.warning(
                                    f"[AI3] Ollama detected error in {log_file.name}: {line}"
                                )
                                logger.info(
                                    f"[AI3] Error details from Ollama: {result.get('details', 'No details provided')}"
                                )
                                report_sent = await self._report_system_error_to_ai1(
                                    str(log_file), line, context_str
                                )
                                if report_sent:
                                    logger.info(
                                        f"[AI3] Successfully reported error to AI1 from {log_file.name}"
                                    )
                                else:
                                    logger.warning(
                                        f"[AI3] Failed to report error to AI1 from {log_file.name}"
                                    )
                        except json.JSONDecodeError:
                            logger.warning(
                                f"[AI3] Invalid JSON response from Ollama for line: {line[:100]}..."
                            )
                            logger.debug(f"[AI3] Full invalid response: {analysis}")

                    logger.info(
                        f"[AI3] Completed analysis of {log_file.name}: {lines_analyzed} lines analyzed, {errors_detected} errors detected"
                    )
                except Exception as file_e:
                    logger.error(
                        f"[AI3] Error processing log file {log_file}: {file_e}"
                    )
        except Exception as e:
            logger.error(f"[AI3] Error scanning logs with Ollama: {e}", exc_info=True)

    async def update_file_and_commit(self, file_path_relative: str, content: str):
        """Updates a file in the repository and commits the change."""
        full_path = os.path.join(self.repo_dir, file_path_relative)
        try:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            # Write the file content
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)
            # Log and commit the changes
            logger.info(f"[AI3-Git] Updated file content: {full_path}")
            commit_message = f"AI3: Updated {file_path_relative}"
            _commit_changes(self.repo, [full_path], commit_message)
        except Exception as e:
            # Log error and initiate collaboration if update/commit fails
            logger.error(
                f"[AI3-Git] Failed to update or commit file {file_path_relative}: {e}",
                exc_info=True,
            )
            await initiate_collaboration(
                f"Failed to update/commit {file_path_relative}: {e}",
                f"Content length: {len(content)}",
            )

    async def handle_ai2_output(self, data):
        file_path = data.get("filename")
        content = data.get("code")
        if file_path and content is not None:
            if os.path.isabs(file_path):
                if file_path.startswith(os.path.abspath(self.repo_dir)):
                    file_path = os.path.relpath(file_path, self.repo_dir)
                else:
                    logger.warning(
                        f"[AI3] Received absolute file path outside repo: {file_path}. Skipping update."
                    )
                    return
            if file_path.startswith(REPO_PREFIX):
                file_path = file_path[len(REPO_PREFIX) :]
            logger.info(
                f"[AI3] Received AI2 output for file: {file_path}. Content length: {len(content)}"
            )
            await self.update_file_and_commit(file_path, content)
        else:
            logger.warning(
                f"[AI3] Failed to extract file path or content from AI2 report: {data.keys()}"
            )

    async def monitor_github_actions(self):
        logger.info("[AI3] Starting GitHub Actions monitoring...")
        github_token = os.getenv("GITHUB_TOKEN")
        github_repo_config = self.config.get("github_repo")
        github_repo_env = os.getenv("GITHUB_REPO_TO_MONITOR")
        if github_repo_config:
            github_repo = github_repo_config
            logger.info(f"[AI3] Using GitHub repo from config: {github_repo}")
        elif github_repo_env:
            github_repo = github_repo_env
            logger.info(
                f"[AI3] Using GitHub repo from GITHUB_REPO_TO_MONITOR env var: {github_repo}"
            )
        else:
            logger.warning(
                "[AI3] Warning: GitHub repository not configured. Cannot monitor GitHub Actions."
            )
            return
        if not github_token:
            logger.warning(
                "[AI3] Warning: GITHUB_TOKEN not configured. Cannot monitor GitHub Actions."
            )
            return
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api_base_url = f"https://api.github.com/repos/{github_repo}"
        check_interval = self.config.get("github_actions_check_interval", 60)
        while True:
            try:
                await self.create_session()
                logger.debug(f"[AI3] Checking GitHub Actions runs for {github_repo}...")
                async with self.session.get(
                    f"{api_base_url}/actions/runs",
                    headers=headers,
                    params={"per_page": "5", "status": "completed"},
                ) as response:
                    if response.status == 200:
                        runs_data = await response.json()
                        workflow_runs = runs_data.get("workflow_runs", [])
                        logger.debug(
                            f"[AI3] Fetched {len(workflow_runs)} completed workflow runs."
                        )
                        processed_this_cycle = False
                        for run in sorted(
                            workflow_runs, key=lambda x: x["created_at"], reverse=True
                        ):
                            run_id = run.get("id")
                            run_conclusion = run.get("conclusion")
                            if run_id and self._is_new_completed_run(run_id):
                                logger.info(
                                    f"[AI3] Found new completed GitHub Actions run: ID={run_id}, Conclusion={run_conclusion}"
                                )
                                await self._analyze_workflow_run(
                                    run_id, run_conclusion, headers, api_base_url
                                )
                                processed_this_cycle = True
                                break
                        if not processed_this_cycle:
                            logger.debug(
                                "[AI3] No new completed GitHub Actions runs found this cycle."
                            )
                    elif response.status == 404:
                        logger.error(
                            f"[AI3] GitHub repository '{github_repo}' not found or access denied. Stopping GitHub monitoring."
                        )
                        break
                    elif response.status == 401:
                        logger.error(
                            "[AI3] GitHub API authentication failed (Invalid GITHUB_TOKEN?). Stopping GitHub monitoring."
                        )
                        break
                    else:
                        logger.warning(
                            f"[AI3] Failed to fetch GitHub Actions runs: Status {response.status} - {await response.text()}"
                        )
            except aiohttp.ClientConnectorError as e:
                logger.error(
                    f"[AI3] Connection error during GitHub Actions monitoring: {e}"
                )
            except asyncio.TimeoutError:
                logger.warning("[AI3] Timeout during GitHub Actions check.")
            except Exception as e:
                logger.error(
                    f"[AI3] Error in GitHub Actions monitoring loop: {e}", exc_info=True
                )
            await asyncio.sleep(check_interval)

    def _is_new_completed_run(self, run_id: int) -> bool:
        if run_id in self._processed_run_ids:
            return False
        else:
            if len(self._processed_run_ids) > 1000:
                self._processed_run_ids.pop()
            self._processed_run_ids.add(run_id)
            return True

    async def _analyze_workflow_run(
        self, run_id, run_conclusion, headers, api_base_url
    ):
        logger.info(
            f"[AI3] Analyzing workflow run ID: {run_id}, Conclusion: {run_conclusion}"
        )
        job_logs = ""
        try:
            await self.create_session()
            async with self.session.get(
                f"{api_base_url}/actions/runs/{run_id}/jobs",
                headers=headers,
                timeout=20,
            ) as response:
                if response.status == 200:
                    jobs_data = await response.json()
                    for job in jobs_data.get("jobs", []):
                        job_name_lower = job.get("name", "").lower()
                        if (
                            "test" in job_name_lower
                            or "build" in job_name_lower
                            or "lint" in job_name_lower
                        ):
                            job_id = job.get("id")
                            log_url = f"{api_base_url}/actions/jobs/{job_id}/logs"
                            async with self.session.get(
                                log_url, headers=headers, timeout=60
                            ) as log_response:
                                if (
                                    log_response.status == 200
                                    and "application/zip"
                                    not in log_response.headers.get("Content-Type", "")
                                ):
                                    job_logs = await log_response.text(
                                        encoding="utf-8", errors="replace"
                                    )
                                    logger.info(
                                        f"[AI3] Fetched logs for job {job_id}. Length: {len(job_logs)} chars."
                                    )
                                    break
        except Exception as e:
            logger.error(
                f"[AI3] Error fetching logs for run {run_id}: {e}", exc_info=True
            )

        if not job_logs:
            logger.warning(
                f"[AI3] No logs available for run {run_id}. Using run conclusion: {run_conclusion}"
            )
            recommendation = "rework" if run_conclusion == "failure" else "accept"
            context = {
                "run_url": f"https://github.com/{self.config.get('github_repo')}/actions/runs/{run_id}"
            }
            await self._send_test_recommendation(recommendation, context)
            return

        ollama_config = (
            self.config.get("ai_config", {})
            .get("ai3", {})
            .get("providers", ["ollama1"])[0]
        )
        endpoint = (
            self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
        )
        model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
        if not endpoint or not model:
            logger.error(
                "[AI3] Ollama configuration not found. Cannot analyze GitHub Actions logs."
            )
            return
        logger.info(
            f"[AI3] Analyzing GitHub Actions logs using Ollama with endpoint '{endpoint}' and model '{model}'"
        )

        prompt = (
            f"Analyze the following GitHub Actions logs and determine if there are test or linting errors:\n"
            f"{job_logs[:4000]}\n"
            f"Respond in JSON format: {{'recommendation': 'accept'|'rework', 'failed_files': list, 'details': str}}"
        )
        analysis = await call_ollama(prompt, endpoint, model)
        try:
            result = json.loads(analysis)
            recommendation = result.get("recommendation", "rework")
            failed_files = result.get("failed_files", [])
            details = result.get("details", "No details provided")
            context = {
                "failed_files": failed_files,
                "details": details,
                "run_url": f"https://github.com/{self.config.get('github_repo')}/actions/runs/{run_id}",
            }
            logger.info(
                f"[AI3] Ollama recommendation for run {run_id}: {recommendation}, Failed files: {failed_files}"
            )
            logger.debug(f"[AI3] Recommendation details: {details}")
            await self._send_test_recommendation(recommendation, context)
        except json.JSONDecodeError:
            logger.error(
                f"[AI3] Invalid JSON response from Ollama for run {run_id}: {analysis}"
            )

    async def _send_test_recommendation(self, recommendation: str, context: dict):
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        try:
            await self.create_session()
            recommendation_data = {"recommendation": recommendation, "context": context}
            logger.info(
                f"[AI3 -> MCP] Sending test recommendation: {recommendation}, Context keys: {list(context.keys())}"
            )
            async with self.session.post(
                f"{mcp_api_url}/test_recommendation",
                json=recommendation_data,
                timeout=15,
            ) as response:
                resp_text = await response.text()
                if response.status == 200:
                    logger.info(
                        f"[AI3 -> MCP] Successfully sent test recommendation '{recommendation}'. Response: {resp_text}"
                    )
                else:
                    logger.error(
                        f"[AI3 -> MCP] Error sending test recommendation: {response.status} - {resp_text}"
                    )
        except asyncio.TimeoutError:
            logger.error("[AI3 -> MCP] Timeout sending test recommendation.")
        except aiohttp.ClientError as e:
            logger.error(
                f"[AI3 -> MCP] Connection error sending test recommendation: {e}"
            )
        except Exception as e:
            logger.error(
                f"[AI3 -> MCP] Failed to send test recommendation: {e}", exc_info=True
            )

    async def monitor_idle_workers(self):
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        check_interval = self.config.get("idle_worker_check_interval", 30)
        logger.info("[AI3] Starting idle worker monitoring.")
        while True:
            try:
                await self.create_session()
                async with self.session.get(
                    f"{mcp_api_url}/worker_status", timeout=10
                ) as response:
                    if response.status == 200:
                        status_data = await response.json()
                        idle_workers = status_data.get("idle_workers", [])
                        if idle_workers:
                            logger.info(f"[AI3] Detected idle workers: {idle_workers}")
                            self.monitoring_stats["idle_workers_detected"] += len(
                                idle_workers
                            )
                            for worker_name in idle_workers:
                                await self.request_task_for_worker(worker_name)
                        else:
                            logger.debug("[AI3] No idle workers detected.")
                    else:
                        logger.warning(
                            f"[AI3] Failed to get worker status: {response.status} - {await response.text()}"
                        )
            except asyncio.TimeoutError:
                logger.warning(
                    "[AI3] Timeout checking worker status. Falling back to log analysis."
                )
                await self._check_logs_for_idle_workers()
            except aiohttp.ClientConnectorError as e:
                logger.error(
                    f"[AI3] Connection error while checking worker status: {e}. Falling back to log analysis."
                )
                await self._check_logs_for_idle_workers()
            except Exception as e:
                logger.error(f"[AI3] Error monitoring idle workers: {e}", exc_info=True)
            await asyncio.sleep(check_interval)

    async def _request_task_for_idle_worker(self, role: str):
        await self.request_task_for_worker(role)

    async def _check_logs_for_idle_workers(self):
        mcp_log_file = self.config.get("log_file", "logs/mcp.log")
        try:
            if not os.path.exists(mcp_log_file):
                logger.warning(
                    f"[AI3] Fallback: MCP log file not found at {mcp_log_file}"
                )
                return
            logger.debug(
                "[AI3] Fallback: Checking MCP logs for idle workers (empty queues)."
            )
            async with aiofiles.open(
                mcp_log_file, "r", encoding="utf-8", errors="ignore"
            ) as f:
                lines = await f.readlines()
                recent_lines = lines[-50:]
                for line in recent_lines:
                    if "Queue is empty for role" in line:
                        match = re.search(r"Queue is empty for role: (\w+)", line)
                        role_to_request = match.group(1) if match else "any"
                        logger.info(
                            f"[AI3] Fallback: Detected empty queue message in MCP log for role '{role_to_request}'. Requesting task."
                        )
                        await self.request_task_for_worker(role_to_request)
                        break
        except Exception as e:
            logger.error(
                f"[AI3] Error checking logs for idle workers: {e}", exc_info=True
            )

    async def _report_system_error_to_ai1(
        self, log_file: str, error_line: str, context: str
    ) -> bool:
        """Reports a system error to AI1 using the standardized communication protocol"""
        try:
            # Use the new communication module instead of direct API calls
            await ai_comm.send_error_report(
                sender="ai3",
                error_type="system_error",
                message=error_line,
                file_path=log_file,
                stack_trace=context,
                severity=ai_comm.Priority.HIGH,
            )
            logger.info(
                f"[AI3 -> AI1] Successfully reported system error to AI1 from {log_file}"
            )
            return True
        except Exception as e:
            logger.error(
                f"[AI3 -> AI1] Failed to send system error report: {e}", exc_info=True
            )
            return False

    async def send_queue_info_to_ai1(self, queue_sizes):
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        try:
            await self.create_session()
            payload = {
                "source": "AI3",
                "type": "queue_rebalance_request",
                "details": {
                    "queue_sizes": queue_sizes,
                    "timestamp": datetime.now().isoformat(),
                },
            }
            logger.info(f"[AI3 -> AI1] Sending queue info to AI1: {queue_sizes}")
            async with self.session.post(
                f"{mcp_api_url}/ai_collaboration", json=payload, timeout=15
            ) as response:
                if response.status == 200:
                    logger.info("[AI3 -> AI1] Queue info sent successfully.")
                    return True
                else:
                    logger.error(
                        f"[AI3 -> AI1] Failed to send queue info: {response.status} - {await response.text()}"
                    )
                    return False
        except asyncio.TimeoutError:
            logger.warning("[AI3 -> AI1] Timeout sending queue info.")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"[AI3 -> AI1] Connection error sending queue info: {e}")
            return False
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Failed to send queue info: {e}", exc_info=True)
            return False

    async def run(self):
        logger.info("[AI3] Starting AI3 background monitoring tasks...")
        logger.info(
            "[AI3] Structure phase complete. Switching to monitoring mode (using APIs, not structure providers)."
        )
        await self.create_session()
        tasks = [
            asyncio.create_task(self.monitor_idle_workers(), name="IdleWorkerMonitor"),
            asyncio.create_task(
                self.monitor_system_errors(), name="SystemErrorMonitor"
            ),
            asyncio.create_task(
                self.monitor_github_actions(), name="GitHubActionsMonitor"
            ),
        ]
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    result = task.result()
                    logger.warning(
                        f"[AI3] Monitoring task {task.get_name()} completed unexpectedly."
                    )
                except Exception as task_e:
                    logger.critical(
                        f"[AI3] Monitoring task {task.get_name()} failed: {task_e}",
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            logger.info("[AI3] AI3 run loop cancelled.")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.critical(
                f"[AI3] An error occurred in AI3 main run loop: {e}", exc_info=True
            )
        finally:
            await self.close_session()
            logger.info("[AI3] AI3 background tasks stopped.")

    async def monitor_system_errors(self):
        """Monitors for system-level errors or critical failures."""
        logger.info("[AI3] System error monitor started.")
        check_interval = self.config.get("error_check_interval", 300)
        error_patterns = {}  # Track error patterns for prediction

        while True:
            try:
                # Run automated tests
                test_results = await self._run_automated_tests()

                # Analyze error patterns
                if test_results and test_results.get("failing_tests"):
                    for test_file, failures in test_results["failing_tests"].items():
                        error_key = f"{test_file}:{str(failures)}"
                        if error_key in error_patterns:
                            error_patterns[error_key]["count"] += 1
                            if error_patterns[error_key]["count"] >= 3:
                                # Pattern detected - attempt proactive fix
                                await self._attempt_pattern_based_fix(
                                    test_file, error_patterns[error_key]
                                )
                        else:
                            error_patterns[error_key] = {
                                "count": 1,
                                "first_seen": datetime.now(),
                                "failures": failures,
                            }

                # Scan logs for errors with context analysis
                await self._scan_logs_with_context()

                # Check system health metrics
                system_metrics = await self._check_system_health()
                if system_metrics.get("requires_attention"):
                    await self._send_system_health_alert(system_metrics)

                # Check queue sizes and balance
                executor_queue_size, all_queue_sizes = await self.check_worker_status()
                if self._detect_queue_imbalance(all_queue_sizes):
                    await self.send_queue_info_to_ai1(all_queue_sizes)
                    await self._rebalance_queues(all_queue_sizes)

                # Cleanup old patterns
                current_time = datetime.now()
                error_patterns = {
                    k: v
                    for k, v in error_patterns.items()
                    if (current_time - v["first_seen"]).total_seconds() < 86400
                }  # 24 hour retention

                await asyncio.sleep(check_interval)

            except asyncio.CancelledError:
                logger.info("[AI3] System error monitor stopped.")
                break
            except Exception as e:
                logger.error(f"[AI3] Error in system error monitor: {e}", exc_info=True)
                await asyncio.sleep(300)  # Wait longer after an error

    async def _run_automated_tests(self):
        """Run automated tests and analyze results with enhanced error recovery"""
        from utils import TestRunner

        logger.info("[AI3] Starting automated test execution...")
        try:
            # Initialize the test runner with retries
            test_runner = TestRunner(repo_dir=self.repo_dir)
            test_results = None
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries and not test_results:
                try:
                    test_results = test_runner.run_tests()
                    break
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"[AI3] Test run attempt {retry_count} failed: {e}")
                    await asyncio.sleep(5)  # Wait before retry

            if not test_results:
                logger.error("[AI3] All test run attempts failed")
                return False

            # Check for failing tests
            failing_tests = {
                path: result
                for path, result in test_results.items()
                if not result.success
            }

            if failing_tests:
                logger.info(
                    f"[AI3] Found {len(failing_tests)} failing tests. Starting self-healing process..."
                )
                await self._attempt_test_fixes(failing_tests)

                # Re-run failed tests after fixes
                retest_results = test_runner.run_specific_tests(
                    list(failing_tests.keys())
                )
                still_failing = {
                    path: result
                    for path, result in retest_results.items()
                    if not result.success
                }

                if still_failing:
                    logger.warning(
                        f"[AI3] {len(still_failing)} tests still failing after fixes"
                    )
                    # Send to AI1 for deeper analysis
                    await self._send_test_insights_to_ai1(
                        {
                            "failing_tests": still_failing,
                            "fix_attempted": True,
                            "initial_failures": len(failing_tests),
                            "remaining_failures": len(still_failing),
                        }
                    )
                else:
                    logger.info("[AI3] All failing tests successfully fixed!")
            else:
                logger.info("[AI3] All tests passed successfully.")

            # Run linters with pattern analysis
            lint_results = test_runner.run_linters()
            failing_lints = {
                path: result
                for path, result in lint_results.items()
                if not result.success
            }

            if failing_lints:
                logger.info(
                    f"[AI3] Found {len(failing_lints)} files with linting issues. Starting pattern analysis..."
                )
                lint_patterns = self._analyze_lint_patterns(failing_lints)
                await self._attempt_lint_fixes(failing_lints, lint_patterns)

                # Re-run linting after fixes
                recheck_results = test_runner.run_specific_lints(
                    list(failing_lints.keys())
                )
                still_failing_lints = {
                    path: result
                    for path, result in recheck_results.items()
                    if not result.success
                }

                if still_failing_lints:
                    logger.warning(
                        f"[AI3] {len(still_failing_lints)} files still have linting issues after fixes"
                    )
                else:
                    logger.info("[AI3] All linting issues successfully fixed!")
            else:
                logger.info("[AI3] All files pass linting checks.")

            # Generate comprehensive test report with insights
            report = {
                "test_results": {
                    "total_tests": len(test_results),
                    "failing_tests": len(failing_tests),
                    "fixed_tests": (
                        len(failing_tests) - len(still_failing) if failing_tests else 0
                    ),
                    "remaining_failures": len(still_failing) if failing_tests else 0,
                },
                "lint_results": {
                    "total_files": len(lint_results),
                    "failing_files": len(failing_lints),
                    "fixed_files": (
                        len(failing_lints) - len(still_failing_lints)
                        if failing_lints
                        else 0
                    ),
                    "remaining_issues": (
                        len(still_failing_lints) if failing_lints else 0
                    ),
                },
                "insights": self._generate_test_insights(test_results, lint_results),
            }

            # Send insights to AI1 for planning if needed
            if report["insights"]:
                await self._send_test_insights_to_ai1(report["insights"])

            return True

        except Exception as e:
            logger.error(f"[AI3] Error running automated tests: {e}", exc_info=True)
            return False

    def _analyze_lint_patterns(self, failing_lints):
        """Analyze patterns in linting failures to guide fixes"""
        patterns = {}
        try:
            for file_path, result in failing_lints.items():
                for failure in result.failures:
                    pattern_key = self._extract_lint_pattern(failure)
                    if pattern_key:
                        if pattern_key not in patterns:
                            patterns[pattern_key] = {
                                "count": 0,
                                "files": set(),
                                "example": failure,
                            }
                        patterns[pattern_key]["count"] += 1
                        patterns[pattern_key]["files"].add(file_path)

            # Sort patterns by frequency
            sorted_patterns = sorted(
                patterns.items(), key=lambda x: x[1]["count"], reverse=True
            )
            return {k: v for k, v in sorted_patterns}

        except Exception as e:
            logger.error(f"[AI3] Error analyzing lint patterns: {e}", exc_info=True)
            return {}

    def _extract_lint_pattern(self, failure_text):
        """Extract a pattern key from a linting failure"""
        try:
            # Common linting error patterns
            patterns = [
                (r"missing type annotation", "missing_type"),
                (r"unused (variable|import)", "unused_code"),
                (r"line too long", "line_length"),
                (r"indentation", "indentation"),
                (r"missing docstring", "missing_docs"),
                (r"trailing whitespace", "whitespace"),
                (r"undefined name", "undefined_name"),
            ]

            for pattern, key in patterns:
                if re.search(pattern, failure_text, re.IGNORECASE):
                    return key

            return "other"

        except Exception as e:
            logger.error(f"[AI3] Error extracting lint pattern: {e}", exc_info=True)
            return None

    def _generate_test_insights(self, test_results, lint_results):
        """Generate insights from test and lint results"""
        insights = []
        try:
            # Analyze test patterns
            if test_results:
                test_patterns = self._analyze_test_failure_patterns(test_results)
                for pattern, data in test_patterns.items():
                    if data["count"] >= 2:  # Pattern occurs multiple times
                        insights.append(
                            {
                                "type": "test_pattern",
                                "pattern": pattern,
                                "frequency": data["count"],
                                "affected_files": list(data["files"]),
                                "priority": "high" if data["count"] > 3 else "medium",
                            }
                        )

            # Analyze lint patterns
            if lint_results:
                lint_patterns = self._analyze_lint_patterns(lint_results)
                for pattern, data in lint_patterns.items():
                    if data["count"] >= 3:  # Common linting issue
                        insights.append(
                            {
                                "type": "lint_pattern",
                                "pattern": pattern,
                                "frequency": data["count"],
                                "affected_files": list(data["files"]),
                                "priority": "high" if data["count"] > 5 else "medium",
                            }
                        )

            return insights

        except Exception as e:
            logger.error(f"[AI3] Error generating test insights: {e}", exc_info=True)
            return []

    async def start_background_tasks(self):
        """Starts all background monitoring tasks."""
        logger.info("[AI3] Starting AI3 background monitoring tasks...")
        if not hasattr(self, "background_tasks"):
            self.background_tasks = []

        # Ensure session is created before starting tasks that might use it
        await self.ensure_session()

        # Start idle worker monitor
        idle_monitor_task = asyncio.create_task(
            self.monitor_idle_workers(), name="IdleWorkerMonitor"
        )
        self.background_tasks.append(idle_monitor_task)
        logger.info("[AI3] Idle worker monitor task created.")

        # Start system error monitor if the method exists
        if hasattr(self, "monitor_system_errors"):
            error_monitor_task = asyncio.create_task(
                self.monitor_system_errors(), name="SystemErrorMonitor"
            )  # <--- Запуск завдання моніторингу помилок
            self.background_tasks.append(error_monitor_task)
            logger.info("[AI3] System error monitor task created.")
        else:
            logger.warning(
                "[AI3] 'monitor_system_errors' method not found. System error monitoring disabled."
            )

        # Add other monitoring tasks here if needed
        # e.g., asyncio.create_task(self.monitor_subtask_progress(), name="SubtaskProgressMonitor")

        await asyncio.sleep(0.1)  # Allow tasks to potentially start up/log messages
        logger.info(
            f"[AI3] Total background tasks started: {len(self.background_tasks)}"
        )

    async def ensure_session(self):
        """Ensures an active aiohttp session exists and is available."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            logger.info("[AI3] Created new aiohttp ClientSession.")

        # Also ensure we have a message bus instance ready
        self.message_bus = await ai_comm.get_message_bus()
        return self.session


async def main():
    config_data = load_config()
    ai3 = AI3(config_data)
    logger.info("[AI3] Starting structure setup...")
    setup_successful = await ai3.setup_structure()
    if setup_successful:
        logger.info(
            "[AI3] Structure setup completed successfully. Starting background tasks."
        )
        await ai3.run()
    else:
        logger.error(
            "[AI3] Structure setup failed. AI3 will not start background monitoring tasks."
        )
        await ai3.close_session()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[AI3] AI3 stopped by user.")
    except Exception as e:
        logger.critical(f"[AI3] AI3 main execution failed: {e}", exc_info=True)


async def call_ollama(
    prompt: str,
    endpoint: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str:
    """Calls Ollama API to generate a response based on the prompt."""
    logger.info(
        f"[AI3-Ollama] Calling Ollama API with model '{model}' at endpoint '{endpoint}'"
    )
    logger.debug(
        f"[AI3-Ollama] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        logger.debug(
            f"[AI3-Ollama] Sending request with max_tokens={max_tokens}, temperature={temperature}"
        )
        start_time = time.time()
        response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=10)
        response.raise_for_status()
        result = response.json().get("response", "")
        elapsed_time = time.time() - start_time
        logger.info(
            f"[AI3-Ollama] Response received in {elapsed_time:.2f}s: {result[:100]}{'...' if len(result) > 100 else ''}"
        )
        return result
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[AI3-Ollama] Connection error to Ollama API: {e}")
        return ""
    except requests.exceptions.Timeout as e:
        logger.error(
            f"[AI3-Ollama] Timeout calling Ollama API after {e.args[0] if e.args else '?'}s"
        )
        return ""
    except requests.exceptions.HTTPError as e:
        logger.error(
            f"[AI3-Ollama] HTTP error from Ollama API: {e} (Status code: {e.response.status_code if hasattr(e, 'response') else 'unknown'})"
        )
        return ""
    except json.JSONDecodeError as e:
        logger.error(f"[AI3-Ollama] Invalid JSON response from Ollama API: {e}")
        return ""
    except Exception as e:
        logger.error(
            f"[AI3-Ollama] Unexpected error calling Ollama: {e}", exc_info=True
        )
        return ""


# Add the missing wait_for_service function
async def wait_for_service(service_url: str, timeout: int = 60) -> bool:
    """Wait for a service to become available by polling its URL.

    Args:
        service_url: The URL of the service to check
        timeout: Maximum time to wait in seconds

    Returns:
        bool: True if service became available, False if timeout occurred
    """
    logger.info(f"[AI3] Waiting for service at {service_url} (timeout: {timeout}s)")
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        while time.time() - start_time < timeout:
            try:
                async with session.get(service_url, timeout=5) as response:
                    if response.status == 200:
                        logger.info(f"[AI3] Service at {service_url} is available")
                        return True
                    else:
                        logger.debug(
                            f"[AI3] Service check: Status {response.status} from {service_url}"
                        )
            except (
                aiohttp.ClientConnectorError,
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ):
                pass  # Expected during startup, don't log each failure
            except Exception as e:
                logger.debug(f"[AI3] Error checking service: {e}")

            # Check every second
            await asyncio.sleep(1)

    logger.warning(
        f"[AI3] Timeout waiting for service at {service_url} after {timeout}s"
    )
    return False


class CodeAnalyzer:
    """Advanced code analysis and pattern recognition for AI3"""

    def __init__(self):
        self.pattern_detectors = {
            "security": self._detect_security_patterns,
            "performance": self._detect_performance_patterns,
            "maintainability": self._detect_maintainability_patterns,
            "reliability": self._detect_reliability_patterns,
            "testability": self._detect_testability_patterns,
        }
        self.quality_metrics = {
            "complexity": self._calculate_complexity,
            "cohesion": self._calculate_cohesion,
            "coupling": self._calculate_coupling,
            "test_coverage": self._calculate_test_coverage,
        }
        self.language_specific = {
            ".py": self._analyze_python,
            ".js": self._analyze_javascript,
            ".ts": self._analyze_typescript,
            ".go": self._analyze_go,
            ".java": self._analyze_java,
            ".cpp": self._analyze_cpp,
            ".rs": self._analyze_rust,
        }

    async def analyze_code(self, file_path: str, content: str) -> Dict[str, Any]:
        """Perform comprehensive code analysis"""
        try:
            ext = os.path.splitext(file_path)[1].lower()

            # Run all pattern detectors
            patterns = {}
            for pattern_type, detector in self.pattern_detectors.items():
                patterns[pattern_type] = await detector(content, ext)

            # Calculate quality metrics
            metrics = {}
            for metric_name, calculator in self.quality_metrics.items():
                metrics[metric_name] = await calculator(content, ext)

            # Run language-specific analysis
            language_analysis = {}
            if ext in self.language_specific:
                language_analysis = await self.language_specific[ext](content)

            return {
                "patterns": patterns,
                "metrics": metrics,
                "language_analysis": language_analysis,
                "recommendations": await self._generate_recommendations(
                    patterns, metrics, language_analysis
                ),
            }
        except Exception as e:
            logger.error(f"Error analyzing code: {e}")
            return {}

    async def _detect_security_patterns(
        self, content: str, ext: str
    ) -> List[Dict[str, Any]]:
        """Detect security-related patterns and potential vulnerabilities"""
        findings = []

        # SQL Injection patterns
        sql_patterns = [
            r'execute\s*\(\s*[\'"].*?\%.*?[\'"]\s*\)',
            r'cursor\.execute\s*\(\s*[\'"].*?\+.*?[\'"]\s*\)',
            r'db\.query\s*\(\s*[\'"].*?\+.*?[\'"]\s*\)',
        ]

        # Command Injection patterns
        cmd_patterns = [
            r"exec\s*\(\s*.*?\+.*?\s*\)",
            r"spawn\s*\(\s*.*?\+.*?\s*\)",
            r"system\s*\(\s*.*?\+.*?\s*\)",
        ]

        # XSS patterns
        xss_patterns = [r"innerHTML\s*=", r"document\.write\s*\(", r"eval\s*\("]

        # Check for hardcoded secrets
        secret_patterns = [
            r'password\s*=\s*[\'"][^\'"]+[\'"]',
            r'secret\s*=\s*[\'"][^\'"]+[\'"]',
            r'api[_-]?key\s*=\s*[\'"][^\'"]+[\'"]',
        ]

        for pattern in sql_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                findings.append(
                    {
                        "type": "security",
                        "subtype": "sql_injection",
                        "severity": "high",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": "Potential SQL injection vulnerability detected",
                    }
                )

        for pattern in cmd_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                findings.append(
                    {
                        "type": "security",
                        "subtype": "command_injection",
                        "severity": "high",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": "Potential command injection vulnerability detected",
                    }
                )

        for pattern in xss_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                findings.append(
                    {
                        "type": "security",
                        "subtype": "xss",
                        "severity": "medium",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": "Potential XSS vulnerability detected",
                    }
                )

        for pattern in secret_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                findings.append(
                    {
                        "type": "security",
                        "subtype": "hardcoded_secret",
                        "severity": "high",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": "Hardcoded secret detected",
                    }
                )

        return findings

    async def _detect_performance_patterns(
        self, content: str, ext: str
    ) -> List[Dict[str, Any]]:
        """Detect performance-related patterns and potential issues"""
        findings = []

        # Nested loop patterns
        nested_loop_pattern = r"for.*?\{.*?for.*?\{.*?\}"
        matches = re.finditer(nested_loop_pattern, content, re.DOTALL)
        for match in matches:
            findings.append(
                {
                    "type": "performance",
                    "subtype": "nested_loops",
                    "severity": "medium",
                    "line": content.count("\n", 0, match.start()) + 1,
                    "description": "Nested loops detected - potential O(n²) complexity",
                }
            )

        # Memory leak patterns (language specific)
        if ext == ".cpp":
            memory_patterns = [r"new\s+\w+(?!\s*delete)", r"malloc\s*\((?!\s*free)"]
            for pattern in memory_patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    findings.append(
                        {
                            "type": "performance",
                            "subtype": "memory_leak",
                            "severity": "high",
                            "line": content.count("\n", 0, match.start()) + 1,
                            "description": "Potential memory leak detected",
                        }
                    )

        # Large object creation in loops
        object_creation_pattern = r"for.*?\{.*?new\s+\w+.*?\}"
        matches = re.finditer(object_creation_pattern, content, re.DOTALL)
        for match in matches:
            findings.append(
                {
                    "type": "performance",
                    "subtype": "object_creation_in_loop",
                    "severity": "low",
                    "line": content.count("\n", 0, match.start()) + 1,
                    "description": "Object creation inside loop - consider moving outside if possible",
                }
            )

        return findings

    async def _detect_maintainability_patterns(
        self, content: str, ext: str
    ) -> List[Dict[str, Any]]:
        """Detect maintainability-related patterns and issues"""
        findings = []

        # Long method detection
        method_pattern = r"(def|function|func)\s+\w+\s*\([^)]*\)\s*\{?[^\}]*\}?"
        matches = re.finditer(method_pattern, content, re.DOTALL)
        for match in matches:
            method_content = match.group(0)
            lines = method_content.count("\n")
            if lines > 30:
                findings.append(
                    {
                        "type": "maintainability",
                        "subtype": "long_method",
                        "severity": "medium",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": f"Long method detected ({lines} lines) - consider breaking down",
                    }
                )

        # High parameter count
        param_pattern = r"(def|function|func)\s+\w+\s*\(([^)]*)\)"
        matches = re.finditer(param_pattern, content)
        for match in matches:
            params = match.group(2).split(",")
            if len(params) > 5:
                findings.append(
                    {
                        "type": "maintainability",
                        "subtype": "high_parameter_count",
                        "severity": "low",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": f"Method has {len(params)} parameters - consider using parameter object",
                    }
                )

        # Duplicate code blocks
        code_blocks = re.findall(r"\{[^\}]+\}", content)
        for i, block1 in enumerate(code_blocks):
            for block2 in code_blocks[i + 1 :]:
                if len(block1) > 50 and block1 == block2:
                    findings.append(
                        {
                            "type": "maintainability",
                            "subtype": "duplicate_code",
                            "severity": "medium",
                            "line": content.count("\n", 0, content.find(block1)) + 1,
                            "description": "Duplicate code block detected",
                        }
                    )

        return findings

    async def _detect_reliability_patterns(
        self, content: str, ext: str
    ) -> List[Dict[str, Any]]:
        """Detect reliability-related patterns and issues"""
        findings = []

        # Empty catch blocks
        catch_pattern = r"catch\s*\([^)]*\)\s*\{\s*\}"
        matches = re.finditer(catch_pattern, content)
        for match in matches:
            findings.append(
                {
                    "type": "reliability",
                    "subtype": "empty_catch",
                    "severity": "high",
                    "line": content.count("\n", 0, match.start()) + 1,
                    "description": "Empty catch block detected",
                }
            )

        # Resource handling patterns
        if ext in [".py", ".js", ".ts"]:
            resource_patterns = [
                r"open\s*\([^)]+\)(?!\s*with)",
                r"connect\s*\([^)]+\)(?!\s*with)",
            ]
            for pattern in resource_patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    findings.append(
                        {
                            "type": "reliability",
                            "subtype": "resource_leak",
                            "severity": "medium",
                            "line": content.count("\n", 0, match.start()) + 1,
                            "description": "Resource not properly managed - consider using context manager",
                        }
                    )

        # Null checks missing
        if ext in [".java", ".ts", ".cpp"]:
            null_patterns = [r"(\w+)\s*\.\s*\w+\s*\([^)]*\)(?!\s*\?)"]
            for pattern in null_patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    findings.append(
                        {
                            "type": "reliability",
                            "subtype": "missing_null_check",
                            "severity": "medium",
                            "line": content.count("\n", 0, match.start()) + 1,
                            "description": f"Consider adding null check for {match.group(1)}",
                        }
                    )

        return findings

    async def _detect_testability_patterns(
        self, content: str, ext: str
    ) -> List[Dict[str, Any]]:
        """Detect patterns affecting code testability"""
        findings = []

        # Direct static method calls
        static_call_pattern = r"\b[A-Z][a-zA-Z]*\.[a-zA-Z]+\s*\("
        matches = re.finditer(static_call_pattern, content)
        for match in matches:
            findings.append(
                {
                    "type": "testability",
                    "subtype": "static_call",
                    "severity": "low",
                    "line": content.count("\n", 0, match.start()) + 1,
                    "description": "Static method call may hinder testability - consider dependency injection",
                }
            )

        # Global state usage
        global_patterns = [
            r"global\s+\w+",
            r"static\s+\w+\s*=",
            r"window\.",
            r"document\.",
        ]
        for pattern in global_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                findings.append(
                    {
                        "type": "testability",
                        "subtype": "global_state",
                        "severity": "medium",
                        "line": content.count("\n", 0, match.start()) + 1,
                        "description": "Global state usage detected - consider dependency injection",
                    }
                )

        # Hard-coded dependencies
        new_instance_pattern = r"new\s+[A-Z][a-zA-Z]*\s*\("
        matches = re.finditer(new_instance_pattern, content)
        for match in matches:
            findings.append(
                {
                    "type": "testability",
                    "subtype": "hard_coded_dependency",
                    "severity": "low",
                    "line": content.count("\n", 0, match.start()) + 1,
                    "description": "Hard-coded dependency - consider dependency injection",
                }
            )

        return findings

    async def _calculate_complexity(self, content: str, ext: str) -> Dict[str, Any]:
        """Calculate various complexity metrics"""
        metrics = {
            "cyclomatic": 0,
            "cognitive": 0,
            "halstead": {"vocabulary": 0, "length": 0, "difficulty": 0},
        }

        # Cyclomatic complexity
        decision_patterns = [
            r"\bif\b",
            r"\belse\b",
            r"\bfor\b",
            r"\bwhile\b",
            r"\bcase\b",
            r"\bcatch\b",
            r"\b\|\|\b",
            r"\b&&\b",
        ]

        for pattern in decision_patterns:
            metrics["cyclomatic"] += len(re.findall(pattern, content))

        # Cognitive complexity
        nesting_level = 0
        lines = content.split("\n")
        for line in lines:
            if re.search(r"\b(if|for|while|switch)\b", line):
                metrics["cognitive"] += nesting_level + 1
                nesting_level += 1
            elif re.search(r"\}", line):
                nesting_level = max(0, nesting_level - 1)

        # Halstead metrics (simplified)
        operators = set(re.findall(r"[+\-*/=<>!&|]", content))
        operands = set(re.findall(r"\b[a-zA-Z_]\w*\b", content))

        metrics["halstead"]["vocabulary"] = len(operators) + len(operands)
        metrics["halstead"]["length"] = len(
            re.findall(r"[+\-*/=<>!&|]", content)
        ) + len(re.findall(r"\b[a-zA-Z_]\w*\b", content))
        metrics["halstead"]["difficulty"] = (len(operators) / 2) * (
            metrics["halstead"]["length"] / len(operands) if len(operands) > 0 else 1
        )

        return metrics

    async def _calculate_cohesion(self, content: str, ext: str) -> float:
        """Calculate code cohesion metrics"""
        # Simplified LCOM (Lack of Cohesion of Methods) calculation
        methods = re.finditer(
            r"(def|function|func)\s+(\w+)\s*\([^)]*\)\s*\{?[^\}]*\}?",
            content,
            re.DOTALL,
        )

        # Extract method bodies and the instance variables they use
        method_vars = {}
        instance_vars = set()

        for method in methods:
            method_name = method.group(2)
            method_body = method.group(0)

            # Find instance variable usage (simplified for example)
            if ext == ".py":
                vars_used = set(re.findall(r"self\.(\w+)", method_body))
            else:
                vars_used = set(re.findall(r"this\.(\w+)", method_body))

            method_vars[method_name] = vars_used
            instance_vars.update(vars_used)

        if not method_vars or not instance_vars:
            return 1.0  # Perfect cohesion for empty/simple files

        # Calculate pairs of methods that share variables
        shared_pairs = 0
        total_pairs = 0

        methods_list = list(method_vars.keys())
        for i in range(len(methods_list)):
            for j in range(i + 1, len(methods_list)):
                total_pairs += 1
                if method_vars[methods_list[i]] & method_vars[methods_list[j]]:
                    shared_pairs += 1

        if total_pairs == 0:
            return 1.0

        return shared_pairs / total_pairs

    async def _calculate_coupling(self, content: str, ext: str) -> Dict[str, Any]:
        """Calculate coupling metrics"""
        metrics = {"incoming": 0, "outgoing": 0, "external_deps": set()}

        # Detect import statements
        if ext == ".py":
            imports = re.findall(r"(?:from|import)\s+([\w.]+)", content)
        elif ext in [".js", ".ts"]:
            imports = re.findall(
                r'(?:import.*?from\s+[\'"](.+?)[\'"]|require\s*\([\'"](.+?)[\'"]\))',
                content,
            )
        elif ext == ".java":
            imports = re.findall(r"import\s+([\w.]+);", content)
        else:
            imports = []

        metrics["outgoing"] = len(imports)
        metrics["external_deps"].update(imports)

        # Detect usage of external classes/functions
        external_usage = re.findall(r"[A-Z][a-zA-Z]*\.[a-zA-Z]+", content)
        metrics["outgoing"] += len(external_usage)

        return metrics

    async def _calculate_test_coverage(self, content: str, ext: str) -> Dict[str, Any]:
        """Calculate test coverage metrics"""
        metrics = {"line_coverage": 0.0, "branch_coverage": 0.0, "test_count": 0}

        # Count test cases
        if ext == ".py":
            test_patterns = [r"def\s+test_\w+", r"@pytest\.mark\.parametrize"]
        elif ext in [".js", ".ts"]:
            test_patterns = [r"it\s*\(", r"test\s*\(", r"describe\s*\("]
        elif ext == ".java":
            test_patterns = [r"@Test", r"public.*?test\w+"]
        else:
            test_patterns = []

        for pattern in test_patterns:
            metrics["test_count"] += len(re.findall(pattern, content))

        # Estimate coverage (simplified)
        total_lines = len(content.split("\n"))
        testable_lines = total_lines - len(
            re.findall(r"^\s*(?:#|//|/\*|\*)", content, re.MULTILINE)
        )

        if testable_lines > 0:
            # Estimate line coverage based on assertion density
            assertions = len(re.findall(r"assert|expect|should|must", content))
            metrics["line_coverage"] = min(1.0, assertions / testable_lines)

            # Estimate branch coverage
            branches = len(re.findall(r"\b(if|else|for|while|switch)\b", content))
            tested_branches = len(
                re.findall(r"assert.*?(if|else|for|while|switch)", content, re.DOTALL)
            )
            metrics["branch_coverage"] = (
                tested_branches / branches if branches > 0 else 1.0
            )

        return metrics

    async def _analyze_python(self, content: str) -> Dict[str, Any]:
        """Python-specific code analysis"""
        analysis = {
            "type_hints": False,
            "async_code": False,
            "docstring_coverage": 0.0,
            "best_practices": [],
        }

        # Check for type hints
        type_hint_patterns = [
            r"def\s+\w+\s*\([^)]*:\s*\w+[^)]*\)\s*->\s*\w+",
            r"\w+\s*:\s*\w+",
        ]
        for pattern in type_hint_patterns:
            if re.search(pattern, content):
                analysis["type_hints"] = True
                break

        # Check for async code
        if re.search(r"\basync\s+def\b|\bawait\b|\bcoroutine\b", content):
            analysis["async_code"] = True

        # Calculate docstring coverage
        functions = re.finditer(r"def\s+\w+\s*\([^)]*\):", content)
        total_funcs = 0
        documented_funcs = 0
        for func in functions:
            total_funcs += 1
            # Look for docstring after function definition
            if re.search(
                r'"""[\s\S]*?"""|\'\'\'\s[\s\S]*?\'\'\'',
                content[func.end() : func.end() + 200],
            ):
                documented_funcs += 1

        if total_funcs > 0:
            analysis["docstring_coverage"] = documented_funcs / total_funcs

        # Check Python best practices
        if not re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]\s*:', content):
            analysis["best_practices"].append("Missing __main__ guard")

        if re.search(r"except\s*:", content):
            analysis["best_practices"].append("Bare except clause found")

        if re.search(r"import\s+\*", content):
            analysis["best_practices"].append("Wildcard import found")

        return analysis

    async def _analyze_javascript(self, content: str) -> Dict[str, Any]:
        """JavaScript-specific code analysis"""
        analysis = {"es_version": 5, "module_type": "unknown", "best_practices": []}

        # Detect ES version
        if re.search(
            r"\bconst\b|\blet\b|\btemplate literal\b|\barrow function\b", content
        ):
            analysis["es_version"] = 6
        if re.search(r"\basync\b|\bawait\b", content):
            analysis["es_version"] = 8

        # Detect module system
        if re.search(r'import\s+.*\s+from\s+[\'"]', content):
            analysis["module_type"] = "esm"
        elif re.search(r"require\s*\(", content):
            analysis["module_type"] = "commonjs"

        # Check JavaScript best practices
        if not re.search(r"use strict", content):
            analysis["best_practices"].append('Missing "use strict" directive')

        if re.search(r"==(?!=)", content):
            analysis["best_practices"].append("Using loose equality comparison")

        if re.search(r"var\s+", content):
            analysis["best_practices"].append("Using var instead of const/let")

        return analysis

    async def _generate_recommendations(
        self, patterns: Dict, metrics: Dict, language_analysis: Dict
    ) -> List[str]:
        """Generate recommendations based on analysis results"""
        recommendations = []

        # Security recommendations
        security_findings = patterns.get("security", [])
        if security_findings:
            for finding in security_findings:
                recommendations.append(
                    f"Security: {finding['description']} at line {finding['line']}"
                )

        # Performance recommendations
        if metrics.get("complexity", {}).get("cyclomatic", 0) > 10:
            recommendations.append(
                "Consider breaking down complex methods to improve maintainability"
            )

        if patterns.get("performance", []):
            for finding in patterns["performance"]:
                recommendations.append(
                    f"Performance: {finding['description']} at line {finding['line']}"
                )

        # Maintainability recommendations
        if metrics.get("cohesion", 1.0) < 0.5:
            recommendations.append(
                "Low cohesion detected - consider reorganizing class responsibilities"
            )

        if metrics.get("coupling", {}).get("outgoing", 0) > 10:
            recommendations.append(
                "High coupling detected - consider reducing dependencies"
            )

        # Testing recommendations
        test_metrics = metrics.get("test_coverage", {})
        if test_metrics.get("line_coverage", 0) < 0.7:
            recommendations.append("Increase test coverage to at least 70%")

        if test_metrics.get("branch_coverage", 0) < 0.5:
            recommendations.append("Improve branch coverage in tests")

        # Language-specific recommendations
        if language_analysis:
            if language_analysis.get("best_practices"):
                for practice in language_analysis["best_practices"]:
                    recommendations.append(f"Best Practice: {practice}")

        return recommendations

    async def _scan_logs_with_context(self):
        """Scans log files for errors and provides detailed context for analysis."""
        logger.info("[AI3] Starting enhanced log scanning with context analysis")
        logs_dir = Path("logs")
        if not logs_dir.exists():
            logger.warning(
                "[AI3] Logs directory 'logs/' not found. Cannot scan for errors."
            )
            return

        try:
            # Determine which log files to scan
            log_files = list(logs_dir.glob("*.log"))
            if not log_files:
                logger.info("[AI3] No log files found in logs/ directory")
                return

            # Get the most recent logs for each component
            log_files = sorted(
                log_files, key=lambda p: p.stat().st_mtime, reverse=True
            )[:5]
            logger.info(
                f"[AI3] Scanning {len(log_files)} recent log files: {[f.name for f in log_files]}"
            )

            error_patterns = [
                r"Error",
                r"Exception",
                r"WARNING",
                r"Failed",
                r"Traceback",
                r"CRITICAL",
            ]

            for log_file in log_files:
                try:
                    # Read most recent lines from the log file
                    async with aiofiles.open(
                        log_file, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        # Read the last 500 lines max to focus on recent issues
                        lines = await f.readlines()
                        lines = lines[-500:] if len(lines) > 500 else lines

                    errors_found = []
                    current_error_context = []
                    in_error_context = False

                    for line in lines:
                        # Check if the line contains an error pattern
                        if any(
                            re.search(pattern, line, re.IGNORECASE)
                            for pattern in error_patterns
                        ):
                            if not in_error_context:
                                in_error_context = True
                                current_error_context = [line]
                            else:
                                current_error_context.append(line)
                        elif in_error_context:
                            # Continue collecting context for a few more lines
                            if len(current_error_context) < 10:
                                current_error_context.append(line)
                            else:
                                # We have enough context, save this error
                                errors_found.append("\n".join(current_error_context))
                                in_error_context = False
                                current_error_context = []

                    # Don't forget any error context we were building at the end
                    if in_error_context and current_error_context:
                        errors_found.append("\n".join(current_error_context))

                    # Report errors with full context if found
                    for i, error_context in enumerate(errors_found):
                        # Skip if the error is about AI3 monitoring itself to avoid loops
                        if "AI3" in error_context and "monitor" in error_context:
                            continue

                        # Only report if we can find signs of code or repo issues
                        if (
                            "repo/" in error_context
                            or "code" in error_context
                            or "file" in error_context
                        ):
                            logger.info(
                                f"[AI3] Found relevant error in {log_file.name} - initiating collaboration"
                            )
                            await self._report_system_error_to_ai1(
                                str(log_file),
                                f"Error {i+1}/{len(errors_found)}",
                                error_context,
                            )
                except Exception as e:
                    logger.error(f"[AI3] Error reading log file {log_file}: {e}")

        except Exception as e:
            logger.error(f"[AI3] Error in log scanning: {e}", exc_info=True)

    async def _attempt_test_fixes(self, failing_tests):
        """Attempts to fix failing tests automatically using LLM assistance."""
        logger.info(f"[AI3] Attempting to fix {len(failing_tests)} failing tests")

        for test_file, test_result in failing_tests.items():
            try:
                # Read the failing test file
                test_file_path = os.path.join(self.repo_dir, test_file)
                if not os.path.exists(test_file_path):
                    logger.warning(f"[AI3] Test file not found: {test_file_path}")
                    continue

                async with aiofiles.open(test_file_path, "r", encoding="utf-8") as f:
                    test_content = await f.read()

                # Determine which file is being tested
                code_file = self._infer_code_file_from_test(test_file, test_content)
                if not code_file:
                    logger.warning(
                        f"[AI3] Could not infer code file for test: {test_file}"
                    )
                    continue

                code_file_path = os.path.join(self.repo_dir, code_file)
                if not os.path.exists(code_file_path):
                    logger.warning(f"[AI3] Code file not found: {code_file_path}")
                    continue

                async with aiofiles.open(code_file_path, "r", encoding="utf-8") as f:
                    code_content = await f.read()

                # Get the first provider from AI3 configuration for LLM calls
                ai_config_base = self.config.get("ai_config", {})
                ai3_config = ai_config_base.get("ai3", {})
                providers = ai3_config.get("providers", ["ollama1"])
                provider_name = providers[0] if providers else "ollama1"
                provider = ProviderFactory.create_provider(provider_name)

                # Generate a fix for the failing test
                prompt = f"""
                I'm trying to fix failing tests in a project. Here's the test file content:
                
                ```
                {test_content}
                ```
                
                Here's the implementation file being tested:
                
                ```
                {code_content}
                ```
                
                This test is failing with the following errors: {test_result.failures}
                
                Please suggest fixes for BOTH the test file AND the implementation file.
                Respond with a JSON containing two keys:
                - 'test_file': the corrected test file content
                - 'code_file': the corrected implementation file content
                """

                logger.info(
                    f"[AI3] Generating fix for test: {test_file} and code: {code_file}"
                )

                try:
                    response = await provider.generate(
                        prompt=prompt,
                        model=ai3_config.get("model"),
                        max_tokens=ai3_config.get("max_tokens", 4000),
                        temperature=0.1,  # Low temperature for more reliable code generation
                    )

                    # Extract JSON from the response
                    json_match = re.search(
                        r"```json\s*([\s\S]*?)\s*```|{\s*\"test_file\"[\s\S]*\"code_file\"[\s\S]*}",
                        response,
                    )
                    if json_match:
                        json_str = json_match.group(1) or json_match.group(0)
                        try:
                            fix_data = json.loads(json_str)
                            # Apply the fixes
                            if fix_data.get("test_file"):
                                async with aiofiles.open(
                                    test_file_path, "w", encoding="utf-8"
                                ) as f:
                                    await f.write(fix_data["test_file"])
                                logger.info(f"[AI3] Updated test file: {test_file}")

                            if fix_data.get("code_file"):
                                async with aiofiles.open(
                                    code_file_path, "w", encoding="utf-8"
                                ) as f:
                                    await f.write(fix_data["code_file"])
                                logger.info(f"[AI3] Updated code file: {code_file}")

                            # Commit the changes
                            commit_message = (
                                f"AI3: Auto-fix for failing test {test_file}"
                            )
                            _commit_changes(
                                self.repo,
                                [test_file_path, code_file_path],
                                commit_message,
                            )

                        except json.JSONDecodeError:
                            logger.error(
                                f"[AI3] Invalid JSON in provider response for {test_file}"
                            )
                    else:
                        logger.warning(
                            f"[AI3] No JSON found in provider response for {test_file}"
                        )
                finally:
                    if hasattr(provider, "close_session") and callable(
                        provider.close_session
                    ):
                        await provider.close_session()

            except Exception as e:
                logger.error(
                    f"[AI3] Error attempting to fix test {test_file}: {e}",
                    exc_info=True,
                )

        logger.info("[AI3] Completed test fix attempts")

    def _infer_code_file_from_test(self, test_file, test_content):
        """Infer the implementation file path from a test file path and content."""
        # Method 1: Based on naming convention
        if test_file.startswith("test_"):
            code_file = test_file[5:]  # Remove "test_" prefix
        elif test_file.endswith("_test.py"):
            code_file = test_file[:-8] + ".py"  # Remove "_test.py" suffix and add .py
        elif test_file.endswith(".test.py"):
            code_file = test_file[:-8] + ".py"  # Remove ".test.py" suffix and add .py
        else:
            # Method 2: Look for imports in the test content
            imports = re.findall(
                r"from\s+([\w.]+)\s+import|import\s+([\w.]+)", test_content
            )
            potential_modules = []
            for imp in imports:
                module = imp[0] or imp[1]
                if module and not module.startswith(("test_", "pytest", "unittest")):
                    potential_modules.append(module.replace(".", "/") + ".py")

            if potential_modules:
                # Choose the most likely implementation file
                for module in potential_modules:
                    module_path = os.path.join(self.repo_dir, module)
                    if os.path.exists(module_path):
                        return module

            # Method 3: Check class/function names being tested
            test_targets = re.findall(r"test_(\w+)", test_content)
            if test_targets:
                # Look for files containing these target names
                for target in test_targets:
                    parent_dir = os.path.dirname(os.path.join(self.repo_dir, test_file))
                    for root, _, files in os.walk(parent_dir):
                        for file in files:
                            if file.endswith(".py") and not file.startswith("test_"):
                                rel_path = os.path.relpath(
                                    os.path.join(root, file), self.repo_dir
                                )
                                return rel_path

            # Fallback: Return None if we couldn't infer the implementation file
            return None

        return code_file

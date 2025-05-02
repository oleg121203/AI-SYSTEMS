import asyncio
import json
import logging
import os
import re
import time
import shutil
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from pathlib import Path

import aiohttp
import git
from git import Repo, GitCommandError

from config import load_config
import ai_communication as ai_comm
from utils import log_message, apply_request_delay, setup_service_logger, wait_for_service
from providers import BaseProvider, ProviderFactory  # Adding missing provider imports
import aiofiles

# Load configuration and set up logging
config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")
LOG_FILE = "logs/ai3.log"

# Define constants
DEFAULT_REPO_DIR = "repo"
DEFAULT_MCP_API_URL = "http://localhost:7860"
REPO_PREFIX = "repo/" # All relative paths should be relative to repo dir

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/ai3.log"),
        logging.StreamHandler()
    ]
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
                        logger.debug(f"[AI3] Service check: Status {response.status} from {service_url}")
            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError):
                pass  # Expected during startup, don't log each failure
            except Exception as e:
                logger.debug(f"[AI3] Error checking service: {e}")
            
            # Check every second
            await asyncio.sleep(1)
    
    logger.warning(f"[AI3] Timeout waiting for service at {service_url} after {timeout}s")
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
            logger.info(f"[AI3-Git] Repository not found, initializing new one at: {repo_path}")
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
            logger.info(f"[AI3-Git] No valid files found to commit for message: {message}")
            return

        paths_to_add = [
            p for p in relative_paths
            if p in repo.untracked_files or p in [item.a_path for item in repo.index.diff(None)]
        ]

        if not paths_to_add:
            logger.info(f"[AI3-Git] No new or modified files to add to index for commit: {message}")
            return

        logger.info(f"[AI3-Git] Adding files to index: {paths_to_add}")
        repo.index.add(paths_to_add)

        is_empty_repo = not repo.head.is_valid()

        if is_empty_repo:
            logger.info(f"[AI3-Git] Empty repository detected. Performing initial commit: {message}")
            repo.index.commit(message)
            logger.info(f"[AI3-Git] Initial commit successful: {message}")
        else:
            staged_diff = repo.index.diff("HEAD")
            if staged_diff:
                logger.info(f"[AI3-Git] Committing {len(paths_to_add)} added/modified file(s): {message}")
                repo.index.commit(message)
                logger.info(f"[AI3-Git] Commit successful: {message}")
            else:
                logger.info(f"[AI3-Git] No staged changes to commit for message: {message}")

    except GitCommandError as e:
        if "nothing to commit" in str(e) or "no changes added to commit" in str(e):
            logger.info(f"[AI3-Git] Git: Nothing to commit for message: {message}")
        else:
            logger.error(f"[AI3-Git] Error committing changes: {message}. Files: {relative_paths}. Error: {e}")
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
        logger.warning("[AI3] Warning: 'ai_config.ai3' section not found. Using defaults.")
        ai3_config = {}

    structure_providers = ai3_config.get("structure_providers")
    if not structure_providers:
        logger.warning("[AI3] 'structure_providers' not found in ai3 config. Using default ['codestral2'].")
        structure_providers = ["codestral2"]

    logger.info(f"[AI3] Using structure_providers: {structure_providers}")

    initial_response_text = None
    selected_provider_name = None

    logger.info(f"[AI3] Starting Cycle 1: Initial structure generation using providers: {structure_providers}")
    for provider_name in structure_providers:
        try:
            logger.info(f"[AI3] Cycle 1: Trying provider for initial generation: {provider_name}")
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
                    logger.info(f"[AI3] Cycle 1: Successfully generated initial structure with provider: {provider_name}")
                    selected_provider_name = provider_name
                    break
                else:
                    logger.warning(f"[AI3] Cycle 1: Provider {provider_name} returned empty response for initial generation.")
            except Exception as e:
                logger.error(f"[AI3] Cycle 1: Failed initial generation with provider {provider_name}: {str(e)}")
            finally:
                if hasattr(provider, "close_session") and callable(provider.close_session):
                    await provider.close_session()
        except Exception as e:
            logger.error(f"[AI3] Cycle 1: Error initializing provider '{provider_name}' for initial generation: {e}")

    if not initial_response_text:
        logger.error("[AI3] Cycle 1: Failed to generate initial structure with all configured providers.")
        return None

    def clean_and_parse_json(response_str: str) -> Optional[Dict]:
        cleaned_str = response_str.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        if not cleaned_str:
            logger.warning("[AI3] Cleaned JSON string is empty.")
            return None
        try:
            return json.loads(cleaned_str)
        except json.JSONDecodeError as e:
            logger.error(f"[AI3] Failed to decode JSON structure: {e}. String: {cleaned_str[:200]}...")
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
    providers_to_try_refinement = [selected_provider_name] if selected_provider_name else structure_providers

    for provider_name in providers_to_try_refinement:
        try:
            logger.info(f"[AI3] Cycle 2: Trying provider for refinement: {provider_name}")
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
                    logger.info(f"[AI3] Cycle 2: Successfully received refinement response with provider: {provider_name}")
                    break
                else:
                    logger.warning(f"[AI3] Cycle 2: Provider {provider_name} returned empty response for refinement.")
            except Exception as e:
                logger.error(f"[AI3] Cycle 2: Failed refinement with provider {provider_name}: {str(e)}")
            finally:
                if hasattr(provider, "close_session") and callable(provider.close_session):
                    await provider.close_session()
        except Exception as e:
            logger.error(f"[AI3] Cycle 2: Error initializing provider '{provider_name}' for refinement: {e}")

    if refined_response_text:
        final_structure_json = clean_and_parse_json(refined_response_text)
        if final_structure_json:
            logger.info("[AI3] Cycle 2: Structure refinement successful. Using refined structure.")
            return final_structure_json
        else:
            logger.warning("[AI3] Cycle 2: Failed to parse refined JSON structure. Falling back to initial structure.")
            return initial_structure_json
    else:
        logger.warning("[AI3] Cycle 2: Failed to get refinement response from providers. Using initial structure.")
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
                    logger.info(f"[AI3 -> API] Structure successfully sent. Response: {response_text}")
                    return True
                else:
                    logger.error(f"[AI3 -> API] Error sending structure. Status: {resp.status}, Response: {response_text}")
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
                    logger.warning(f"[AI3 -> API] Failed to send report '{status}'. Status: {resp.status}, Response: {response_text}")
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
    logger.info(f"[AI3 -> API] Initiating collaboration via {api_url} for error: {error[:100]}...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, json=collaboration_request, timeout=20) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info(f"[AI3 -> API] Collaboration request sent successfully. Response: {response_text}")
                else:
                    logger.warning(f"[AI3 -> API] Failed to send collaboration request. Status: {resp.status}, Response: {response_text}")
                return resp.status == 200
        except asyncio.TimeoutError:
            logger.warning("[AI3 -> API] Timeout initiating collaboration.")
            return False
        except aiohttp.ClientError as e:
            logger.error(f"[AI3 -> API] Connection error initiating collaboration: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"[AI3 -> API] Unexpected error initiating collaboration: {str(e)}")
            return False


async def create_files_from_structure(structure_obj: dict, repo: Repo) -> Tuple[List[str], List[str]]:
    """Creates file structure from the JSON structure object."""
    base_path = repo.working_dir
    created_files = []
    skipped_files = []
    created_dirs = []

    async def _create_recursive(struct: dict, current_path: str):
        nonlocal created_files, skipped_files, created_dirs

        if not isinstance(struct, dict):
            logger.error(f"[AI3] Invalid structure object provided: Expected dict, got {type(struct)}")
            return

        for key, value in struct.items():
            sanitized_key = re.sub(r'[<>:"/\\|?*]', "_", key).strip()
            sanitized_key = re.sub(r'\s+', '_', sanitized_key)
            if not sanitized_key:
                logger.warning(f"[AI3] Skipping empty/invalid name: '{key}' in path '{current_path}'")
                continue

            full_path = os.path.join(base_path, current_path, sanitized_key)
            rel_path = os.path.join(current_path, sanitized_key)

            try:
                parent_dir = os.path.dirname(full_path)
                if (parent_dir != base_path and not os.path.exists(parent_dir)):
                    os.makedirs(parent_dir, exist_ok=True)
                    logger.info(f"[AI3] Created parent directory: {os.path.relpath(parent_dir, base_path)}")

                if isinstance(value, dict):
                    if not os.path.exists(full_path):
                        os.makedirs(full_path, exist_ok=True)
                        created_dirs.append(full_path)
                        logger.info(f"[AI3] Created directory: {rel_path}")

                        if not value:
                            gitkeep_path = os.path.join(full_path, GITKEEP_FILENAME)
                            async with aiofiles.open(gitkeep_path, "w", encoding="utf-8") as f:
                                await f.write("")
                            created_files.append(gitkeep_path)
                            logger.info(f"[AI3] Created .gitkeep in empty directory: {rel_path}")

                    await _create_recursive(value, rel_path)

                elif value is None or isinstance(value, str):
                    if not os.path.exists(full_path):
                        content = value if isinstance(value, str) else ""
                        if content and not content.endswith('\n'):
                            content += '\n'

                        async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                            await f.write(content)

                        created_files.append(full_path)
                        logger.info(f"[AI3] Created file: {rel_path}")
                    else:
                        skipped_files.append(full_path)
                        logger.info(f"[AI3] File already exists, skipping: {rel_path}")
                else:
                    logger.warning(f"[AI3] Unknown data type '{type(value)}' for '{key}' in '{rel_path}'")

            except OSError as e:
                logger.error(f"[AI3] OS Error creating file/directory {rel_path}: {e}")
            except Exception as e:
                logger.error(f"[AI3] Error creating {rel_path}: {e}", exc_info=True)

    try:
        logger.info("[AI3] Starting file creation from structure...")
        await _create_recursive(structure_obj, "")

        if created_files:
            logger.info(f"[AI3] Committing {len(created_files)} created files...")
            _commit_changes(repo, created_files, "AI3: Created initial project structure")
        else:
            logger.info("[AI3] No new files were created to commit.")

        logger.info(f"[AI3] File creation completed: {len(created_files)} files created, {len(skipped_files)} skipped")
        await send_ai3_report("structure_creation_completed", {"created_count": len(created_files), "skipped_count": len(skipped_files)})
        return created_files, skipped_files
    except Exception as e:
        logger.error(f"[AI3] Error in create_files_from_structure: {e}", exc_info=True)
        await send_ai3_report("structure_creation_failed", {"error": str(e)})
        await initiate_collaboration(f"Failed during create_files_from_structure: {e}", f"Structure object keys: {list(structure_obj.keys()) if isinstance(structure_obj, dict) else 'Invalid structure'}")
        return [], []


async def generate_initial_idea_md(target: str, ai3_config: Dict, provider_name: str) -> Optional[str]:
    """Generates the initial detailed description for idea.md using an LLM."""
    logger.info(f"[AI3] Generating initial idea.md content for target: {target}")
    prompt = f"Based on the project target \"{target}\", create a detailed initial description for the project. This description will be stored in idea.md and used by other AI agents to understand the project goals and requirements. Describe the main features, target audience, and key functionalities. Be reasonably detailed but concise, as another AI will refine this later."
    system_prompt = "You are a helpful assistant tasked with creating project descriptions."

    try:
        # Use the utility function to call the provider
        idea_content = await call_llm_provider(
            provider_name=provider_name,
            prompt=prompt,
            system_prompt=system_prompt,
            config=config, # Pass the global config
            ai_config=ai3_config, # Pass the specific AI config section
            service_name="ai3" # Specify the service name for delay
        )

        if idea_content:
            logger.info("[AI3] Successfully generated initial idea.md content.")
            return idea_content
        else:
            logger.warning("[AI3] LLM provider returned empty response for idea.md generation.")
            return None
    except Exception as e:
        logger.error(f"[AI3] Failed to generate initial idea.md content: {e}", exc_info=True)
        return None


class AI3:
    def __init__(self, config_data):
        self.config = config_data
        self.repo_dir = self.config.get("repo_dir", DEFAULT_REPO_DIR)
        self.target = self.config.get("target")
        logger.info(f"[AI3] Repository directory set to: {self.repo_dir}")
        logger.info(f"[AI3] Project Target: {self.target if self.target else 'Not specified'}")
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
        ollama_config = self.config.get("ai_config", {}).get("ai3", {}).get("providers", ["ollama1"])[0]
        endpoint = self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
        model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
        if endpoint and model:
            logger.info(f"[AI3-Ollama] Successfully initialized Ollama with endpoint '{endpoint}' and model '{model}'")
        else:
            logger.error("[AI3-Ollama] Failed to initialize Ollama: Configuration not found in config.json")

    def _init_or_open_repo(self, repo_path: str) -> Repo:
        return _init_or_open_repo(repo_path)

    async def clear_and_init_repo(self):
        try:
            if os.path.exists(self.repo_dir):
                logger.info(f"[AI3-Git] Removing existing repository directory: {self.repo_dir}")
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
                self.repo = Repo.init('.')  # Ініціалізація в поточному каталозі
                logger.info(f"[AI3-Git] Successfully initialized new repository at: {self.repo_dir}")
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
                logger.warning(f"[AI3-Git] Found unexpected 'project/' directory at {project_path}. Removing it.")
                shutil.rmtree(project_path)

            await send_ai3_report("repo_cleared")
            return True
        except Exception as e:
            logger.error(f"[AI3-Git] Error clearing and initializing repository: {e}", exc_info=True)
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
                logger.error("[AI3] MCP API did not become available. Aborting structure setup.")
                return False

            success = await self.clear_and_init_repo()
            if not success:
                logger.error("[AI3] Failed to initialize repository. Aborting structure setup.")
                return False

            logger.info("[AI3] Generating and refining project structure...")
            structure = await generate_structure(self.target)
            if not structure:
                logger.error("[AI3] Failed to generate structure. Aborting structure setup.")
                await send_ai3_report("structure_generation_failed")
                return False
            else:
                logger.info("[AI3] Structure generation/refinement successful.")

            created_files, skipped_files = await create_files_from_structure(structure, self.repo)

            if not created_files and not skipped_files:
                logger.warning("[AI3] No files were created or skipped from the generated structure. Structure might be empty or all files existed.")

            # --- NEW: Generate and commit idea.md ---
            logger.info("[AI3] Generating initial idea.md...")
            ai_config_base = self.config.get("ai_config", {})
            ai3_config = ai_config_base.get("ai3", {})
            # Use the first provider from structure_providers or a default
            structure_providers = ai3_config.get("structure_providers", ["codestral2"])
            provider_name_for_idea = structure_providers[0] if structure_providers else "codestral2"

            idea_content = await generate_initial_idea_md(self.target, ai3_config, provider_name_for_idea)
            idea_md_path = os.path.join(self.repo_dir, "idea.md")
            if idea_content:
                try:
                    async with aiofiles.open(idea_md_path, "w", encoding="utf-8") as f:
                        await f.write(idea_content)
                    logger.info(f"[AI3] Successfully wrote initial content to {idea_md_path}")
                    _commit_changes(self.repo, [idea_md_path], "AI3: Add initial idea.md")
                except Exception as e:
                    logger.error(f"[AI3] Failed to write or commit idea.md: {e}", exc_info=True)
                    # Decide if this is critical enough to abort
            else:
                logger.warning("[AI3] Failed to generate initial idea.md content. Proceeding without it.")
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
            await self.close_session() # Ensure session is closed on error
            return False

    async def start_monitoring(self):
        logger.info("[AI3] Starting AI3 monitoring service...")
        await self.create_session()
        tasks = [
            self.monitor_idle_workers(),
            self.monitor_system_errors(),
            self.monitor_github_actions()
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
            async with self.session.get(f"{mcp_api_url}/worker_status", timeout=10) as resp:
                if resp.status == 200:
                    status_data = await resp.json()
                    logger.debug(f"[AI3] Worker status received: {status_data}")
                    all_queue_sizes = status_data.get("queue_sizes", {})
                    executor_queue_size = all_queue_sizes.get("executor", 0)
                else:
                    logger.warning(f"[AI3] Failed to get worker status: {resp.status} - {await resp.text()}")
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
                timeout=15
            ) as resp:
                if resp.status == 200:
                    response_data = await resp.json()
                    if response_data.get("task_assigned"):
                        self.monitoring_stats["successful_requests"] += 1
                        logger.info(f"[AI3 -> MCP] Task successfully requested for worker: {worker_name}")
                    else:
                        logger.info(f"[AI3 -> MCP] No suitable task found for worker: {worker_name}")
                elif resp.status == 404:
                    logger.warning(f"[AI3 -> MCP] Worker '{worker_name}' not found or no tasks available.")
                else:
                    logger.error(f"[AI3 -> MCP] Error requesting task for worker {worker_name}: {resp.status} - {await resp.text()}")
        except asyncio.TimeoutError:
            logger.warning(f"[AI3 -> MCP] Timeout requesting task for worker {worker_name}.")
        except aiohttp.ClientError as e:
            logger.error(f"[AI3 -> MCP] Connection error requesting task for worker {worker_name}: {e}")
        except Exception as e:
            logger.error(f"[AI3 -> MCP] Error requesting task for worker {worker_name}: {e}", exc_info=True)

    async def scan_logs_for_errors(self):
        """Scans configured log files for errors related to 'repo/' using Ollama."""
        logger.info("[AI3] Starting log scan for errors using Ollama")
        logs_dir = Path("logs")
        if not logs_dir.exists():
            logger.warning("[AI3] Logs directory 'logs/' not found. Cannot scan for errors.")
            return

        try:
            ollama_config = self.config.get("ai_config", {}).get("ai3", {}).get("providers", ["ollama1"])[0]
            endpoint = self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
            model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
            if not endpoint or not model:
                logger.error("[AI3] Ollama configuration not found in config.json. Cannot proceed with log analysis.")
                return
            logger.info(f"[AI3] Ollama configured with endpoint '{endpoint}' and model '{model}'")

            current_time = time.time()
            time_threshold = self.last_check_time
            self.last_check_time = current_time

            for log_file in logs_dir.glob("*.log"):
                if log_file.stat().st_mtime < time_threshold:
                    continue
                logger.info(f"[AI3] Scanning log file: {log_file.name}")
                try:
                    async with aiofiles.open(log_file, "r", encoding="utf-8", errors="ignore") as f:
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
                            logger.debug(f"[AI3] Analyzing log line {i}/{len(lines)} in {log_file.name}")

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
                                context_lines = [l.strip() for l in lines[context_start:i]]
                                context_str = "\n".join(context_lines)
                                logger.warning(f"[AI3] Ollama detected error in {log_file.name}: {line}")
                                logger.info(f"[AI3] Error details from Ollama: {result.get('details', 'No details provided')}")
                                report_sent = await self._report_system_error_to_ai1(str(log_file), line, context_str)
                                if report_sent:
                                    logger.info(f"[AI3] Successfully reported error to AI1 from {log_file.name}")
                                else:
                                    logger.warning(f"[AI3] Failed to report error to AI1 from {log_file.name}")
                        except json.JSONDecodeError:
                            logger.warning(f"[AI3] Invalid JSON response from Ollama for line: {line[:100]}...")
                            logger.debug(f"[AI3] Full invalid response: {analysis}")

                    logger.info(f"[AI3] Completed analysis of {log_file.name}: {lines_analyzed} lines analyzed, {errors_detected} errors detected")
                except Exception as file_e:
                    logger.error(f"[AI3] Error processing log file {log_file}: {file_e}")
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
            logger.error(f"[AI3-Git] Failed to update or commit file {file_path_relative}: {e}", exc_info=True)
            await initiate_collaboration(f"Failed to update/commit {file_path_relative}: {e}", f"Content length: {len(content)}")

    async def handle_ai2_output(self, data):
        file_path = data.get("filename")
        content = data.get("code")
        if file_path and content is not None:
            if os.path.isabs(file_path):
                if file_path.startswith(os.path.abspath(self.repo_dir)):
                    file_path = os.path.relpath(file_path, self.repo_dir)
                else:
                    logger.warning(f"[AI3] Received absolute file path outside repo: {file_path}. Skipping update.")
                    return
            if file_path.startswith(REPO_PREFIX):
                file_path = file_path[len(REPO_PREFIX):]
            logger.info(f"[AI3] Received AI2 output for file: {file_path}. Content length: {len(content)}")
            await self.update_file_and_commit(file_path, content)
        else:
            logger.warning(f"[AI3] Failed to extract file path or content from AI2 report: {data.keys()}")

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
            logger.info(f"[AI3] Using GitHub repo from GITHUB_REPO_TO_MONITOR env var: {github_repo}")
        else:
            logger.warning("[AI3] Warning: GitHub repository not configured. Cannot monitor GitHub Actions.")
            return
        if not github_token:
            logger.warning("[AI3] Warning: GITHUB_TOKEN not configured. Cannot monitor GitHub Actions.")
            return
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
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
                    params={"per_page": "5", "status": "completed"}
                ) as response:
                    if response.status == 200:
                        runs_data = await response.json()
                        workflow_runs = runs_data.get("workflow_runs", [])
                        logger.debug(f"[AI3] Fetched {len(workflow_runs)} completed workflow runs.")
                        processed_this_cycle = False
                        for run in sorted(workflow_runs, key=lambda x: x['created_at'], reverse=True):
                            run_id = run.get("id")
                            run_conclusion = run.get("conclusion")
                            if run_id and self._is_new_completed_run(run_id):
                                logger.info(f"[AI3] Found new completed GitHub Actions run: ID={run_id}, Conclusion={run_conclusion}")
                                await self._analyze_workflow_run(run_id, run_conclusion, headers, api_base_url)
                                processed_this_cycle = True
                                break
                        if not processed_this_cycle:
                            logger.debug("[AI3] No new completed GitHub Actions runs found this cycle.")
                    elif response.status == 404:
                        logger.error(f"[AI3] GitHub repository '{github_repo}' not found or access denied. Stopping GitHub monitoring.")
                        break
                    elif response.status == 401:
                        logger.error("[AI3] GitHub API authentication failed (Invalid GITHUB_TOKEN?). Stopping GitHub monitoring.")
                        break
                    else:
                        logger.warning(f"[AI3] Failed to fetch GitHub Actions runs: Status {response.status} - {await response.text()}")
            except aiohttp.ClientConnectorError as e:
                logger.error(f"[AI3] Connection error during GitHub Actions monitoring: {e}")
            except asyncio.TimeoutError:
                logger.warning("[AI3] Timeout during GitHub Actions check.")
            except Exception as e:
                logger.error(f"[AI3] Error in GitHub Actions monitoring loop: {e}", exc_info=True)
            await asyncio.sleep(check_interval)

    def _is_new_completed_run(self, run_id: int) -> bool:
        if run_id in self._processed_run_ids:
            return False
        else:
            if len(self._processed_run_ids) > 1000:
                self._processed_run_ids.pop()
            self._processed_run_ids.add(run_id)
            return True

    async def _analyze_workflow_run(self, run_id, run_conclusion, headers, api_base_url):
        logger.info(f"[AI3] Analyzing workflow run ID: {run_id}, Conclusion: {run_conclusion}")
        job_logs = ""
        try:
            await self.create_session()
            async with self.session.get(
                f"{api_base_url}/actions/runs/{run_id}/jobs",
                headers=headers,
                timeout=20
            ) as response:
                if response.status == 200:
                    jobs_data = await response.json()
                    for job in jobs_data.get("jobs", []):
                        job_name_lower = job.get("name", "").lower()
                        if "test" in job_name_lower or "build" in job_name_lower or "lint" in job_name_lower:
                            job_id = job.get("id")
                            log_url = f"{api_base_url}/actions/jobs/{job_id}/logs"
                            async with self.session.get(log_url, headers=headers, timeout=60) as log_response:
                                if log_response.status == 200 and 'application/zip' not in log_response.headers.get('Content-Type', ''):
                                    job_logs = await log_response.text(encoding='utf-8', errors='replace')
                                    logger.info(f"[AI3] Fetched logs for job {job_id}. Length: {len(job_logs)} chars.")
                                    break
        except Exception as e:
            logger.error(f"[AI3] Error fetching logs for run {run_id}: {e}", exc_info=True)

        if not job_logs:
            logger.warning(f"[AI3] No logs available for run {run_id}. Using run conclusion: {run_conclusion}")
            recommendation = "rework" if run_conclusion == "failure" else "accept"
            context = {"run_url": f"https://github.com/{self.config.get('github_repo')}/actions/runs/{run_id}"}
            await self._send_test_recommendation(recommendation, context)
            return

        ollama_config = self.config.get("ai_config", {}).get("ai3", {}).get("providers", ["ollama1"])[0]
        endpoint = self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
        model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
        if not endpoint or not model:
            logger.error("[AI3] Ollama configuration not found. Cannot analyze GitHub Actions logs.")
            return
        logger.info(f"[AI3] Analyzing GitHub Actions logs using Ollama with endpoint '{endpoint}' and model '{model}'")

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
                "run_url": f"https://github.com/{self.config.get('github_repo')}/actions/runs/{run_id}"
            }
            logger.info(f"[AI3] Ollama recommendation for run {run_id}: {recommendation}, Failed files: {failed_files}")
            logger.debug(f"[AI3] Recommendation details: {details}")
            await self._send_test_recommendation(recommendation, context)
        except json.JSONDecodeError:
            logger.error(f"[AI3] Invalid JSON response from Ollama for run {run_id}: {analysis}")

    async def _send_test_recommendation(self, recommendation: str, context: dict):
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        try:
            await self.create_session()
            recommendation_data = {"recommendation": recommendation, "context": context}
            logger.info(f"[AI3 -> MCP] Sending test recommendation: {recommendation}, Context keys: {list(context.keys())}")
            async with self.session.post(f"{mcp_api_url}/test_recommendation", json=recommendation_data, timeout=15) as response:
                resp_text = await response.text()
                if response.status == 200:
                    logger.info(f"[AI3 -> MCP] Successfully sent test recommendation '{recommendation}'. Response: {resp_text}")
                else:
                    logger.error(f"[AI3 -> MCP] Error sending test recommendation: {response.status} - {resp_text}")
        except asyncio.TimeoutError:
            logger.error("[AI3 -> MCP] Timeout sending test recommendation.")
        except aiohttp.ClientError as e:
            logger.error(f"[AI3 -> MCP] Connection error sending test recommendation: {e}")
        except Exception as e:
            logger.error(f"[AI3 -> MCP] Failed to send test recommendation: {e}", exc_info=True)

    async def monitor_idle_workers(self):
        mcp_api_url = self.config.get("mcp_api_url", DEFAULT_MCP_API_URL)
        check_interval = self.config.get("idle_worker_check_interval", 30)
        logger.info("[AI3] Starting idle worker monitoring.")
        while True:
            try:
                await self.create_session()
                async with self.session.get(f"{mcp_api_url}/worker_status", timeout=10) as response:
                    if response.status == 200:
                        status_data = await response.json()
                        idle_workers = status_data.get("idle_workers", [])
                        if idle_workers:
                            logger.info(f"[AI3] Detected idle workers: {idle_workers}")
                            self.monitoring_stats["idle_workers_detected"] += len(idle_workers)
                            for worker_name in idle_workers:
                                await self.request_task_for_worker(worker_name)
                        else:
                            logger.debug("[AI3] No idle workers detected.")
                    else:
                        logger.warning(f"[AI3] Failed to get worker status: {response.status} - {await response.text()}")
            except asyncio.TimeoutError:
                logger.warning("[AI3] Timeout checking worker status. Falling back to log analysis.")
                await self._check_logs_for_idle_workers()
            except aiohttp.ClientConnectorError as e:
                logger.error(f"[AI3] Connection error while checking worker status: {e}. Falling back to log analysis.")
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
                logger.warning(f"[AI3] Fallback: MCP log file not found at {mcp_log_file}")
                return
            logger.debug("[AI3] Fallback: Checking MCP logs for idle workers (empty queues).")
            async with aiofiles.open(mcp_log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = await f.readlines()
                recent_lines = lines[-50:]
                for line in recent_lines:
                    if "Queue is empty for role" in line:
                        match = re.search(r"Queue is empty for role: (\w+)", line)
                        role_to_request = match.group(1) if match else "any"
                        logger.info(f"[AI3] Fallback: Detected empty queue message in MCP log for role '{role_to_request}'. Requesting task.")
                        await self.request_task_for_worker(role_to_request)
                        break
        except Exception as e:
            logger.error(f"[AI3] Error checking logs for idle workers: {e}", exc_info=True)

    async def _report_system_error_to_ai1(self, log_file: str, error_line: str, context: str) -> bool:
        """Reports a system error to AI1 using the standardized communication protocol"""
        try:
            # Use the new communication module instead of direct API calls
            await ai_comm.send_error_report(
                sender="ai3",
                error_type="system_error",
                message=error_line,
                file_path=log_file,
                stack_trace=context,
                severity=ai_comm.Priority.HIGH
            )
            logger.info(f"[AI3 -> AI1] Successfully reported system error to AI1 from {log_file}")
            return True
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Failed to send system error report: {e}", exc_info=True)
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
                    "timestamp": datetime.now().isoformat()
                }
            }
            logger.info(f"[AI3 -> AI1] Sending queue info to AI1: {queue_sizes}")
            async with self.session.post(f"{mcp_api_url}/ai_collaboration", json=payload, timeout=15) as response:
                if response.status == 200:
                    logger.info("[AI3 -> AI1] Queue info sent successfully.")
                    return True
                else:
                    logger.error(f"[AI3 -> AI1] Failed to send queue info: {response.status} - {await response.text()}")
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
        logger.info("[AI3] Structure phase complete. Switching to monitoring mode (using APIs, not structure providers).")
        await self.create_session()
        tasks = [
            asyncio.create_task(self.monitor_idle_workers(), name="IdleWorkerMonitor"),
            asyncio.create_task(self.monitor_system_errors(), name="SystemErrorMonitor"),
            asyncio.create_task(self.monitor_github_actions(), name="GitHubActionsMonitor")
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                    logger.warning(f"[AI3] Monitoring task {task.get_name()} completed unexpectedly.")
                except Exception as task_e:
                    logger.critical(f"[AI3] Monitoring task {task.get_name()} failed: {task_e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("[AI3] AI3 run loop cancelled.")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.critical(f"[AI3] An error occurred in AI3 main run loop: {e}", exc_info=True)
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
                                await self._attempt_pattern_based_fix(test_file, error_patterns[error_key])
                        else:
                            error_patterns[error_key] = {"count": 1, "first_seen": datetime.now(), "failures": failures}

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
                error_patterns = {k: v for k, v in error_patterns.items() 
                                if (current_time - v["first_seen"]).total_seconds() < 86400}  # 24 hour retention

                await asyncio.sleep(check_interval)
                
            except asyncio.CancelledError:
                logger.info("[AI3] System error monitor stopped.")
                break
            except Exception as e:
                logger.error(f"[AI3] Error in system error monitor: {e}", exc_info=True)
                await asyncio.sleep(300)  # Wait longer after an error

    async def _run_automated_tests(self):
        """Run automated tests and analyze results"""
        from utils import TestRunner
        
        logger.info("[AI3] Starting automated test execution...")
        try:
            # Initialize the test runner
            test_runner = TestRunner(repo_dir=self.repo_dir)
            
            # Run tests and collect results
            test_results = test_runner.run_tests()
            
            # Check if we have any failing tests
            failing_tests = {path: result for path, result in test_results.items() if not result.success}
            
            if failing_tests:
                logger.info(f"[AI3] Found {len(failing_tests)} failing tests. Starting self-healing process...")
                await self._attempt_test_fixes(failing_tests)
            else:
                logger.info("[AI3] All tests passed successfully.")
                
            # Run linters to check code quality
            lint_results = test_runner.run_linters()
            failing_lints = {path: result for path, result in lint_results.items() if not result.success}
            
            if failing_lints:
                logger.info(f"[AI3] Found {len(failing_lints)} files with linting issues. Attempting to fix...")
                await self._attempt_lint_fixes(failing_lints)
            else:
                logger.info("[AI3] All files pass linting checks.")
                
            # Generate and save comprehensive test report
            report = test_runner.generate_test_report(test_results)
            
            # Send insights to AI1 for planning if needed
            if report["insights"]:
                await self._send_test_insights_to_ai1(report["insights"])
                
            return True
        except Exception as e:
            logger.error(f"[AI3] Error running automated tests: {e}", exc_info=True)
            return False
            
    async def _attempt_test_fixes(self, failing_tests):
        """Attempt to fix failing tests automatically"""
        # Get an Ollama provider for fixing tests
        try:
            ollama_config = self.config.get("ai_config", {}).get("ai3", {}).get("providers", ["ollama1"])[0]
            endpoint = self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
            model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
            
            if not endpoint or not model:
                logger.error("[AI3] Ollama configuration not found. Cannot attempt test fixes.")
                return
                
            # Process each failing test
            for test_path, test_result in failing_tests.items():
                # Find the original file being tested
                original_file = self._get_original_file_from_test(test_path)
                if not original_file:
                    logger.warning(f"[AI3] Could not determine original file for test: {test_path}")
                    continue
                    
                # Get content of both files
                try:
                    with open(os.path.join(self.repo_dir, test_path), 'r', encoding='utf-8') as f:
                        test_content = f.read()
                        
                    original_path = os.path.join(self.repo_dir, original_file)
                    if not os.path.exists(original_path):
                        logger.warning(f"[AI3] Original file not found: {original_file}")
                        continue
                        
                    with open(original_path, 'r', encoding='utf-8') as f:
                        original_content = f.read()
                    
                    # Prepare context for fixing
                    failures_text = "\n".join(test_result.failures[:5])  # Limit to first 5 failures for clarity
                    
                    # Use Ollama to fix the code
                    prompt = f"""
                    I need to fix a failing test. Below are:
                    1. The original implementation file
                    2. The test file that's failing
                    3. The specific test failures
                    
                    Please analyze and fix the ORIGINAL code so the tests pass. Return ONLY the fixed implementation without explanation.
                    
                    ORIGINAL IMPLEMENTATION ({original_file}):
                    ```
                    {original_content}
                    ```
                    
                    TEST FILE ({test_path}):
                    ```
                    {test_content}
                    ```
                    
                    TEST FAILURES:
                    ```
                    {failures_text}
                    ```
                    
                    FIXED IMPLEMENTATION:
                    """
                    
                    logger.info(f"[AI3] Requesting fix for failing test: {test_path}")
                    fixed_code = await call_ollama(prompt, endpoint, model, max_tokens=4000)
                    
                    if fixed_code:
                        # Extract just the code (remove any markdown or explanations)
                        code_pattern = r"```(?:.*?)\n([\s\S]*?)\n```"
                        code_match = re.search(code_pattern, fixed_code)
                        if code_match:
                            fixed_code = code_match.group(1)
                        
                        # Remove any explanations before or after the code
                        if "```" not in fixed_code:
                            lines = fixed_code.split("\n")
                            # Find where the actual code might begin (skip explanatory text)
                            start_idx = 0
                            for i, line in enumerate(lines):
                                if line.strip().startswith("import ") or line.strip().startswith("class ") or line.strip().startswith("def "):
                                    start_idx = i
                                    break
                            fixed_code = "\n".join(lines[start_idx:])
                        
                        # Apply fix if code was generated
                        if fixed_code.strip():
                            logger.info(f"[AI3] Applying fix to: {original_file}")
                            await self.update_file_and_commit(original_file, fixed_code)
                            
                            # Re-run the specific test to verify fix
                            await self._verify_test_fix(test_path)
                        else:
                            logger.warning(f"[AI3] Generated fix was empty for {original_file}")
                            
                except Exception as e:
                    logger.error(f"[AI3] Error attempting to fix test {test_path}: {e}", exc_info=True)
        
        except Exception as e:
            logger.error(f"[AI3] Error in test fix process: {e}", exc_info=True)
    
    async def _verify_test_fix(self, test_path):
        """Verify if a test fix was successful by running the test again"""
        try:
            # Detect test type and run appropriate command
            if test_path.endswith('.py'):
                # Run Python test
                test_cmd = ["python", "-m", "pytest", test_path, "-v"]
            elif test_path.endswith('.js') or test_path.endswith('.jsx') or test_path.endswith('.tsx'):
                # Run JavaScript test
                test_cmd = ["npx", "jest", test_path, "--no-cache"]
            else:
                logger.warning(f"[AI3] Unsupported test file type for verification: {test_path}")
                return False
                
            # Run the test
            orig_dir = os.getcwd()
            os.chdir(self.repo_dir)
            try:
                process = subprocess.run(test_cmd, capture_output=True, text=True)
                success = process.returncode == 0
                
                if success:
                    logger.info(f"[AI3] Test fix verified successfully: {test_path}")
                    # Generate a success report
                    await self._report_fix_success_to_ai1(test_path)
                else:
                    logger.warning(f"[AI3] Test fix was not successful: {test_path}")
                    output = process.stdout + process.stderr
                    # Possibly send for another round of fixing if needed
                    await self._report_fix_failure_to_ai1(test_path, output)
                    
                return success
            finally:
                os.chdir(orig_dir)
                
        except Exception as e:
            logger.error(f"[AI3] Error verifying test fix: {e}", exc_info=True)
            return False
    
    async def _attempt_lint_fixes(self, failing_lints):
        """Attempt to fix linting issues automatically"""
        # Similar to test fixes but for linting issues
        try:
            ollama_config = self.config.get("ai_config", {}).get("ai3", {}).get("providers", ["ollama1"])[0]
            endpoint = self.config.get("providers", {}).get(ollama_config, {}).get("endpoint")
            model = self.config.get("providers", {}).get(ollama_config, {}).get("model")
            
            if not endpoint or not model:
                logger.error("[AI3] Ollama configuration not found. Cannot attempt lint fixes.")
                return
                
            # Process each file with lint errors
            for file_path, lint_result in failing_lints.items():
                try:
                    with open(os.path.join(self.repo_dir, file_path), 'r', encoding='utf-8') as f:
                        file_content = f.read()
                    
                    # Prepare context for fixing
                    failures_text = "\n".join(lint_result.failures[:10])
                    
                    # Use Ollama to fix the code
                    prompt = f"""
                    Fix the following linting issues in this file. Return ONLY the fixed implementation without explanation.
                    
                    FILE ({file_path}):
                    ```
                    {file_content}
                    ```
                    
                    LINTING ERRORS:
                    ```
                    {failures_text}
                    ```
                    
                    FIXED IMPLEMENTATION:
                    """
                    
                    logger.info(f"[AI3] Requesting fix for linting issues: {file_path}")
                    fixed_code = await call_ollama(prompt, endpoint, model)
                    
                    if fixed_code:
                        # Extract just the code (remove any markdown or explanations)
                        code_pattern = r"```(?:.*?)\n([\s\S]*?)\n```"
                        code_match = re.search(code_pattern, fixed_code)
                        if code_match:
                            fixed_code = code_match.group(1)
                        
                        # Apply fix if code was generated
                        if fixed_code.strip():
                            logger.info(f"[AI3] Applying lint fix to: {file_path}")
                            await self.update_file_and_commit(file_path, fixed_code)
                        else:
                            logger.warning(f"[AI3] Generated lint fix was empty for {file_path}")
                except Exception as e:
                    logger.error(f"[AI3] Error attempting to fix lint issues for {file_path}: {e}", exc_info=True)
                    
        except Exception as e:
            logger.error(f"[AI3] Error in lint fix process: {e}", exc_info=True)
    
    async def _send_test_insights_to_ai1(self, insights):
        """Send test insights to AI1 for planning and decision making"""
        try:
            insights_text = "\n".join([f"- {insight}" for insight in insights])
            payload = {
                "source": "AI3",
                "type": "test_insights",
                "details": {
                    "insights": insights_text,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            logger.info(f"[AI3 -> AI1] Sending test insights to AI1")
            await self.create_session()
            async with self.session.post(f"{MCP_API_URL}/ai_collaboration", json=payload, timeout=15) as response:
                if response.status == 200:
                    logger.info("[AI3 -> AI1] Successfully sent test insights to AI1")
                else:
                    logger.error(f"[AI3 -> AI1] Failed to send test insights: {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Error sending test insights to AI1: {e}", exc_info=True)
    
    async def _report_fix_success_to_ai1(self, file_path):
        """Report successful test fix to AI1"""
        try:
            payload = {
                "source": "AI3",
                "type": "test_fix_success",
                "details": {
                    "file_path": file_path,
                    "message": f"Successfully fixed and verified test: {file_path}",
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            logger.info(f"[AI3 -> AI1] Reporting successful test fix for {file_path}")
            await self.create_session()
            async with self.session.post(f"{MCP_API_URL}/ai_collaboration", json=payload, timeout=15) as response:
                if response.status == 200:
                    logger.info(f"[AI3 -> AI1] Successfully reported test fix for {file_path}")
                else:
                    logger.error(f"[AI3 -> AI1] Failed to report test fix: {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Error reporting test fix to AI1: {e}", exc_info=True)
    
    async def _report_fix_failure_to_ai1(self, file_path, output):
        """Report failed test fix attempt to AI1"""
        try:
            # Limit output size to avoid huge payloads
            if len(output) > 2000:
                output = output[:2000] + "... [truncated]"
                
            payload = {
                "source": "AI3",
                "type": "test_fix_failure",
                "details": {
                    "file_path": file_path,
                    "message": f"Failed to fix test: {file_path}",
                    "output": output,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            logger.info(f"[AI3 -> AI1] Reporting failed test fix for {file_path}")
            await self.create_session()
            async with self.session.post(f"{MCP_API_URL}/ai_collaboration", json=payload, timeout=15) as response:
                if response.status == 200:
                    logger.info(f"[AI3 -> AI1] Successfully reported test fix failure for {file_path}")
                else:
                    logger.error(f"[AI3 -> AI1] Failed to report test fix failure: {response.status} - {await response.text()}")
        except Exception as e:
            logger.error(f"[AI3 -> AI1] Error reporting test fix failure to AI1: {e}", exc_info=True)
    
    def _get_original_file_from_test(self, test_file):
        """Determine the original file that is being tested"""
        from utils import get_original_file_from_test
        return get_original_file_from_test(test_file)

    async def start_background_tasks(self):
        """Starts all background monitoring tasks."""
        logger.info("[AI3] Starting AI3 background monitoring tasks...")
        if not hasattr(self, 'background_tasks'):
            self.background_tasks = []

        # Ensure session is created before starting tasks that might use it
        await self.ensure_session()

        # Start idle worker monitor
        idle_monitor_task = asyncio.create_task(self.monitor_idle_workers(), name="IdleWorkerMonitor")
        self.background_tasks.append(idle_monitor_task)
        logger.info("[AI3] Idle worker monitor task created.")

        # Start system error monitor if the method exists
        if hasattr(self, 'monitor_system_errors'):
            error_monitor_task = asyncio.create_task(self.monitor_system_errors(), name="SystemErrorMonitor") # <--- Запуск завдання моніторингу помилок
            self.background_tasks.append(error_monitor_task)
            logger.info("[AI3] System error monitor task created.")
        else:
             logger.warning("[AI3] 'monitor_system_errors' method not found. System error monitoring disabled.")


        # Add other monitoring tasks here if needed
        # e.g., asyncio.create_task(self.monitor_subtask_progress(), name="SubtaskProgressMonitor")

        await asyncio.sleep(0.1) # Allow tasks to potentially start up/log messages
        logger.info(f"[AI3] Total background tasks started: {len(self.background_tasks)}")

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
    if (setup_successful):
        logger.info("[AI3] Structure setup completed successfully. Starting background tasks.")
        await ai3.run()
    else:
        logger.error("[AI3] Structure setup failed. AI3 will not start background monitoring tasks.")
        await ai3.close_session()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[AI3] AI3 stopped by user.")
    except Exception as e:
        logger.critical(f"[AI3] AI3 main execution failed: {e}", exc_info=True)

async def call_ollama(prompt: str, endpoint: str, model: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
    """Calls Ollama API to generate a response based on the prompt."""
    logger.info(f"[AI3-Ollama] Calling Ollama API with model '{model}' at endpoint '{endpoint}'")
    logger.debug(f"[AI3-Ollama] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    try:
        logger.debug(f"[AI3-Ollama] Sending request with max_tokens={max_tokens}, temperature={temperature}")
        start_time = time.time()
        response = requests.post(f"{endpoint}/api/generate", json=payload, timeout=10)
        response.raise_for_status()
        result = response.json().get("response", "")
        elapsed_time = time.time() - start_time
        logger.info(f"[AI3-Ollama] Response received in {elapsed_time:.2f}s: {result[:100]}{'...' if len(result) > 100 else ''}")
        return result
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[AI3-Ollama] Connection error to Ollama API: {e}")
        return ""
    except requests.exceptions.Timeout as e:
        logger.error(f"[AI3-Ollama] Timeout calling Ollama API after {e.args[0] if e.args else '?'}s")
        return ""
    except requests.exceptions.HTTPError as e:
        logger.error(f"[AI3-Ollama] HTTP error from Ollama API: {e} (Status code: {e.response.status_code if hasattr(e, 'response') else 'unknown'})")
        return ""
    except json.JSONDecodeError as e:
        logger.error(f"[AI3-Ollama] Invalid JSON response from Ollama API: {e}")
        return ""
    except Exception as e:
        logger.error(f"[AI3-Ollama] Unexpected error calling Ollama: {e}", exc_info=True)
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
                        logger.debug(f"[AI3] Service check: Status {response.status} from {service_url}")
            except (aiohttp.ClientConnectorError, aiohttp.ClientError, asyncio.TimeoutError):
                pass  # Expected during startup, don't log each failure
            except Exception as e:
                logger.debug(f"[AI3] Error checking service: {e}")
            
            # Check every second
            await asyncio.sleep(1)
    
    logger.warning(f"[AI3] Timeout waiting for service at {service_url} after {timeout}s")
    return False
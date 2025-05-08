import asyncio
import copy
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Third-party libraries
import aiofiles
import aiohttp
import psutil  # Added psutil
from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from pydantic import BaseModel, Field  # Added BaseModel and Field from pydantic

# Local application/library specific imports
from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import call_ollama  # Changed from relative import to absolute import
from utils import GITKEEP_FILENAME
from utils import LOG_DIR as LOGS_DIR
from utils import MCP_API_URL as DEFAULT_MCP_API_URL
from utils import REPO_DIR

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Constants
HTTP_LOCALHOST_7860 = "http://localhost:7860"
DETAILED_EXCEPTION_INFO = "Detailed exception information:"
TESTS_TEST_PREFIX = "tests/test_"
DOT_TEST_SUFFIX = ".test"
DOT_JAVA_SUFFIX = ".java"
ERROR_RETRY_DELAY = 5  # seconds
MAX_LOG_LINE_ANALYSIS = 200
MAX_CONTEXT_LINES = 5
GITHUB_API_BASE_URL = "https://api.github.com"
REPO_PREFIX = "/repo/"
GITIGNORE_FILENAME = ".gitignore"
IDEA_MD_FILENAME = "idea.md"
NES_FLASH_GAME_DIR = "nes_flash_game/"
RETRO_NES_FLASH_GAME_DIR = "retro_nes_flash_game/"
DEFAULT_LOG_ANALYSIS_PROVIDER = "ollama"  # Default provider for log analysis
DEFAULT_LOG_ANALYSIS_MODEL = "llama3"  # Default model for log analysis
DEFAULT_CODE_FIX_PROVIDER = "codestral"  # Default provider for code fixing
DEFAULT_CODE_FIX_MODEL = "codestral-latest"  # Default model for code fixing


def update_structure_provider_in_config(
    config_data: Dict[str, Any], provider_name: str
) -> None:
    """
    Updates the config.json file to save the successful structure provider.
    Also updates the in-memory config_data.
    """
    try:
        updated_config = copy.deepcopy(config_data)
        ai_config = updated_config.setdefault("ai_config", {})
        ai3_config = ai_config.setdefault("ai3", {})
        ai3_config["structure_provider"] = provider_name

        model = None
        # Simplified model selection logic, assuming provider names map to models
        # This should ideally be more robust or data-driven from config
        if provider_name == "codestral":  # Example, adjust as per your provider setup
            model = "codestral-latest"
        elif provider_name == "gemini":
            model = "gemini-1.5-flash"  # Or other appropriate model
        elif (
            provider_name == "ollama"
        ):  # Generic ollama, specific model might be needed
            model = ai3_config.get("model", "llama3")  # Keep existing or default
        # Add other provider-model mappings as needed

        if model:
            ai3_config["model"] = model

        providers_list = ai3_config.setdefault(
            "structure_providers", ["codestral", "gemini"]  # Default list
        )
        if not isinstance(providers_list, list):  # Ensure it's a list
            providers_list = ["codestral", "gemini"]
            ai3_config["structure_providers"] = providers_list

        if provider_name in providers_list:
            providers_list.remove(provider_name)
        providers_list.insert(0, provider_name)

        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(updated_config, f, indent=4)
        logger.info(
            f"[AI3] Updated config.json: provider='{provider_name}', model='{model}'"
        )

        # Update in-memory config_data
        mem_ai_config = config_data.setdefault("ai_config", {})
        mem_ai3_config = mem_ai_config.setdefault("ai3", {})
        mem_ai3_config["structure_provider"] = provider_name
        if model:
            mem_ai3_config["model"] = model
        mem_providers_list = mem_ai3_config.setdefault(
            "structure_providers", ["codestral", "gemini"]
        )
        if not isinstance(mem_providers_list, list):
            mem_providers_list = ["codestral", "gemini"]
            mem_ai3_config["structure_providers"] = mem_providers_list
        if provider_name in mem_providers_list:
            mem_providers_list.remove(provider_name)
        mem_providers_list.insert(0, provider_name)

    except Exception as e:
        logger.error(
            f"[AI3] Error updating structure provider in config: {e}", exc_info=True
        )


async def _initialize_repository(repo_path_str: str) -> Optional[Repo]:
    """Initializes or opens a Git repository at the given path."""
    repo_path = Path(repo_path_str)
    try:
        if not repo_path.exists():
            repo_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"[AI3-Git] Created repository directory: {repo_path}")

        if not repo_path.is_dir():
            logger.error(f"[AI3-Git] Path exists but is not a directory: {repo_path}")
            return None

        try:
            repo = Repo(str(repo_path))
            logger.info(f"[AI3-Git] Opened existing repository: {repo_path}")
        except InvalidGitRepositoryError:
            logger.info(f"[AI3-Git] Initializing new repository: {repo_path}")
            repo = Repo.init(str(repo_path))
            # Initial commit with .gitignore
            gitignore_content = "*.pyc\\n__pycache__/\\n.DS_Store\\n.env\\nlogs/\\ntmp/\\nnode_modules/\\ndist/\\nbuild/\\n*.log\\ncoverage.xml\\n.pytest_cache/\\n.mypy_cache/\\n.idea/\\n.vscode/\\n"
            gitignore_file = repo_path / GITIGNORE_FILENAME
            async with aiofiles.open(gitignore_file, "w", encoding="utf-8") as gf:
                await gf.write(gitignore_content)
            _commit_changes(
                repo, [str(gitignore_file)], f"Initial commit: Add {GITIGNORE_FILENAME}"
            )
            logger.info(
                f"[AI3-Git] Initialized new repo with {GITIGNORE_FILENAME}: {repo_path}"
            )
        return repo
    except GitCommandError as e:
        logger.critical(
            f"[AI3-Git] Git command error during repo init: {e}", exc_info=True
        )
        return None
    except Exception as e:
        logger.critical(
            f"[AI3-Git] Failed to initialize/open repository: {e}", exc_info=True
        )
        return None


def _commit_changes(repo: Repo, file_paths: List[str], message: str):
    """Commits specified files to the repository."""
    if not file_paths:
        logger.info(f"[AI3-Git] No files provided for commit: {message}")
        return

    abs_file_paths = [os.path.abspath(p) for p in file_paths]
    repo_root_abs = os.path.abspath(repo.working_dir)

    paths_to_add = []
    for abs_path_str in abs_file_paths:
        abs_path = Path(abs_path_str)
        if not abs_path.exists():
            logger.warning(f"[AI3-Git] File not found, skipping add: {abs_path_str}")
            continue
        # Ensure path is within the repository
        if not str(abs_path).startswith(repo_root_abs):
            logger.warning(
                f"[AI3-Git] File {abs_path_str} is outside repository {repo_root_abs}, skipping."
            )
            continue
        # Convert absolute path to relative for Git
        relative_path = str(abs_path.relative_to(repo_root_abs))
        paths_to_add.append(relative_path)

    if not paths_to_add:
        logger.info(f"[AI3-Git] No valid files to commit for: {message}")
        return

    try:
        repo.index.add(paths_to_add)
        # Check if there are staged changes
        # For initial commit, diff against an empty tree
        diff_to_head = repo.index.diff("HEAD" if repo.head.is_valid() else None)
        if not diff_to_head:
            logger.info(
                f"[AI3-Git] No actual changes staged for commit: {message}. Files: {paths_to_add}"
            )
            # If files were added but no diff, they might be unchanged or gitignored effectively
            # Check if files are truly gitignored
            actually_ignored = [p for p in paths_to_add if repo.is_ignored(p)]
            if actually_ignored:
                logger.info(f"[AI3-Git] Files are gitignored: {actually_ignored}")
            return

        repo.index.commit(message)
        logger.info(
            f"[AI3-Git] Successfully committed: {message} (Files: {paths_to_add})"
        )
    except GitCommandError as e:
        if (
            "nothing to commit" in str(e).lower()
            or "no changes added to commit" in str(e).lower()
        ):
            logger.info(f"[AI3-Git] Git: Nothing to commit for: {message}")
        else:
            logger.error(
                f"[AI3-Git] Error committing files {paths_to_add} for '{message}': {e}",
                exc_info=True,
            )
    except Exception as e:
        logger.error(
            f"[AI3-Git] Unexpected error during commit for '{message}': {e}",
            exc_info=True,
        )


async def generate_structure_llm_prompt(target_project_description: str) -> str:
    return f"""
    Project Target: {target_project_description}

    Based on the project target described above, generate a detailed JSON structure
    representing the directories and files for this project.
    The JSON structure should be a nested dictionary where keys are filenames or
    directory names, and values are either:
    1. Another dictionary (for a directory).
    2. A string (for a file with initial content).
    3. null (for an empty file).

    Consider typical files needed (e.g., config, tests, docs, main entry points,
    utility modules, build scripts, Dockerfile, README.md, .gitignore).
    Include potential initial content placeholders or comments within the files
    where appropriate (use strings for content, null for empty files).
    Ensure the structure is logical and follows common best practices for the
    described project type. For example, if it's a web application, include
    frontend and backend directories. If it's a Python project, include
    `requirements.txt` or `pyproject.toml`.

    Output ONLY the JSON structure, enclosed in triple backticks
    (```json ... ```), without any introductory text or explanations.
    Example for a simple Python library:
    ```json
    {{
      "my_library/": {{
        "__init__.py": "VERSION = \\"0.1.0\\"",
        "core.py": "# Core functionality here",
        "utils.py": null
      }},
      "tests/": {{
        "__init__.py": null,
        "test_core.py": "# Tests for core.py"
      }},
      "README.md": "# My Library\\nDescription of my library.",
      ".gitignore": "*.pyc\\n__pycache__/",
      "pyproject.toml": "[project]\\nname = \\"my_library\\"\\nversion = \\"0.1.0\\""
    }}
    ```
    """


async def generate_structure_refinement_prompt(
    target_desc: str, current_structure: Dict[str, Any]
) -> str:
    """Generates the prompt for LLM to refine a project structure."""
    return f"""
    Project Target: {target_desc}
    Current Project Structure (JSON):
    ```json
    {json.dumps(current_structure, indent=2)}
    ```

    Review the current project structure. Refine it for the project target.
    Consider adding/removing files, or restructuring for clarity/best practices.
    Output ONLY the refined JSON structure, enclosed in triple backticks (```json ... ```).
    """


async def generate_idea_md_llm_prompt(target_project_description: str) -> str:
    """Generates the prompt for LLM to create an idea.md file."""
    return f"""
    Project Target: {target_project_description}

    Based on the project target, generate a comprehensive `{IDEA_MD_FILENAME}` document.
    This document should outline:
    - Project vision
    - Key features
    - Technical stack considerations
    - Potential challenges
    - High-level roadmap or development strategy.
    The tone should be suitable for a technical lead or project manager.
    Format the output as a Markdown document.

    Output ONLY the Markdown content for `{IDEA_MD_FILENAME}`.
    """


async def _get_provider_instance(
    provider_factory: ProviderFactory,
    provider_name: str,
    config_data: Dict[str, Any],
    ai3_config: Dict[str, Any],
    client_session: aiohttp.ClientSession,
    ui_selected_provider: Optional[str],
    ui_selected_model: Optional[str],
) -> Optional[BaseProvider]:
    """Helper to create and configure a provider instance."""
    provider_global_config = config_data.get("providers", {}).get(provider_name, {})
    ai3_llm_params = {
        k: v
        for k, v in ai3_config.items()
        if k
        not in [
            "structure_provider",
            "structure_providers",
            "idea_md_provider",
            "idea_md_providers",
            "refinement_providers",
        ]
        and not isinstance(v, (dict, list))
    }
    ai3_provider_specific_overrides = (
        ai3_config.get(provider_name, {})
        if isinstance(ai3_config.get(provider_name), dict)
        else {}
    )
    merged_config = {
        **provider_global_config,
        **ai3_llm_params,
        **ai3_provider_specific_overrides,
        "name": provider_name,
    }

    model_to_use = merged_config.get("model")
    if provider_name == ui_selected_provider and ui_selected_model:
        model_to_use = ui_selected_model
        logger.info(
            f"[AI3] Using UI selected model for {provider_name}: {model_to_use}"
        )
    elif provider_name == "structure_fallback":
        model_to_use = None
    elif provider_name == "codestral2":
        model_to_use = "codestral-latest"
    elif provider_name == "gemini":
        model_to_use = "gemini-1.5-flash"
    elif provider_name == "ollama1":
        model_to_use = "llama3.2:latest"

    merged_config["model"] = model_to_use  # Update merged_config with final model

    logger.info(f"[AI3] Final model for provider {provider_name}: {model_to_use}")
    return provider_factory.create_provider(
        provider_name, config_arg=merged_config, session=client_session
    )


async def _generate_with_provider_cycle(
    prompt: str,
    provider_instance: BaseProvider,
    provider_name: str,
    cycle_name: str,
    temperature: float,
    max_tokens: int,
) -> Optional[Dict[str, Any]]:
    """Helper for a single generation cycle (initial or refinement)."""
    try:
        generated_str = await provider_instance.generate(
            prompt=prompt,
            model=provider_instance.config.get(
                "model"
            ),  # Get model from instance config
            temperature=temperature,
            max_tokens=max_tokens,
        )
        await provider_instance.close_session()

        if generated_str:
            json_match = re.search(
                r"```(?:json)?\\s*([\\s\\S]*?)\\s*```", generated_str
            )
            if json_match:
                generated_str = json_match.group(1).strip()
            try:
                parsed_json = json.loads(generated_str)
                logger.info(
                    f"[AI3] {cycle_name}: Parsed structure from {provider_name}"
                )
                return parsed_json
            except json.JSONDecodeError:
                logger.warning(
                    f"[AI3] Invalid JSON from {provider_name} in {cycle_name}. "
                    f"Response: {generated_str[:200]}..."
                )
    except Exception as e:
        logger.error(f"[AI3] Error with provider {provider_name} in {cycle_name}: {e}")
    return None


async def generate_structure(
    target_desc: str,
    provider_factory: ProviderFactory,
    config_data: Dict[str, Any],
    client_session: aiohttp.ClientSession,
    selected_provider_name: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Generates project structure via LLM (initial generation + refinement).
    """
    logger.info(f"[AI3] Starting structure generation for: {target_desc[:100]}...")
    ai3_config = config_data.get("ai_config", {}).get("ai3", {})
    ui_structure_provider = ai3_config.get("structure_provider")
    ui_structure_model = ai3_config.get("structure_model")

    # Determine providers for Cycle 1
    providers_c1 = []
    if selected_provider_name:
        providers_c1 = [selected_provider_name]
    elif ui_structure_provider and isinstance(ui_structure_provider, str):
        providers_c1.append(ui_structure_provider)

    default_providers = ["codestral"]
    structure_providers_list = ai3_config.get("structure_providers", default_providers)
    if not (
        isinstance(structure_providers_list, list)
        and all(isinstance(p, str) for p in structure_providers_list)
    ):
        logger.warning("[AI3] 'structure_providers' invalid. Using default.")
        structure_providers_list = default_providers

    for p_name in structure_providers_list:
        if p_name not in providers_c1:
            providers_c1.append(p_name)
    if not providers_c1:
        providers_c1 = default_providers
        logger.error("[AI3] No providers for Cycle 1. Defaulting.")

    logger.info(f"[AI3] Cycle 1 Providers: {providers_c1}")

    initial_structure: Optional[Dict[str, Any]] = None
    chosen_provider_c1: Optional[str] = None
    prompt_c1 = await generate_structure_llm_prompt(target_desc)

    for provider_name in providers_c1:
        logger.info(f"[AI3] Cycle 1: Trying provider {provider_name}")
        instance = await _get_provider_instance(
            provider_factory,
            provider_name,
            config_data,
            ai3_config,
            client_session,
            ui_structure_provider,
            ui_structure_model,
        )
        if not instance:
            logger.error(f"[AI3] Cycle 1: Failed to create {provider_name}")
            continue

        initial_structure = await _generate_with_provider_cycle(
            prompt_c1,
            instance,
            provider_name,
            "Cycle 1",
            instance.config.get("temperature", 0.5),
            instance.config.get("max_tokens", 3000),
        )
        if initial_structure:
            chosen_provider_c1 = provider_name
            update_structure_provider_in_config(config_data, provider_name)
            break

    # Determine providers for Cycle 2
    providers_c2 = []
    refinement_cfg = ai3_config.get("refinement_providers")
    if selected_provider_name:
        providers_c2 = [selected_provider_name]
    elif isinstance(refinement_cfg, list) and all(
        isinstance(p, str) for p in refinement_cfg
    ):
        providers_c2 = refinement_cfg
    elif chosen_provider_c1:
        providers_c2.append(chosen_provider_c1)
        for p_name in providers_c1:  # Reuse Cycle 1 list
            if p_name not in providers_c2:
                providers_c2.append(p_name)
    else:
        providers_c2 = providers_c1  # Fallback

    if not providers_c2:
        providers_c2 = default_providers
        logger.error("[AI3] No providers for Cycle 2. Defaulting.")
    logger.info(f"[AI3] Cycle 2 Providers: {providers_c2}")

    refined_structure: Optional[Dict[str, Any]] = None
    if initial_structure:
        prompt_c2 = await generate_structure_refinement_prompt(
            target_desc, initial_structure
        )
        for provider_name in providers_c2:
            logger.info(f"[AI3] Cycle 2: Trying provider {provider_name}")
            instance = await _get_provider_instance(
                provider_factory,
                provider_name,
                config_data,
                ai3_config,
                client_session,
                ui_structure_provider,
                ui_structure_model,
            )
            if not instance:
                logger.error(f"[AI3] Cycle 2: Failed to create {provider_name}")
                continue

            refined_structure = await _generate_with_provider_cycle(
                prompt_c2,
                instance,
                provider_name,
                "Cycle 2",
                instance.config.get("temperature", 0.3),
                instance.config.get("max_tokens", 4000),
            )
            if refined_structure:
                break  # Use first successful refinement

    if refined_structure:
        return refined_structure, chosen_provider_c1
    return initial_structure, chosen_provider_c1


async def send_structure_to_mcp(
    structure_obj: Dict[str, Any],
    target_desc: str,
    mcp_api_url: str,
    client_session: aiohttp.ClientSession,
) -> bool:
    """Sends the generated project structure to the MCP API."""
    api_url = f"{mcp_api_url}/structure"
    payload = {"structure": structure_obj, "target": target_desc}
    logger.debug(f"[AI3->API] Struct keys: {list(structure_obj.keys())}")

    if IDEA_MD_FILENAME not in structure_obj:
        logger.warning(
            f"[AI3->API] {IDEA_MD_FILENAME} not in structure. Adding default."
        )
        structure_obj[IDEA_MD_FILENAME] = "# Project Overview\\n\\nDetails here."
        payload["structure"] = structure_obj  # Update payload

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with client_session.post(api_url, json=payload, timeout=30) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info(f"[AI3->API] Structure sent. Resp: {response_text}")
                    # Trigger AI1
                    try:
                        ai1_url = f"{mcp_api_url}/start_ai1"
                        ai1_payload = {"reason": "Structure by AI3", "status": "ready"}
                        async with client_session.post(
                            ai1_url, json=ai1_payload, timeout=30
                        ) as ai1_resp:
                            if ai1_resp.status == 200:
                                logger.info("[AI3->API] Triggered AI1 start")
                            else:
                                logger.warning(
                                    f"[AI3->API] Failed to trigger AI1: {ai1_resp.status}"
                                )
                    except Exception as ai1_e:
                        logger.error(f"[AI3->API] Error triggering AI1: {ai1_e}")
                    return True
                else:
                    logger.error(
                        f"[AI3->API] Error sending structure. Status: "
                        f"{resp.status}, Response: {response_text}"
                    )
                    if attempt < max_retries - 1:
                        logger.info(f"[AI3->API] Retrying upload (attempt {attempt+2})")
                        await asyncio.sleep(ERROR_RETRY_DELAY)
                    else:
                        return False  # All retries failed
        except asyncio.TimeoutError:
            logger.error(f"[AI3->API] Timeout sending structure (attempt {attempt+1})")
            if attempt < max_retries - 1:
                await asyncio.sleep(ERROR_RETRY_DELAY)
            else:
                return False  # All retries failed
        except aiohttp.ClientConnectionError as e:
            logger.error(f"[AI3->API] Connection error sending structure: {e}")
            return False  # No retry on connection error immediately
        except Exception as e:
            logger.error(
                f"[AI3->API] Unexpected error sending structure: {e}",
                exc_info=True,
            )
            return False  # No retry on unexpected error
    return False


async def _report_status_to_mcp(
    status: str,
    details: Optional[Dict[str, Any]],
    mcp_api_url: str,
    client_session: aiohttp.ClientSession,
) -> bool:
    api_url = f"{mcp_api_url}/report_status"
    payload = {"source": "ai3", "status": status, "details": details or {}}
    try:
        async with client_session.post(api_url, json=payload, timeout=15) as resp:
            if resp.status == 200:
                logger.debug(f"[AI3->API] Report '{status}' sent.")
                return True
            else:
                response_text = await resp.text()
                logger.error(
                    f"[AI3->API] Failed report '{status}'. "
                    f"Status: {resp.status}, Resp: {response_text}"
                )
                return False
    except asyncio.TimeoutError:
        logger.error(f"[AI3->API] Timeout sending report '{status}'.")
        return False
    except aiohttp.ClientConnectionError as e:
        logger.error(f"[AI3->API] Connection error sending report: {e}")
        return False
    except Exception as e:
        logger.error(
            f"[AI3->API] Unexpected error sending report: {e}",
            exc_info=True,
        )
        return False


async def _initiate_collaboration_via_mcp(
    error_description: str,
    context: Optional[Dict[str, Any]],
    mcp_api_url: str,
    client_session: aiohttp.ClientSession,
) -> bool:
    api_url = f"{mcp_api_url}/collaboration_request"
    payload = {
        "source": "ai3",
        "error_description": error_description,
        "context": context or {},
    }
    logger.info(
        f"[AI3->API] Initiating collaboration via {api_url} "
        f"for error: {error_description[:100]}..."
    )
    try:
        async with client_session.post(api_url, json=payload, timeout=30) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                logger.info(
                    f"[AI3->API] Collaboration request sent. Resp: {response_text}"
                )
                return True
            else:
                logger.error(
                    f"[AI3->API] Failed collaboration request. Status: "
                    f"{resp.status}, Resp: {response_text}"
                )
                return False
    except asyncio.TimeoutError:
        logger.error("[AI3->API] Timeout initiating collaboration.")
        return False
    except aiohttp.ClientConnectionError as e:
        logger.error(f"[AI3->API] Connection error initiating collaboration: {e}")
        return False
    except Exception as e:
        logger.error(
            f"[AI3->API] Unexpected error initiating collaboration: {e}",
            exc_info=True,
        )
        return False


async def _create_single_file_or_dir(
    full_path_on_disk: str,
    path_in_repo_for_item: str,
    value: Any,
    base_path: str,
    created_files_list: List[str],
    skipped_files_list: List[str],
):
    """Helper to create a single file or directory."""
    try:
        if isinstance(value, dict):  # Directory
            os.makedirs(full_path_on_disk, exist_ok=True)
            logger.info(f"[AI3] Created dir: {path_in_repo_for_item}")
            # Return True to indicate directory, for .gitkeep logic
            return True
        elif isinstance(value, str) or value is None:  # File
            parent_dir = os.path.dirname(full_path_on_disk)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
                logger.info(
                    f"[AI3] Created parent dir: "
                    f"{os.path.relpath(parent_dir, base_path)}"
                )
            if not os.path.exists(full_path_on_disk):
                async with aiofiles.open(full_path_on_disk, "w", encoding="utf-8") as f:
                    if value is not None:
                        await f.write(value)
                logger.info(f"[AI3] Created file: {path_in_repo_for_item}")
                created_files_list.append(full_path_on_disk)
            else:
                logger.info(f"[AI3] File exists, skipping: {path_in_repo_for_item}")
                skipped_files_list.append(full_path_on_disk)
        else:
            logger.warning(
                f"[AI3] Unknown type '{type(value)}' for '{path_in_repo_for_item}'"
            )
    except OSError as e:
        logger.error(f"[AI3] OS error creating {full_path_on_disk}: {e}", exc_info=True)
        skipped_files_list.append(full_path_on_disk)
    except Exception as e:
        logger.error(
            f"[AI3] Unexpected error creating {full_path_on_disk}: {e}",
            exc_info=True,
        )
        skipped_files_list.append(full_path_on_disk)
    return False  # Not a directory or error occurred


async def create_files_from_structure(
    base_path: str,
    struct: Dict[str, Any],
    repo: Optional[Repo] = None,
    initial_commit: bool = True,
    current_path_in_repo: str = "",
) -> Tuple[List[str], List[str]]:
    if not isinstance(struct, dict):
        logger.error(f"[AI3] Invalid structure: Expected dict, got {type(struct)}")
        return [], []

    created_files: List[str] = []
    skipped_files: List[str] = []
    abs_base_path = os.path.abspath(os.path.normpath(base_path))

    # Sort to process .gitignore first if at root
    sorted_items = sorted(
        struct.items(), key=lambda item: item[0] == GITIGNORE_FILENAME, reverse=True
    )

    for key, value in sorted_items:
        if not key:
            logger.warning(f"[AI3] Skipped creating entry for empty key: {key}")
            continue

        sanitized_key = key.replace("..", "").strip()
        if not sanitized_key or sanitized_key != key:
            logger.warning(
                f"[AI3] Key '{key}' sanitized to '{sanitized_key}'. "
                "Skipping if empty, or using sanitized."
            )
            if not sanitized_key:
                continue
            key = sanitized_key

        path_in_repo = os.path.join(current_path_in_repo, key)
        full_disk_path = os.path.join(abs_base_path, path_in_repo)

        is_dir = await _create_single_file_or_dir(
            full_disk_path,
            path_in_repo,
            value,
            abs_base_path,
            created_files,
            skipped_files,
        )

        if is_dir and isinstance(
            value, dict
        ):  # If it was a directory and has sub-structure
            sub_created, sub_skipped = await create_files_from_structure(
                abs_base_path, value, repo, False, path_in_repo  # Pass abs_base_path
            )
            created_files.extend(sub_created)
            skipped_files.extend(sub_skipped)
            # Add .gitkeep to empty directories (after sub-structure processed)
            if not os.listdir(full_disk_path) and current_path_in_repo:
                gitkeep_path = os.path.join(full_disk_path, GITKEEP_FILENAME)
                async with aiofiles.open(gitkeep_path, "w", encoding="utf-8") as f:
                    await f.write("")
                logger.info(f"[AI3] Created .gitkeep in empty dir: {path_in_repo}")
                created_files.append(gitkeep_path)

    if initial_commit and repo and created_files:
        logger.info(f"[AI3] Committing {len(created_files)} created files...")
        _commit_changes(repo, created_files, "AI3: Initial project structure")

    return created_files, skipped_files


async def _generate_idea_md_content_with_provider(
    provider_instance: BaseProvider, prompt: str, provider_name: str
) -> Optional[str]:
    """Helper to generate idea.md content with a single provider."""
    try:
        content_str = await provider_instance.generate(
            prompt=prompt,
            model=provider_instance.config.get("model"),
            temperature=provider_instance.config.get("temperature", 0.7),
            max_tokens=provider_instance.config.get("max_tokens", 1500),
        )
        if content_str:
            logger.info(
                f"[AI3] Generated {IDEA_MD_FILENAME} content using {provider_name}"
            )
            return content_str
        else:
            logger.warning(
                f"[AI3] Provider {provider_name} returned empty for {IDEA_MD_FILENAME}."
            )
    except Exception as e:
        logger.error(
            f"[AI3] Error with provider {provider_name} for {IDEA_MD_FILENAME}: {e}"
        )
    return None


async def generate_initial_idea_md(
    target: str,
    provider_factory: ProviderFactory,
    config_data: Dict[str, Any],
    client_session: aiohttp.ClientSession,
    selected_provider_name: Optional[str] = None,
) -> str:
    """Generates initial idea.md content using LLM, with fallback."""
    logger.info(f"[AI3] Generating {IDEA_MD_FILENAME} for target: {target}")
    ai3_config = config_data.get("ai_config", {}).get("ai3", {})

    providers_to_try: List[str] = []
    specific_provider = ai3_config.get("idea_md_provider")

    if selected_provider_name:
        providers_to_try = [selected_provider_name]
    elif specific_provider and isinstance(specific_provider, str):
        providers_to_try.append(specific_provider)

    default_idea_providers = ["codestral"]
    idea_providers_list = ai3_config.get("idea_md_providers", default_idea_providers)
    if not (
        isinstance(idea_providers_list, list)
        and all(isinstance(p, str) for p in idea_providers_list)
    ):
        logger.warning("[AI3] 'idea_md_providers' invalid. Using default.")
        idea_providers_list = default_idea_providers

    for p_name in idea_providers_list:
        if p_name not in providers_to_try:
            providers_to_try.append(p_name)

    if not providers_to_try:
        providers_to_try = default_idea_providers
        logger.error(f"[AI3] No providers for {IDEA_MD_FILENAME}. Defaulting.")

    logger.info(f"[AI3] Providers for {IDEA_MD_FILENAME}: {providers_to_try}")

    prompt = await generate_idea_md_llm_prompt(target)
    idea_md_content: str = ""

    for provider_name in providers_to_try:
        logger.info(f"[AI3] Trying provider for {IDEA_MD_FILENAME}: {provider_name}")
        instance = await _get_provider_instance(  # Use the helper
            provider_factory,
            provider_name,
            config_data,
            ai3_config,
            client_session,
            ai3_config.get("idea_md_provider"),  # UI selected provider for idea.md
            ai3_config.get("idea_md_model"),  # UI selected model for idea.md
        )
        if not instance:
            logger.error(
                f"[AI3] Failed to create {provider_name} for {IDEA_MD_FILENAME}"
            )
            continue

        content = await _generate_idea_md_content_with_provider(
            instance, prompt, provider_name
        )
        if content:
            idea_md_content = content
            break  # Success

    return idea_md_content


async def ensure_idea_md_exists(
    repo_dir: str,
    target: str,
    provider_factory: ProviderFactory,  # Corrected type
    config: Dict[str, Any],
    client_session: aiohttp.ClientSession,
) -> bool:
    """
    Ensures idea.md exists, creating it if needed. Safeguard for AI1.
    """
    idea_md_path = os.path.join(repo_dir, IDEA_MD_FILENAME)

    if os.path.exists(idea_md_path):
        logger.info(f"[AI3] {IDEA_MD_FILENAME} already exists at {idea_md_path}")
        return True

    logger.info(f"[AI3] {IDEA_MD_FILENAME} not found, generating: {idea_md_path}")
    idea_md_content = await generate_initial_idea_md(
        target, provider_factory, config, client_session
    )

    if not idea_md_content:
        idea_md_content = (
            f"# Project: {target}\\n\\nThis project aims to "
            f"create a {target} as specified."
        )
        logger.warning(
            f"[AI3] Failed LLM gen for {IDEA_MD_FILENAME}, using basic template"
        )

    try:
        async with aiofiles.open(idea_md_path, "w", encoding="utf-8") as f:
            await f.write(idea_md_content)
        logger.info(f"[AI3] Successfully created {IDEA_MD_FILENAME} at {idea_md_path}")
        try:
            repo = Repo(repo_dir)
            _commit_changes(
                repo, [idea_md_path], f"AI3: Create initial {IDEA_MD_FILENAME}"
            )
            logger.info(f"[AI3] Committed {IDEA_MD_FILENAME} to repository")
        except (InvalidGitRepositoryError, GitCommandError) as e:
            logger.warning(f"[AI3] Could not commit {IDEA_MD_FILENAME}: {e}")
        return True
    except Exception as e:
        logger.error(f"[AI3] Error creating {IDEA_MD_FILENAME}: {e}", exc_info=True)
        return False


class AI3:
    """Main class for AI3 operations."""

    def __init__(
        self,
        target: str,
        provider_factory: ProviderFactory,
        config_data: Dict[str, Any],
        client_session: aiohttp.ClientSession,
    ):
        self.target = target
        self.provider_factory = provider_factory
        self.config_data = config_data
        self.client_session = client_session
        self.repo_dir = self.config_data.get(
            "repo_dir", REPO_DIR
        )  # Use config or default
        self.mcp_api_url = self.config_data.get("mcp_api_url", DEFAULT_MCP_API_URL)
        self.ai_config = self.config_data.get("ai_config", {})
        self.ai3_config = self.ai_config.get("ai3", {})
        self.repo: Optional[Repo] = None
        self.monitoring_tasks: List[asyncio.Task] = []
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_repo_owner = self.ai3_config.get("github_repo_owner")
        self.github_repo_name = self.ai3_config.get("github_repo_name")

        self.current_project_structure: Optional[Dict[str, Any]] = (
            None  # Initialize attribute
        )

        self._initialize_ollama_config()  # For log analysis
        self._initialize_code_fix_config()  # For code fixing

        if not self.github_token:
            logger.warning(
                "[AI3] GITHUB_TOKEN not set. GitHub Actions monitoring will be disabled."
            )
        if not (self.github_repo_owner and self.github_repo_name):
            logger.warning(
                "[AI3] GitHub repo owner/name not configured. "
                "GitHub Actions monitoring will be limited."
            )
        self.processed_log_files: Dict[Path, int] = (
            {}
        )  # For tracking processed log lines
        self.active_log_analyses: Dict[Path, asyncio.Lock] = (
            {}
        )  # To prevent concurrent analysis of same log

    def _initialize_ollama_config(self):
        """Initializes configuration for Ollama (or other log analysis provider)."""
        log_analysis_defaults = {
            "provider": DEFAULT_LOG_ANALYSIS_PROVIDER,
            "model": DEFAULT_LOG_ANALYSIS_MODEL,
            "endpoint": self.ai3_config.get(
                "ollama_endpoint"
            ),  # Legacy, prefer provider config
            # Add other params like temperature, max_tokens if needed for log analysis
        }

        # Prefer provider-specific config within ai3_config if available
        # e.g., ai3_config: { "log_analysis": { "provider": "ollama", "model": "phi3" } }
        log_analysis_cfg = self.ai3_config.get("log_analysis", {})

        self.log_analysis_provider_name = log_analysis_cfg.get(
            "provider", log_analysis_defaults["provider"]
        )
        self.log_analysis_model = log_analysis_cfg.get(
            "model", log_analysis_defaults["model"]
        )
        # Store the whole sub-config if needed for _get_provider_instance
        self.log_analysis_provider_config = {
            "model": self.log_analysis_model,
            "endpoint": log_analysis_cfg.get(
                "endpoint", log_analysis_defaults["endpoint"]
            ),
            # Add other relevant parameters from log_analysis_cfg or defaults
        }
        logger.info(
            f"[AI3] Log analysis configured: Provider='{self.log_analysis_provider_name}', "
            f"Model='{self.log_analysis_model}'"
        )

    def _initialize_code_fix_config(self):
        """Initializes configuration for the code fixing provider."""
        code_fix_defaults = {
            "provider": DEFAULT_CODE_FIX_PROVIDER,
            "model": DEFAULT_CODE_FIX_MODEL,
        }
        code_fix_cfg = self.ai3_config.get("code_fixing", {})

        self.code_fix_provider_name = code_fix_cfg.get(
            "provider", code_fix_defaults["provider"]
        )
        self.code_fix_model = code_fix_cfg.get("model", code_fix_defaults["model"])
        self.code_fix_provider_config = {
            "model": self.code_fix_model,
            # Add other relevant parameters like temperature, max_tokens
            "temperature": code_fix_cfg.get("temperature", 0.3),  # Example
            "max_tokens": code_fix_cfg.get("max_tokens", 2048),  # Example
        }
        logger.info(
            f"[AI3] Code fixing configured: Provider='{self.code_fix_provider_name}', "
            f"Model='{self.code_fix_model}'"
        )

    async def _send_test_recommendation_to_mcp(
        self, recommendation_data: Dict[str, Any]
    ) -> bool:
        """Sends test analysis results and recommendations to MCP."""
        api_url = f"{self.mcp_api_url}/test_recommendation"
        payload = {
            "source": "ai3",
            "recommendation": recommendation_data.get("recommendation", "review"),
            "summary": recommendation_data.get("summary", "No summary provided."),
            "details": recommendation_data,  # Send the whole analysis
            "run_id": recommendation_data.get("run_id"),
            "run_url": recommendation_data.get("run_url"),
            "failed_files": recommendation_data.get("failed_files", []),
            "fixed_files": recommendation_data.get(
                "fixed_files", []
            ),  # From _attempt_test_fixes
            "unfixed_files": recommendation_data.get(
                "unfixed_files", []
            ),  # From _attempt_test_fixes
        }
        logger.info(
            f"[AI3->MCP] Sending test recommendation: {payload.get('recommendation')}"
        )
        try:
            async with self.client_session.post(
                api_url, json=payload, timeout=30
            ) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info(
                        f"[AI3->MCP] Test recommendation sent. Response: {response_text}"
                    )
                    return True
                else:
                    logger.error(
                        f"[AI3->MCP] Failed to send test recommendation. Status: {resp.status}, "
                        f"Response: {response_text}"
                    )
                    return False
        except asyncio.TimeoutError:
            logger.error("[AI3->MCP] Timeout sending test recommendation.")
            return False
        except aiohttp.ClientConnectionError as e:
            logger.error(
                f"[AI3->MCP] Connection error sending test recommendation: {e}"
            )
            return False
        except Exception as e:
            logger.error(
                f"[AI3->MCP] Unexpected error sending test recommendation: {e}",
                exc_info=True,
            )
            return False

    async def start_monitoring(self):
        """Start all monitoring background tasks."""
        logger.info("[AI3] Starting background monitoring tasks...")
        self.monitoring_active = True
        monitor_tasks_coroutines = [
            self.monitor_system_health(),
            self.monitor_github_actions(),
            self.monitor_idle_workers(),
            self.monitor_tests(),  # Added test monitoring
            # Add more monitoring tasks as needed
        ]
        self.background_tasks = [
            asyncio.create_task(coro) for coro in monitor_tasks_coroutines
        ]
        logger.info(f"[AI3] Started {len(self.background_tasks)} background tasks")

    async def stop_monitoring(self):
        """Stop all monitoring background tasks."""
        logger.info(f"[AI3] Stopping {len(self.background_tasks)} background tasks...")
        self.monitoring_active = False
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.background_tasks.clear()
        logger.info("[AI3] All background monitoring tasks stopped")

    async def clear_repository(self) -> bool:
        """Clears the project repository directory."""
        repo_path = Path(self.repo_dir)
        logger.info(f"[AI3] Clearing repository directory: {repo_path}")
        try:
            if repo_path.exists():
                # Be careful with shutil.rmtree
                # Add checks or make it configurable if it's too dangerous
                for item in repo_path.iterdir():
                    if item.is_dir():
                        # Preserve .git directory if it exists and is a git repo
                        if item.name == ".git" and (repo_path / ".git").is_dir():
                            logger.info("[AI3] Preserving .git directory.")
                            continue
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                logger.info(f"[AI3] Repository directory cleared: {repo_path}")
            else:
                logger.info(
                    f"[AI3] Repository directory does not exist, no need to clear: {repo_path}"
                )

            # Recreate the directory if it was removed entirely by rmtree (if .git wasn't there)
            repo_path.mkdir(exist_ok=True)

            await _report_status_to_mcp(
                "repo_cleared",
                {"path": str(repo_path)},
                self.mcp_api_url,
                self.client_session,
            )
            return True
        except Exception as e:
            logger.error(
                f"[AI3] Error clearing repository {repo_path}: {e}", exc_info=True
            )
            await _report_status_to_mcp(
                "repo_clear_failed",
                {"path": str(repo_path), "error": str(e)},
                self.mcp_api_url,
                self.client_session,
            )
            return False

    async def _perform_mcp_health_check(self) -> bool:
        """Performs health check for MCP API."""
        try:
            async with self.client_session.get(
                self.mcp_api_url + "/health", timeout=10  # Shorter timeout
            ) as resp:
                if resp.status == 200:
                    logger.info("[AI3] MCP API health check OK.")
                    return True
                logger.warning(
                    f"[AI3] MCP API health check failed: {resp.status}. Retrying..."
                )
        except Exception as e:
            logger.error(f"[AI3] MCP API health check error: {e}. Retrying...")
        await asyncio.sleep(ERROR_RETRY_DELAY)  # Wait before retry
        return False

    async def _initialize_git_repo_in_dir(self) -> bool:
        """Initializes a Git repository in self.repo_dir."""
        original_cwd = os.getcwd()
        try:
            # Ensure the repository directory exists before changing into it
            Path(self.repo_dir).mkdir(parents=True, exist_ok=True)
            os.chdir(self.repo_dir)
            self.repo = Repo.init(".")
            logger.info(
                f"[AI3-Git] Initialized new Git repo at: {self.repo_dir} (CWD: {os.getcwd()})"
            )

            # .gitignore path is now relative to the CWD (which is self.repo_dir, the repo root)
            gitignore_filename_in_repo = GITIGNORE_FILENAME

            if not os.path.exists(gitignore_filename_in_repo):
                logger.info(
                    f"[AI3-Git] Creating {gitignore_filename_in_repo} in {os.getcwd()} (fallback)."
                )
                with open(gitignore_filename_in_repo, "w", encoding="utf-8") as f:
                    f.write(
                        "__pycache__/\\n*.pyc\\nlogs/\\ntmp/\\nnode_modules/\\ndist/\\nbuild/\\n*.log\\ncoverage.xml\\n.pytest_cache/\\n.mypy_cache/\\n.idea/\\n.vscode/\\n"
                    )  # Basic .gitignore
                _commit_changes(
                    self.repo,
                    [gitignore_filename_in_repo],
                    f"Initial commit: Add {gitignore_filename_in_repo}",
                )
            return True
        except Exception as e:
            logger.critical(
                f"[AI3-Git] Failed to init Git repo in '{self.repo_dir}': {e}",
                exc_info=True,
            )
            await _report_status_to_mcp(
                "error_git_init_failed",
                {"details": str(e), "path": self.repo_dir},
                self.mcp_api_url,
                self.client_session,
            )
            return False
        finally:
            os.chdir(original_cwd)

    async def _generate_and_create_project_structure(self) -> Optional[Dict[str, Any]]:
        """Generates structure JSON and creates files."""
        structure = None
        for attempt in range(3):  # Retry structure generation
            logger.info(f"[AI3] Structure generation attempt {attempt + 1}/3")
            try:
                structure, _ = await generate_structure(  # chosen_provider unused here
                    self.target,
                    self.provider_factory,
                    self.config_data,
                    self.client_session,
                )
                if structure:
                    logger.info(
                        "[AI3] Successfully generated structure. Root keys: "
                        f"{list(structure.keys())}"
                    )
                    break
            except Exception as e:
                logger.error(f"[AI3] Error in structure gen attempt {attempt + 1}: {e}")
            if attempt < 2:  # If not the last attempt
                await asyncio.sleep(ERROR_RETRY_DELAY)  # Wait before retrying

        if not structure:
            logger.critical("[AI3] All structure generation attempts failed.")
            await _report_status_to_mcp(
                "error_structure_generation_failed",
                {"details": "All LLM structure gen attempts failed"},
                self.mcp_api_url,
                self.client_session,
            )
            return None

        self.current_project_structure = structure  # Store it

        # Handle potential duplicate project folders
        has_retro = RETRO_NES_FLASH_GAME_DIR in structure
        has_nes = NES_FLASH_GAME_DIR in structure
        if has_retro and has_nes:
            logger.warning(
                f"[AI3] Both '{RETRO_NES_FLASH_GAME_DIR}' and '{NES_FLASH_GAME_DIR}' found. "
                f"Removed '{NES_FLASH_GAME_DIR}'."
            )
            del structure[NES_FLASH_GAME_DIR]
        elif has_nes and not has_retro:
            logger.info(
                f"[AI3] Only '{NES_FLASH_GAME_DIR}' found. Renamed to '{RETRO_NES_FLASH_GAME_DIR}'."
            )
            structure[RETRO_NES_FLASH_GAME_DIR] = structure.pop(NES_FLASH_GAME_DIR)

        # Remove 'idea' or 'idea.md' from LLM structure to avoid conflict
        for key_to_remove in ["idea", IDEA_MD_FILENAME]:
            if key_to_remove in structure:
                del structure[key_to_remove]
                logger.info(f"[AI3] Removed '{key_to_remove}' from LLM structure.")

        created_files, skipped_files = [], []
        for attempt in range(3):  # Retry file creation
            try:
                created_files, skipped_files = await create_files_from_structure(
                    self.repo_dir, structure, self.repo, True  # Pass repo for commit
                )
                if created_files or skipped_files:  # If something happened
                    break
                logger.warning(
                    f"[AI3] No files created/skipped, retrying ({attempt+1}/3)"
                )
            except Exception as e:
                logger.error(f"[AI3] Error creating files (attempt {attempt+1}): {e}")
            if attempt < 2:
                await asyncio.sleep(ERROR_RETRY_DELAY)

        logger.info(
            f"[AI3] File creation: {len(created_files)} created, {len(skipped_files)} skipped"
        )
        await _report_status_to_mcp(
            "structure_creation_completed",
            {"created": len(created_files), "skipped": len(skipped_files)},
            self.mcp_api_url,
            self.client_session,
        )
        if not created_files and not skipped_files:  # If truly nothing happened
            logger.critical("[AI3] Failed to create any project files.")
            # Continue to ensure idea.md is attempted

        return structure

    async def _ensure_and_send_idea_md_to_mcp(self, final_structure: Dict[str, Any]):
        """Ensures idea.md exists, updates structure, and sends to MCP."""
        idea_md_created_or_exists = await ensure_idea_md_exists(
            self.repo_dir,
            self.target,
            self.provider_factory,
            self.config_data,
            self.client_session,
        )
        if not idea_md_created_or_exists:
            logger.error(f"[AI3] Critical: Failed to ensure {IDEA_MD_FILENAME} exists.")
            # Proceed to send structure anyway, MCP might handle missing idea.md

        # Add idea.md to the structure to be sent if not already (should be by ensure_idea_md_exists)
        if IDEA_MD_FILENAME not in final_structure and os.path.exists(
            os.path.join(self.repo_dir, IDEA_MD_FILENAME)
        ):
            try:
                async with aiofiles.open(
                    os.path.join(self.repo_dir, IDEA_MD_FILENAME), "r", encoding="utf-8"
                ) as f:
                    final_structure[IDEA_MD_FILENAME] = await f.read()
            except Exception as e:
                logger.error(
                    f"[AI3] Failed to read {IDEA_MD_FILENAME} for MCP structure: {e}"
                )
                final_structure[IDEA_MD_FILENAME] = "# Error reading idea.md"

        mcp_send_success = False
        for attempt in range(3):
            logger.info(f"[AI3] Sending structure to MCP (attempt {attempt+1}/3)")
            if await send_structure_to_mcp(
                final_structure, self.target, self.mcp_api_url, self.client_session
            ):
                mcp_send_success = True
                break
            logger.warning(f"[AI3] MCP structure send attempt {attempt+1} failed.")
            if attempt < 2:
                await asyncio.sleep(ERROR_RETRY_DELAY)

        if not mcp_send_success:
            logger.error("[AI3] Failed to send final structure to MCP.")
            await _report_status_to_mcp(
                "error_mcp_send_failed",
                {"details": "Failed to send structure to MCP"},
                self.mcp_api_url,
                self.client_session,
            )
        else:
            logger.info("[AI3] Final structure successfully sent to MCP.")
            await _report_status_to_mcp(
                "structure_setup_completed",
                {"final_keys": list(final_structure.keys())},
                self.mcp_api_url,
                self.client_session,
            )

    async def setup_structure(self):
        logger.info("[AI3] Starting project structure setup...")
        if not await self._perform_mcp_health_check():
            logger.critical("[AI3] MCP API unavailable after retries. Aborting setup.")
            return

        if not await self.clear_repository():
            logger.critical("[AI3] Repo clearing failed. Aborting setup.")
            await _report_status_to_mcp(
                "error_repo_clear_failed",
                {"details": "Failed to clear repo"},
                self.mcp_api_url,
                self.client_session,
            )
            return
        await _report_status_to_mcp(
            "repo_cleared", None, self.mcp_api_url, self.client_session
        )

        if not await self._initialize_git_repo_in_dir():
            logger.critical("[AI3] Git repo init failed. Aborting setup.")
            return  # Error reported in helper

        # Remove unexpected "project/" directory
        project_path = Path(self.repo_dir) / "project"
        if project_path.exists() and project_path.is_dir():
            logger.warning(f"[AI3] Removing unexpected 'project/' dir: {project_path}")
            try:
                shutil.rmtree(project_path)
            except Exception as e:
                logger.error(f"[AI3] Error removing 'project/' dir: {e}")

        generated_structure = await self._generate_and_create_project_structure()
        if not generated_structure:
            logger.critical(
                "[AI3] Structure generation/creation failed. Aborting further setup."
            )
            # Errors reported in helper
            return

        await self._ensure_and_send_idea_md_to_mcp(generated_structure)

        # Explicitly signal AI1 to start if structure was generated
        # This is also done inside send_structure_to_mcp, but can be a fallback
        if generated_structure:
            try:
                async with self.client_session.post(
                    f"{self.mcp_api_url}/start_ai1",
                    json={"reason": "AI3 setup_structure complete"},
                    timeout=15,
                ) as resp:
                    if resp.status == 200:
                        logger.info("[AI3] Signaled AI1 to start (post-setup).")
                    else:
                        logger.warning(
                            f"[AI3] Signal AI1 (post-setup) status: {resp.status}"
                        )
            except Exception as e:
                logger.error(f"[AI3] Error signaling AI1 (post-setup): {e}")

        logger.info("[AI3] Structure setup phase completed.")

    async def _check_service_status(
        self, service_name: str, health_metrics: Dict[str, Any]
    ):
        """Helper to check status of a single service."""
        pid_file = Path(LOGS_DIR) / f"{service_name}.pid"
        log_file = Path(LOGS_DIR) / f"{service_name}.log"
        status_info = {
            "status": "UNKNOWN",
            "pid_found": False,
            "running": False,
            "log_exists": log_file.exists(),
        }
        try:
            if pid_file.exists():
                status_info["pid_found"] = True
                with open(pid_file, "r") as pf:
                    pid = int(pf.read().strip())
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    # Basic check if process name/cmdline matches expected, if possible
                    # For now, just checking if PID is running
                    status_info["running"] = True
                    status_info["status"] = "RUNNING"
                else:
                    status_info["status"] = "STOPPED_UNEXPECTEDLY"
                    health_metrics["service_status"]["overall"] = "ERROR"
                    health_metrics["service_status"]["errors"].append(
                        f"Service {service_name} (PID {pid}) not running."
                    )
            else:
                status_info["status"] = "NO_PID_FILE"
        except (
            psutil.NoSuchProcess,
            ValueError,
            IOError,
        ) as e:  # Added ValueError for bad PID file
            status_info["status"] = "ERROR_CHECKING_PID"
            health_metrics["service_status"]["overall"] = "ERROR"
            health_metrics["service_status"]["errors"].append(
                f"Error checking PID for {service_name}: {e}"
            )
        health_metrics["services"][service_name] = status_info

    async def _scan_log_file_for_errors(
        self, log_file_path: Path, health_metrics: Dict[str, Any]
    ):
        """Helper to scan a single log file for errors."""
        try:
            async with aiofiles.open(
                log_file_path, "r", encoding="utf-8", errors="ignore"
            ) as lf:
                recent_lines = (await lf.readlines())[-100:]  # Check last 100 lines
            for i, line_content in enumerate(recent_lines):
                error_patterns = ["ERROR", "CRITICAL", "Exception", "Traceback"]
                if any(pattern in line_content for pattern in error_patterns):
                    error_detail = (
                        f"{log_file_path.name} "
                        f"(line ~{len(recent_lines) - i}): {line_content.strip()}"
                    )
                    health_metrics["log_errors"]["details"].append(error_detail)
        except Exception as e_log:
            logger.error(f"[AI3-Health] Error reading log {log_file_path}: {e_log}")
            health_metrics["log_errors"]["details"].append(
                f"Error reading {log_file_path.name}: {e_log}"
            )

    async def _check_system_health(self) -> Dict[str, Any]:
        health_metrics: Dict[str, Any] = {
            "status": "OK",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {},
            "resource_usage": {},
            "log_errors": {"count": 0, "details": []},
            "error_count": 0,
            "warnings": [],
            "requires_attention": False,
            "service_status": {
                "overall": "OK",
                "errors": [],
            },  # Initialize service_status
        }
        try:
            import psutil  # Import locally

            mem = psutil.virtual_memory()
            health_metrics["resource_usage"]["memory"] = {
                "total_gb": f"{mem.total / (1024**3):.2f}",
                "available_gb": f"{mem.available / (1024**3):.2f}",
                "percent_used": f"{mem.percent:.2f}%",
            }
            if mem.percent > 85:
                health_metrics["warnings"].append("High memory usage.")

            disk_path = self.repo_dir if Path(self.repo_dir).exists() else "/"
            disk = psutil.disk_usage(disk_path)
            health_metrics["resource_usage"]["disk"] = {
                "total_gb": f"{disk.total / (1024**3):.2f}",
                "free_gb": f"{disk.free / (1024**3):.2f}",
                "percent_used": f"{disk.percent:.2f}%",
            }
            if disk.percent > 90:
                health_metrics["warnings"].append("High disk usage.")
        except ImportError:
            logger.warning("[AI3-Health] psutil not found. No resource usage.")
            for key in ["memory", "disk"]:
                health_metrics["resource_usage"][key] = {"status": "psutil missing"}
        except Exception as e:
            logger.error(f"[AI3-Health] Error getting resource usage: {e}")
            health_metrics["resource_usage"]["error"] = str(e)

        services_to_check = [
            "mcp_api",
            "ai1",
            "ai2_executor",
            "ai2_tester",
            "ai2_documenter",
        ]
        for service_name in services_to_check:
            await self._check_service_status(service_name, health_metrics)

        try:
            log_files_to_scan = list(Path(LOGS_DIR).glob("*.log"))
            for log_file_path in log_files_to_scan:
                await self._scan_log_file_for_errors(log_file_path, health_metrics)
        except Exception as e_scan_logs:
            logger.error(f"[AI3-Health] Error scanning log dir: {e_scan_logs}")
            health_metrics["log_errors"]["details"].append(
                f"Error scanning log dir: {e_scan_logs}"
            )

        health_metrics["log_errors"]["count"] = len(
            health_metrics["log_errors"]["details"]
        )
        health_metrics["error_count"] = (
            len(health_metrics["service_status"].get("errors", []))
            + health_metrics["log_errors"]["count"]
        )
        if health_metrics["error_count"] > 0 or health_metrics["warnings"]:
            health_metrics["requires_attention"] = True
            health_metrics["status"] = (
                "WARNING" if not health_metrics["service_status"]["errors"] else "ERROR"
            )

        return health_metrics

    async def monitor_system_health(self):
        # ...
        try:
            health_status = await self._check_system_health()
            # ...
            # current_time_utc = datetime.utcnow().replace(tzinfo=None) # Naive UTC
            # health_status["timestamp"] = current_time_utc.isoformat() + "Z"
            # ...
            if health_status.get("requires_attention"):
                logger.warning(
                    f"[AI3-Monitor] System health requires attention: {health_status}"
                )  # Log full status
                # TODO: Implement more sophisticated alerting or recovery
            # ...
        except Exception as e:
            logger.error(
                f"[AI3-MonitorSysHealth] Error in health monitoring loop: {e}",
                exc_info=True,
            )

    async def _analyze_log_line_with_ollama(
        self, log_file: Path, line_content: str, context: str, line_num: int
    ) -> bool:
        """Analyzes a single log line with Ollama to detect errors."""
        prompt = (
            f"Log File: {log_file.name}\\nContext (lines around {line_num}):\\n"
            f"```log\\n{context}```\\n"
            f"Current line under analysis (line {line_num}): {line_content.strip()}\\n\\n"
            "Is this log line a significant error related to file ops, code execution, "
            "or system stability in a dev project (often in 'repo/' dir)? "
            "Ignore benign errors/routine messages. "
            'Respond JSON: {"is_error": true/false, "reason": "brief explanation"}'
        )
        analysis_json_str = await call_ollama(
            self.client_session,
            prompt,
            self.ollama_endpoint,
            self.ollama_model,
            temperature=0.1,
            max_tokens=150,
            timeout=45,
        )
        if analysis_json_str:
            try:
                analysis = json.loads(analysis_json_str)
                if analysis.get("is_error"):
                    logger.warning(
                        f"[AI3-Ollama] Detected error in {log_file.name} (line {line_num}): "
                        f"{line_content.strip()} - Reason: {analysis.get('reason')}"
                    )
                    return True
            except json.JSONDecodeError:
                logger.warning(
                    f"[AI3-Ollama] Invalid JSON from Ollama for log line: "
                    f"{analysis_json_str}"
                )
        return False

    async def scan_logs_for_errors(self):
        """Scans log files for errors using Ollama."""
        if not self.ollama_initialized or not self.client_session:
            logger.warning("[AI3-Ollama] Not initialized. Skipping log scan.")
            return []

        logger.info("[AI3-Ollama] Starting log scan for errors...")
        logs_dir = Path(self.config.get("logs_dir", LOGS_DIR))
        if not logs_dir.is_dir():
            logger.error(f"[AI3-Ollama] Logs dir '{logs_dir}' not found.")
            return []

        detected_errors_info = []
        log_files = [
            f for f in logs_dir.iterdir() if f.is_file() and f.suffix == ".log"
        ]

        for log_file in log_files:
            lines_analyzed, errors_in_file = 0, 0
            try:
                async with aiofiles.open(
                    log_file, "r", encoding="utf-8", errors="ignore"
                ) as lf:
                    lines = await lf.readlines()
                logger.info(
                    f"[AI3-Ollama] Read {len(lines)} lines from {log_file.name}"
                )

                for i, line_content in enumerate(lines):
                    if lines_analyzed >= MAX_LOG_LINE_ANALYSIS:
                        logger.info(
                            f"[AI3-Ollama] Max analysis lines for {log_file.name}"
                        )
                        break

                    # Basic keyword filter
                    if not any(
                        kw in line_content.upper()
                        for kw in ["ERROR", "FAIL", "EXCEPTION", "CRITICAL"]
                    ):
                        continue

                    lines_analyzed += 1
                    context_start = max(0, i - MAX_CONTEXT_LINES)
                    context_end = min(len(lines), i + MAX_CONTEXT_LINES + 1)
                    context = "".join(lines[context_start:context_end])

                    if await self._analyze_log_line_with_ollama(
                        log_file, line_content, context, i + 1
                    ):
                        errors_in_file += 1
                        detected_errors_info.append(
                            {
                                "file": log_file.name,
                                "line_num": i + 1,
                                "content": line_content.strip(),
                            }
                        )
                        # TODO: Implement ai_comm for reporting if needed here
                        # self._report_system_error_to_ai1(...)
            except Exception as e:
                logger.error(f"[AI3-Ollama] Error processing {log_file.name}: {e}")
            if lines_analyzed > 0:
                logger.info(
                    f"[AI3-Ollama] {log_file.name}: {errors_in_file} errors in {lines_analyzed} analyzed lines."
                )

        logger.info(
            f"[AI3-Ollama] Log scan done. Total errors: {len(detected_errors_info)}"
        )
        return detected_errors_info

    async def monitor_github_actions(self):
        # ...
        github_repo = os.getenv("GITHUB_REPO_TO_MONITOR") or self.config.get(
            "github_repo_to_monitor"
        )
        github_token = os.getenv("GITHUB_TOKEN") or self.config.get("github_token")

        if not github_repo:
            logger.debug(
                "[AI3-GitHub] GITHUB_REPO_TO_MONITOR not set. Skipping."
            )  # Debug, not warning
            return
        if not github_token:
            logger.warning(
                "[AI3-GitHub] GITHUB_TOKEN not set. Skipping."
            )  # Warning, as it's needed if repo is set
            return

        logger.debug(f"[AI3-GitHub] Checking Actions for {github_repo}...")
        api_url = f"{GITHUB_API_BASE_URL}/repos/{github_repo}/actions/runs"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        # ...
        try:
            # type: ignore below because aiohttp.ClientSession.get has overloads
            # that mypy struggles with when params is included.
            async with self.client_session.get(  # type: ignore
                api_url, headers=headers, params={"status": "completed"}, timeout=30
            ) as response:
                if response.status == 200:
                    runs_data = await response.json()
                    workflow_runs = runs_data.get("workflow_runs", [])
                    logger.debug(
                        f"[AI3-GitHub] Fetched {len(workflow_runs)} completed runs."
                    )
                    # Sort by creation time, newest first
                    sorted_runs = sorted(
                        workflow_runs, key=lambda x: x["created_at"], reverse=True
                    )
                    new_runs_processed_this_cycle = 0
                    for run in sorted_runs:
                        run_id = run["id"]
                        if run_id not in self.processed_github_run_ids:
                            logger.info(
                                f"[AI3-GitHub] New completed run: ID {run_id}, "
                                f"Status {run.get('status')}, Conclusion {run.get('conclusion')}"
                            )
                            await self._analyze_workflow_run(
                                run_id,
                                run.get("conclusion"),
                                headers,  # Pass headers
                                # Removed api_base_url as it's constant
                            )
                            self.processed_github_run_ids.add(run_id)
                            new_runs_processed_this_cycle += 1
                            if new_runs_processed_this_cycle >= 5:  # Limit per cycle
                                logger.info(
                                    "[AI3-GitHub] Reached processing limit for this cycle."
                                )
                                break
                    if new_runs_processed_this_cycle == 0 and sorted_runs:
                        logger.debug("[AI3-GitHub] No new completed runs this cycle.")
                    elif not sorted_runs:
                        logger.debug("[AI3-GitHub] No completed runs found for repo.")

                elif response.status == 404:
                    logger.warning(
                        f"[AI3-GitHub] Repo '{github_repo}' not found or "
                        "actions disabled."
                    )
                elif response.status == 401:
                    logger.error(
                        "[AI3-GitHub] API auth failed (Invalid GITHUB_TOKEN?)."
                    )
                else:
                    logger.error(
                        f"[AI3-GitHub] API error: {response.status} - {await response.text()}"
                    )
        except asyncio.TimeoutError:
            logger.warning("[AI3-GitHub] API request timed out.")
        except aiohttp.ClientError as e:
            logger.error(f"[AI3-GitHub] HTTP client error: {e}")
        except Exception as e:
            logger.error(f"[AI3-GitHub] Unexpected error: {e}", exc_info=True)

    async def _analyze_workflow_run(
        self,
        run_id: int,
        run_conclusion: Optional[str],
        headers: dict,  # Keep headers for potential future use (e.g. fetching logs)
        # api_base_url: str, # Removed, use constant GITHUB_API_BASE_URL
    ):
        logger.info(
            f"[AI3] Analyzing workflow run ID: {run_id}, Conclusion: {run_conclusion}"
        )
        # Placeholder: Fetch detailed logs if needed. For now, assume summary is enough.
        # logs_url = f"{GITHUB_API_BASE_URL}/repos/{self.config.get('github_repo_to_monitor')}/actions/runs/{run_id}/logs"
        # async with self.client_session.get(logs_url, headers=headers) as log_resp:
        # if log_resp.status == 200:
        # actual_logs = await log_resp.text() # This might be a zip file, needs handling

        # For now, we'll use a simplified approach or assume logs are passed if complex
        # This part uses Ollama to analyze, which might be too slow or resource-intensive
        # for every run. Consider a simpler check first or making this configurable.
        analysis_result = await self._analyze_github_actions_logs_with_ollama(
            logs=f"Run ID {run_id} concluded with {run_conclusion}.",  # Simplified log input
            run_id=run_id,
            run_conclusion=run_conclusion,
        )
        analysis_result["run_id"] = run_id  # Ensure run_id is in the result

        if analysis_result.get("recommendation") == "rework" and self.repo:
            logger.info(f"[AI3] Rework recommended for run {run_id}. Attempting fixes.")
            fix_summary = await self._attempt_test_fixes(analysis_result)
            analysis_result["fix_attempts_summary"] = fix_summary
            # Potentially re-evaluate recommendation based on fix_summary
            if fix_summary.get("all_files_fixed"):
                logger.info(
                    f"[AI3] All identified files fixed for run {run_id}. Updating recommendation to 'accept_after_fix'."
                )
                analysis_result["recommendation"] = "accept_after_fix"
            elif fix_summary.get("some_files_fixed"):
                logger.info(
                    f"[AI3] Some files fixed for run {run_id}. Recommendation remains 'rework'."
                )
                analysis_result["recommendation"] = "rework_after_partial_fix"

        # Send recommendation to MCP API
        await self._send_test_recommendation_to_mcp(analysis_result)

        # Old logging, replaced by MCP call
        # logger.info(f"[AI3-GitHub] Analysis for run {run_id}: {analysis_result}")

    async def _analyze_github_actions_logs_with_ollama(
        self, logs: str, run_id: int, run_conclusion: Optional[str]
    ) -> Dict[str, Any]:
        # ...
        prompt = (
            f"GitHub Actions Run ID: {run_id}, Conclusion: {run_conclusion}\\n"
            f"Logs (first 15k chars):\\n```\\n{logs[:15000]}```\\n\\n"
            "Analyze GitHub Actions logs: test/lint errors? Failed files? "
            "Recommend 'rework' for failed tests, 'accept' for passed/minor lint. "
            "If unsure, 'accept' with note. "
            'JSON: {"recommendation": "accept"|"rework", '
            '"failed_files": list[str], "summary": "str", '
            '"confidence": float (0.0-1.0)}'
        )
        # ...existing code...
        if not self.ollama_initialized or not self.client_session:
            logger.warning(
                "[AI3-Ollama] Not init. Default recommendation for GH Actions."
            )
            return default_recommendation

        analysis_json_str = await call_ollama(
            self.client_session,  # Pass client_session
            prompt,
            self.ollama_endpoint,  # Pass endpoint
            self.ollama_model,  # Pass model
            temperature=0.2,
            max_tokens=500,
            timeout=60,
        )
        if analysis_json_str:
            try:
                result = json.loads(analysis_json_str)
                if "run_url" not in result:
                    result["run_url"] = default_recommendation["run_url"]
                logger.info(
                    f"[AI3] Ollama recommendation for run {run_id}: "
                    f"{result.get('recommendation')}, Failed files: {result.get('failed_files')}"
                )
                return result
            except json.JSONDecodeError:
                logger.warning(
                    f"[AI3] Invalid JSON response from Ollama for run {run_id}: {analysis_json_str}"
                )
                return default_recommendation
        return default_recommendation

    async def monitor_idle_workers(self):
        # ...existing code...
        # Placeholder for actual queue size retrieval
        executor_queue_size = 0
        if executor_queue_size == 0:  # Check aggregate first
            logger.info(
                "[AI3-MonitorIdle] Fallback: Main executor queue is empty. "
                "Requesting generic executor task."
            )
            # await self._request_task_for_idle_worker("executor") # Generic executor
        # ...

    async def _report_system_error_to_ai1(
        self,
        error_type: str,
        # error_description: str, # Parameter removed as it was unused
        log_file: str,
        context: Optional[Dict] = None,
    ):
        """Reports a system error to AI1 (placeholder)."""
        logger.info(f"[AI3->AI1] Attempting report: {error_type} from {log_file}")
        # TODO: Implement with ai_comm or similar
        # ...
        logger.warning(
            "[AI3->AI1] _report_system_error_to_ai1: ai_comm not implemented."
        )
        return False

    async def main_loop(self):
        # ...
        if self.current_project_structure is None:  # Check if structure was set up
            logger.warning(
                "[AI3] Project structure not available. Monitoring may be limited."
            )
        # ...

    async def _attempt_test_fixes(
        self, analysis_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Attempts to fix failing files identified by GitHub Actions analysis.
        Returns a summary of fix attempts.
        """
        logger.info("[AI3] Attempting to fix identified test/linting errors...")
        failed_files_from_analysis = analysis_result.get("failed_files", [])
        error_summary = analysis_result.get(
            "summary", "No specific error summary provided."
        )

        fixed_files: List[str] = []
        failed_to_fix_files: List[str] = []

        if not failed_files_from_analysis:
            logger.info("[AI3] No failed files provided for fix attempt.")
            return {
                "fixes_attempted": False,
                "summary_message": "No failed files to process.",
            }

        if not self.repo:
            logger.error("[AI3] Repository not initialized. Cannot attempt fixes.")
            return {
                "fixes_attempted": False,
                "summary_message": "Repository not initialized.",
            }

        provider_name_for_fix = self.ai_config.get("code_fix_provider", "codestral")
        # Model for fix provider can be specified in config or defaults in _get_provider_instance

        for rel_file_path in failed_files_from_analysis:
            full_file_path = Path(self.repo_dir) / rel_file_path
            logger.info(f"[AI3] Attempting to fix file: {full_file_path}")

            if not full_file_path.exists() or not full_file_path.is_file():
                logger.warning(
                    f"[AI3] File not found or is not a file: {full_file_path}"
                )
                failed_to_fix_files.append(rel_file_path)
                continue

            try:
                async with aiofiles.open(full_file_path, "r", encoding="utf-8") as f:
                    original_content = await f.read()
            except Exception as e:
                logger.error(f"[AI3] Error reading file {full_file_path}: {e}")
                failed_to_fix_files.append(rel_file_path)
                continue

            fix_prompt = (
                f"You are an expert software developer. The following file has errors.\n"
                f"File Path: {rel_file_path}\n"
                f"Error(s) Reported:\n{error_summary}\n\n"
                f"Original Code:\n```{Path(rel_file_path).suffix.lstrip('.') if Path(rel_file_path).suffix else 'text'}\n"
                f"{original_content}\n```\n\n"
                "Please provide the corrected code for the ENTIRE file. "
                "Output ONLY the corrected code block for the file, enclosed in triple backticks "
                "(e.g., ```language\n...code...\n```). "
                "If you cannot determine a fix or the error is too complex, output an empty code block: "
                "```\n```"
            )

            provider_instance = await _get_provider_instance(
                self.provider_factory,
                provider_name_for_fix,
                self.config_data,
                self.ai3_config,
                self.client_session,
                ui_selected_provider=None,  # Not UI driven
                ui_selected_model=None,  # Not UI driven
            )

            if not provider_instance:
                logger.error(
                    f"[AI3] Failed to create provider instance {provider_name_for_fix} for code fixing."
                )
                failed_to_fix_files.append(rel_file_path)
                continue

            corrected_content_str: Optional[str] = None
            try:
                logger.info(
                    f"[AI3] Calling LLM provider {provider_name_for_fix} to fix {rel_file_path}"
                )
                # Use temperature/max_tokens from provider config or sensible defaults
                temperature = provider_instance.config.get("temperature", 0.3)
                max_tokens = provider_instance.config.get("max_tokens", 3000)
                model_to_use = provider_instance.config.get("model")

                corrected_content_str = await provider_instance.generate(
                    prompt=fix_prompt,
                    model=model_to_use,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.error(
                    f"[AI3] Error calling LLM for file {rel_file_path}: {e}",
                    exc_info=True,
                )
                failed_to_fix_files.append(rel_file_path)
                continue
            finally:
                if provider_instance and hasattr(provider_instance, "close_session"):
                    await provider_instance.close_session()

            if corrected_content_str:
                # Extract code from ```language ... ``` or ``` ... ```
                match = re.search(
                    r"```(?:[a-zA-Z0-9_\\.-]+)?\\s*([\\s\\S]*?)\\s*```",
                    corrected_content_str,
                )
                if match:
                    extracted_code = match.group(1).strip()
                    if (
                        extracted_code and extracted_code != original_content
                    ):  # Ensure there's a change
                        try:
                            async with aiofiles.open(
                                full_file_path, "w", encoding="utf-8"
                            ) as f:
                                await f.write(extracted_code)
                            logger.info(f"[AI3] Applied fix to {rel_file_path}")
                            _commit_changes(
                                self.repo,
                                [str(full_file_path)],
                                f"AI3: Attempt to fix errors in {rel_file_path} based on test/lint results.",
                            )
                            fixed_files.append(rel_file_path)
                            # Remove from failed_to_fix if it was added due to an earlier error in this loop for this file
                            if rel_file_path in failed_to_fix_files:
                                failed_to_fix_files.remove(rel_file_path)
                        except Exception as e:
                            logger.error(
                                f"[AI3] Error writing or committing fix for {rel_file_path}: {e}"
                            )
                            if rel_file_path not in failed_to_fix_files:
                                failed_to_fix_files.append(rel_file_path)
                            # Revert to original content on write/commit error? For now, no.
                    elif not extracted_code:
                        logger.info(
                            f"[AI3] LLM returned empty code block for {rel_file_path}. No fix applied."
                        )
                        if rel_file_path not in failed_to_fix_files:
                            failed_to_fix_files.append(rel_file_path)
                    else:  # extracted_code == original_content
                        logger.info(
                            f"[AI3] LLM returned original content for {rel_file_path}. No fix applied."
                        )
                        if rel_file_path not in failed_to_fix_files:
                            failed_to_fix_files.append(rel_file_path)
                else:
                    logger.warning(
                        f"[AI3] Could not extract code from LLM response for {rel_file_path}. Response: {corrected_content_str[:200]}..."
                    )
                    if rel_file_path not in failed_to_fix_files:
                        failed_to_fix_files.append(rel_file_path)
            else:
                logger.warning(
                    f"[AI3] LLM provider returned no response for {rel_file_path}."
                )
                if rel_file_path not in failed_to_fix_files:
                    failed_to_fix_files.append(rel_file_path)

        num_attempted = len(failed_files_from_analysis)
        num_fixed = len(fixed_files)
        num_failed = len(failed_to_fix_files)  # Should be num_attempted - num_fixed

        summary_message = f"Attempted fixes for {num_attempted} files. Fixed: {num_fixed}, Failed to fix: {num_failed}."
        logger.info(f"[AI3] Fix attempt summary: {summary_message}")

        return {
            "fixes_attempted": True,
            "files_fixed": fixed_files,
            "files_failed_fix": failed_to_fix_files,  # Use the explicitly tracked list
            "summary_message": summary_message,
            "all_files_fixed": num_attempted > 0 and num_fixed == num_attempted,
            "some_files_fixed": num_fixed > 0 and num_fixed < num_attempted,
        }

    async def monitor_tests(self):
        """Monitors test results and automatically fixes errors when possible."""
        logger.info("[AI3] Starting test monitoring...")

        while self.monitoring_active:
            try:
                # Check for test logs
                test_logs_path = Path(LOGS_DIR) / "test_results.log"
                if test_logs_path.exists():
                    await self._analyze_and_fix_test_results(test_logs_path)

                # Check pytest output files if they exist
                pytest_results = list(Path(self.repo_dir).glob("**/pytest-results.xml"))
                for result_file in pytest_results:
                    await self._analyze_and_fix_pytest_results(result_file)

                # Wait before checking again
                await asyncio.sleep(60)  # Check every minute
            except asyncio.CancelledError:
                logger.info("[AI3] Test monitoring task cancelled")
                break
            except Exception as e:
                logger.error(f"[AI3] Error in test monitoring: {e}", exc_info=True)
                await asyncio.sleep(120)  # Longer sleep on error

    async def _analyze_and_fix_test_results(self, log_file: Path):
        """Analyzes test logs and fixes errors when possible."""
        if log_file in self.processed_log_files:
            last_size = self.processed_log_files[log_file]
            if log_file.stat().st_size == last_size:
                # No changes since last check
                return

        # Use a lock to prevent concurrent analysis of the same file
        if log_file not in self.active_log_analyses:
            self.active_log_analyses[log_file] = asyncio.Lock()

        lock = self.active_log_analyses[log_file]
        if lock.locked():
            logger.debug(
                f"[AI3] Analysis of {log_file.name} already in progress, skipping"
            )
            return

        async with lock:
            try:
                current_size = log_file.stat().st_size

                # Read the file
                async with aiofiles.open(
                    log_file, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    log_content = await f.read()

                # Analyze the log file
                analysis_result = await self._analyze_test_logs_with_llm(
                    log_content, log_file.name
                )

                if analysis_result.get("recommendation") in ["rework", "needs_fix"]:
                    logger.info(
                        f"[AI3] Test failures detected in {log_file.name}. Attempting fixes."
                    )
                    fix_summary = await self._attempt_test_fixes(analysis_result)

                    # Update recommendation based on fix results
                    if fix_summary.get("all_files_fixed", False):
                        analysis_result["recommendation"] = "accept_after_fix"
                        logger.info(
                            f"[AI3] All test failures in {log_file.name} fixed successfully."
                        )
                    elif fix_summary.get("some_files_fixed", False):
                        analysis_result["recommendation"] = "rework_after_partial_fix"
                        logger.info(
                            f"[AI3] Some test failures in {log_file.name} fixed."
                        )

                    # Update analysis with fix information
                    analysis_result["fix_summary"] = fix_summary

                # Send recommendation to MCP API
                await self._send_test_recommendation_to_mcp(analysis_result)

                # Mark as processed
                self.processed_log_files[log_file] = current_size

            except Exception as e:
                logger.error(
                    f"[AI3] Error analyzing test results from {log_file}: {e}",
                    exc_info=True,
                )

    async def _analyze_test_logs_with_llm(
        self, log_content: str, log_filename: str
    ) -> Dict[str, Any]:
        """Uses LLM to analyze test logs and identify issues."""
        prompt = (
            f"Test Log File: {log_filename}\n"
            f"Log content (first 15k chars):\n```\n{log_content[:15000]}\n```\n\n"
            "Analyze the test log content. Identify any test failures, their causes, "
            "and which files need to be fixed. Determine whether the issues are simple "
            "enough for automatic fixing, or if they need more complex rework.\n\n"
            "Format your response as a JSON object with these fields:\n"
            '{"recommendation": "accept"|"rework"|"needs_fix", '
            '"failed_files": list[str], "summary": "str", '
            '"failure_details": {file: error_details}, "confidence": float (0.0-1.0)}'
        )

        default_response = {
            "recommendation": "accept",
            "failed_files": [],
            "summary": "No issues detected in test logs.",
            "failure_details": {},
            "confidence": 0.0,
        }

        try:
            provider_instance = await _get_provider_instance(
                self.provider_factory,
                self.code_fix_provider_name,
                self.config_data,
                self.ai3_config,
                self.client_session,
                ui_selected_provider=None,
                ui_selected_model=None,
            )

            if not provider_instance:
                logger.error(f"[AI3] Failed to create provider for test log analysis")
                return default_response

            analysis_json_str = await provider_instance.generate(
                prompt=prompt,
                model=provider_instance.config.get("model"),
                temperature=0.2,
                max_tokens=2000,
            )

            if not analysis_json_str:
                logger.warning(
                    f"[AI3] Empty response from provider for test log analysis"
                )
                return default_response

            try:
                analysis = json.loads(analysis_json_str)
                logger.info(
                    f"[AI3] Test analysis complete. Recommendation: {analysis.get('recommendation')}"
                )
                return analysis
            except json.JSONDecodeError:
                logger.warning(
                    f"[AI3] Invalid JSON from provider: {analysis_json_str[:200]}..."
                )
                return default_response

        except Exception as e:
            logger.error(f"[AI3] Error analyzing test logs: {e}", exc_info=True)
            return default_response

    async def _analyze_and_fix_pytest_results(self, result_file: Path):
        """Analyzes pytest XML results and fixes errors when possible."""
        try:
            # Similar implementation to _analyze_and_fix_test_results but for pytest XML format
            logger.info(f"[AI3] Analyzing pytest results from {result_file}")

            # Check if already processed
            if result_file in self.processed_log_files:
                last_mtime = self.processed_log_files[result_file]
                current_mtime = result_file.stat().st_mtime
                if current_mtime <= last_mtime:
                    return

            # Read XML content
            async with aiofiles.open(result_file, "r", encoding="utf-8") as f:
                xml_content = await f.read()

            # Parse XML to find failures
            failed_tests = []
            failed_files = []

            # Simple regex-based parsing as a fallback
            for match in re.finditer(
                r'file="([^"]+)".*?failures="([^"0]+)"', xml_content
            ):
                file_path, failure_count = match.groups()
                if int(failure_count) > 0:
                    failed_tests.append(file_path)
                    # Extract source file from test file
                    source_file = self._get_source_file_from_test(file_path)
                    if source_file:
                        failed_files.append(source_file)

            if failed_files:
                logger.info(
                    f"[AI3] Found {len(failed_files)} failed files in pytest results: {failed_files}"
                )

                # Create analysis result
                analysis_result = {
                    "recommendation": "rework" if failed_files else "accept",
                    "failed_files": failed_files,
                    "summary": f"Found {len(failed_tests)} failing tests affecting {len(failed_files)} source files.",
                    "confidence": 0.8,
                }

                # Attempt fixes
                if failed_files:
                    fix_summary = await self._attempt_test_fixes(analysis_result)

                    # Update recommendation based on fix results
                    if fix_summary.get("all_files_fixed", False):
                        analysis_result["recommendation"] = "accept_after_fix"
                    elif fix_summary.get("some_files_fixed", False):
                        analysis_result["recommendation"] = "rework_after_partial_fix"

                    # Update analysis with fix information
                    analysis_result["fix_summary"] = fix_summary

                # Send recommendation to MCP API
                await self._send_test_recommendation_to_mcp(analysis_result)

            # Mark as processed with current mtime
            self.processed_log_files[result_file] = result_file.stat().st_mtime

        except Exception as e:
            logger.error(
                f"[AI3] Error analyzing pytest results from {result_file}: {e}",
                exc_info=True,
            )

    def _get_source_file_from_test(self, test_file_path: str) -> Optional[str]:
        """Extracts source file path from test file path."""
        test_path = Path(test_file_path)

        # Common patterns for test files
        if test_path.name.startswith("test_"):
            # test_module.py -> module.py
            source_name = test_path.name[5:]
            source_dir = test_path.parent
            if "tests" in source_dir.parts:
                # Adjust source directory if needed
                parts = list(source_dir.parts)
                try:
                    test_index = parts.index("tests")
                    # Replace "tests" with "src" or remove it
                    if test_index > 0:
                        if (Path(self.repo_dir) / "src").exists():
                            parts[test_index] = "src"
                        else:
                            parts.pop(test_index)
                        source_dir = Path(*parts)
                except ValueError:
                    pass

            # Check if source file exists
            potential_source = source_dir / source_name
            if potential_source.exists():
                return str(potential_source.relative_to(self.repo_dir))

        # If no match found
        return None


class TestRecommendation(BaseModel):
    """Model for test recommendations from AI3 analysis"""

    recommendation: str = Field(
        ...,
        description="Recommendation action: 'accept', 'rework', 'accept_after_fix', 'rework_after_partial_fix'",
    )
    summary: str = Field(..., description="Summary of test results")
    confidence: float = Field(default=0.0, description="Confidence level (0.0-1.0)")
    failed_files: List[str] = Field(
        default_factory=list, description="List of files that failed tests"
    )
    run_id: Optional[int] = Field(
        None, description="GitHub Actions run ID if applicable"
    )
    run_url: Optional[str] = Field(None, description="URL to GitHub Actions run")
    context: Dict[str, Any] = Field(
        default_factory=dict, description="Additional context information"
    )


async def main(target: str, config_path: Optional[str] = None):
    logger.info(f"[AI3] Starting AI3 system with target: {target}")
    ai3_instance = None  # Renamed for clarity
    client_session = None  # Define here for finally block
    try:
        # Initialize aiohttp ClientSession
        client_session = aiohttp.ClientSession()

        # Create AI3 instance
        provider_factory = ProviderFactory()
        config_data = load_config(config_path)
        if not target and "target" in config_data:  # Get target from config if not arg
            target = config_data["target"]
            logger.info(f"[AI3] Using target from config: {target[:100]}...")
        if not target:  # If still no target
            logger.critical("[AI3] Target project description is missing. Exiting.")
            sys.exit(1)

        ai3_instance = AI3(target, provider_factory, config_data, client_session)

        await ai3_instance.setup_structure()
        await ai3_instance.start_monitoring()
        await ai3_instance.main_loop()

    except KeyboardInterrupt:
        logger.info("[AI3] Keyboard interrupt. Shutting down.")
    except Exception as e:
        logger.critical(f"[AI3] Unhandled exception in main: {e}", exc_info=True)
        # TODO: Implement ai_comm for reporting critical shutdown
        # if ai3_instance and ai3_instance.client_session and not ai3_instance.client_session.closed:
        #     await _report_status_to_mcp("critical_error_shutdown", {"error": str(e)},
        #                                 ai3_instance.mcp_api_url, ai3_instance.client_session)
    finally:
        if ai3_instance:
            await ai3_instance.stop_monitoring()  # Ensure monitoring stops
        if client_session and not client_session.closed:
            await client_session.close()
            logger.info("[AI3] Closed aiohttp client session.")
        logger.info("[AI3] AI3 system shutdown complete.")
        # Exit with error if an exception occurred in the try block
        # sys.exit(1 if 'e' in locals() and isinstance(e, Exception) else 0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI3 - Structure generator and system monitor"
    )
    parser.add_argument(
        "--target", type=str, help="Target project description", default=None
    )
    parser.add_argument("--config", type=str, help="Path to config.json", default=None)
    args = parser.parse_args()  # Changed from ArgumentParser() to parse_args()

    # Get target from config if not specified via argument
    target_arg = args.target
    if target_arg is None:
        try:
            temp_config = load_config(args.config)  # Load temporary to get target
            target_arg = temp_config.get("target")  # Default to None if not in config
            if target_arg:
                logger.info(
                    f"[AI3] Target not by arg, using from config: {target_arg[:100]}..."
                )
            else:  # If still None after checking config
                logger.error(
                    "[AI3] Target description not provided via --target or in config. Please specify a target."
                )
                sys.exit(1)
        except Exception as e:
            logger.error(f"[AI3] Error loading config to get target: {e}")
            sys.exit(1)

    try:
        asyncio.run(main(target_arg, args.config))  # Pass the resolved target
        sys.exit(0)
    except Exception:  # Catch-all for asyncio.run or main() if it re-raises
        # Logging should have happened inside main() or AI3 methods
        sys.exit(1)

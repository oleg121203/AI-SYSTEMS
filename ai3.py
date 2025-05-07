import asyncio
import json
import logging
import os
import re
import shutil  # Added shutil
import sys  # Added sys
import time
from datetime import datetime, timezone  # Added timezone
from pathlib import Path  # Added Path
from typing import Any, Dict, List, Optional, Tuple

# Third-party libraries
import aiofiles
import aiohttp
from git import GitCommandError  # Added missing imports
from git import InvalidGitRepositoryError, NoSuchPathError, Repo

# Local application/library specific imports
from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import GITKEEP_FILENAME
from utils import LOG_DIR as LOGS_DIR
from utils import (
    MCP_API_URL as DEFAULT_MCP_API_URL,
)  # LOGS_DIR, # Marked as unused; extract_json_from_response, # Marked as unused
from utils import REPO_DIR

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Constants for duplicated literals
HTTP_LOCALHOST_7860 = (
    "http://localhost:7860"  # For MCP_API_URL default if not from utils
)
DETAILED_EXCEPTION_INFO = "Detailed exception information:"
TESTS_TEST_PREFIX = "tests/test_"
DOT_TEST_SUFFIX = ".test"
DOT_JAVA_SUFFIX = ".java"

# Ensure these are not redefined if imported from utils
# DEFAULT_MCP_API_URL = HTTP_LOCALHOST_7860 # Defined by import
# GITKEEP_FILENAME = ".gitkeep" # Defined by import
# REPO_DIR = "repo" # Defined by import, ensure utils.py has a sensible default

ERROR_RETRY_DELAY = 5  # seconds
MAX_LOG_LINE_ANALYSIS = 200  # Max log lines to analyze with LLM in one go
MAX_CONTEXT_LINES = 5  # Max context lines for log analysis
GITHUB_API_BASE_URL = "https://api.github.com"
REPO_PREFIX = "/repo/"  # Used in handle_ai2_output

# --- END MODIFIED IMPORTS AND GLOBAL SETUP ---


async def _initialize_repository(repo_path: str) -> Optional[Repo]:
    # ...existing code...
    try:
        repo_path_obj = Path(repo_path)  # Use Path object
        if not repo_path_obj.exists():
            logger.info(
                f"[AI3-Git] Repository path does not exist. Creating: {repo_path}"
            )
            repo_path_obj.mkdir(parents=True, exist_ok=True)
        elif not repo_path_obj.is_dir():
            logger.error(
                f"[AI3-Git] Repository path exists but is not a directory: {repo_path}"
            )
            return None

        try:
            repo = Repo(repo_path)
            logger.info(f"[AI3-Git] Opened existing repository at: {repo_path}")
        except InvalidGitRepositoryError:  # Catch specific error
            logger.info(
                f"[AI3-Git] Repository not found, initializing new one at: {repo_path}"
            )
            repo = Repo.init(repo_path)
            logger.info(f"[AI3-Git] Initialized new repository at: {repo_path}")

        gitignore_path = os.path.join(repo_path, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(
                    """*.pyc
__pycache__/
.DS_Store
.env
logs/
tmp/
node_modules/
dist/
build/
*.log
coverage.xml
.pytest_cache/
.mypy_cache/
.idea/
.vscode/
"""
                )
            logger.info(f"[AI3-Git] Created .gitignore at {gitignore_path}")
            # Commit .gitignore
            _commit_changes(repo, [gitignore_path], "Initial commit: .gitignore")
            logger.info(
                "[AI3-Git] Initial commit successful: .gitignore"
            )  # Removed f-string
        return repo
    except GitCommandError as init_e:
        logger.critical(
            "[AI3-Git] CRITICAL: Git command error during repository initialization "
            f"at {repo_path}: {init_e}"
        )
        return None
    except Exception as e:  # General exception
        logger.critical(
            f"[AI3-Git] CRITICAL: Failed to initialize or open repository "
            f"at {repo_path}: {e}"
        )
        return None


def _commit_changes(repo: Repo, file_paths: list, message: str):
    if not file_paths:
        logger.info(f"[AI3-Git] No file paths provided for commit message: {message}")
        return

    relative_paths = [
        os.path.relpath(p, repo.working_dir) if os.path.isabs(p) else p
        for p in file_paths
    ]

    # Filter out paths that are outside the repository or don't exist
    valid_paths_to_add = []
    for rel_path in relative_paths:
        abs_path = os.path.join(repo.working_dir, rel_path)
        if not os.path.exists(abs_path):
            logger.warning(f"[AI3-Git] File not found, skipping add: {rel_path}")
            continue
        # Basic check to prevent adding files outside the repo, though relpath should handle it.
        if not abs_path.startswith(os.path.abspath(repo.working_dir)):
            logger.warning(f"[AI3-Git] File outside repo, skipping add: {rel_path}")
            continue
        valid_paths_to_add.append(rel_path)

    if not valid_paths_to_add:
        logger.info(f"[AI3-Git] No valid files found to commit for message: {message}")
        return

    try:
        repo.index.add(valid_paths_to_add)

        # Check if there are staged changes
        if not repo.index.diff("HEAD") and not repo.is_dirty(
            untracked_files=True, working_tree=False
        ):  # Check only staged
            # A more robust check for staged changes
            staged_changes = repo.index.diff("HEAD")
            if not staged_changes and not repo.head.is_valid():  # initial commit case
                # If it's the very first commit, diff against empty tree
                staged_changes = repo.index.diff(None)

            if not staged_changes:
                logger.info(
                    f"[AI3-Git] No new or modified files staged to commit for: {message}"
                )
                return

        repo.index.commit(message)
        logger.info(f"[AI3-Git] Successfully committed: {message}")
    except GitCommandError as e:
        # More specific check for "nothing to commit"
        if (
            "nothing to commit" in str(e).lower()
            or "no changes added to commit" in str(e).lower()
        ):
            logger.info(f"[AI3-Git] Git: Nothing to commit for message: {message}")
        else:
            logger.error(
                f"[AI3-Git] Error committing changes: {message}. "
                f"Files: {valid_paths_to_add}. Error: {e}"
            )
    except Exception as e:
        logger.error(f"[AI3-Git] Unexpected error during commit: {e}", exc_info=True)


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


async def generate_structure(
    target: str, config: Dict[str, Any], session: aiohttp.ClientSession
) -> Optional[Dict[str, Any]]:
    # ... (function body as before, but apply line wrapping and other fixes)
    ai3_config = config.get("ai_config", {}).get("ai3", {})
    structure_providers = ai3_config.get(
        "structure_providers", ["codestral2"]
    )  # Default provider
    if not structure_providers:  # Ensure there's at least one
        structure_providers = ["codestral2"]
        logger.warning(
            "[AI3] 'structure_providers' is empty in ai3 config. "
            "Using default ['codestral2']."
        )

    fallback_structure = {
        "retro_nes_flash_game/": {
            "README.md": (
                "# Retro NES-Style Flash Game\\n\\nA simple yet addictive flash game "
                "inspired by classic NES games."
            ),
            "backend/": {
                "main.py": "# Main Python backend (e.g., Flask or FastAPI)",
                "requirements.txt": "flask",
            },
            "frontend/": {
                "index.html": "<!-- Main HTML file -->",
                "js/": {"game.js": "// Main game logic"},
                "css/": {"styles.css": "/* Basic styles */"},
            },
            "docs/": {"api.md": "# API Documentation"},
            ".gitignore": "__pycache__/\\n*.pyc\\nnode_modules/",
        }
    }
    # ... rest of the function, ensure line wrapping for long log messages and prompts
    logger.info(
        "[AI3] Starting Cycle 1: Initial structure generation using providers: "
        f"{structure_providers}"
    )
    generated_structure_str: Optional[str] = None
    selected_provider_name: Optional[str] = None

    prompt = await generate_structure_llm_prompt(target)

    for provider_name in structure_providers:
        logger.info(
            f"[AI3] Cycle 1: Trying provider for initial generation: {provider_name}"
        )
        try:
            provider_instance: BaseProvider = ProviderFactory.create_provider(
                provider_name, config=config.get("providers", {}).get(provider_name)
            )
            # TODO: Implement or import apply_request_delay
            # await apply_request_delay("ai3")
            response_str = await provider_instance.generate_text(
                prompt, max_tokens=4000, temperature=0.5  # Increased max_tokens
            )

            # Ensure proper cleanup of provider resources
            if hasattr(provider_instance, "close_session") and callable(
                getattr(provider_instance, "close_session")
            ):
                await provider_instance.close_session()

            if response_str and response_str.strip():
                logger.info(
                    "[AI3] Cycle 1: Successfully generated initial structure with "
                    f"provider: {provider_name}"
                )
                generated_structure_str = response_str
                selected_provider_name = provider_name
                break  # Success, exit loop
            else:
                logger.warning(
                    f"[AI3] Cycle 1: Provider {provider_name} returned empty response "
                    "for initial generation."
                )
        except Exception as e:
            logger.error(
                f"[AI3] Cycle 1: Failed initial generation with provider "
                f"{provider_name}: {str(e)}",
                exc_info=True,
            )
            # Ensure cleanup even in case of exception
            if (
                "provider_instance" in locals()
                and hasattr(provider_instance, "close_session")
                and callable(getattr(provider_instance, "close_session"))
            ):
                await provider_instance.close_session()

    # ... (similar fixes for refinement cycle)

    if not generated_structure_str:
        logger.warning(
            "[AI3] Cycle 1: Failed to generate initial structure with all "
            "configured providers. Using fallback structure."
        )
        logger.info(
            "[AI3] Using pre-defined fallback structure for the NES-style game project"
        )
        return fallback_structure  # Return fallback if all providers fail

    # Attempt to parse the generated structure
    try:
        # Enhanced cleaning for various backtick styles
        cleaned_str = generated_structure_str.strip()
        if cleaned_str.startswith("```json"):
            cleaned_str = cleaned_str[len("```json") :]
        elif cleaned_str.startswith("```"):
            cleaned_str = cleaned_str[len("```") :]
        if cleaned_str.endswith("```"):
            cleaned_str = cleaned_str[: -len("```")]
        cleaned_str = cleaned_str.strip()

        initial_structure = json.loads(cleaned_str)
        logger.info("[AI3] Successfully parsed initial JSON structure.")
    except json.JSONDecodeError as e:
        logger.error(
            f"[AI3] Failed to decode JSON structure: {e}. "
            f"String: {cleaned_str[:200]}..."
        )
        logger.warning(
            "[AI3] Failed to parse the initial JSON structure. Using fallback structure."
        )
        return fallback_structure  # Use fallback if parsing fails

    # Cycle 2: Refinement
    refinement_prompt_template = """
    Target: {target_desc}
    Initial Structure (JSON):
    ```json
    {initial_struct_json}
    ```
    Analyze the initial project structure above for the target: '{target_desc}'.
    Consider its completeness, logical organization, and adherence to common
    practices for such a project.
    Think about typical files needed (e.g., config, tests, docs, main entry points,
    utility modules, build scripts, Dockerfile, README.md, .gitignore).
    If you identify areas for improvement (e.g., missing essential
    files/directories, better organization, incorrect file types), provide an
    updated and refined JSON structure.
    If the structure looks good and complete, return the original JSON structure.
    Output ONLY the JSON structure, enclosed in triple backticks (```json ... ```),
    without any introductory text or explanations.
    """
    # ... (rest of generate_structure with fixes)
    refinement_providers = (
        [selected_provider_name] if selected_provider_name else structure_providers
    )
    refined_structure_json_str: Optional[str] = None
    logger.info(
        f"[AI3] Starting Cycle 2: Structure refinement using providers: {refinement_providers}"
    )

    initial_structure_pretty_json = json.dumps(initial_structure, indent=2)
    refinement_prompt = refinement_prompt_template.format(
        target_desc=target, initial_struct_json=initial_structure_pretty_json
    )

    for provider_name in refinement_providers:
        logger.info(f"[AI3] Cycle 2: Trying provider for refinement: {provider_name}")
        try:
            provider_instance: BaseProvider = ProviderFactory.create_provider(
                provider_name, config=config.get("providers", {}).get(provider_name)
            )
            # TODO: Implement or import apply_request_delay
            # await apply_request_delay("ai3")
            response_str = await provider_instance.generate_text(
                refinement_prompt,
                max_tokens=4000,
                temperature=0.3,  # Increased max_tokens
            )

            # Ensure proper cleanup of provider resources
            if hasattr(provider_instance, "close_session") and callable(
                getattr(provider_instance, "close_session")
            ):
                await provider_instance.close_session()

            if response_str and response_str.strip():
                logger.info(
                    "[AI3] Cycle 2: Successfully received refinement response with "
                    f"provider: {provider_name}"
                )
                refined_structure_json_str = response_str
                break
            else:
                logger.warning(
                    f"[AI3] Cycle 2: Provider {provider_name} returned empty response "
                    "for refinement."
                )
        except Exception as e:
            logger.error(
                f"[AI3] Cycle 2: Failed refinement with provider {provider_name}: {str(e)}",
                exc_info=True,
            )
            # Ensure cleanup even in case of exception
            if (
                "provider_instance" in locals()
                and hasattr(provider_instance, "close_session")
                and callable(getattr(provider_instance, "close_session"))
            ):
                await provider_instance.close_session()

    if refined_structure_json_str:
        try:
            cleaned_refined_str = refined_structure_json_str.strip()
            if cleaned_refined_str.startswith("```json"):
                cleaned_refined_str = cleaned_refined_str[len("```json") :]
            elif cleaned_refined_str.startswith("```"):
                cleaned_refined_str = cleaned_refined_str[len("```") :]

            if cleaned_refined_str.endswith("```"):
                cleaned_refined_str = cleaned_refined_str[: -len("```")]
            cleaned_refined_str = cleaned_refined_str.strip()

            final_structure = json.loads(cleaned_refined_str)
            logger.info(
                "[AI3] Cycle 2: Structure refinement successful. Using refined structure."
            )
            return final_structure
        except json.JSONDecodeError as e:
            logger.error(
                "[AI3] Cycle 2: Failed to parse refined JSON structure. "
                f"Error: {e}. Falling back to initial structure."
            )
            return initial_structure
    else:
        logger.warning(
            "[AI3] Cycle 2: Failed to get refinement response from providers. "
            "Using initial structure."
        )
        return initial_structure


async def send_structure_to_mcp(
    structure_obj: Dict[str, Any],
    target_desc: str,
    mcp_api_url: str,
    client_session: aiohttp.ClientSession,
) -> bool:
    api_url = f"{mcp_api_url}/structure"
    payload = {"structure": structure_obj, "target": target_desc}
    logger.debug(f"[AI3 -> API] Structure payload keys: {list(structure_obj.keys())}")
    try:
        async with client_session.post(api_url, json=payload, timeout=30) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                logger.info(
                    "[AI3 -> API] Structure successfully sent. "
                    f"Response: {response_text}"
                )
                return True
            else:
                logger.error(
                    "[AI3 -> API] Error sending structure. Status: "
                    f"{resp.status}, Response: {response_text}"
                )
                return False
    except asyncio.TimeoutError:
        logger.error(f"[AI3 -> API] Timeout sending structure to {api_url}.")
        return False
    except aiohttp.ClientConnectionError as e:
        logger.error(f"[AI3 -> API] Connection error sending structure: {str(e)}")
        return False
    except Exception as e:
        logger.error(
            f"[AI3 -> API] Unexpected error sending structure: {str(e)}", exc_info=True
        )
        return False


# ... (similar fixes for other functions like _report_status_to_mcp, _initiate_collaboration_via_mcp)
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
                logger.debug(f"[AI3 -> API] Report '{status}' sent successfully.")
                return True
            else:
                response_text = await resp.text()
                logger.error(
                    f"[AI3 -> API] Failed to send report '{status}'. "
                    f"Status: {resp.status}, Response: {response_text}"
                )
                return False
    except asyncio.TimeoutError:
        logger.error(f"[AI3 -> API] Timeout sending report '{status}'.")
        return False
    except aiohttp.ClientConnectionError as e:
        logger.error(f"[AI3 -> API] Connection error sending report: {str(e)}")
        return False
    except Exception as e:
        logger.error(
            f"[AI3 -> API] Unexpected error sending report: {str(e)}", exc_info=True
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
        "[AI3 -> API] Initiating collaboration via "
        f"{api_url} for error: {error_description[:100]}..."
    )
    try:
        async with client_session.post(api_url, json=payload, timeout=30) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                logger.info(
                    "[AI3 -> API] Collaboration request sent successfully. "
                    f"Response: {response_text}"
                )
                return True
            else:
                logger.error(
                    "[AI3 -> API] Failed to send collaboration request. Status: "
                    f"{resp.status}, Response: {response_text}"
                )
                return False
    except asyncio.TimeoutError:
        logger.error("[AI3 -> API] Timeout initiating collaboration.")
        return False
    except aiohttp.ClientConnectionError as e:
        logger.error(
            f"[AI3 -> API] Connection error initiating collaboration: {str(e)}"
        )
        return False
    except Exception as e:
        logger.error(
            f"[AI3 -> API] Unexpected error initiating collaboration: {str(e)}",
            exc_info=True,
        )
        return False


async def create_files_from_structure(
    base_path: str,
    struct: Dict[str, Any],
    repo: Optional[Repo] = None,
    initial_commit: bool = True,
    current_path_in_repo: str = "",
) -> Tuple[List[str], List[str]]:
    # ... (function body with fixes)
    if not isinstance(struct, dict):
        logger.error(
            "[AI3] Invalid structure object provided: Expected dict, got "
            f"{type(struct)}"
        )
        return [], []

    created_files: List[str] = []
    skipped_files: List[str] = []
    # Ensure base_path is absolute and normalized
    base_path = os.path.abspath(os.path.normpath(base_path))

    # Sort items to process .gitignore first if it's at the root
    # This is a simple sort; more complex logic might be needed for true ordering
    sorted_items = sorted(
        struct.items(), key=lambda item: item[0] == ".gitignore", reverse=True
    )

    for key, value in sorted_items:
        if not key:  # Skip empty keys that might come from LLM
            logger.warning(
                f"[AI3] Skipped creating entry for empty key from original: {key}"
            )
            continue

        # Sanitize key to prevent path traversal or invalid characters
        # This is a basic sanitization; more robust validation might be needed
        sanitized_key = key.replace("..", "").strip()
        if not sanitized_key or sanitized_key != key:
            logger.warning(
                f"[AI3] Original key '{key}' was sanitized to '{sanitized_key}'. "
                "Skipping if now empty, or using sanitized."
            )
            if not sanitized_key:
                continue
            key = sanitized_key

        # Construct full_path relative to the repo's root for logging and git
        # current_path_in_repo is the path *within* the repo structure being built
        path_in_repo_for_this_item = os.path.join(current_path_in_repo, key)
        # full_path_on_disk is the absolute path on the filesystem
        full_path_on_disk = os.path.join(base_path, path_in_repo_for_this_item)

        try:
            if isinstance(value, dict):  # Directory
                os.makedirs(full_path_on_disk, exist_ok=True)
                logger.info(f"[AI3] Created directory: {path_in_repo_for_this_item}")
                # Recursively create files in the new directory
                # Pass the updated current_path_in_repo for the recursive call
                sub_created, sub_skipped = await create_files_from_structure(
                    base_path, value, repo, False, path_in_repo_for_this_item
                )
                created_files.extend(sub_created)
                skipped_files.extend(sub_skipped)

                # Add .gitkeep to empty directories, but not for the root call
                if (
                    not os.listdir(full_path_on_disk) and current_path_in_repo
                ):  # Check if dir is empty
                    gitkeep_path = os.path.join(full_path_on_disk, GITKEEP_FILENAME)
                    async with aiofiles.open(gitkeep_path, "w", encoding="utf-8") as f:
                        await f.write("")  # Empty .gitkeep
                    logger.info(
                        f"[AI3] Created .gitkeep in empty directory: {path_in_repo_for_this_item}"
                    )
                    created_files.append(gitkeep_path)

            elif isinstance(value, str) or value is None:  # File
                # Ensure parent directory exists
                parent_dir = os.path.dirname(full_path_on_disk)
                if not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)
                    logger.info(
                        "[AI3] Created parent directory: "
                        f"{os.path.relpath(parent_dir, base_path)}"
                    )

                if not os.path.exists(full_path_on_disk):
                    async with aiofiles.open(
                        full_path_on_disk, "w", encoding="utf-8"
                    ) as f:
                        if value is not None:
                            await f.write(value)
                    logger.info(f"[AI3] Created file: {path_in_repo_for_this_item}")
                    created_files.append(full_path_on_disk)
                else:
                    logger.info(
                        f"[AI3] File already exists, skipping: {path_in_repo_for_this_item}"
                    )
                    skipped_files.append(full_path_on_disk)
            else:
                logger.warning(
                    f"[AI3] Unknown data type '{type(value)}' for '{key}' in "
                    f"'{path_in_repo_for_this_item}'"
                )
        except OSError as e:  # Catch OS-level errors like permission denied
            logger.error(
                f"[AI3] OS error creating {full_path_on_disk}: {e}", exc_info=True
            )
            skipped_files.append(full_path_on_disk)  # Add to skipped if creation failed
        except Exception as e:  # Catch other unexpected errors
            logger.error(
                f"[AI3] Unexpected error creating {full_path_on_disk}: {e}",
                exc_info=True,
            )
            skipped_files.append(full_path_on_disk)

    if initial_commit and repo and created_files:
        logger.info(f"[AI3] Committing {len(created_files)} created files...")
        _commit_changes(repo, created_files, "AI3: Initial project structure")

    return created_files, skipped_files


# ... (similar fixes for generate_initial_idea_md)
async def generate_initial_idea_md(
    target: str,
    provider_factory: ProviderFactory,
    config: Dict[str, Any],
    session: aiohttp.ClientSession,
) -> Optional[str]:
    logger.info(f"[AI3] Generating initial idea.md content for target: {target}")
    prompt = (
        f"Based on the project target: '{target}', write a concise project "
        "description suitable for an idea.md file. This description should "
        "outline the main goals, key features, and overall purpose of the project. "
        "Focus on a high-level overview. Output only the markdown content."
    )
    system_prompt = (
        "You are a helpful assistant tasked with creating project descriptions."
    )

    ai3_config = config.get("ai_config", {}).get("ai3", {})

    # Get list of providers to try in order for idea.md generation
    idea_md_providers = ai3_config.get(
        "idea_md_providers", ["codestral2", "anthropic", "gemini3"]
    )
    if not idea_md_providers:
        idea_md_providers = [
            "codestral2",
            "anthropic",
            "gemini3",
        ]  # Default fallback providers
        logger.warning(
            "[AI3] 'idea_md_providers' not found in ai3 config. "
            f"Using default providers: {idea_md_providers}"
        )

    # Try each provider in sequence until one succeeds
    for provider_name in idea_md_providers:
        try:
            logger.info(
                f"[AI3] Trying to generate idea.md content with provider: {provider_name}"
            )
            provider_config = config.get("providers", {}).get(provider_name, {})

            # Create the provider instance with explicit config
            provider: BaseProvider = ProviderFactory.create_provider(
                provider_name, config=provider_config
            )

            # TODO: Implement or import apply_request_delay
            # await apply_request_delay("ai3")

            content = await provider.generate_text(
                prompt,
                system_prompt=system_prompt,
                max_tokens=800,  # Increased for better descriptions
                temperature=0.7,
            )

            # Ensure proper cleanup of provider resources
            if hasattr(provider, "close_session") and callable(
                getattr(provider, "close_session")
            ):
                await provider.close_session()

            # Check if we got a valid response
            if content and content.strip():
                logger.info(
                    f"[AI3] Successfully generated initial idea.md content with {provider_name}."
                )
                return content.strip()
            else:
                logger.warning(
                    f"[AI3] Provider {provider_name} returned empty response for idea.md generation."
                )
        except Exception as e:
            logger.error(
                f"[AI3] Failed to generate idea.md content with provider {provider_name}: {e}",
                exc_info=True,
            )
            # Ensure cleanup even in case of exception
            if (
                "provider" in locals()
                and hasattr(provider, "close_session")
                and callable(getattr(provider, "close_session"))
            ):
                await provider.close_session()
            # Continue to next provider on error

    # If all providers failed, return a simple template
    default_content = f"# Project: {target}\n\nInitial project description for {target}. This project aims to create a functional application based on the specified requirements."
    logger.warning(
        "[AI3] All providers failed to generate idea.md content. Using default template."
    )
    return default_content


async def ensure_idea_md_exists(
    repo_dir: str,
    target: str,
    provider_factory,
    config: Dict[str, Any],
    client_session: aiohttp.ClientSession,
) -> bool:
    """
    Ensures that idea.md exists in the repository root, creating it if needed.
    This function serves as a safeguard to ensure AI1 always has access to the required idea.md file.

    Args:
        repo_dir: Repository directory path
        target: Project target description
        provider_factory: Factory for creating LLM providers
        config: Configuration dictionary
        client_session: aiohttp client session for API calls

    Returns:
        bool: True if idea.md exists or was created successfully, False otherwise
    """
    idea_md_path = os.path.join(repo_dir, "idea.md")

    # Check if idea.md already exists
    if os.path.exists(idea_md_path):
        logger.info(f"[AI3] idea.md already exists at {idea_md_path}")
        return True

    logger.info(f"[AI3] idea.md not found at {idea_md_path}, generating it...")

    # Generate content for idea.md
    idea_md_content = await generate_initial_idea_md(
        target, provider_factory, config, client_session
    )

    if not idea_md_content:
        # If LLM generation fails, create a basic idea.md with minimal content
        idea_md_content = f"# Project: {target}\n\nThis project aims to create a {target} as specified in the configuration."
        logger.warning(
            "[AI3] Failed to generate idea.md content via LLM, using basic template"
        )

    # Write idea.md
    try:
        async with aiofiles.open(idea_md_path, "w", encoding="utf-8") as f:
            await f.write(idea_md_content)
        logger.info(f"[AI3] Successfully created idea.md at {idea_md_path}")

        # Commit the file if repo exists
        try:
            repo = Repo(repo_dir)
            _commit_changes(repo, [idea_md_path], "AI3: Create initial idea.md")
            logger.info("[AI3] Committed idea.md to the repository")
        except (InvalidGitRepositoryError, GitCommandError) as e:
            logger.warning(f"[AI3] Could not commit idea.md: {e}")

        return True
    except Exception as e:
        logger.error(f"[AI3] Error creating idea.md: {e}", exc_info=True)
        return False


class AI3:
    # ... (AI3 class definition with fixes)
    def __init__(self, target: str, config_path: Optional[str] = None):
        self.target = target
        self.config = load_config(config_path)
        self.repo_dir = os.path.abspath(
            self.config.get("output_dir", REPO_DIR)  # Use REPO_DIR from utils
        )
        self.repo: Optional[Repo] = None
        self.client_session: Optional[aiohttp.ClientSession] = None
        self.mcp_api_url = self.config.get(
            "mcp_api_url", DEFAULT_MCP_API_URL  # Use DEFAULT_MCP_API_URL from utils
        )
        self.monitoring_active = False
        self.background_tasks: List[asyncio.Task] = []
        self.processed_github_run_ids = set()  # type: ignore
        self.ollama_initialized = False
        self.ollama_endpoint: Optional[str] = None
        self.ollama_model: Optional[str] = None
        self.provider_factory = ProviderFactory()  # Remove arguments here
        self.current_project_structure: Optional[Dict[str, Any]] = None

        # Initialize Ollama configuration
        self._initialize_ollama_config()

    # Add the missing start_monitoring and stop_monitoring methods
    async def start_monitoring(self):
        """Start all monitoring background tasks."""
        logger.info("[AI3] Starting background monitoring tasks...")

        self.monitoring_active = True

        # Create and start background tasks
        monitor_tasks = [
            self.monitor_system_health(),
            self.monitor_github_actions(),
            self.monitor_idle_workers(),
            # Add more monitoring tasks as needed
        ]

        for task in monitor_tasks:
            background_task = asyncio.create_task(task)
            self.background_tasks.append(background_task)

        logger.info(
            f"[AI3] Started {len(self.background_tasks)} background monitoring tasks"
        )

    async def stop_monitoring(self):
        """Stop all monitoring background tasks."""
        logger.info(
            f"[AI3] Stopping {len(self.background_tasks)} background monitoring tasks..."
        )

        self.monitoring_active = False

        # Cancel all running background tasks
        for task in self.background_tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete their cancellation
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)

        self.background_tasks.clear()
        logger.info("[AI3] All background monitoring tasks stopped")

    def _initialize_ollama_config(self):
        # Check if structure_providers exists in ai3 configuration
        structure_providers = (
            self.config.get("ai_config", {})
            .get("ai3", {})
            .get("structure_providers", ["ollama1"])
        )

        # Get the first provider from the structure_providers list
        ollama_config_key = None
        for provider_name in structure_providers:
            if provider_name.startswith("ollama"):
                ollama_config_key = provider_name
                break

        # Default to "ollama" if no ollama provider found in structure_providers
        if not ollama_config_key:
            ollama_config_key = "ollama"

        # Get the Ollama provider configuration
        ollama_provider_config = self.config.get("providers", {}).get(
            ollama_config_key, {}
        )

        self.ollama_endpoint = ollama_provider_config.get("endpoint")
        self.ollama_model = ollama_provider_config.get("model")

        if self.ollama_endpoint and self.ollama_model:
            self.ollama_initialized = True
            logger.info(
                "[AI3-Ollama] Successfully initialized Ollama with endpoint "
                f"'{self.ollama_endpoint}' and model '{self.ollama_model}'"
            )
        else:
            logger.warning(
                "[AI3-Ollama] Failed to initialize Ollama: Configuration not found "
                f"for key '{ollama_config_key}' in config.json"
            )

    async def clear_repository(self) -> bool:
        """Clears the repository directory."""
        logger.info(f"[AI3-Git] Attempting to clear repository at: {self.repo_dir}")
        try:
            if os.path.exists(self.repo_dir):
                # Check if it's a git repository before trying to use self.repo
                try:
                    temp_repo = Repo(self.repo_dir)
                    # If it is a repo, try to clean it using git commands if preferred
                    # For simplicity here, we'll just remove the directory
                    logger.info(
                        f"[AI3-Git] Removing existing repository directory: {self.repo_dir}"
                    )
                except InvalidGitRepositoryError:
                    logger.info(
                        f"[AI3-Git] Directory exists but is not a git repo: {self.repo_dir}. Removing."
                    )
                except NoSuchPathError:  # Should not happen if os.path.exists is true
                    logger.warning(f"[AI3-Git] Repo path disappeared: {self.repo_dir}")

                # Use shutil.rmtree to remove the directory and its contents
                shutil.rmtree(self.repo_dir)
                logger.info(f"[AI3-Git] Removed existing repository: {self.repo_dir}")

            # Recreate the directory for the new repository
            os.makedirs(self.repo_dir, exist_ok=True)
            logger.info(f"[AI3-Git] Created new repository directory: {self.repo_dir}")
            return True
        except Exception as e:
            logger.error(f"[AI3-Git] Error clearing repository: {e}", exc_info=True)
            return False

    async def setup_structure(self):
        logger.info("[AI3] Starting project structure setup...")
        # TODO: Implement or import wait_for_service
        # if not await wait_for_service(self.mcp_api_url, self.client_session, timeout=60):
        #     logger.critical(
        #         "[AI3] MCP API did not become available. Aborting structure setup."
        #     )
        #     return

        if not await self.clear_repository():
            logger.critical(
                "[AI3] Repository clearing failed. Cannot proceed with structure setup."
            )
            await _report_status_to_mcp(
                "error_repo_clear_failed",
                {"details": "Failed to clear repository"},
                self.mcp_api_url,
                self.client_session,
            )
            return

        # Initialize the Git repository after clearing
        # Change current directory to self.repo_dir before calling Repo.init
        original_cwd = os.getcwd()
        try:
            os.chdir(self.repo_dir)
            self.repo = Repo.init(
                "."
            )  # Initialize in the current directory (self.repo_dir)
            logger.info(
                f"[AI3-Git] Successfully initialized new repository at: {self.repo_dir}"
            )

            # Create and commit .gitignore to create an initial commit
            gitignore_path = os.path.join(self.repo_dir, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write(
                        """*.pyc
__pycache__/
.DS_Store
.env
logs/
tmp/
node_modules/
dist/
build/
*.log
coverage.xml
.pytest_cache/
.mypy_cache/
.idea/
.vscode/
"""
                    )
                logger.info(f"[AI3-Git] Created .gitignore at {gitignore_path}")

                # Create initial commit manually instead of using _commit_changes
                if self.repo:
                    try:
                        self.repo.git.add(gitignore_path)
                        self.repo.git.commit("-m", "Initial commit: .gitignore")
                        logger.info("[AI3-Git] Successfully created initial commit")
                    except Exception as e:
                        logger.error(
                            f"[AI3-Git] Error creating initial commit: {e}",
                            exc_info=True,
                        )

        except Exception as e:
            logger.critical(
                f"[AI3-Git] Failed to initialize Git repository: {e}", exc_info=True
            )
            await _report_status_to_mcp(
                "error_git_init_failed",
                {"details": str(e)},
                self.mcp_api_url,
                self.client_session,
            )
            return
        finally:
            os.chdir(original_cwd)  # Restore original CWD

        await _report_status_to_mcp(
            "repo_cleared", None, self.mcp_api_url, self.client_session
        )

        # Check for and remove unexpected "project/" directory if it exists
        project_path = os.path.join(self.repo_dir, "project")
        if os.path.exists(project_path) and os.path.isdir(project_path):
            logger.warning(
                "[AI3-Git] Found unexpected 'project/' directory at "
                f"{project_path}. Removing it."
            )
            try:
                shutil.rmtree(project_path)
                logger.info(f"[AI3-Git] Successfully removed {project_path}")
            except Exception as e:
                logger.error(f"[AI3-Git] Error removing {project_path}: {e}")

        structure = await generate_structure(
            self.target, self.config, self.client_session  # type: ignore
        )
        if not structure:
            logger.critical("[AI3] Structure generation failed. Cannot proceed.")
            await _report_status_to_mcp(
                "error_structure_generation_failed",
                {"details": "LLM failed to generate structure"},
                self.mcp_api_url,
                self.client_session,
            )
            return

        logger.info(
            f"[AI3] Successfully generated structure. Root keys: {list(structure.keys())}"
        )
        self.current_project_structure = structure  # Store the structure

        # Handle potential duplicate project folders from LLM
        # (e.g., "nes_flash_game" and "retro_nes_flash_game")
        has_retro = "retro_nes_flash_game/" in structure
        has_nes = "nes_flash_game/" in structure

        if has_retro and has_nes:
            logger.warning(
                "[AI3] Both 'retro_nes_flash_game' and 'nes_flash_game' found "
                "in LLM structure. Removed 'nes_flash_game'."
            )
            del structure["nes_flash_game/"]
        elif has_nes and not has_retro:
            logger.info(
                "[AI3] Only 'nes_flash_game' found in LLM structure. Renamed to "
                "'retro_nes_flash_game'."
            )
            structure["retro_nes_flash_game/"] = structure.pop("nes_flash_game/")

        # Remove 'idea' entry from the LLM structure if it exists at the root,
        # to prevent conflict with the system-generated 'idea.md'.
        if "idea" in structure:  # Check if "idea" key exists at the root
            del structure["idea"]
            logger.info(
                "[AI3] Removed 'idea' entry (whether file or directory placeholder) "
                "from the root of the generated project structure to prevent "
                "conflict with 'idea.md'."
            )
        if "idea.md" in structure:  # Also remove idea.md if LLM tried to make one
            del structure["idea.md"]
            logger.info(
                "[AI3] Removed 'idea.md' from LLM structure, will generate fresh."
            )

        created_count, skipped_count = await create_files_from_structure(
            self.repo_dir, structure, self.repo, initial_commit=True
        )
        if created_count == 0 and skipped_count == 0:
            logger.warning(
                "[AI3] No files were created or skipped. The structure might have "
                "been empty or problematic."
            )
        else:
            logger.info(
                f"[AI3] File creation completed: {created_count} files created, "
                f"{skipped_count} skipped"
            )

        await _report_status_to_mcp(
            "structure_creation_completed",
            {"created_count": created_count, "skipped_count": skipped_count},
            self.mcp_api_url,
            self.client_session,  # type: ignore
        )

        # Generate idea.md
        idea_md_content = await generate_initial_idea_md(
            self.target, self.provider_factory, self.config, self.client_session  # type: ignore
        )
        idea_md_path = os.path.join(self.repo_dir, "idea.md")

        if idea_md_content:
            try:
                async with aiofiles.open(idea_md_path, "w", encoding="utf-8") as f:
                    await f.write(idea_md_content)
                logger.info(
                    f"[AI3] Successfully wrote initial content to {idea_md_path}"
                )
                if self.repo:
                    _commit_changes(
                        self.repo, [idea_md_path], "AI3: Add initial idea.md"
                    )
            except Exception as e:
                logger.error(f"[AI3] Error writing idea.md: {e}", exc_info=True)
        else:
            logger.warning(
                "[AI3] Failed to generate initial idea.md content. "
                "Proceeding without it."
            )

        # Explicitly remove any file named "idea" (without extension) if it exists
        # This is a final safety check after structure creation.
        idea_file_path = os.path.join(self.repo_dir, "idea")
        if os.path.exists(idea_file_path):
            try:
                if os.path.isfile(idea_file_path):
                    os.remove(idea_file_path)
                    logger.info(
                        f"[AI3] Ensured removal of '{idea_file_path}' to keep 'idea.md' "
                        "as the sole project description file."
                    )
                    if self.repo:  # Commit this removal if it happened
                        _commit_changes(
                            self.repo,
                            [idea_file_path],
                            "AI3: Remove conflicting 'idea' file",
                        )
                elif os.path.isdir(idea_file_path):
                    logger.warning(
                        f"[AI3] Path 'idea' is a directory, not removing: {idea_file_path}"
                    )
            except Exception as e:
                logger.error(
                    f"[AI3] Error during explicit removal of '{idea_file_path}': {e}",
                    exc_info=True,
                )

        # Ensure idea.md exists before sending the final structure to MCP
        await ensure_idea_md_exists(
            self.repo_dir,
            self.target,
            self.provider_factory,
            self.config,
            self.client_session,
        )

        if not await send_structure_to_mcp(
            structure, self.target, self.mcp_api_url, self.client_session  # type: ignore
        ):
            logger.error("[AI3] Failed to send final structure to MCP.")
            await _report_status_to_mcp(
                "error_mcp_send_failed",
                {"details": "Failed to send structure to MCP"},
                self.mcp_api_url,
                self.client_session,
            )
            # Decide if this is critical enough to stop
        else:
            logger.info("[AI3] Final structure successfully sent to MCP.")
            await _report_status_to_mcp(
                "structure_setup_completed",
                {"final_structure_keys": list(structure.keys())},
                self.mcp_api_url,
                self.client_session,
            )

        logger.info("[AI3] Structure setup phase completed.")

    # ... (AI3 methods with fixes for line length, undefined names, etc.)
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
                    f"[AI3] System health requires attention: {health_status}"
                )
                # TODO: Implement ai_comm
                # await self._report_system_error_to_ai1(
                #     "System Health Alert",
                #     f"Details: {health_status.get('warnings', 'N/A')}, "
                #     f"Errors: {health_status.get('error_count', 0)}",
                #     "system_health.log" # Placeholder log file
                # )
            # ...
        except Exception as e:
            logger.error(
                f"[AI3-MonitorSysHealth] Error in system health monitoring loop: {e}",
                exc_info=True,
            )

    # ...
    async def _check_system_health(self) -> Dict[str, Any]:
        health_metrics: Dict[str, Any] = {
            "status": "OK",
            "timestamp": datetime.now(timezone.utc).isoformat(),  # Use timezone.utc
            "services": {},
            "resource_usage": {},
            "log_errors": {"count": 0, "details": []},
            "error_count": 0,
            "warnings": [],
            "requires_attention": False,
        }
        try:
            import psutil  # Import psutil locally

            mem = psutil.virtual_memory()
            health_metrics["resource_usage"]["memory"] = {
                "total_gb": f"{mem.total / (1024**3):.2f}",
                "available_gb": f"{mem.available / (1024**3):.2f}",
                "percent_used": f"{mem.percent:.2f}%",
            }
            if mem.percent > 85:
                health_metrics["warnings"].append("High memory usage (>85%)")

            disk = psutil.disk_usage(
                self.repo_dir if os.path.exists(self.repo_dir) else "/"
            )
            health_metrics["resource_usage"]["disk"] = {
                "total_gb": f"{disk.total / (1024**3):.2f}",
                "free_gb": f"{disk.free / (1024**3):.2f}",
                "percent_used": f"{disk.percent:.2f}%",
            }
            if disk.percent > 90:
                health_metrics["warnings"].append("High disk usage (>90%)")
        except ImportError:
            logger.warning(
                "[AI3-Health] psutil module not found. Cannot report detailed resource usage."
            )
            health_metrics["resource_usage"]["memory"] = {
                "status": "psutil module not available"
            }
            health_metrics["resource_usage"]["disk"] = {
                "status": "psutil module not available"
            }
        except Exception as e:
            logger.error(f"[AI3-Health] Error getting resource usage: {e}")
            health_metrics["resource_usage"]["error"] = str(e)

        # Check service status (conceptual, needs actual service checks)
        services_to_check = [
            "mcp_api",
            "ai1",
            "ai2_executor",
            "ai2_tester",
            "ai2_documenter",
        ]
        service_status: Dict[str, Any] = {"overall": "OK", "errors": []}

        for service_name in services_to_check:
            pid_file = Path(LOGS_DIR) / f"{service_name}.pid"  # LOGS_DIR from utils
            log_file = Path(LOGS_DIR) / f"{service_name}.log"
            status = {
                "status": "UNKNOWN",
                "pid_found": False,
                "running": False,
                "log_exists": log_file.exists(),
            }

            if pid_file.exists():
                status["pid_found"] = True
                try:
                    pid = int(pid_file.read_text().strip())
                    if psutil.pid_exists(pid):  # psutil needs to be imported
                        # p = psutil.Process(pid) # Requires psutil
                        # if p.name().lower() in service_name: # Basic check
                        status["running"] = True
                        status["status"] = "RUNNING"
                        # else:
                        #     status["status"] = "PID_MISMATCH"
                        #     service_status["errors"].append(f"Service {service_name} PID mismatch.")
                    else:
                        status["status"] = "NOT_RUNNING_PID_STALE"
                        service_status["errors"].append(
                            f"Service {service_name} has PID file but process {pid} is not running"
                        )
                except (
                    ValueError,
                    FileNotFoundError,
                    psutil.NoSuchProcess if "psutil" in sys.modules else Exception,
                ) as e:  # Handle if psutil not imported
                    status["status"] = "ERROR_CHECKING_PID"
                    service_status["errors"].append(
                        f"Error checking PID for {service_name}: {e}"
                    )
            else:  # No PID file
                status["status"] = "NO_PID_FILE"
                # This might be normal for some services or if they haven't started
                # health_metrics["warnings"].append(f"No PID file for service {service_name}")

            health_metrics["services"][service_name] = status
            if status["status"] not in [
                "RUNNING",
                "UNKNOWN",
                "NO_PID_FILE",
            ]:  # Consider NO_PID_FILE as warning not error initially
                service_status["overall"] = "DEGRADED"

        health_metrics["service_status"] = service_status
        if service_status["overall"] != "OK":
            health_metrics["warnings"].append(
                f"One or more services are in a '{service_status['overall']}' state."
            )

        # Basic log error check (last N lines for keywords)
        error_logs_details = []
        try:
            log_files_to_scan = list(
                Path(LOGS_DIR).glob("*.log")
            )  # LOGS_DIR from utils
            for log_file_path in log_files_to_scan:
                try:
                    with open(
                        log_file_path, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        # Read last N lines for quick scan
                        log_lines = f.readlines()
                        recent_lines = (
                            log_lines[-100:] if len(log_lines) > 100 else log_lines
                        )
                        error_patterns = ["ERROR", "CRITICAL", "Exception", "Traceback"]
                        for i, line_content in enumerate(recent_lines):
                            if any(
                                pattern in line_content for pattern in error_patterns
                            ):
                                error_logs_details.append(
                                    f"{log_file_path.name} (line ~{len(log_lines) - len(recent_lines) + i}): {line_content.strip()}"
                                )
                except Exception as e_log:
                    logger.error(
                        f"[AI3-Health] Error reading log file {log_file_path}: {e_log}"
                    )
                    error_logs_details.append(
                        f"Error reading {log_file_path.name}: {e_log}"
                    )
        except Exception as e_scan_logs:
            logger.error(f"[AI3-Health] Error scanning log directory: {e_scan_logs}")
            error_logs_details.append(f"Error scanning log directory: {e_scan_logs}")

        if error_logs_details:
            health_metrics["log_errors"]["count"] = len(error_logs_details)
            health_metrics["log_errors"]["details"] = error_logs_details[
                :20
            ]  # Limit details
            health_metrics["warnings"].append(
                f"Found {len(error_logs_details)} error indicators in logs."
            )

        health_metrics["error_count"] = (
            len(health_metrics["service_status"].get("errors", []))
            + health_metrics["log_errors"]["count"]  # Use count here
        )

        if health_metrics["error_count"] > 0 or health_metrics["warnings"]:
            health_metrics["requires_attention"] = True
            if health_metrics["error_count"] > 0:
                health_metrics["status"] = "ERROR"
            elif health_metrics["warnings"]:
                health_metrics["status"] = "WARNING"

        return health_metrics

    # ...
    async def scan_logs_for_errors(self):
        """Scans configured log files for errors related to 'repo/' using Ollama."""
        if not self.ollama_initialized:
            logger.warning(
                "[AI3] Ollama not initialized. Skipping log scan for errors."
            )
            return []

        logger.info("[AI3] Starting log scan for errors using Ollama...")
        # logs_dir_path = Path(LOGS_DIR) # LOGS_DIR from utils
        logs_dir_path = Path(
            self.config.get("logs_dir", LOGS_DIR)
        )  # Use configured or default
        if not logs_dir_path.exists() or not logs_dir_path.is_dir():
            logger.error(
                f"[AI3] Logs directory '{logs_dir_path}' not found. Cannot scan for errors."
            )
            return []

        # Ensure Ollama config is loaded (should be by _initialize_ollama_config)
        if not self.ollama_endpoint or not self.ollama_model:
            logger.error(
                "[AI3] Ollama configuration not found in config.json. "
                "Cannot proceed with log analysis."
            )
            return []

        logger.info(
            "[AI3] Ollama configured with endpoint "
            f"'{self.ollama_endpoint}' and model '{self.ollama_model}'"
        )

        detected_errors = []
        log_files = [
            f for f in logs_dir_path.iterdir() if f.is_file() and f.suffix == ".log"
        ]

        for log_file in log_files:
            try:
                logger.info(f"[AI3] Scanning log file: {log_file.name}")
                lines_analyzed = 0
                errors_detected_in_file = 0

                async with aiofiles.open(
                    log_file, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    lines = await f.readlines()
                    logger.info(f"[AI3] Read {len(lines)} lines from {log_file.name}")

                    for i, line_content in enumerate(lines):
                        if lines_analyzed >= MAX_LOG_LINE_ANALYSIS:
                            logger.info(
                                f"[AI3] Reached max analysis lines for {log_file.name}"
                            )
                            break

                        # Basic filter for common error keywords to reduce LLM calls
                        if not any(
                            kw in line_content.upper()
                            for kw in ["ERROR", "FAIL", "EXCEPTION", "CRITICAL"]
                        ):
                            continue

                        logger.debug(
                            f"[AI3] Analyzing log line {i+1}/{len(lines)} in {log_file.name}"
                        )

                        context_start = max(0, i - MAX_CONTEXT_LINES)
                        context_end = min(len(lines), i + MAX_CONTEXT_LINES + 1)
                        context = "".join(lines[context_start:context_end])

                        prompt = (
                            f"Log file: {log_file.name}\\n"
                            f"Context (lines {context_start+1}-{context_end}):\\n```log\\n{context}```\\n"
                            f"Current line under analysis (line {i+1}): {line_content.strip()}\\n\\n"
                            "Analyze this log line and its context. Determine if it indicates a "
                            "significant error, particularly related to file operations, code execution, "
                            "or system stability within a software development project (files often in a 'repo/' directory). "
                            "Ignore benign errors or routine operational messages unless they clearly point to a problem. "
                            "Respond in JSON format: "
                            '{{"is_error": bool, "confidence": float (0.0-1.0), "error_type": "str (e.g., FileSystem, CodeExecution, Configuration, Network, Unknown)", "summary": "str (brief summary of the error)", "affected_file_or_module": "str (if identifiable, otherwise null)"}}'
                        )

                        # TODO: Implement or import apply_request_delay
                        # await apply_request_delay("ai3_ollama")
                        analysis_json_str = (
                            await call_ollama(  # Use specific call_ollama
                                self.client_session,  # type: ignore
                                prompt,
                                self.ollama_endpoint,
                                self.ollama_model,
                                temperature=0.3,
                                max_tokens=300,  # Smaller response expected
                                timeout=45,  # Shorter timeout for log line analysis
                            )
                        )
                        lines_analyzed += 1

                        if analysis_json_str:
                            try:
                                result = json.loads(analysis_json_str)
                                if (
                                    result.get("is_error")
                                    and result.get("confidence", 0.0) > 0.6
                                ):
                                    logger.info(
                                        f"[AI3] Ollama detected error in {log_file.name}: {line_content.strip()}"
                                    )
                                    error_detail = {
                                        "log_file": log_file.name,
                                        "line_number": i + 1,
                                        "line_content": line_content.strip(),
                                        "ollama_analysis": result,
                                    }
                                    detected_errors.append(error_detail)
                                    errors_detected_in_file += 1
                                    # TODO: Implement ai_comm
                                    # report_sent = await self._report_system_error_to_ai1(
                                    #     f"Ollama detected error in {log_file.name}",
                                    #     result.get("summary", "No summary"),
                                    #     log_file.name,
                                    #     context=error_detail
                                    # )
                                    # if report_sent:
                                    #     logger.info(
                                    #         "[AI3] Successfully reported error to AI1 from "
                                    #         f"{log_file.name}"
                                    #     )
                                    # else:
                                    #     logger.warning(
                                    #         "[AI3] Failed to report error to AI1 from "
                                    #         f"{log_file.name}"
                                    #     )

                            except json.JSONDecodeError:
                                logger.warning(
                                    "[AI3] Invalid JSON response from Ollama for line: "
                                    f"{line_content.strip()[:100]}..."
                                )
                                logger.debug(
                                    f"[AI3] Full invalid response: {analysis_json_str}"
                                )
                        # else: # No response from Ollama or empty
                        # logger.debug(f"[AI3] No Ollama response for line: {line_content.strip()[:100]}...")

                logger.info(
                    f"[AI3] Completed analysis of {log_file.name}: "
                    f"{lines_analyzed} lines analyzed, {errors_detected_in_file} errors detected"
                )
            except Exception as e:
                logger.error(
                    f"[AI3] Error processing log file {log_file.name}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"[AI3] Log scanning completed. Total errors detected by Ollama: {len(detected_errors)}"
        )
        return detected_errors

    # ...
    async def monitor_github_actions(self):
        # ...
        github_repo = os.getenv("GITHUB_REPO_TO_MONITOR") or self.config.get(
            "github_repo_to_monitor"
        )
        github_token = os.getenv("GITHUB_TOKEN") or self.config.get("github_token")

        if not github_repo:
            logger.info(
                "[AI3] Warning: GitHub repository not configured. "
                "Cannot monitor GitHub Actions."
            )
            return
        if not github_token:
            logger.info(
                "[AI3] Warning: GITHUB_TOKEN not configured. "
                "Cannot monitor GitHub Actions."
            )
            return

        logger.debug(f"[AI3] Checking GitHub Actions runs for {github_repo}...")
        api_url = f"{GITHUB_API_BASE_URL}/repos/{github_repo}/actions/runs"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        # ...
        try:
            async with self.client_session.get(api_url, headers=headers, params={"status": "completed"}, timeout=30) as response:  # type: ignore
                if response.status == 200:
                    runs_data = await response.json()
                    workflow_runs = runs_data.get("workflow_runs", [])
                    logger.info(
                        f"[AI3] Fetched {len(workflow_runs)} completed workflow runs."
                    )

                    # Sort runs by creation time, newest first
                    sorted_runs = sorted(
                        workflow_runs, key=lambda x: x["created_at"], reverse=True
                    )

                    new_runs_found = False
                    for run in sorted_runs:
                        run_id = run["id"]
                        if run_id not in self.processed_github_run_ids:
                            new_runs_found = True
                            run_conclusion = run.get("conclusion")
                            logger.info(
                                "[AI3] Found new completed GitHub Actions run: "
                                f"ID={run_id}, Conclusion={run_conclusion}"
                            )
                            await self._analyze_workflow_run(
                                run_id,
                                run_conclusion,
                                headers,
                                GITHUB_API_BASE_URL,  # Use constant
                            )
                            self.processed_github_run_ids.add(run_id)
                            # Limit processing to a few new runs per cycle to avoid rate limits
                            if (
                                len(self.processed_github_run_ids) > 1000
                            ):  # Prune old IDs
                                self.processed_github_run_ids = set(
                                    list(self.processed_github_run_ids)[-500:]
                                )

                    if (
                        not new_runs_found and workflow_runs
                    ):  # Only log if there were runs but none new
                        logger.info(
                            "[AI3] No new completed GitHub Actions runs found this cycle."
                        )
                    elif not workflow_runs:
                        logger.info(
                            "[AI3] No completed GitHub Actions runs found for the repository."
                        )

                elif response.status == 404:
                    logger.error(
                        f"[AI3] GitHub repository '{github_repo}' not found or "
                        "access denied. Stopping GitHub monitoring."
                    )
                    self.monitoring_active = False  # Stop if repo not found
                elif response.status == 401:
                    logger.error(
                        "[AI3] GitHub API authentication failed (Invalid GITHUB_TOKEN?). "
                        "Stopping GitHub monitoring."
                    )
                    self.monitoring_active = False  # Stop if auth fails
                else:
                    logger.error(
                        "[AI3] Failed to fetch GitHub Actions runs: Status "
                        f"{response.status} - {await response.text()}"
                    )
        except asyncio.TimeoutError:
            logger.warning("[AI3] Timeout during GitHub Actions monitoring.")
        except aiohttp.ClientError as e:
            logger.error(
                f"[AI3] Connection error during GitHub Actions monitoring: {e}"
            )
        except Exception as e:
            logger.error(
                f"[AI3] Error in GitHub Actions monitoring loop: {e}", exc_info=True
            )

    # ...
    async def _analyze_workflow_run(
        self,
        run_id: int,
        run_conclusion: Optional[str],
        headers: dict,
        api_base_url: str,
    ):
        logger.info(
            f"[AI3] Analyzing workflow run ID: {run_id}, Conclusion: {run_conclusion}"
        )
        # ...
        # TODO: Implement ai_comm
        # await self._send_test_recommendation(recommendation, context)

    # ...
    async def _analyze_github_actions_logs_with_ollama(
        self, logs: str, run_id: int, run_conclusion: Optional[str]
    ) -> Dict[str, Any]:
        # ...
        prompt = (
            f"GitHub Actions Run ID: {run_id}, Conclusion: {run_conclusion}\\n"
            f"Logs:\\n```\\n{logs[:15000]}```\\n\\n"  # Limit log size
            "Analyze the following GitHub Actions logs and determine if there are "
            "test or linting errors. Identify any specific files that failed. "
            "If tests failed, recommend 'rework'. If tests passed or only minor "
            "linting issues (that might be auto-fixed) occurred, recommend 'accept'. "
            "If unsure or logs are inconclusive, recommend 'accept' but note it. "
            'Respond in JSON format: {{"recommendation": "accept"|"rework", '
            '"failed_files": list[str], "summary": "str (brief summary of findings)", '
            '"confidence": float (0.0-1.0)}}'
        )
        # ...
        # default_recommendation = {
        #     "recommendation": "accept" if run_conclusion != "failure" else "rework",
        #     "failed_files": [],
        #     "summary": f"Default based on run conclusion: {run_conclusion}",
        #     "confidence": 0.5,
        #     "run_url": f"https://github.com/{self.config.get('github_repo_to_monitor')}/actions/runs/{run_id}",
        # }
        # ...
        if analysis_json_str:
            try:
                result = json.loads(analysis_json_str)
                # ...
                logger.info(
                    f"[AI3] Ollama recommendation for run {run_id}: "
                    f"{result.get('recommendation')}, Failed files: {result.get('failed_files')}"
                )
                # ...
            except json.JSONDecodeError:
                logger.warning(
                    f"[AI3] Invalid JSON response from Ollama for run {run_id}: {analysis_json_str}"
                )
                # return default_recommendation
        # return default_recommendation

    # ...
    async def _send_test_recommendation(self, recommendation: str, context: dict):
        api_url = f"{self.mcp_api_url}/test_recommendation"
        recommendation_data = {"recommendation": recommendation, "context": context}
        logger.info(
            "[AI3 -> MCP] Sending test recommendation: "
            f"{recommendation}, Context keys: {list(context.keys())}"
        )
        # ...

    async def monitor_idle_workers(self):
        # ...
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
        error_description: str,
        log_file: str,
        context: Optional[Dict] = None,
    ):
        """Reports a system error to AI1 using the standardized communication protocol"""
        logger.info(f"[AI3 -> AI1] Attempting to report system error: {error_type}")
        # TODO: This needs a proper implementation with ai_comm or similar
        # try:
        #     # Assuming ai_comm is a module or object that provides messaging capabilities
        #     # This is a placeholder for the actual communication mechanism
        #     # message_bus = await ai_comm.get_message_bus() # Placeholder
        #     # error_message = ai_comm.Message( # Placeholder
        #     #     source="ai3",
        #     #     target="ai1",
        #     #     type="system_error",
        #     #     payload={
        #     #         "error_type": error_type,
        #     #         "description": error_description,
        #     #         "log_file": log_file,
        #     #         "timestamp": datetime.now(timezone.utc).isoformat(),
        #     #         "context": context or {}
        #     #     }
        #     # )
        #     # await message_bus.publish(error_message) # Placeholder
        #     logger.info(f"[AI3 -> AI1] Reported system error from {log_file} to AI1.")
        #     return True
        # except Exception as e:
        #     logger.error(
        #         f"[AI3 -> AI1] Failed to report system error to AI1: {e}", exc_info=True
        #     )
        #     return False
        logger.warning(
            "[AI3 -> AI1] _report_system_error_to_ai1: ai_comm not implemented."
        )
        return False  # Placeholder return

    # ...
    async def main_loop(self):
        # ...
        if self.current_project_structure is None:  # Check if structure was set up
            logger.info(
                "[AI3] Structure phase complete. Switching to monitoring mode "
                "(using APIs, not structure providers)."
            )
        # ...

    async def _attempt_test_fixes(self, failing_tests: Dict[str, Any]):
        # ...
        prompt = (
            f"Test File: {test_file}\\n"
            f"Test File Content (first 1000 chars):\\n```\\n{test_content[:1000]}\\n```\\n\n"
            f"Code File: {code_file_rel}\\n"
            f"Code File Content (first 3000 chars):\\n```\\n{code_content[:3000]}\\n```\\n\n"
            f"Test Result Details (first 1000 chars):\\n```\\n"
            f"{json.dumps(test_result.get('details', 'No details')[:1000], indent=2)}\\n```\\n\n"
            "The tests in the test file are failing for the corresponding code file. "
            "The error details are provided above. "
            f"Please analyze the error and the code, then provide a fix for the CODE FILE ({code_file_rel}). "
            f"Output ONLY the corrected code for {code_file_rel}, enclosed in triple backticks "
            "(e.g., ```python ...corrected code... ``` or ```javascript ...corrected code... ```). "
            "Do not include explanations or the test file code in your response. "
            "If you cannot determine a fix, output an empty code block: ```<code>\\n```"
        )
        # ...
        code_fix_content_raw = await call_llm_provider(  # Generic call_llm_provider
            provider_name_for_fix,
            prompt,
            session=self.client_session,  # type: ignore
            config=self.config,  # Pass full config
            # system_prompt="You are an expert debugging assistant. Provide only the corrected code.", # Pass as kwarg if provider supports
            max_tokens=2000,  # Allow larger fixes
            temperature=0.4,  # Slightly more creative for fixes
            # Additional kwargs for specific provider if needed
            model_kwargs={
                "system_prompt": "You are an expert debugging assistant. Provide only the corrected code."
            },  # Example
        )
        # ...
        # Regex to extract code, more permissive of language specifier
        match = re.search(
            r"```(?:code|python|javascript|typescript|java|c\+\+|go|rust|php)?\s*\n(.*?)\n```",
            code_fix_content_raw,
            re.DOTALL | re.IGNORECASE,
        )
        # ...

    def _infer_code_file_from_test(
        self, test_file: str, test_content: str
    ) -> Optional[str]:
        # ...
        base, ext = os.path.splitext(test_file)
        potential_name = ""

        # Handle common test naming conventions like "test_module.py" -> "module.py"
        # or "module.test.js" -> "module.js"
        if base.startswith(TESTS_TEST_PREFIX):  # "tests/test_"
            potential_name = base[len(TESTS_TEST_PREFIX) :]
        elif base.endswith(DOT_TEST_SUFFIX):  # ".test"
            potential_name = base[: -len(DOT_TEST_SUFFIX)]
        else:  # Fallback if no common prefix/suffix, just use base name
            potential_name = base
        # ...
        # Search for import statements in test_content (basic example)
        # Example: from project_name.module import ClassA -> project_name/module.py
        # This regex is very basic and might need significant improvement
        import_match = re.search(r"from\s+([\w.]+)\s+import", test_content)
        if import_match:
            module_path = import_match.group(1).replace(".", "/")
            potential_code_file = f"{module_path}{ext}"
            if os.path.exists(os.path.join(self.repo_dir, potential_code_file)):
                logger.info(
                    f"[AI3-InferCode] Inferred code file '{potential_code_file}' for "
                    f"test '{test_file}' via import."
                )
                return potential_code_file
        # ...


async def call_ollama(  # Specific Ollama call
    session: aiohttp.ClientSession,
    prompt: str,
    endpoint: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: int = 120,  # Increased default timeout for Ollama
) -> Optional[str]:
    if not endpoint or not model:
        logger.error("[AI3-Ollama] Endpoint or model not configured for Ollama call.")
        return None

    logger.info(
        "[AI3-Ollama] Calling Ollama API with model "
        f"'{model}' at endpoint '{endpoint}'"
    )
    # logger.debug(
    #     f"[AI3-Ollama] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
    # )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,  # Ensure non-streaming for single response
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    # logger.debug(f"[AI3-Ollama] Sending request with payload: {payload}")
    start_time = time.time()
    try:
        async with session.post(
            f"{endpoint}/api/generate", json=payload, timeout=timeout
        ) as response:
            elapsed_time = time.time() - start_time
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            data = await response.json()
            result = data.get("response", "").strip()
            logger.info(
                f"[AI3-Ollama] Response received in {elapsed_time:.2f}s: "
                f"{result[:100]}{'...' if len(result) > 100 else ''}"
            )
            return result
    except asyncio.TimeoutError:
        logger.error(
            f"[AI3-Ollama] Timeout calling Ollama API after {timeout}s"
        )  # Use param
        return None
    except aiohttp.ClientResponseError as e:  # Catch HTTP errors
        logger.error(
            f"[AI3-Ollama] HTTP error from Ollama API: {e.message} "
            f"(Status code: {e.status})"
        )
        # logger.debug(f"Ollama error response: {await response.text() if response else 'N/A'}")
        return None
    except json.JSONDecodeError as e:  # Catch JSON parsing errors
        logger.error(f"[AI3-Ollama] Invalid JSON response from Ollama API: {e}")
        # logger.debug(f"Ollama non-JSON response: {await response.text() if response else 'N/A'}")
        return None
    except Exception as e:
        logger.error(
            f"[AI3-Ollama] Unexpected error calling Ollama: {e}", exc_info=True
        )
        return None


async def call_llm_provider(  # Generic LLM provider call
    provider_name: str,
    prompt: str,
    session: Optional[aiohttp.ClientSession] = None,  # Added session
    config: Optional[Dict] = None,  # Added config
    max_retries: int = 1,
    service_name: str = "ai3",  # For request delay
    **kwargs,
) -> Optional[str]:
    # ...
    # TODO: Implement or import apply_request_delay
    # await apply_request_delay(service_name)
    # ...
    if provider_instance:
        # ...
        if hasattr(provider_instance, "close_session") and callable(
            provider_instance.close_session
        ):
            await provider_instance.close_session()
    # ...


# ... (rest of the file with similar fixes for line lengths, etc.)
async def main(target: str, config_path: Optional[str] = None):
    logger.info(f"[AI3] Starting AI3 system with target: {target}")
    ai3 = None
    try:
        # Initialize aiohttp ClientSession
        client_session = aiohttp.ClientSession()

        # Create AI3 instance
        ai3 = AI3(target, config_path)
        ai3.client_session = client_session  # Set the client session explicitly

        # Set up the project structure
        await ai3.setup_structure()

        # Start monitoring tasks
        await ai3.start_monitoring()

        # Keep the system running
        await ai3.main_loop()
    except KeyboardInterrupt:
        logger.info("[AI3] Received keyboard interrupt. Shutting down gracefully.")
    except Exception as e:
        logger.critical(f"[AI3] Unhandled exception in main: {e}", exc_info=True)
        # TODO: Implement ai_comm
        # if ai3 and ai3.client_session and not ai3.client_session.closed:
        #     await ai3._report_status_to_mcp("critical_error_shutdown", {"error": str(e)}, ai3.mcp_api_url, ai3.client_session)

    finally:
        if ai3:
            await ai3.stop_monitoring()
            if ai3.client_session and not ai3.client_session.closed:
                await ai3.client_session.close()
                logger.info("[AI3] Closed aiohttp ClientSession.")
        logger.info("[AI3] AI3 system shutdown complete.")
        # sys.exit(1 if 'e' in locals() and isinstance(e, Exception) else 0) # Exit with error if exception occurred


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI3 - Structure generator and system monitor"
    )
    parser.add_argument(
        "--target", type=str, help="Target project description", default=None
    )
    parser.add_argument("--config", type=str, help="Path to config.json", default=None)
    args = parser.parse_args()

    # Get target from config if not specified via argument
    if args.target is None:
        try:
            config = load_config(args.config)
            args.target = config.get("target", "Create a modern web application")
            logger.info(
                f"[AI3] Target not specified, using from config: {args.target[:100]}..."
            )
        except Exception as e:
            logger.error(f"[AI3] Error loading target from config: {e}")
            logger.info("[AI3] Using default target")
            args.target = "Create a modern web application"

    try:
        asyncio.run(main(args.target, args.config))
        sys.exit(0)
    except Exception:  # Catch all exceptions from main to ensure sys.exit(1)
        # Logging of this exception should happen inside main() or AI3 methods
        sys.exit(1)

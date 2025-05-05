import asyncio
import json
import os
import time
import uuid

# from datetime import datetime # Removed unused import
from typing import Any, Dict, List, Optional, Union

import aiohttp

from config import load_config
from providers import BaseProvider, ProviderFactory  # Add the missing import
from utils import apply_request_delay, log_message

# Load configuration and set up logging
config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")


class AI1:
    """
    AI1 - Project Coordinator
    Formulates tasks for AI2 based on project structure and tracks progress
    """

    def __init__(self, target: str):
        self.target = target
        # Restore LLM initialization
        ai1_config_base = config.get("ai_config", {})
        ai1_config = ai1_config_base.get("ai1", {})
        if not ai1_config:
            log_message(
                "[AI1] Warning: 'ai_config.ai1' section not found in configuration. Using defaults."
            )
            ai1_config = {"providers": ["openai"]}  # Default provider list

        # Read the list of providers
        provider_names = ai1_config.get("providers", ["openai"])
        if not provider_names:
            log_message(
                "[AI1] Warning: No providers specified for AI1 in config. Defaulting to ['openai']"
            )
            provider_names = ["openai"]
        provider_name = provider_names[
            0
        ]  # Use the first provider from the list for AI1
        log_message(f"[AI1] Attempting to initialize provider: {provider_name}")

        # Load system prompt for LLM from configuration
        self.system_prompt = config.get(
            "ai1_prompt", "You are AI1, the project coordinator."
        )  # Default prompt
        log_message(f"[AI1] Loaded system prompt: {self.system_prompt[:100]}...")

        # System instructions that will be added to the base prompt
        self.system_instructions = " Use only Latin characters in your responses. Format your output as requested in specific prompts. Provide JSON when asked. Be precise and direct in your decisions."

        # Create LLM instance
        try:
            # Pass provider name and configuration for it
            provider_config = config.get("providers", {}).get(provider_name, {})
            full_ai1_config = {
                **provider_config,
                **ai1_config,
            }  # Merge general and specific configuration
            self.llm: BaseProvider = ProviderFactory.create_provider(
                provider_name, full_ai1_config
            )
            log_message(f"[AI1] Provider '{provider_name}' created successfully.")
        except ValueError as e:
            log_message(
                f"[AI1] CRITICAL ERROR: Failed to create provider '{provider_name}'. {e}. LLM features disabled."
            )
            self.llm = None  # Disable LLM if initialization failed
        except Exception as e:
            log_message(
                f"[AI1] CRITICAL ERROR: Unexpected error creating provider '{provider_name}'. {e}. LLM features disabled."
            )
            self.llm = None  # Disable LLM

        # Save LLM configuration for future use
        self.ai1_llm_config = ai1_config

        self.status = "initializing"
        self.project_structure: Optional[Dict] = None
        self.structure_fetch_attempted = False
        self.idea_content: Optional[str] = None  # Add this
        self.idea_md_path = "idea.md"  # Define path relative to repo root
        self.files_to_fill = []  # All files to be filled (complete list)
        self.pending_files_to_fill = []  # Files waiting to be tasked
        self.files_to_test = []  # All files to be tested (complete list)
        self.pending_files_to_test = []  # Files waiting to be tested
        self.files_to_document = []  # All files to be documented (complete list)
        self.pending_files_to_document = []  # Files waiting to be documented

        # Maximum number of concurrent tasks from configuration (default 10)
        self.max_concurrent_tasks = config.get("ai1_max_concurrent_tasks", 10)
        log_message(
            f"[AI1] Maximum concurrent tasks set to: {self.max_concurrent_tasks}"
        )

        # Task statuses: pending, sending, sent, code_received, fetch_failed,
        #                tested, accepted, review_needed, failed_tests,
        #                completed_by_ai2, failed_by_ai2, error_processing, skipped
        self.task_status: Dict[str, Dict[str, str]] = {}
        self.active_tasks = set()  # Stores "filename::role::subtask_id"
        self.api_session = None  # Initialize session

    async def _get_api_session(self) -> aiohttp.ClientSession:
        """Gets or creates the aiohttp session."""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session

    async def close_session(self):
        """Closes the aiohttp session."""
        if self.api_session and not self.api_session.closed:
            await self.api_session.close()
            log_message("[AI1] API session closed.")

    async def run(self):
        """Main work cycle of AI1"""
        log_message(f"[AI1] Started with target: {self.target}")
        self.status = "waiting_for_structure"

        try:
            # Fetch structure first
            await self.ensure_structure_received()
            if not self.project_structure:
                log_message("[AI1] Failed to obtain project structure. Exiting.")
                self.status = "error"
                return

            # Then fetch initial idea.md content
            await self._fetch_and_process_idea_md()
            # Optional: Exit if idea.md is crucial and fetch failed
            # if not self.idea_content:
            #     log_message("[AI1] Failed to obtain initial idea.md content. Exiting.")
            #     self.status = "error"
            #     return

            # Initialize statuses including the idea.md task
            self.initialize_task_status()
            self.status = "processing_tasks"

            while self.status == "processing_tasks":
                await self.manage_tasks()
                if self.check_completion():
                    self.status = "completed"
                    log_message("[AI1] All tasks completed. Project finished.")
                    break
                # Adjust sleep time as needed
                await asyncio.sleep(config.get("ai1_sleep_interval", 15))

        except Exception as e:
            log_message(f"[AI1] Unhandled exception in run loop: {e}")
            self.status = "error"
        finally:
            await self.close_session()  # Ensure session is closed on exit

    async def ensure_structure_received(self, timeout=300):
        """Attempts to retrieve the project structure from the API with retries."""
        if self.project_structure:
            return True

        log_message("[AI1] Attempting to fetch project structure...")
        start_time = asyncio.get_event_loop().time()
        session = await self._get_api_session()
        api_url = f"{MCP_API_URL}/structure"

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                async with session.get(api_url, timeout=30) as response:
                    if response.status == 200:
                        structure_data = await response.json()
                        if (
                            structure_data
                            and isinstance(structure_data.get("structure"), dict)
                            and structure_data["structure"]
                        ):
                            self.project_structure = structure_data["structure"]
                            log_message("[AI1] Structure received successfully.")
                            # Call process_structure HERE, before fetching idea.md
                            self.process_structure(self.project_structure)
                            return True  # Structure fetched, proceed to fetch idea.md
                        else:
                            log_message(
                                f"[AI1] Received invalid or empty structure data: {structure_data}. Retrying..."
                            )
                    elif response.status == 404:
                        log_message(
                            "[AI1] Structure not yet available from API (404). Retrying..."
                        )
                    else:
                        log_message(
                            f"[AI1] Failed to fetch structure. Status: {response.status}, Body: {await response.text()}. Retrying..."
                        )

            except asyncio.TimeoutError:
                log_message("[AI1] Timeout while fetching structure. Retrying...")
            except aiohttp.ClientError as e:
                log_message(f"[AI1] Error fetching structure: {str(e)}. Retrying...")
            except Exception as e:
                log_message(
                    f"[AI1] Unexpected error fetching structure: {str(e)}. Retrying..."
                )

            await asyncio.sleep(5)

        log_message(
            f"[AI1] Failed to obtain project structure after {timeout} seconds."
        )
        return False

    async def _fetch_and_process_idea_md(self):
        """Fetches the initial content of idea.md."""
        log_message(
            f"[AI1] Attempting to fetch initial content for: {self.idea_md_path}"
        )
        content = await self.get_file_content(self.idea_md_path)
        if content is not None:
            self.idea_content = content
            log_message(
                f"[AI1] Successfully fetched initial idea.md content (Length: {len(self.idea_content)})."
            )
        else:
            log_message(
                f"[AI1] Failed to fetch initial content for {self.idea_md_path}. Proceeding without it."
            )
            self.idea_content = None  # Ensure it's None if fetch failed

    def process_structure(self, structure_data):
        """Process project structure, identify files for tasks, including idea.md."""
        self.files_to_fill = self._extract_files(structure_data)
        # Ensure idea.md is not in the list extracted from structure if it's handled separately
        if self.idea_md_path in self.files_to_fill:
            self.files_to_fill.remove(self.idea_md_path)
            log_message(
                f"[AI1] Removed {self.idea_md_path} from files_to_fill as it's handled separately."
            )

        # Determine which files need testing based on extension
        testable_extensions = (
            ".py",
            ".js",
            ".ts",
            ".java",
            ".cpp",
            ".go",
            ".rs",
            ".php",
            ".html",
            ".css",
            ".scss",
            ".jsx",
            ".tsx",
            ".vue",
        )
        self.files_to_test = [
            f for f in self.files_to_fill if f.lower().endswith(testable_extensions)
        ]
        # Documentation list should include regular files + idea.md
        self.files_to_document = list(self.files_to_fill) + [self.idea_md_path]

        # Initialize pending lists
        self.pending_files_to_fill = list(self.files_to_fill)
        self.pending_files_to_test = list(self.files_to_test)
        # Add idea.md to the front of the documenter queue for priority
        self.pending_files_to_document = [self.idea_md_path] + list(self.files_to_fill)

        log_message(
            f"[AI1] Structure processed. Files to implement: {len(self.files_to_fill)}, Files to test: {len(self.files_to_test)}, Files to document (incl. idea.md): {len(self.files_to_document)}"
        )

    def _extract_files(self, node, current_path="") -> List[str]:
        """Recursively extracts all files from the JSON structure."""
        files = []
        if not isinstance(node, dict):
            return files

        for key, value in node.items():
            # Basic sanitization, might need refinement based on actual structure keys
            sanitized_key = (
                key.replace("..", "_").strip().replace(" ", "_")
            )  # Replace spaces too
            if not sanitized_key:
                continue

            new_path = (
                os.path.join(current_path, sanitized_key)
                if current_path
                else sanitized_key
            )

            if isinstance(value, dict):
                # It's a directory node, recurse
                files.extend(self._extract_files(value, new_path))
            elif value is None or isinstance(value, str):
                # It's a file node
                # Normalize path separators to forward slashes for consistency
                normalized_path = os.path.normpath(new_path).replace(os.sep, "/")

                # Remove potential project name prefix if structure includes it at the root
                # Assumes self.target is the root directory name used in the structure JSON
                if self.target and normalized_path.startswith(self.target + "/"):
                    normalized_path = normalized_path[len(self.target) + 1 :]

                # Avoid adding placeholder files like .gitkeep
                if os.path.basename(normalized_path) != ".gitkeep":
                    files.append(normalized_path)
            # else: handle other types if necessary
        return files

    def initialize_task_status(self):
        """Initializes task statuses, including the idea.md refinement task."""
        self.task_status = {}
        # Initialize status for regular files
        for file_path in self.files_to_fill:
            self.task_status[file_path] = {
                "executor": "pending",
                "tester": "pending" if file_path in self.files_to_test else "skipped",
                "documenter": "pending",
            }
        # Initialize status specifically for idea.md refinement
        # Check if idea.md path exists before adding
        if self.idea_md_path:  # Simple check if path is defined
            self.task_status[self.idea_md_path] = {
                "executor": "skipped",  # No execution needed
                "tester": "skipped",  # No testing needed
                "documenter": "pending",  # This represents the refinement task
            }
        else:
            log_message(
                "[AI1] Warning: idea_md_path is not defined, cannot initialize its task status."
            )

        log_message(
            f"[AI1] Task status initialized for {len(self.task_status)} files (including idea.md if applicable)."
        )

    async def get_file_content(self, file_path: str) -> Optional[str]:
        """Gets file content from the API, handling potential repo prefix."""
        api_url = f"{MCP_API_URL}/file_content"
        # Ensure the path sent to the API doesn't have an unexpected prefix like 'repo/'
        # Assuming file_path is relative to the repo root already
        params = {"path": file_path}
        log_message(f"[AI1] Attempting to fetch content for: {file_path}")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, params=params, timeout=45) as response:
                if response.status == 200:
                    content = await response.text()
                    log_message(
                        f"[AI1] Successfully fetched content for: {file_path} (Length: {len(content)})"
                    )
                    return content
                elif response.status == 404:
                    log_message(f"[AI1] File not found via API for: {file_path}")
                    return None
                else:
                    error_text = await response.text()
                    log_message(
                        f"[AI1] Failed to fetch content for {file_path}. Status: {response.status}, Response: {error_text}"
                    )
                    return None
        except asyncio.TimeoutError:
            log_message(f"[AI1] Timeout fetching content for: {file_path}")
            return None
        except aiohttp.ClientError as e:
            log_message(
                f"[AI1] Connection error fetching content for {file_path}: {str(e)}"
            )
            return None
        except Exception as e:
            log_message(
                f"[AI1] Unexpected error fetching content for {file_path}: {str(e)}"
            )
            return None

    async def get_task_status_from_api(self, subtask_id: str) -> Optional[str]:
        """Fetches the status of a specific subtask from the API."""
        api_url = f"{MCP_API_URL}/subtask_status/{subtask_id}"
        log_message(f"[AI1] Querying API for status of subtask: {subtask_id}")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    status = data.get("status")
                    log_message(f"[AI1] API status for {subtask_id}: {status}")
                    return status
                elif response.status == 404:
                    log_message(
                        f"[AI1] Subtask {subtask_id} not found in API status check."
                    )
                    return None  # Or maybe 'unknown'
                else:
                    log_message(
                        f"[AI1] Failed to get status for {subtask_id}. Status: {response.status}"
                    )
                    return None
        except asyncio.TimeoutError:
            log_message(f"[AI1] Timeout getting status for {subtask_id}")
            return None
        except aiohttp.ClientError as e:
            log_message(f"[AI1] Connection error getting status for {subtask_id}: {e}")
            return None
        except Exception as e:
            log_message(f"[AI1] Unexpected error getting status for {subtask_id}: {e}")
            return None

    async def get_all_task_statuses_from_api(self) -> Dict[str, str]:
        """Fetches all task statuses from the API."""
        api_url = f"{MCP_API_URL}/all_subtask_statuses"
        log_message("[AI1] Querying API for all subtask statuses...")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    log_message(f"[AI1] Received {len(data)} task statuses from API.")
                    return data
                else:
                    log_message(
                        f"[AI1] Failed to get all statuses. Status: {response.status}"
                    )
                    return {}
        except asyncio.TimeoutError:
            log_message("[AI1] Timeout getting all statuses.")
            return {}
        except aiohttp.ClientError as e:
            log_message(f"[AI1] Connection error getting all statuses: {e}")
            return {}
        except Exception as e:
            log_message(f"[AI1] Unexpected error getting all statuses: {e}")
            return {}

    async def update_local_task_statuses(self):
        """Updates the local task status dictionary based on API data."""
        api_statuses = await self.get_all_task_statuses_from_api()
        updated_count = 0
        if not api_statuses:
            log_message("[AI1] No statuses received from API to update local state.")
            return

        tasks_to_remove = set()
        final_states = [
            "accepted",
            "skipped",
            "failed_by_ai2",
            "error_processing",
            "review_needed",
            "failed_tests",
        ]

        # First, check for tasks that have been in code_received state for too long
        current_time = time.time()
        code_received_timeout = 300  # 5 minutes

        for task_key in list(self.active_tasks):  # Iterate over a copy
            try:
                filename, role, subtask_id = task_key.split("::")
                api_status = api_statuses.get(subtask_id)
                local_status = self.task_status.get(filename, {}).get(role)

                # If a task has been in code_received state for too long, force it to accepted state
                if local_status == "code_received" and role == "executor":
                    # Check if we've stored a timestamp for this task
                    if not hasattr(self, "_code_received_timestamps"):
                        self._code_received_timestamps = {}

                    if task_key not in self._code_received_timestamps:
                        self._code_received_timestamps[task_key] = current_time

                    time_in_state = (
                        current_time - self._code_received_timestamps[task_key]
                    )
                    if time_in_state > code_received_timeout:
                        log_message(
                            f"[AI1] Task {filename} ({role}) has been in code_received state for {time_in_state:.1f} seconds. Forcing transition to accepted."
                        )
                        self.task_status[filename][role] = "accepted"
                        updated_count += 1
                        # Remove from active tasks as it's now complete
                        tasks_to_remove.add(task_key)
                        # Remove timestamp entry
                        del self._code_received_timestamps[task_key]
                        continue

                if api_status:
                    if api_status != local_status:
                        log_message(
                            f"[AI1] Updating status for {filename} ({role}) from '{local_status}' to '{api_status}' (Subtask: {subtask_id})"
                        )
                        if (
                            filename in self.task_status
                            and role in self.task_status[filename]
                        ):
                            self.task_status[filename][role] = api_status
                            updated_count += 1
                        else:
                            log_message(
                                f"[AI1] Warning: Cannot update status for non-existent local task {filename} ({role})"
                            )

                    if api_status in final_states:
                        tasks_to_remove.add(task_key)
                else:
                    log_message(
                        f"[AI1] Warning: Active subtask {subtask_id} ({filename}::{role}) not found in API status response."
                    )
                    # Consider adding logic to remove stale tasks after a certain time/retries

            except ValueError:
                log_message(f"[AI1] Error parsing active task key: {task_key}")
                tasks_to_remove.add(task_key)
            except Exception as e:
                log_message(
                    f"[AI1] Error processing active task {task_key} during status update: {e}"
                )

        self.active_tasks -= tasks_to_remove
        log_message(
            f"[AI1] Local task statuses updated ({updated_count} changes). Active tasks remaining: {len(self.active_tasks)}"
        )

    async def _calculate_task_counts(self) -> tuple[int, int]:
        """Calculates the count of final and active tasks."""
        tasks_done_count = 0
        active_task_count = 0
        final_statuses = [
            "accepted",
            "skipped",
            "failed_by_ai2",
            "error_processing",
            "review_needed",
            "failed_tests",
            "failed_to_send",
        ]
        active_statuses = ["sending", "sent", "processing", "code_received", "tested"]
        current_active_tasks_details = []

        for file_path, statuses in self.task_status.items():
            for role, status in statuses.items():
                if status in final_statuses:
                    tasks_done_count += 1
                elif status in active_statuses:
                    active_task_count += 1
                    current_active_tasks_details.append(
                        f"{file_path} ({role}): {status}"
                    )

        log_message(f"[AI1] Calculated completed/final tasks: {tasks_done_count}")
        log_message(f"[AI1] Calculated active (in-progress) tasks: {active_task_count}")
        if current_active_tasks_details:
            log_message(
                f"[AI1] Active tasks list: {'; '.join(current_active_tasks_details)}"
            )

        return tasks_done_count, active_task_count

    async def _get_prioritized_roles(self) -> List[str]:
        """Gets prioritized roles, giving high priority to idea.md refinement if pending."""
        # Check if idea.md refinement is pending
        idea_refinement_pending = (
            self.task_status.get(self.idea_md_path, {}).get("documenter") == "pending"
        )

        if idea_refinement_pending:
            log_message("[AI1] Prioritizing 'documenter' role for idea.md refinement.")
            # Return documenter first, then default order for the rest
            default_order = ["executor", "tester", "documenter"]
            prioritized = ["documenter"] + [
                r for r in default_order if r != "documenter"
            ]
            return prioritized

        # If idea.md is done or not applicable, use LLM or default for other tasks
        if not self.llm or not (
            self.pending_files_to_fill
            or self.pending_files_to_test
            or self.pending_files_to_document
        ):
            return ["executor", "tester", "documenter"]  # Default order

        log_message(
            "[AI1] Requesting LLM for task prioritization (idea.md refinement done or not applicable)..."
        )
        try:
            status_summary = {}
            for statuses in self.task_status.values():
                for status in statuses.values():
                    status_summary[status] = status_summary.get(status, 0) + 1

            pending_summary = {
                "executor": len(self.pending_files_to_fill),
                "tester": len(self.pending_files_to_test),
                # Exclude idea.md from documenter count for LLM context
                "documenter": len(
                    [
                        f
                        for f in self.pending_files_to_document
                        if f != self.idea_md_path
                    ]
                ),
            }
            role_example_files = {
                "executor": self.pending_files_to_fill[:5],
                "tester": self.pending_files_to_test[:5],
                "documenter": [
                    f for f in self.pending_files_to_document if f != self.idea_md_path
                ][
                    :5
                ],  # Exclude idea.md
            }
            idea_status = self.task_status.get(self.idea_md_path, {}).get(
                "documenter", "unknown"
            )

            llm_prompt = f"""{{
"system_prompt": "{self.system_prompt}{self.system_instructions}",
"context": {{
    "project_target": "{self.target}",
    "pending_files": {json.dumps(pending_summary)},
    "example_files": {json.dumps(role_example_files)},
    "project_status": {json.dumps(status_summary)},
    "active_tasks": {len(self.active_tasks)},
    "idea_md_refinement_status": "{idea_status}"
}},
"request": "Given the current project state (idea.md refinement is {idea_status}), provide guidance on which type of tasks (executor, tester, documenter) for the *remaining code files* should be prioritized. Consider dependencies (executor -> tester -> documenter), critical files, and balanced progress. Respond with a JSON structure like: {{ \\"priorities\\": [\\"executor\\", \\"tester\\", \\"documenter\\"] }} listing roles in recommended priority order."
}}"""
            await apply_request_delay("ai1")
            llm_response = await self.llm.generate(
                prompt=llm_prompt,
                temperature=self.ai1_llm_config.get("temperature", 0.3),
                max_tokens=self.ai1_llm_config.get("max_tokens", 150),
            )

            if llm_response:
                import re

                # Try to extract JSON robustly
                json_match = re.search(
                    r"```(?:json)?\s*({.*?})\s*```", llm_response, re.DOTALL
                )
                if not json_match:
                    json_match = re.search(r"({.*?})", llm_response, re.DOTALL)

                if json_match:
                    try:
                        llm_json = json.loads(json_match.group(1))
                        prioritized_roles = llm_json.get("priorities", [])
                        if isinstance(prioritized_roles, list) and all(
                            isinstance(r, str) for r in prioritized_roles
                        ):
                            log_message(
                                f"[AI1] LLM recommended prioritization: {prioritized_roles}"
                            )
                            # Ensure all roles are present, append missing ones in default order
                            base_roles = ["executor", "tester", "documenter"]
                            final_roles = prioritized_roles + [
                                r for r in base_roles if r not in prioritized_roles
                            ]
                            return final_roles
                        else:
                            log_message(
                                f"[AI1] LLM returned invalid priorities format: {prioritized_roles}. Using default."
                            )
                    except json.JSONDecodeError as e:
                        log_message(
                            f"[AI1] JSON decode error from LLM prioritization response: {e}. Response: {llm_response}"
                        )
                else:
                    log_message(
                        f"[AI1] Could not find JSON in LLM response: {llm_response}. Using default."
                    )
            else:
                log_message(
                    "[AI1] Empty response from LLM for prioritization. Using default."
                )

        except Exception as e:
            log_message(f"[AI1] Error using LLM for prioritization: {e}")

        return ["executor", "tester", "documenter"]  # Default order on error

    async def _queue_tasks_for_role(
        self,
        role: str,
        pending_files: List[str],
        tasks_to_send: List[Dict],
        current_active_count: int,
        slots_filled_this_cycle: int,
        dynamic_max_concurrent: int,
    ) -> int:
        """Queues tasks for a specific role if slots are available, handling idea.md."""
        processed_files = []
        executor_done_statuses = [
            "code_received",
            "tested",
            "accepted",
            "completed_by_ai2",
            "review_needed",
            "failed_tests",
        ]

        for file_path in list(pending_files):  # Iterate over a copy
            if current_active_count + slots_filled_this_cycle >= dynamic_max_concurrent:
                log_message(
                    f"[AI1] {role.capitalize()} task for {file_path} skipped: dynamic concurrent task limit ({dynamic_max_concurrent}) reached."
                )
                break  # Stop queuing for this role if limit reached

            if file_path not in self.task_status:
                log_message(
                    f"[AI1] Warning: File {file_path} not found in task_status for role {role}. Skipping."
                )
                processed_files.append(file_path)  # Remove from pending if invalid
                continue

            file_statuses = self.task_status[file_path]

            # --- Handle idea.md refinement specifically ---
            if file_path == self.idea_md_path and role == "documenter":
                if file_statuses.get("documenter") == "pending":
                    if self.idea_content is not None:
                        task_text = f"Refine and add detail to the project description in {self.idea_md_path}. Focus on clarifying features, target audience, and technical considerations based on the project target: {self.target}. Ensure the output is well-structured markdown."
                        tasks_to_send.append(
                            {
                                "task_text": task_text,
                                "role": "documenter",  # Use documenter role
                                "filename": self.idea_md_path,
                                "code": self.idea_content,  # Provide current content
                            }
                        )
                        slots_filled_this_cycle += 1
                        processed_files.append(file_path)
                        log_message(
                            f"[AI1] Queued {role} task for {file_path} (Refinement). Cycle queue size: {len(tasks_to_send)}. Total active aim: {current_active_count + slots_filled_this_cycle}"
                        )
                    else:
                        log_message(
                            f"[AI1] Cannot queue refinement for {self.idea_md_path}: initial content not available. Skipping."
                        )
                        file_statuses["documenter"] = (
                            "fetch_failed"  # Or a specific skip status
                        )
                        processed_files.append(file_path)
                continue  # Move to the next file after handling idea.md

            # --- Handle regular files ---
            can_queue = False
            # Check dependencies and current status for regular files
            if role == "executor" and file_statuses.get("executor") == "pending":
                can_queue = True
            elif (
                role == "tester"
                and file_statuses.get("tester") == "pending"
                and file_statuses.get("executor") in executor_done_statuses
            ):
                can_queue = True
            elif (
                role == "documenter"
                and file_statuses.get("documenter") == "pending"
                and file_statuses.get("executor") in executor_done_statuses
            ):  # Assuming doc depends on executor completion
                can_queue = True

            if can_queue:
                code_content = None
                # Fetch content if needed (tester, documenter for regular files)
                if role != "executor":
                    code_content = await self.get_file_content(file_path)
                    if code_content is None:
                        log_message(
                            f"[AI1] Failed to fetch content for {file_path} for {role} task. Setting status to fetch_failed."
                        )
                        file_statuses[role] = "fetch_failed"
                        processed_files.append(file_path)
                        continue

                # --- Add idea.md context to task prompts for regular files ---
                idea_context_prompt = ""
                if self.idea_content:
                    # Limit length to avoid overly long prompts
                    idea_context_prompt = f"\n\nProject Description Context (from idea.md):\n---\n{self.idea_content[:1500]}...\n---\n"
                else:
                    idea_context_prompt = (
                        "\n\n(Project description from idea.md not available)\n"
                    )

                task_text = ""
                if role == "executor":
                    task_text = f"Implement the required functionality in file: {file_path} based on the overall project goal: {self.target}.{idea_context_prompt}Ensure the code aligns with the project description."
                elif role == "tester":
                    task_text = f"Generate unit tests for the code in file: {file_path}.{idea_context_prompt}Consider the project description when defining test cases."
                elif role == "documenter":
                    # This is for regular files, not idea.md refinement
                    task_text = f"Generate documentation (e.g., docstrings, comments) for the code in file: {file_path}.{idea_context_prompt}Ensure documentation reflects the project description."

                tasks_to_send.append(
                    {
                        "task_text": task_text,
                        "role": role,
                        "filename": file_path,
                        "code": code_content,
                    }
                )
                slots_filled_this_cycle += 1
                processed_files.append(file_path)
                log_message(
                    f"[AI1] Queued {role} task for {file_path}. Cycle queue size: {len(tasks_to_send)}. Total active aim: {current_active_count + slots_filled_this_cycle}"
                )

        # Remove processed files from the original pending list
        for file_path in processed_files:
            if file_path in pending_files:
                pending_files.remove(file_path)

        return slots_filled_this_cycle

    async def _send_queued_tasks(self, tasks_to_send: List[Dict]):
        """Sends the queued tasks to the API and updates statuses."""
        if not tasks_to_send:
            log_message("[AI1] No new tasks to send in this cycle.")
            return

        log_message(f"[AI1] Attempting to send {len(tasks_to_send)} new subtasks...")
        tasks_being_sent_keys = []
        for task_data in tasks_to_send:
            file_path = task_data["filename"]
            role = task_data["role"]
            if self.task_status.get(file_path, {}).get(role) == "pending":
                self.task_status[file_path][role] = "sending"
                tasks_being_sent_keys.append((file_path, role))
            else:
                log_message(
                    f"[AI1] Warning: Task {file_path} ({role}) status changed from 'pending' before sending. Skipping status update to 'sending'."
                )

        results = await asyncio.gather(
            *[self.create_subtask(**task_data) for task_data in tasks_to_send],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            task_data = tasks_to_send[i]
            file_path = task_data["filename"]
            role = task_data["role"]
            original_key = next(
                (
                    (fp, r)
                    for fp, r in tasks_being_sent_keys
                    if fp == file_path and r == role
                ),
                None,
            )
            subtask_id = result if isinstance(result, str) else None

            if isinstance(result, Exception) or result is False:
                error_msg = (
                    result if isinstance(result, Exception) else "API returned failure"
                )
                log_message(
                    f"[AI1] Failed to send subtask for {file_path} ({role}): {error_msg}"
                )
                if (
                    original_key
                    and self.task_status.get(file_path, {}).get(role) == "sending"
                ):
                    self.task_status[file_path][role] = "failed_to_send"
                    # Re-add to pending list
                    if (
                        role == "executor"
                        and file_path not in self.pending_files_to_fill
                    ):
                        self.pending_files_to_fill.append(file_path)
                    elif (
                        role == "tester" and file_path not in self.pending_files_to_test
                    ):
                        self.pending_files_to_test.append(file_path)
                    elif (
                        role == "documenter"
                        and file_path not in self.pending_files_to_document
                    ):
                        self.pending_files_to_document.append(file_path)
                # Remove potential active task entry (though unlikely for failed_to_send)
                task_key_to_remove = f"{file_path}::{role}::{subtask_id or 'unknown'}"
                self.active_tasks.discard(task_key_to_remove)

            elif subtask_id:
                log_message(
                    f"[AI1] Subtask {subtask_id} sent successfully for {file_path} ({role})."
                )
                if (
                    original_key
                    and self.task_status.get(file_path, {}).get(role) == "sending"
                ):
                    self.task_status[file_path][role] = "sent"
                    task_key = f"{file_path}::{role}::{subtask_id}"
                    self.active_tasks.add(task_key)
                else:
                    log_message(
                        f"[AI1] Warning: Subtask {subtask_id} sent, but local status for {file_path} ({role}) was not 'sending'. Current: {self.task_status.get(file_path, {}).get(role)}"
                    )

            else:
                log_message(
                    f"[AI1] Unexpected result after sending subtask for {file_path} ({role}): {result}"
                )
                if (
                    original_key
                    and self.task_status.get(file_path, {}).get(role) == "sending"
                ):
                    self.task_status[file_path][role] = "error_processing"
                task_key_to_remove = f"{file_path}::{role}::{subtask_id or 'unknown'}"
                self.active_tasks.discard(task_key_to_remove)

    async def _retry_failed_fetches(self):
        """Resets 'fetch_failed' statuses to 'pending' for retry."""
        for file_path, statuses in self.task_status.items():
            if statuses.get("tester") == "fetch_failed":
                log_message(f"[AI1] Retrying fetch for tester task: {file_path}")
                statuses["tester"] = "pending"
                if (
                    file_path not in self.pending_files_to_test
                    and file_path in self.files_to_test
                ):
                    self.pending_files_to_test.append(file_path)

            if statuses.get("documenter") == "fetch_failed":
                log_message(f"[AI1] Retrying fetch for documenter task: {file_path}")
                statuses["documenter"] = "pending"
                if file_path not in self.pending_files_to_document:
                    # Ensure we only add it back if it's supposed to be documented
                    if (
                        file_path == self.idea_md_path
                        or file_path in self.files_to_fill
                    ):
                        self.pending_files_to_document.append(file_path)

    async def _log_progress_and_sleep(
        self, tasks_done_count: int, active_task_count: int
    ):
        """Logs progress and determines sleep interval."""
        total_expected_tasks = sum(
            len(statuses) for statuses in self.task_status.values()
        )
        if total_expected_tasks > 0:
            progress_percent = (tasks_done_count / total_expected_tasks) * 100
            log_message(
                f"[AI1] Progress: {progress_percent:.2f}% ({tasks_done_count}/{total_expected_tasks} tasks in final state)"
            )
        else:
            log_message("[AI1] Progress: No tasks initialized yet.")

        sleep_interval = config.get("ai1_idle_sleep_interval", 15)  # Default idle
        if active_task_count > 0:
            sleep_interval = config.get("ai1_active_sleep_interval", 5)
        elif any(
            status == "pending"
            for roles in self.task_status.values()
            for status in roles.values()
        ):
            sleep_interval = config.get("ai1_pending_sleep_interval", 10)

        await asyncio.sleep(sleep_interval)

    async def manage_tasks(self):
        """Main task management logic: maintains a buffer of active tasks."""
        log_message("[AI1] Starting task management cycle...")

        await self.update_local_task_statuses()

        tasks_done_count, active_task_count = await self._calculate_task_counts()

        # Determine dynamic concurrency limit
        desired_active_buffer = config.get("ai1_desired_active_buffer", 10)
        try:
            desired_active_buffer = int(desired_active_buffer)
            if desired_active_buffer < 0:
                desired_active_buffer = 10
        except (ValueError, TypeError):
            log_message(
                f"[AI1] Warning: Invalid ai1_desired_active_buffer '{desired_active_buffer}'. Using 10."
            )
            desired_active_buffer = 10
        dynamic_max_concurrent = min(
            tasks_done_count + desired_active_buffer, self.max_concurrent_tasks
        )
        log_message(
            f"[AI1] Target concurrent tasks: {dynamic_max_concurrent} (Completed: {tasks_done_count} + Buffer: {desired_active_buffer}, Capped by Max: {self.max_concurrent_tasks})"
        )

        tasks_to_send = []
        slots_filled_this_cycle = 0

        # Get prioritized roles (potentially from LLM or based on idea.md status)
        prioritized_roles = await self._get_prioritized_roles()
        log_message(f"[AI1] Processing roles in order: {prioritized_roles}")

        # Queue tasks based on priority
        role_to_pending_list = {
            "executor": self.pending_files_to_fill,
            "tester": self.pending_files_to_test,
            "documenter": self.pending_files_to_document,
        }

        for role in prioritized_roles:
            if role in role_to_pending_list:
                pending_list = role_to_pending_list[role]
                slots_filled_this_cycle = await self._queue_tasks_for_role(
                    role,
                    pending_list,
                    tasks_to_send,
                    active_task_count,
                    slots_filled_this_cycle,
                    dynamic_max_concurrent,
                )
                # If we hit the limit while processing a role, stop queuing for subsequent roles in this cycle
                if (
                    active_task_count + slots_filled_this_cycle
                    >= dynamic_max_concurrent
                ):
                    log_message(
                        f"[AI1] Dynamic concurrent limit ({dynamic_max_concurrent}) reached during {role} queuing. Stopping for this cycle."
                    )
                    break

        # Send queued tasks
        await self._send_queued_tasks(tasks_to_send)

        # Retry failed fetches
        await self._retry_failed_fetches()

        # Log progress and sleep
        # Recalculate active_task_count after sending tasks might be more accurate for sleep interval decision
        _, current_active_count = await self._calculate_task_counts()
        await self._log_progress_and_sleep(tasks_done_count, current_active_count)

    async def create_subtask(
        self,
        task_text: str,
        role: str,
        filename: str,
        code: Optional[str] = None,
        is_rework: bool = False,
    ) -> Union[
        str, bool, Exception
    ]:  # Return subtask_id on success, False or Exception on failure
        """Create subtask via API, adding idea.md context if applicable."""
        api_url = f"{MCP_API_URL}/subtask"
        subtask_id = str(uuid.uuid4())

        # Add idea.md context consistently, except for the idea.md refinement task itself
        final_task_text = task_text
        if filename != self.idea_md_path:
            idea_context_prompt = ""
            if self.idea_content:
                idea_context_prompt = f"\n\nProject Description Context (from idea.md):\n---\n{self.idea_content[:1500]}...\n---\n"
            else:
                idea_context_prompt = (
                    "\n\n(Project description from idea.md not available)\n"
                )
            final_task_text += idea_context_prompt

        payload = {
            "subtask": {
                "id": subtask_id,
                "text": final_task_text,  # Use potentially modified task text
                "role": role,
                "filename": filename,
                "is_rework": is_rework,
            }
        }
        if code is not None:
            payload["subtask"]["code"] = code

        log_message(
            f"[AI1] Sending subtask: ID={subtask_id}, Role={role}, Filename={filename}, Is_rework={is_rework}{', Code included' if code is not None else ''}"
        )
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.post(api_url, json=payload, timeout=60) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if (
                        response_data.get("status") == "subtask received"
                        and response_data.get("id") == subtask_id
                    ):
                        log_message(
                            f"[AI1] Subtask {subtask_id} creation acknowledged by API for {filename} ({role})"
                        )
                        return subtask_id  # Return ID on success
                    else:
                        log_message(
                            f"[AI1] API acknowledged subtask for {filename} ({role}) but returned unexpected data: {response_data}"
                        )
                        return False
                else:
                    response_text = await response.text()
                    log_message(
                        f"[AI1] Failed to create subtask for {filename} ({role}). Status: {response.status}, Response: {response_text}"
                    )
                    return False
        except asyncio.TimeoutError as e:
            log_message(
                f"[AI1] Timeout error creating subtask {subtask_id} for {filename} ({role})."
            )
            return e  # Return exception
        except aiohttp.ClientError as e:
            log_message(
                f"[AI1] Connection error creating subtask {subtask_id} for {filename} ({role}): {str(e)}"
            )
            return e  # Return exception
        except Exception as e:
            log_message(
                f"[AI1] Unexpected error creating subtask {subtask_id} for {filename} ({role}): {str(e)}"
            )
            return e  # Return exception

    async def handle_test_result(self, test_recommendation: dict):
        """Handles test result recommendations from AI3."""
        recommendation = test_recommendation.get("recommendation")
        context = test_recommendation.get("context", {})

        if not recommendation:
            log_message("[AI1] Received empty recommendation from AI3. Ignoring.")
            return False

        log_message(f"[AI1] Received recommendation from AI3: {recommendation}")

        decision = await self.decide_on_test_results(recommendation, context)
        log_message(f"[AI1] Final decision on test results: {decision}")

        if decision == "accept":
            # Mark relevant files as accepted
            files_to_accept = set()
            if (
                "failed_files" in context
            ):  # Accept might come even with failed files if LLM overrides
                for test_file in context["failed_files"]:
                    original_file = self._get_original_file_from_test(test_file)
                    if original_file:
                        files_to_accept.add(original_file)
            else:  # If no failed_files, accept all that were 'tested'
                for file_path, statuses in self.task_status.items():
                    if statuses.get("tester") == "tested":
                        files_to_accept.add(file_path)

            for file_path in files_to_accept:
                if (
                    file_path in self.task_status
                    and self.task_status[file_path].get("tester") != "accepted"
                ):
                    self.task_status[file_path]["tester"] = "accepted"
                    log_message(f"[AI1] File {file_path} marked as accepted (testing).")
            return True

        elif decision == "rework":
            failed_files = context.get("failed_files", [])
            run_url = context.get("run_url", "")

            if not failed_files:
                log_message("[AI1] Rework recommended, but no failed files specified.")
                return False

            rework_tasks_created = 0
            for test_file in failed_files:
                original_file = self._get_original_file_from_test(test_file)
                if not original_file or original_file not in self.task_status:
                    log_message(
                        f"[AI1] Cannot determine or find original file for test {test_file}. Skipping rework."
                    )
                    continue

                # Check if already marked for manual review (due to exceeding limits)
                if (
                    self.task_status[original_file].get("tester") == "review_needed"
                    or self.task_status[original_file].get("executor")
                    == "review_needed"
                ):
                    log_message(
                        f"[AI1] Skipping rework for {original_file} as it's marked for manual review."
                    )
                    continue

                self.task_status[original_file][
                    "tester"
                ] = "failed_tests"  # Mark tester status

                test_content = await self.get_file_content(
                    test_file
                )  # Get test file content for context
                original_content = await self.get_file_content(original_file)

                if not original_content:  # Original content is crucial
                    log_message(
                        f"[AI1] Failed to get original content for {original_file}. Cannot create rework task."
                    )
                    continue

                # Construct rework task text
                task_text = (
                    f"Code in {original_file} failed tests. Fix the code based on test results.\n\n"
                    f"Test file: {test_file}\n"
                    f"GitHub Actions run: {run_url}\n\n"
                )
                if test_content:  # Add test content if available
                    task_text += f"Test file content snippet (may contain errors):\n```\n{test_content[:1000]}...\n```\n"  # Limit length
                task_text += (
                    "Please fix the code in the original file to pass the tests."
                )

                # Reset executor status and queue for rework
                self.task_status[original_file][
                    "executor"
                ] = "needs_rework"  # Specific status for rework
                if original_file not in self.pending_files_to_fill:
                    self.pending_files_to_fill.append(
                        original_file
                    )  # Add back to pending executor queue

                # Note: create_subtask will add the idea.md context automatically
                subtask_result = await self.create_subtask(
                    task_text=task_text,
                    role="executor",
                    filename=original_file,
                    code=original_content,  # Provide original code for context
                    is_rework=True,
                )

                if isinstance(subtask_result, str):  # Check if it's a subtask ID
                    log_message(
                        f"[AI1] Rework task created for {original_file}: {subtask_result}"
                    )
                    rework_tasks_created += 1
                else:
                    log_message(
                        f"[AI1] Failed to create rework task for {original_file}. Error: {subtask_result}"
                    )
                    # Consider reverting status if task creation failed?
                    self.task_status[original_file][
                        "executor"
                    ] = "failed_to_send_rework"  # Or similar error status

            return (
                rework_tasks_created > 0
            )  # Return True if at least one rework task was created

        elif decision == "manual_review":
            failed_files = context.get("failed_files", [])
            log_message(
                f"[AI1] Decision is manual_review. Marking relevant files: {failed_files}"
            )
            for test_file in failed_files:
                original_file = self._get_original_file_from_test(test_file)
                if original_file and original_file in self.task_status:
                    if self.task_status[original_file].get("tester") != "review_needed":
                        self.task_status[original_file]["tester"] = "review_needed"
                        log_message(
                            f"[AI1] Marked {original_file} (tester) for manual review."
                        )
                    if (
                        self.task_status[original_file].get("executor")
                        != "review_needed"
                    ):
                        self.task_status[original_file]["executor"] = "review_needed"
                        log_message(
                            f"[AI1] Marked {original_file} (executor) for manual review."
                        )
                    # Remove from pending queues if present
                    if original_file in self.pending_files_to_fill:
                        self.pending_files_to_fill.remove(original_file)
                    if original_file in self.pending_files_to_test:
                        self.pending_files_to_test.remove(original_file)
                    if original_file in self.pending_files_to_document:
                        self.pending_files_to_document.remove(original_file)
            return True  # Indicate the decision was processed

        else:
            log_message(
                f"[AI1] Unknown decision from decide_on_test_results: {decision}"
            )
            return False

    async def decide_on_test_results(self, recommendation: str, context: dict) -> str:
        """Makes the final decision on test results, potentially using LLM."""
        decision = recommendation  # Default to AI3's recommendation
        max_rework_attempts = config.get("ai1_max_rework_attempts", 3)
        exceeded_rework_limit = False

        log_message(
            f"[AI1] Analyzing recommendation '{recommendation}' with context: {context}"
        )

        # Check rework limits if recommendation is 'rework'
        if recommendation == "rework":
            original_failed_files = [
                self._get_original_file_from_test(f)
                for f in context.get("failed_files", [])
            ]
            original_failed_files = [
                f for f in original_failed_files if f and f in self.task_status
            ]  # Filter None and files not in status

            for file_path in original_failed_files:
                # Increment rework attempt counter
                rework_attempts = (
                    self.task_status[file_path].get("rework_attempts", 0) + 1
                )
                self.task_status[file_path]["rework_attempts"] = rework_attempts

                if rework_attempts > max_rework_attempts:
                    log_message(
                        f"[AI1] File {file_path} exceeded max rework attempts ({max_rework_attempts})."
                    )
                    exceeded_rework_limit = True
                    # Mark for manual review immediately
                    self.task_status[file_path]["tester"] = "review_needed"
                    if "executor" in self.task_status[file_path]:
                        self.task_status[file_path]["executor"] = "review_needed"
                    # Remove from pending queues
                    if file_path in self.pending_files_to_fill:
                        self.pending_files_to_fill.remove(file_path)
                    if file_path in self.pending_files_to_test:
                        self.pending_files_to_test.remove(file_path)
                    if file_path in self.pending_files_to_document:
                        self.pending_files_to_document.remove(file_path)

            if exceeded_rework_limit:
                decision = "manual_review"  # Override decision if limit exceeded
                log_message(
                    "[AI1] Changed decision to 'manual_review' due to exceeding rework limits."
                )

        # --- LLM Decision Override ---
        if self.llm:
            log_message("[AI1] Querying LLM for final decision on test results...")
            try:
                # Prepare context for LLM
                failed_files_str = ", ".join(context.get("failed_files", []))
                run_url = context.get("run_url", "N/A")
                original_files_context = [
                    self._get_original_file_from_test(f)
                    for f in context.get("failed_files", [])
                ]
                original_files_context = [
                    f for f in original_files_context if f
                ]  # Filter None

                rework_history_info = "".join(
                    [
                        f"  - {f}: {self.task_status[f].get('rework_attempts', 0)} attempts\\n"
                        for f in original_files_context
                        if f in self.task_status
                    ]
                )

                llm_prompt = f"""{{
    "system_prompt": "{self.system_prompt}{self.system_instructions}",
    "context": {{
        "project_target": "{self.target}",
        "ai3_recommendation": "{recommendation}",
        "algorithmic_decision_before_llm": "{decision}", # Inform LLM about the current algorithmic decision
        "failed_test_files": "{failed_files_str}",
        "original_code_files_potentially_needing_rework": "{', '.join(original_files_context)}",
        "github_actions_url": "{run_url}",
        "rework_history": "{rework_history_info.strip()}",
        "max_rework_attempts_allowed": {max_rework_attempts}
        # Consider adding log snippets or error summaries if available in context
    }},
    "request": "You are AI1, the project coordinator. Based on the test results and context (especially rework history and limits), make the final decision: 'accept' (accept code, potentially even with minor failures if justified), 'rework' (send back for fixes if attempts remain), or 'manual_review' (if rework limit exceeded or issues are complex). Respond ONLY with the single word: 'accept', 'rework', or 'manual_review'."
}}"""

                await apply_request_delay("ai1")
                llm_response = await self.llm.generate(
                    prompt=llm_prompt,
                    temperature=self.ai1_llm_config.get("temperature", 0.2),
                    max_tokens=self.ai1_llm_config.get(
                        "max_tokens", 20
                    ),  # Slightly increased
                )

                if llm_response:
                    llm_decision_raw = llm_response.strip().lower()
                    llm_final_decision = None
                    # Find the first valid decision word in the response
                    for valid_decision in ["accept", "rework", "manual_review"]:
                        if valid_decision in llm_decision_raw:
                            llm_final_decision = valid_decision
                            break

                    if llm_final_decision and llm_final_decision != decision:
                        log_message(
                            f"[AI1] LLM overrides decision from '{decision}' to '{llm_final_decision}'."
                        )
                        decision = llm_final_decision
                    elif llm_final_decision:
                        log_message(f"[AI1] LLM confirms decision: '{decision}'.")
                    else:
                        log_message(
                            f"[AI1] LLM response '{llm_decision_raw}' did not contain a valid decision word. Using algorithmic decision: '{decision}'."
                        )
                else:
                    log_message(
                        "[AI1] Empty response from LLM for decision making. Using algorithmic decision."
                    )

            except Exception as e:
                log_message(
                    f"[AI1] Error using LLM for decision making: {e}. Using algorithmic decision: '{decision}'."
                )

        return decision

    def _get_original_file_from_test(
        self, test_file: str
    ) -> Optional[str]:  # Updated return type hint
        """Determines the original file based on the test file name."""
        # Simple algorithm: remove 'test_' prefix or '_test' suffix
        dir_name = os.path.dirname(test_file)
        base_name = os.path.basename(test_file)
        original_name = None

        if base_name.startswith("test_"):
            original_name = base_name[5:]
        elif "_test." in base_name:
            original_name = base_name.replace("_test.", ".")
        # Add more specific patterns if needed, e.g., for different languages/frameworks
        elif base_name.endswith("_test.py"):
            original_name = base_name[:-8] + ".py"
        elif base_name.endswith("_test.js"):
            original_name = base_name[:-8] + ".js"
        # Add other extensions as needed...

        if not original_name:
            log_message(
                f"[AI1] Could not determine original filename pattern for test: {test_file}"
            )
            return None

        # Search for the original file in the known file list (self.files_to_fill)
        # This is more reliable than guessing paths
        possible_matches = []
        # Normalize expected path components for comparison
        normalized_original_name = os.path.normpath(original_name).replace(os.sep, "/")
        normalized_dir_name = os.path.normpath(dir_name).replace(os.sep, "/")

        for file_path in self.files_to_fill:
            # Normalize file_path for comparison
            normalized_file_path = os.path.normpath(file_path).replace(os.sep, "/")
            file_base_name = os.path.basename(normalized_file_path)
            file_dir_name = os.path.dirname(normalized_file_path)

            # Check 1: Exact match of basename and directory name
            if (
                file_base_name == normalized_original_name
                and file_dir_name == normalized_dir_name
            ):
                return file_path  # Best match

            # Check 2: Basename matches, directory might be slightly different (e.g., tests/ vs src/)
            if file_base_name == normalized_original_name:
                possible_matches.append(file_path)

        if len(possible_matches) == 1:
            log_message(
                f"[AI1] Found unique original file by basename match for {test_file}: {possible_matches[0]}"
            )
            return possible_matches[0]
        elif len(possible_matches) > 1:
            log_message(
                f"[AI1] Ambiguous original file match for {test_file}. Found: {possible_matches}. Returning first match."
            )
            return possible_matches[0]  # Or handle ambiguity differently
        else:
            log_message(
                f"[AI1] Original file not found in known structure for test: {test_file} (expected name: {original_name})"
            )
            return None  # Return None if no match found

    def check_completion(self) -> bool:
        """Checks if all tasks are in a final state ('accepted', 'skipped', or failed/review)."""
        if not self.task_status:
            log_message("[AI1] Task status not initialized, cannot check completion.")
            return False

        final_complete_statuses = ["accepted", "skipped"]
        final_failed_statuses = [
            "failed_by_ai2",
            "error_processing",
            "review_needed",
            "failed_tests",  # Added failed_tests as a final (though unsuccessful) state
            "failed_to_send",  # Added failed_to_send
            "fetch_failed",  # Added fetch_failed if we consider it final after retries
        ]

        for file_path, statuses in self.task_status.items():
            for role, status in statuses.items():
                if (
                    status not in final_complete_statuses
                    and status not in final_failed_statuses
                ):
                    # If any task is still pending, sending, sent, processing, etc., it's not complete
                    log_message(
                        f"[AI1] Completion check: Task {file_path} ({role}) is not final (Status: {status})."
                    )
                    return False
        log_message("[AI1] Completion check: All tasks are in a final state.")
        return True


class ProjectAnalyzer:
    """Analyzes project structure and requirements to generate optimal task sequence"""

    def __init__(self):
        self.context_history = []
        self.language_analyzers = {
            "python": self._analyze_python_project,
            "javascript": self._analyze_js_project,
            "typescript": self._analyze_ts_project,
            "go": self._analyze_go_project,
            "rust": self._analyze_rust_project,
            "java": self._analyze_java_project,
            "cpp": self._analyze_cpp_project,
        }
        self.framework_analyzers = {
            "django": self._analyze_django_project,
            "flask": self._analyze_flask_project,
            "fastapi": self._analyze_fastapi_project,
            "react": self._analyze_react_project,
            "vue": self._analyze_vue_project,
            "angular": self._analyze_angular_project,
            "next": self._analyze_next_project,
            "express": self._analyze_express_project,
            "spring": self._analyze_spring_project,
        }

    async def analyze_project(
        self, project_spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Analyze project specification and generate prioritized task list"""
        try:
            # Store project context
            self.context_history.append(
                {
                    "timestamp": time.time(),
                    "spec": project_spec,
                    "language_hints": self._detect_languages(project_spec),
                    "framework_hints": self._detect_frameworks(project_spec),
                }
            )

            tasks = []

            # Determine main language and framework
            main_language = self._determine_main_language(project_spec)
            main_framework = self._determine_main_framework(project_spec)

            # Get specialized analysis for language/framework
            if main_language and main_language in self.language_analyzers:
                language_tasks = await self.language_analyzers[main_language](
                    project_spec
                )
                tasks.extend(language_tasks)

            if main_framework and main_framework in self.framework_analyzers:
                framework_tasks = await self.framework_analyzers[main_framework](
                    project_spec
                )
                tasks.extend(framework_tasks)

            # Generate common tasks
            common_tasks = await self._generate_common_tasks(project_spec)
            tasks.extend(common_tasks)

            # Prioritize and order tasks
            ordered_tasks = self._prioritize_tasks(tasks, project_spec)

            return ordered_tasks

        except Exception as e:
            log_message(f"[ProjectAnalyzer] Error analyzing project: {e}")
            return []

    def _detect_languages(self, spec: Dict[str, Any]) -> List[str]:
        """Detect programming languages from project specification"""
        languages = set()

        # Check explicit language mentions
        if "languages" in spec:
            languages.update(lang.lower() for lang in spec["languages"])

        # Look for language-specific patterns in description
        description = spec.get("description", "").lower()
        patterns = {
            "python": ["python", "django", "flask", "fastapi", "pip"],
            "javascript": ["javascript", "js", "node", "npm", "yarn"],
            "typescript": ["typescript", "ts", "angular"],
            "go": ["golang", "go build"],
            "rust": ["rust", "cargo"],
            "java": ["java", "spring", "maven", "gradle"],
            "cpp": ["c++", "cpp", "cmake"],
        }

        for lang, keywords in patterns.items():
            if any(kw in description for kw in keywords):
                languages.add(lang)

        return list(languages)

    def _detect_frameworks(self, spec: Dict[str, Any]) -> List[str]:
        """Detect frameworks from project specification"""
        frameworks = set()

        # Check explicit framework mentions
        if "frameworks" in spec:
            frameworks.update(fw.lower() for fw in spec["frameworks"])

        # Look for framework-specific patterns
        description = spec.get("description", "").lower()
        patterns = {
            "django": ["django"],
            "flask": ["flask"],
            "fastapi": ["fastapi"],
            "react": ["react", "jsx", "tsx"],
            "vue": ["vue", "vuex", "nuxt"],
            "angular": ["angular", "ng"],
            "next": ["next.js", "nextjs"],
            "express": ["express", "expressjs"],
            "spring": ["spring boot", "spring framework"],
        }

        for framework, keywords in patterns.items():
            if any(kw in description for kw in keywords):
                frameworks.add(framework)

        return list(frameworks)

    def _determine_main_language(self, spec: Dict[str, Any]) -> Optional[str]:
        """Determine the main programming language for the project"""
        languages = self._detect_languages(spec)
        if not languages:
            return None

        # Use explicitly specified main language if available
        if "main_language" in spec:
            main = spec["main_language"].lower()
            if main in languages:
                return main

        # Otherwise use heuristics to determine main language
        language_scores = {}
        description = spec.get("description", "").lower()

        for lang in languages:
            score = 0
            # Check frequency of language mentions
            score += description.count(lang) * 2
            # Check for build/config files
            if lang == "python" and (
                "requirements.txt" in description or "setup.py" in description
            ):
                score += 3
            elif lang == "javascript" and (
                "package.json" in description or "webpack" in description
            ):
                score += 3
            elif lang == "typescript" and ("tsconfig" in description):
                score += 3
            # Add more language-specific scoring rules

            language_scores[lang] = score

        # Return language with highest score, or first language if tied
        return (
            max(language_scores.items(), key=lambda x: x[1])[0]
            if language_scores
            else None
        )

    def _determine_main_framework(self, spec: Dict[str, Any]) -> Optional[str]:
        """Determine the main framework for the project"""
        frameworks = self._detect_frameworks(spec)
        if not frameworks:
            return None

        # Use explicitly specified main framework if available
        if "main_framework" in spec:
            main = spec["main_framework"].lower()
            if main in frameworks:
                return main

        # Otherwise use heuristics to determine main framework
        framework_scores = {}
        description = spec.get("description", "").lower()

        for framework in frameworks:
            score = 0
            # Check frequency of framework mentions
            score += description.count(framework) * 2
            # Check for framework-specific patterns
            if framework == "django" and "models.py" in description:
                score += 3
            elif framework == "react" and (
                "jsx" in description or "tsx" in description
            ):
                score += 3
            elif framework == "vue" and "components/" in description:
                score += 3
            # Add more framework-specific scoring rules

            framework_scores[framework] = score

        # Return framework with highest score, or first framework if tied
        if not framework_scores:
            return None
        # Find the item (framework, score) with the highest score
        best_framework_item = max(framework_scores.items(), key=lambda item: item[1])
        # Return the framework name (the first element of the tuple)
        return best_framework_item[0]

    async def _analyze_python_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to Python projects"""
        tasks = []

        # Add Python-specific setup tasks
        tasks.append(
            {
                "type": "setup",
                "priority": 10,
                "description": "Set up Python virtual environment",
                "file": "requirements.txt",
                "dependencies": [],
            }
        )

        # Add core Python files
        tasks.append(
            {
                "type": "code",
                "priority": 8,
                "description": "Create main application entry point",
                "file": "main.py",
                "dependencies": ["requirements.txt"],
            }
        )

        # Add test configuration
        tasks.append(
            {
                "type": "test",
                "priority": 7,
                "description": "Set up pytest configuration",
                "file": "pytest.ini",
                "dependencies": ["requirements.txt"],
            }
        )

        # Add type hints if using Python 3
        tasks.append(
            {
                "type": "code",
                "priority": 6,
                "description": "Add type hints to core modules",
                "dependencies": ["main.py"],
            }
        )

        return tasks

    async def _analyze_js_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to JavaScript projects"""
        tasks = []

        # Add JavaScript-specific setup tasks
        tasks.append(
            {
                "type": "setup",
                "priority": 10,
                "description": "Initialize package.json and install dependencies",
                "file": "package.json",
                "dependencies": [],
            }
        )

        # Add core JS files
        tasks.append(
            {
                "type": "code",
                "priority": 8,
                "description": "Create main application entry point",
                "file": "index.js",
                "dependencies": ["package.json"],
            }
        )

        # Add test configuration
        tasks.append(
            {
                "type": "test",
                "priority": 7,
                "description": "Set up Jest configuration",
                "file": "jest.config.js",
                "dependencies": ["package.json"],
            }
        )

        return tasks

    async def _analyze_ts_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to TypeScript projects"""
        tasks = []

        # Add TypeScript-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": (
                        "Initialize package.json and install " "TypeScript dependencies"
                    ),
                    "file": "package.json",
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure TypeScript compiler options",
                    "file": "tsconfig.json",
                    "dependencies": ["package.json"],
                },
            ]
        )

        # Add core TS files
        tasks.append(
            {
                "type": "code",
                "priority": 8,
                "description": "Create main application entry point",
                "file": "index.ts",
                "dependencies": ["tsconfig.json"],
            }
        )

        return tasks

    async def _analyze_react_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to React projects"""
        tasks = []

        # Add React-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize React application with Create React App",
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure React testing library",
                    "dependencies": ["package.json"],
                },
            ]
        )

        # Add core React components
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create App component",
                    "file": "src/App.tsx",
                    "dependencies": ["package.json"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Set up routing configuration",
                    "file": "src/routes.tsx",
                    "dependencies": ["src/App.tsx"],
                },
            ]
        )

        return tasks

    async def _analyze_go_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to Go projects"""
        tasks = []

        # Add Go-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Go module",
                    "file": "go.mod",
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Create initial project structure",
                    "dependencies": ["go.mod"],
                },
            ]
        )

        # Add core Go files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create main package",
                    "file": "main.go",
                    "dependencies": ["go.mod"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Set up configuration package",
                    "file": "pkg/config/config.go",
                    "dependencies": ["main.go"],
                },
            ]
        )

        return tasks

    async def _analyze_rust_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to Rust projects"""
        tasks = []

        # Add Rust-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Cargo project",
                    "file": "Cargo.toml",
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure Rust edition and dependencies",
                    "dependencies": ["Cargo.toml"],
                },
            ]
        )

        # Add core Rust files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create lib.rs with core functionality",
                    "file": "src/lib.rs",
                    "dependencies": ["Cargo.toml"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create main.rs as entry point",
                    "file": "src/main.rs",
                    "dependencies": ["src/lib.rs"],
                },
            ]
        )

        return tasks

    async def _analyze_java_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to Java projects"""
        tasks = []

        # Add Java-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Maven or Gradle project",
                    "file": (
                        "pom.xml"
                        if "maven" in spec.get("description", "").lower()
                        else "build.gradle"
                    ),
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure Java version and dependencies",
                    "dependencies": [
                        (
                            "pom.xml"
                            if "maven" in spec.get("description", "").lower()
                            else "build.gradle"
                        )
                    ],
                },
            ]
        )

        # Add core Java files
        base_package = spec.get("package", "com.example.app").replace(".", "/")
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create main application class",
                    "file": f"src/main/java/{base_package}/Application.java",
                    "dependencies": [
                        (
                            "pom.xml"
                            if "maven" in spec.get("description", "").lower()
                            else "build.gradle"
                        )
                    ],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create configuration class",
                    "file": f"src/main/java/{base_package}/config/AppConfig.java",
                    "dependencies": [f"src/main/java/{base_package}/Application.java"],
                },
            ]
        )

        return tasks

    async def _analyze_cpp_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to C++ projects"""
        tasks = []

        # Add C++-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize CMake project",
                    "file": "CMakeLists.txt",
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure C++ standard and dependencies",
                    "dependencies": ["CMakeLists.txt"],
                },
            ]
        )

        # Add core C++ files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create main entry point",
                    "file": "src/main.cpp",
                    "dependencies": ["CMakeLists.txt"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create core utility header",
                    "file": "include/utils.hpp",
                    "dependencies": ["CMakeLists.txt"],
                },
            ]
        )

        return tasks

    async def _analyze_django_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to Django projects"""
        tasks = []

        project_name = spec.get("project_name", "djangoproject")

        # Add Django-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Django project",
                    "file": f"{project_name}/settings.py",
                    "dependencies": ["requirements.txt"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Create initial Django app",
                    "file": "app/models.py",
                    "dependencies": [f"{project_name}/settings.py"],
                },
            ]
        )

        # Add core Django files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Django models",
                    "file": "app/models.py",
                    "dependencies": [f"{project_name}/settings.py"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create Django views",
                    "file": "app/views.py",
                    "dependencies": ["app/models.py"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Configure Django URLs",
                    "file": "app/urls.py",
                    "dependencies": ["app/views.py"],
                },
            ]
        )

        return tasks

    async def _analyze_flask_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to Flask projects"""
        tasks = []

        # Add Flask-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Flask application",
                    "file": "app/__init__.py",
                    "dependencies": ["requirements.txt"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Create Flask configuration",
                    "file": "config.py",
                    "dependencies": ["app/__init__.py"],
                },
            ]
        )

        # Add core Flask files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Flask routes",
                    "file": "app/routes.py",
                    "dependencies": ["app/__init__.py"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create Flask models",
                    "file": "app/models.py",
                    "dependencies": ["app/__init__.py"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up Flask templates",
                    "file": "app/templates/index.html",
                    "dependencies": ["app/routes.py"],
                },
            ]
        )

        return tasks

    async def _analyze_fastapi_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to FastAPI projects"""
        tasks = []

        # Add FastAPI-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize FastAPI application",
                    "file": "app/main.py",
                    "dependencies": ["requirements.txt"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Create FastAPI configuration",
                    "file": "app/config.py",
                    "dependencies": ["app/main.py"],
                },
            ]
        )

        # Add core FastAPI files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Pydantic models",
                    "file": "app/models.py",
                    "dependencies": ["app/main.py"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create API routers",
                    "file": "app/routers/items.py",
                    "dependencies": ["app/models.py"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up database connection",
                    "file": "app/database.py",
                    "dependencies": ["app/main.py"],
                },
            ]
        )

        return tasks

    async def _analyze_next_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to Next.js projects"""
        tasks = []

        # Add Next.js-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Next.js application",
                    "file": "next.config.js",
                    "dependencies": ["package.json"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure TypeScript for Next.js",
                    "file": "tsconfig.json",
                    "dependencies": ["next.config.js"],
                },
            ]
        )

        # Add core Next.js files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Next.js pages",
                    "file": "pages/index.tsx",
                    "dependencies": ["next.config.js"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create API routes",
                    "file": "pages/api/hello.ts",
                    "dependencies": ["pages/index.tsx"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up components",
                    "file": "components/Layout.tsx",
                    "dependencies": ["pages/index.tsx"],
                },
            ]
        )

        return tasks

    async def _analyze_express_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to Express.js projects"""
        tasks = []

        # Add Express-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Express application",
                    "file": "app.js",
                    "dependencies": ["package.json"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure Express middleware",
                    "file": "middleware/index.js",
                    "dependencies": ["app.js"],
                },
            ]
        )

        # Add core Express files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Express routes",
                    "file": "routes/index.js",
                    "dependencies": ["app.js"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create Express controllers",
                    "file": "controllers/index.js",
                    "dependencies": ["routes/index.js"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up database models",
                    "file": "models/index.js",
                    "dependencies": ["app.js"],
                },
            ]
        )

        return tasks

    async def _analyze_vue_project(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate tasks specific to Vue.js projects"""
        tasks = []

        # Add Vue-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Vue application",
                    "file": "vue.config.js",
                    "dependencies": ["package.json"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure Vue router",
                    "file": "src/router/index.js",
                    "dependencies": ["vue.config.js"],
                },
            ]
        )

        # Add core Vue files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Vue components",
                    "file": "src/components/HelloWorld.vue",
                    "dependencies": ["vue.config.js"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create Vue views",
                    "file": "src/views/Home.vue",
                    "dependencies": ["src/components/HelloWorld.vue"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up Vuex store",
                    "file": "src/store/index.js",
                    "dependencies": ["src/views/Home.vue"],
                },
            ]
        )

        return tasks

    async def _analyze_angular_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to Angular projects"""
        tasks = []

        # Add Angular-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Angular application",
                    "file": "angular.json",
                    "dependencies": ["package.json"],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure TypeScript for Angular",
                    "file": "tsconfig.json",
                    "dependencies": ["angular.json"],
                },
            ]
        )

        # Add core Angular files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Angular components",
                    "file": "src/app/components/hello.component.ts",
                    "dependencies": ["angular.json"],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create Angular services",
                    "file": "src/app/services/data.service.ts",
                    "dependencies": ["src/app/components/hello.component.ts"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up Angular routing",
                    "file": "src/app/app-routing.module.ts",
                    "dependencies": ["src/app/components/hello.component.ts"],
                },
            ]
        )

        return tasks

    async def _analyze_spring_project(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate tasks specific to Spring Boot projects"""
        tasks = []

        base_package = spec.get("package", "com.example.demo").replace(".", "/")

        # Add Spring-specific setup tasks
        tasks.extend(
            [
                {
                    "type": "setup",
                    "priority": 10,
                    "description": "Initialize Spring Boot application",
                    "file": (
                        "pom.xml"
                        if "maven" in spec.get("description", "").lower()
                        else "build.gradle"
                    ),
                    "dependencies": [],
                },
                {
                    "type": "setup",
                    "priority": 9,
                    "description": "Configure Spring Boot properties",
                    "file": "src/main/resources/application.properties",
                    "dependencies": [
                        (
                            "pom.xml"
                            if "maven" in spec.get("description", "").lower()
                            else "build.gradle"
                        )
                    ],
                },
            ]
        )

        # Add core Spring files
        tasks.extend(
            [
                {
                    "type": "code",
                    "priority": 8,
                    "description": "Create Spring Boot main class",
                    "file": f"src/main/java/{base_package}/Application.java",
                    "dependencies": [
                        (
                            "pom.xml"
                            if "maven" in spec.get("description", "").lower()
                            else "build.gradle"
                        )
                    ],
                },
                {
                    "type": "code",
                    "priority": 7,
                    "description": "Create Spring Boot controllers",
                    "file": f"src/main/java/{base_package}/controller/MainController.java",
                    "dependencies": [f"src/main/java/{base_package}/Application.java"],
                },
                {
                    "type": "code",
                    "priority": 6,
                    "description": "Set up Spring Boot services",
                    "file": f"src/main/java/{base_package}/service/MainService.java",
                    "dependencies": [
                        f"src/main/java/{base_package}/controller/MainController.java"
                    ],
                },
            ]
        )

        return tasks

    async def _generate_common_tasks(
        self, spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate common tasks applicable to all projects"""
        tasks = []

        # Add documentation tasks
        tasks.extend(
            [
                {
                    "type": "doc",
                    "priority": 9,
                    "description": "Create main README.md",
                    "file": "README.md",
                    "dependencies": [],
                },
                {
                    "type": "doc",
                    "priority": 8,
                    "description": "Add API documentation",
                    "file": "docs/api.md",
                    "dependencies": ["README.md"],
                },
            ]
        )

        # Add testing tasks
        tasks.append(
            {
                "type": "test",
                "priority": 7,
                "description": "Set up continuous integration",
                "file": ".github/workflows/ci.yml",
                "dependencies": [],
            }
        )

        # Add deployment tasks
        tasks.append(
            {
                "type": "deploy",
                "priority": 5,
                "description": "Configure deployment pipeline",
                "file": "deploy/docker-compose.yml",
                "dependencies": [],
            }
        )

        return tasks

    def _prioritize_tasks(
        self, tasks: List[Dict[str, Any]], spec: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Prioritize and order tasks based on dependencies and importance"""
        # Build dependency graph
        graph = {}
        for task in tasks:
            task_id = task.get("file", task["description"])
            graph[task_id] = {
                "task": task,
                "dependencies": task["dependencies"],
                "dependents": set(),
            }

        # Add reverse dependencies
        for task_id, node in graph.items():
            for dep in node["dependencies"]:
                if dep in graph:
                    graph[dep]["dependents"].add(task_id)

        # Calculate priority scores
        scores = {}
        for task_id, node in graph.items():
            base_priority = node["task"]["priority"]
            dep_count = len(node["dependencies"])
            dependent_count = len(node["dependents"])

            # Priority formula: base_priority + (dependent_count * 2) - (dep_count * 1)
            scores[task_id] = base_priority + (dependent_count * 2) - dep_count

        # Sort tasks by score (highest first)
        ordered_tasks = []
        visited = set()

        def visit(task_id):
            if task_id in visited:
                return
            visited.add(task_id)

            # Visit dependencies first
            for dep in graph[task_id]["dependencies"]:
                if dep in graph:
                    visit(dep)

            ordered_tasks.append(graph[task_id]["task"])

        # Visit tasks in order of priority score
        sorted_tasks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for task_id, _ in sorted_tasks:
            visit(task_id)

        return ordered_tasks


async def main():
    target = config.get("target")
    if not target:
        print("CRITICAL: 'target' not found in config.json. Exiting.")
        return

    ai1 = AI1(target)
    try:
        await ai1.run()
    except SystemExit as e:
        print(f"AI1 exited prematurely: {e}")
        raise  # Reraise SystemExit to ensure the program exits
    except Exception as e:
        print(f"An unexpected error occurred in AI1 main loop: {e}")


if __name__ == "__main__":
    asyncio.run(main())

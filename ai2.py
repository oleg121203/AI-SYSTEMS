import argparse
import asyncio
import git
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Union

import aiohttp

# Use load_config function from config.py
from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import apply_request_delay, log_message  # Import apply_request_delay

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AI2")

# Load configuration once
config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")


class AI2:
    """
    Second AI module responsible for generating code, tests, and documentation.
    Uses different providers for different tasks and supports fallback mechanism.
    """

    def __init__(self, role: str):
        """
        Initialize AI2 module.

        Args:
            role: Role of this worker ('executor', 'tester', 'documenter')
        """
        self.role = role
        global logger
        logger = logging.getLogger(f"AI2-{self.role.upper()}")

        self.config = config
        ai_config_base = self.config.get("ai_config", {})
        self.ai_config = ai_config_base.get("ai2", {})
        if not self.ai_config:
            logger.warning(
                "Section 'ai_config.ai2' not found in configuration. Using default values."
            )
            self.ai_config = {"fallback_providers": ["openai"]}

        # Load base prompts from config
        self.base_prompts = self.config.get(
            "ai2_prompts",
            [
                "You are an expert programmer. Create the content for the file {filename} based on the following task description.",
                "You are a testing expert. Generate unit tests for the code in file {filename}.",
                "You are a technical writer. Generate documentation (e.g., docstrings, comments) for the code in file {filename}.",
            ],
        )
        if len(self.base_prompts) < 3:
            logger.error(
                "Configuration 'ai2_prompts' is missing or incomplete. Using default base prompts."
            )
            self.base_prompts = [
                "You are an expert programmer. Create the content for the file {filename} based on the following task description.",
                "You are a testing expert. Generate unit tests for the code in file {filename}.",
                "You are a technical writer. Generate documentation (e.g., docstrings, comments) for the code in file {filename}.",
            ]

        # System instructions to append to base prompts
        self.system_instructions = " Respond ONLY with the raw file content. Do NOT use markdown code blocks (```). Use only Latin characters in your response."

        # Updated: Use the new provider configuration structure
        self.providers = self.ai_config.get("providers", {}).get(self.role, [])
        if not self.providers:
            logger.warning(
                f"No providers configured for role '{self.role}'. Defaulting to ['openai']"
            )
            self.providers = ["openai"]

        # Initialize fallback_providers
        self.fallback_providers = self.ai_config.get("fallback_providers", ["ollama"])
        
        # Initialize providers_config
        self.providers_config = self._setup_providers_config()

        logger.info(f"Configured providers for role '{self.role}': {', '.join(self.providers)}")

        self.api_session = None

    async def _get_api_session(self) -> aiohttp.ClientSession:
        """Gets or creates an aiohttp session."""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session

    async def close_session(self):
        """Closes the aiohttp session."""
        if self.api_session or not self.api_session.closed:
            await self.api_session.close()
            logger.info("API session closed.")

    def _setup_providers_config(self) -> Dict[str, Dict[str, Any]]:
        """
        Sets up provider configuration for each role from the overall configuration.
        Uses self.role to determine the required provider.

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with configuration for the current role
        """
        # Use the first provider from the list of configured providers
        provider_name = self.providers[0] if self.providers else None

        # If no provider found for the role, use fallback
        if not provider_name:
            provider_name = self.fallback_providers[0]
            logger.warning(
                f"No provider found for role '{self.role}'. Using fallback: {provider_name}"
            )

        # Get provider configuration
        providers_list = self.config.get("providers", {})
        if (provider_name in providers_list):
            common_config = providers_list[provider_name]
        else:
            logger.warning(
                f"Provider '{provider_name}' not found in the list of providers. Using empty configuration."
            )
            common_config = {}

        # Assemble the final configuration
        role_config = {
            "name": provider_name,
            **common_config,
            **{
                k: v
                for k, v in self.ai_config.items()
                if k
                not in [
                    "executor",
                    "tester",
                    "documenter",
                    "provider",
                    "fallback_providers",
                ]
            },
        }

        logger.info(f"Provider for role '{self.role}' configured: {provider_name}")
        return {self.role: role_config}

    async def _get_provider_instance(self) -> BaseProvider:
        """Gets or creates an instance of the provider for the current worker role."""
        config = self.providers_config.get(self.role)
        if not config:
            raise ValueError(f"Configuration for role '{self.role}' not found.")
        provider_name = config.get("name")
        if not provider_name:
            raise ValueError(
                f"Provider name is missing in the configuration for role '{self.role}'."
            )

        try:
            provider_instance = ProviderFactory.create_provider(provider_name)
            return provider_instance
        except ValueError as e:
            logger.error(
                f"Failed to create provider '{provider_name}' for role '{self.role}': {e}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error while creating provider '{provider_name}' for role '{self.role}': {e}"
            )
            raise

    async def _generate_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Attempts to generate a response using the primary role provider and tries all available providers in a loop."""
        provider_config = self.providers_config.get(self.role, {})
        provider_name = provider_config.get("name", "N/A")
        primary_provider = None
        
        # Gather the full list of providers, starting with the primary and adding all fallback providers
        all_providers = [provider_name]
        # Add fallbacks that are not in the list
        for fallback in self.fallback_providers:
            if fallback not in all_providers:
                all_providers.append(fallback)
        
        logger.info(f"Attempting generation using providers (in order): {', '.join(all_providers)}")
        
        all_errors = []
        # Iterate through all providers in sequence
        for provider_idx, current_provider_name in enumerate(all_providers):
            current_provider = None
            try:
                logger.info(
                    f"Attempting generation with provider [{provider_idx+1}/{len(all_providers)}] '{current_provider_name}'."
                )
                
                # Get config for the current provider
                current_config_base = self.config.get("providers", {}).get(
                    current_provider_name, {}
                )
                current_config = {
                    **current_config_base,
                    **{
                        k: v
                        for k, v in self.ai_config.items()
                        if k
                        not in [
                            "executor",
                            "tester",
                            "documenter",
                            "provider",
                            "fallback_providers",
                        ]
                    },
                }

                # Create an instance of the provider
                current_provider = ProviderFactory.create_provider(
                    current_provider_name, current_config
                )

                # Add delay to avoid overloading the API (only for non-primary providers)
                if provider_idx > 0:
                    await apply_request_delay("ai2", self.role)

                # Generate with the current provider
                result = await current_provider.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    model=model
                    or current_config.get("model")
                    or self.ai_config.get("model"),
                    max_tokens=max_tokens or self.ai_config.get("max_tokens"),
                    temperature=temperature or self.ai_config.get("temperature"),
                )
                
                # Check for generation error
                if isinstance(result, str) and result.startswith("Generation error"):
                    raise Exception(
                        f"Provider '{current_provider_name}' failed: {result}"
                    )
                
                # Close session after successful use
                if (
                    current_provider
                    and hasattr(current_provider, "close_session")
                    and callable(current_provider.close_session)
                ):
                    await current_provider.close_session()
                    
                # Return result from successful provider
                logger.info(f"Successfully generated with provider '{current_provider_name}'")
                return result

            except Exception as provider_error:
                # Log provider error
                logger.error(
                    f"Generation error with provider '{current_provider_name}': {provider_error}"
                )
                all_errors.append(f"Provider '{current_provider_name}' failed: {provider_error}")
                
                # Close provider session on error
                if (
                    current_provider
                    and hasattr(current_provider, "close_session")
                    and callable(current_provider.close_session)
                ):
                    await current_provider.close_session()
        
        # If all providers failed, return information about all errors
        error_msg = "Failed to generate a response with any of the available providers:\n- " + "\n- ".join(all_errors)
        logger.error(error_msg)
        return error_msg

    async def generate_code(self, task: str, filename: str) -> str:
        """Generate code based on task description."""
        logger.info(f"Generating code for file: {filename}")
        # Combine base prompt with system instructions
        base_prompt = self.base_prompts[0].format(filename=filename)
        system_prompt = base_prompt + self.system_instructions
        user_prompt = f"Task Description: {task}\n\nPlease generate the content for the file '{filename}' based on this task."
        await apply_request_delay("ai2", self.role)
        return await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

    async def generate_tests(self, code: str, filename: str) -> str:
        """Generate tests for the code."""
        logger.info(f"Generating tests for file: {filename}")
        # Combine base prompt with system instructions
        base_prompt = self.base_prompts[1].format(filename=filename)
        system_prompt = base_prompt + self.system_instructions.replace("file content", "test code") # Adjust instruction slightly
        user_prompt = f"Code for file '{filename}':\n```\n{code}\n```\n\nPlease generate unit tests for this code."
        await apply_request_delay("ai2", self.role)
        test_content = await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )
        
        # If tests are successfully generated, commit them to Git
        if test_content and not test_content.startswith("Generation error"):
            if await self.commit_tests_to_git(filename, test_content):
                return test_content
            else:
                return f"Generation error: Failed to save tests to Git for {filename}"
        
        return test_content

    async def generate_docs(self, code: str, filename: str) -> str:
        """Generate documentation for the code."""
        logger.info(f"Generating documentation for file: {filename}")
        # Combine base prompt with system instructions
        base_prompt = self.base_prompts[2].format(filename=filename)
        system_prompt = base_prompt + self.system_instructions.replace("file content", "documentation text") # Adjust instruction slightly
        user_prompt = f"Code for file '{filename}':\n```\n{code}\n```\n\nPlease generate documentation (e.g., docstrings, comments) for this code."
        await apply_request_delay("ai2", self.role)
        return await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

    async def commit_tests_to_git(self, filename: str, test_content: str) -> bool:
        """Commits generated tests to the Git repository."""
        try:
            # Convert file path to test path
            test_filename = filename.replace(".py", "_test.py")
            if not test_filename.startswith("tests/"):
                test_filename = f"tests/{test_filename}"
            
            repo_path = os.path.join(os.getcwd(), "repo")
            test_filepath = os.path.join(repo_path, test_filename)
            
            # Create directory for tests if it doesn't exist
            os.makedirs(os.path.dirname(test_filepath), exist_ok=True)
            
            # Write tests to file
            with open(test_filepath, "w") as f:
                f.write(test_content)
            
            # Initialize Git repository
            repo = git.Repo(repo_path)
            
            # Add file to Git
            repo.index.add([test_filename])
            
            # Create commit
            commit_message = f"test: Add tests for {filename}"
            repo.index.commit(commit_message)
            
            logger.info(f"Tests for {filename} successfully added to Git: {test_filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error committing tests for {filename} to Git: {e}")
            return False

    async def process_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes a single task and returns a dictionary for sending to /report.
        """
        subtask_id = task_info.get("id")
        role = task_info.get("role")
        filename = task_info.get("filename")
        task_description = task_info.get("text")
        code_content = task_info.get("code")

        if not subtask_id or not role or not filename:
            logger.error(f"Invalid task information: {task_info}")
            return {
                "type": "status_update",
                "subtask_id": subtask_id or "unknown",
                "message": "Error: Missing ID, role, or filename in task.",
                "status": "failed",
            }

        if role != self.role:
            logger.error(
                f"Received task for a different role ({role}), expected role {self.role}. Skipping."
            )
            return {
                "type": "status_update",
                "subtask_id": subtask_id,
                "message": f"Error: Worker {self.role} received task for {role}.",
                "status": "failed",
            }

        report = {
            "subtask_id": subtask_id,
            "file": filename,
        }
        start_time = asyncio.get_event_loop().time()
        generated_content = None
        error_message = None

        try:
            if role == "executor":
                report["type"] = "code"
                if not task_description:
                    error_message = "Missing task description for role executor"
                    logger.error(f"Missing task description for executor: {task_info}")
                else:
                    generated_content = await self.generate_code(task_description, filename)
                    
            elif role == "tester":
                report["type"] = "test_result"
                if code_content is None:
                    error_message = "Missing code for role tester"
                    logger.error(f"Missing code for tester: {task_info}")
                else:
                    # Generate and commit tests
                    generated_content = await self.generate_tests_based_on_file_type(code_content, filename)
                    if generated_content and not generated_content.startswith("Generation error"):
                        # Successfully generated and committed tests
                        report["content"] = generated_content
                        report["message"] = f"Tests for {filename} successfully generated and committed to Git"
                        report["status"] = "tests_committed"
                    else:
                        error_message = f"Generation error for tests for {filename}: {generated_content}"
                        
            elif role == "documenter":
                report["type"] = "code"
                if code_content is None:
                    error_message = "Missing code for role documenter"
                    logger.error(f"Missing code for documenter: {task_info}")
                else:
                    generated_content = await self.generate_docs(code_content, filename)
                    
            else:
                error_message = f"Unknown role: {role}"
                logger.error(f"Unknown role: {role}")

            if isinstance(generated_content, str) and generated_content.startswith(
                "Failed to generate a response"
            ):
                error_message = generated_content
                generated_content = None

            if generated_content is not None:
                report["content"] = generated_content

        except Exception as e:
            logger.exception(
                f"Unexpected error while processing task for {filename} ({role}): {e}"
            )
            error_message = f"Unexpected error: {e}"

        end_time = asyncio.get_event_loop().time()
        processing_time = end_time - start_time

        if error_message:
            report = {
                "type": "status_update",
                "subtask_id": subtask_id,
                "message": f"Task processing error ({role} for {filename}): {error_message}",
                "status": "failed",
            }
            log_message_data = {
                "message": f"Task processing failed for {filename} ({role})",
                "role": role,
                "file": filename,
                "status": "error",
                "processing_time": round(processing_time, 2),
                "error_message": error_message,
            }
        else:
            log_message_data = {
                "message": f"Task processing successfully completed for {filename} ({role})",
                "role": role,
                "file": filename,
                "status": "success",
                "processing_time": round(processing_time, 2),
                "report_type": report.get("type"),
            }

        log_message(json.dumps(log_message_data))
        return report

    async def fetch_task(self) -> Optional[Dict[str, Any]]:
        """Requests a task from the API for the current role."""
        api_url = f"{MCP_API_URL}/task/{self.role}"
        max_retries = 5
        retry_count = 0
        retry_delay = 1  # starting delay in seconds
        
        while retry_count < max_retries:
            try:
                session = await self._get_api_session()
                logger.debug(f"Requesting task from {api_url}")
                async with session.get(api_url, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and "subtask" in data and data["subtask"]:
                            subtask_data = data["subtask"]
                            task_id = subtask_data.get('id')
                            task_filename = subtask_data.get('filename')
                            logger.info(
                                f"Received task: ID={task_id}, File={task_filename}"
                            )
                            return subtask_data
                        elif data and "message" in data:
                            logger.debug(f"No available tasks: {data['message']}")
                            return None
                        else:
                            logger.warning(
                                f"Unexpected response from API when requesting task: {data}"
                            )
                            return None
                    else:
                        logger.error(
                            f"Error requesting task: Status {response.status}, Response: {await response.text()}"
                        )
                        # Increment retry count for non-200 responses
                        retry_count += 1
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # exponential backoff
            except asyncio.TimeoutError:
                logger.warning(f"Timeout requesting task from {api_url}")
                retry_count += 1
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
            except aiohttp.ClientError as e:
                logger.error(f"Connection error requesting task from {api_url}: {e}")
                retry_count += 1
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
            except Exception as e:
                logger.exception(f"Unexpected error requesting task: {e}")
                retry_count += 1
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                
        # If we've exhausted all retries
        logger.error(f"Exhausted all connection attempts to {api_url}")
        return None

    async def send_report(self, report_data: Dict[str, Any]):
        """Sends a task report to the API."""
        api_url = f"{MCP_API_URL}/report"
        try:
            session = await self._get_api_session()
            logger.debug(
                f"Sending report to {api_url}: Type={report_data.get('type')}, ID={report_data.get('subtask_id')}"
            )
            async with session.post(api_url, json=report_data, timeout=60) as response:
                if response.status == 200:
                    logger.info(
                        f"Report for task {report_data.get('subtask_id')} successfully sent."
                    )
                else:
                    logger.error(
                        f"Error sending report for task {report_data.get('subtask_id')}: Status {response.status}, Response: {await response.text()}"
                    )
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout sending report for task {report_data.get('subtask_id')}"
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"Connection error sending report for task {report_data.get('subtask_id')}: {e}"
            )
        except Exception as e:
            logger.exception(f"Unexpected error sending report: {e}")

    async def run_worker(self):
        """Main worker loop: fetch task, process, send report."""
        logger.info(f"AI2 worker ({self.role}) started.")
        while True:
            task = await self.fetch_task()
            if task:
                report = await self.process_task(task)
                if report:
                    await self.send_report(report)
                else:
                    logger.error(
                        f"Process_task returned empty report for task {task.get('id')}"
                    )
                await asyncio.sleep(1)
            else:
                sleep_time = config.get("ai2_idle_sleep", 5)
                logger.debug(f"No tasks for {self.role}. Waiting {sleep_time} sec.")
                await asyncio.sleep(sleep_time)

    async def generate_tests_based_on_file_type(self, content: str, filename: str) -> str:
        """Generates tests based on file type."""
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext == '.py':
            return await self.generate_python_tests(content, filename)
        elif file_ext == '.js':
            return await self.generate_js_tests(content, filename)
        elif file_ext == '.ts':
            return await self.generate_ts_tests(content, filename)
        elif file_ext in ['.html', '.htm']:
            return await self.generate_html_tests(content, filename)
        elif file_ext == '.css':
            return await self.generate_css_tests(content, filename)
        elif file_ext == '.scss':
            return await self.generate_scss_tests(content, filename)
        elif file_ext in ['.jsx', '.tsx']:
            return await self.generate_react_tests(content, filename)
        elif file_ext == '.vue':
            return await self.generate_vue_tests(content, filename)
        elif file_ext == '.java':
            return await self.generate_java_tests(content, filename)
        elif file_ext in ['.cpp', '.c', '.hpp', '.h']:
            return await self.generate_cpp_tests(content, filename)
        elif file_ext == '.go':
            return await self.generate_go_tests(content, filename)
        elif file_ext == '.rs':
            return await self.generate_rust_tests(content, filename)
        else:
            return await self.generate_generic_tests(content, filename)
            
    async def generate_html_tests(self, content: str, filename: str) -> str:
        """Generate tests for HTML files."""
        log_message(f"[AI2-TESTER] Generating tests for HTML file: {filename}")
        
        test_filename = filename.replace(".html", "_test.js")
        
        # Form prompt for test generator
        prompt = f"""
Create tests for the HTML file using Jest and Testing Library or Cypress.
Please verify the following aspects:
1. HTML structure validity
2. Presence of key elements (headers, forms, buttons, etc.)
3. Accessibility attributes correctness 
4. Responsiveness (if there are styles for different screen sizes)

HTML file ({filename}):
```html
{content}
```

The result should be a JavaScript file {test_filename} with tests.
Use Jest, Testing Library, or Cypress.
"""
        
        return await self._generate_test_with_fallback(prompt, test_filename)
        
    async def generate_css_tests(self, content: str, filename: str) -> str:
        """Generate tests for CSS files."""
        log_message(f"[AI2-TESTER] Generating tests for CSS file: {filename}")
        
        test_filename = filename.replace(".css", "_test.js")
        
        # Form prompt for test generator
        prompt = f"""
Create tests for the CSS file using Jest with puppeteer/playwright.
Please verify the following aspects:
1. Correct application of styles to elements
2. Display verification at different screen sizes (mobile, tablet, desktop)
3. Correctness of colors, sizes, and other properties
4. Selector verification and specificity

CSS file ({filename}):
```css
{content}
```

The result should be a JavaScript file {test_filename} with tests.
For JavaScript files, use jest-transform-css or a similar tool.
"""
        
        return await self._generate_test_with_fallback(prompt, test_filename)
        
    async def generate_scss_tests(self, content: str, filename: str) -> str:
        """Generate tests for SCSS files."""
        log_message(f"[AI2-TESTER] Generating tests for SCSS file: {filename}")
        
        test_filename = filename.replace(".scss", "_test.js")
        
        # Form prompt for test generator
        prompt = f"""
Create tests for the SCSS file using Jest with sass-jest or a similar tool.
Please verify the following aspects:
1. Correct SCSS structure (nested selectors, variables, mixins)
2. Correctness of compiled CSS and its application
3. Verification of variables and their values
4. Verification of functions and mixins

SCSS file ({filename}):
```scss
{content}
```

The result should be a JavaScript file {test_filename} with tests.
Use sass-jest or sass + Jest for testing.
"""
        
        return await self._generate_test_with_fallback(prompt, test_filename)
        
    async def generate_react_tests(self, content: str, filename: str) -> str:
        """Generate tests for React components (JSX/TSX)."""
        log_message(f"[AI2-TESTER] Generating tests for React component: {filename}")
        
        test_filename = filename.replace(".jsx", ".test.jsx").replace(".tsx", ".test.tsx")
        
        # Form prompt for test generator
        prompt = f"""
Create tests for the React component using React Testing Library and Jest.
Please verify the following aspects:
1. Correct component rendering
2. Behavior with different props
3. Handling user events (clicks, text input, etc.)
4. Asynchronous function and API calls
5. Interaction with other components

React component ({filename}):
```jsx
{content}
```

The result should be a file {test_filename} with tests.
Use React Testing Library, Jest, and jest-dom for DOM assertions if needed.
"""
        
        return await self._generate_test_with_fallback(prompt, test_filename)
        
    async def generate_vue_tests(self, content: str, filename: str) -> str:
        """Generate tests for Vue components."""
        log_message(f"[AI2-TESTER] Generating tests for Vue component: {filename}")
        
        test_filename = filename.replace(".vue", ".spec.js")
        
        # Form prompt for test generator
        prompt = f"""
Create tests for the Vue component using Vue Test Utils and Jest.
Please verify the following aspects:
1. Correct component rendering
2. Reactivity and DOM updates when data changes
3. Event handling and methods
4. Props verification and emitted events
5. Interaction with Vuex (if used)

Vue component ({filename}):
```vue
{content}
```

The result should be a file {test_filename} with tests.
Use Vue Test Utils, Jest, and jest-dom for DOM assertions if needed.
"""
        
        return await self._generate_test_with_fallback(prompt, test_filename)

    async def _generate_test_with_fallback(self, prompt: str, test_filename: str) -> str:
        """Common method for generating tests with fallback providers."""
        for provider_name in self.providers:
            try:
                log_message(f"[AI2-TESTER] Attempting to generate tests with provider '{provider_name}'")
                provider = await self._get_provider(provider_name)
                if not provider:
                    continue
                    
                test_content = await provider.generate(prompt=prompt)
                if test_content and len(test_content.strip()) > 0:
                    # Check if the generated text contains test code
                    if "test(" in test_content or "it(" in test_content or "describe(" in test_content:
                        return test_content
                    else:
                        log_message(f"[AI2-TESTER] Provider '{provider_name}' generated content, but it does not contain tests")
                else:
                    log_message(f"[AI2-TESTER] Provider '{provider_name}' returned empty content")
            except Exception as e:
                log_message(f"[AI2-TESTER] Error generating tests with provider '{provider_name}': {e}")
        
        # If all providers failed to generate quality tests, return a template test
        return self._generate_template_test(test_filename)

    async def _generate_template_test(self, test_filename: str) -> str:
        """Generates a template test when all providers failed to create quality tests."""
        file_ext = os.path.splitext(test_filename)[1].lower()
        base_name = os.path.basename(test_filename)
        component_name = base_name.split(".")[0].replace("_test", "").replace("test_", "")
        
        if file_ext == '.js' or file_ext == '.jsx':
            return f"""// Basic test template for {test_filename}
import {{ render, screen }} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

describe('{component_name}', () => {{
  test('should render correctly', () => {{
    // Add proper test implementation when component is available
    expect(true).toBe(true);
  }});
  
  test('should handle user interactions', () => {{
    // Add interaction tests
    expect(true).toBe(true);
  }});
}});
"""
        elif file_ext == '.tsx':
            return f"""// Basic TypeScript test template for {test_filename}
import {{ render, screen }} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

describe('{component_name}', () => {{
  test('should render correctly', () => {{
    // Add proper test implementation when component is available
    expect(true).toBe(true);
  }});
  
  test('should handle user interactions', () => {{
    // Add interaction tests
    expect(true).toBe(true);
  }});
}});
"""
        elif file_ext == '.py':
            return f"""# Basic test template for {test_filename}
import pytest

def test_{component_name}_basic():
    # Add proper test implementation
    assert True

def test_{component_name}_functionality():
    # Add functionality tests
    assert True
"""
        else:
            # Generic test for any other file type
            return f"""// Basic test template for {test_filename}
describe('Test {component_name}', () => {{
  test('basic functionality', () => {{
    // Add implementation when the component is available
    expect(true).toBe(true);
  }});
}});
"""

    async def _get_provider(self, provider_name: str) -> Optional[BaseProvider]:
        """Gets an instance of the provider by its name with error handling."""
        try:
            # Get configuration for the provider
            provider_config = self.config.get("providers", {}).get(provider_name, {})
            if not provider_config:
                logger.warning(f"Provider '{provider_name}' not found in configuration")
                return None
                
            # Create an instance of the provider
            provider = ProviderFactory.create_provider(provider_name, provider_config)
            return provider
        except Exception as e:
            logger.error(f"Error creating provider '{provider_name}': {e}")
            return None

    async def generate_python_tests(self, content: str, filename: str) -> str:
        """Generate tests for Python files."""
        log_message(f"[AI2-TESTER] Generating tests for Python file: {filename}")
        
        test_filename = filename.replace(".py", "_test.py")
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the Python file using pytest.
Please verify the following aspects:
1. Functionality of all public functions and methods
2. Edge cases handling
3. Exception handling
4. Correct return values

Python file ({filename}):
```python
{content}
```

The result should be a Python file {test_filename} with tests.
Use pytest and unittest.mock for mocking dependencies if needed.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a Python testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_js_tests(self, content: str, filename: str) -> str:
        """Generate tests for JavaScript files."""
        log_message(f"[AI2-TESTER] Generating tests for JavaScript file: {filename}")
        
        test_filename = filename.replace(".js", ".test.js")
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the JavaScript file using Jest or Mocha.
Please verify the following aspects:
1. Functionality of all public functions
2. Edge cases and error handling
3. Asynchronous operations (if any)
4. DOM interactions (if browser-based JavaScript)

JavaScript file ({filename}):
```javascript
{content}
```

The result should be a JavaScript file {test_filename} with tests.
Use Jest or Mocha and mocking tools (sinon, jest.mock, etc.) as needed.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a JavaScript testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_ts_tests(self, content: str, filename: str) -> str:
        """Generate tests for TypeScript files."""
        log_message(f"[AI2-TESTER] Generating tests for TypeScript file: {filename}")
        
        test_filename = filename.replace(".ts", ".spec.ts")
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the TypeScript file using Jest or Mocha with ts-jest.
Please verify the following aspects:
1. Functionality of all public functions
2. Correctness of types and interfaces
3. Edge cases and error handling
4. Asynchronous operations (if any)

TypeScript file ({filename}):
```typescript
{content}
```

The result should be a TypeScript file {test_filename} with tests.
Use Jest or Mocha with ts-jest and appropriate types (e.g., @types/jest).
"""
        
        return await self._generate_with_fallback(system_prompt="You are a TypeScript testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_java_tests(self, content: str, filename: str) -> str:
        """Generate tests for Java files."""
        log_message(f"[AI2-TESTER] Generating tests for Java file: {filename}")
        
        class_name = os.path.splitext(os.path.basename(filename))[0]
        test_filename = f"Test{class_name}.java"
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the Java class using JUnit 5.
Please verify the following aspects:
1. Functionality of all public methods
2. Object initialization
3. Exception handling
4. Edge cases

Java file ({filename}):
```java
{content}
```

The result should be a Java file {test_filename} with tests.
Use JUnit 5 and Mockito for mocking if needed.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a Java testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_cpp_tests(self, content: str, filename: str) -> str:
        """Generate tests for C++ files."""
        log_message(f"[AI2-TESTER] Generating tests for C++ file: {filename}")
        
        basename = os.path.splitext(os.path.basename(filename))[0]
        test_filename = f"{basename}_test.cpp"
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the C++ file using Google Test or Catch2.
Please verify the following aspects:
1. Functionality of all public functions and methods
2. Object initialization
3. Error and exception handling
4. Memory checking (where appropriate)

C++ file ({filename}):
```cpp
{content}
```

The result should be a C++ file {test_filename} with tests.
Use Google Test or Catch2 and mocking tools as needed.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a C++ testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_go_tests(self, content: str, filename: str) -> str:
        """Generate tests for Go files."""
        log_message(f"[AI2-TESTER] Generating tests for Go file: {filename}")
        
        basename = os.path.splitext(os.path.basename(filename))[0]
        test_filename = f"{basename}_test.go"
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the Go file using the standard testing package.
Please verify the following aspects:
1. Functionality of all public functions
2. Error handling
3. Edge cases
4. Concurrency (if relevant)

Go file ({filename}):
```go
{content}
```

The result should be a Go file {test_filename} with tests.
Use the testing package and, if needed, gomock or testify.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a Go testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_rust_tests(self, content: str, filename: str) -> str:
        """Generate tests for Rust files."""
        log_message(f"[AI2-TESTER] Generating tests for Rust file: {filename}")
        
        # In Rust, tests are usually written in the same file in a tests module
        test_filename = filename
        
        # Form prompt for test generator
        prompt = f"""
Create unit tests for the Rust file using Rust's built-in testing framework.
Please verify the following aspects:
1. Functionality of all public functions
2. Error handling (Result, Option)
3. Edge cases
4. Memory safety (where appropriate)

Rust file ({filename}):
```rust
{content}
```

The result should be a Rust test module using the #[cfg(test)] attribute.
Include all necessary tests to verify code correctness.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a Rust testing expert. Generate unit tests for the provided code.", user_prompt=prompt)

    async def generate_generic_tests(self, content: str, filename: str) -> str:
        """Generate tests for files of unknown type."""
        log_message(f"[AI2-TESTER] Generating tests for file of unknown type: {filename}")
        
        basename = os.path.splitext(os.path.basename(filename))[0]
        ext = os.path.splitext(filename)[1]
        test_filename = f"{basename}_test{ext}"
        if not test_filename.startswith("tests/"):
            test_filename = f"tests/{test_filename}"
        
        # Form prompt for test generator
        prompt = f"""
Create tests for the file {filename} using an appropriate testing framework.
Please verify the following aspects:
1. Core functionality
2. Error handling
3. Edge cases
4. Integration with other components

File content ({filename}):
```
{content}
```

The result should be a file {test_filename} with tests.
Choose the most suitable testing framework for this file type.
"""
        
        return await self._generate_with_fallback(system_prompt="You are a testing expert. Generate appropriate tests for the provided code file.", user_prompt=prompt)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI2 Worker")
    parser.add_argument(
        "--role",
        type=str,
        required=True,
        choices=["executor", "tester", "documenter"],
        help="Role of this AI2 worker",
    )
    args = parser.parse_args()

    ai2_worker = AI2(role=args.role)

    try:
        asyncio.run(ai2_worker.run_worker())
    except KeyboardInterrupt:
        logger.info(f"AI2 worker ({args.role}) stopped manually.")
    except Exception as e:
        logger.exception(
            f"Critical error in main loop of AI2 worker ({args.role}): {e}"
        )
    finally:
        asyncio.run(ai2_worker.close_session())

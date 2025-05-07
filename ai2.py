import argparse
import asyncio
import json
import logging
import os
import re  # Import re
import time
from typing import Any, Dict, List, Optional, Union

import aiohttp
import git

# Use load_config function from config.py
from config import load_config

# Fix import statement - use ProviderFactory.create_provider instead of separate create_provider
from providers import BaseProvider, ProviderFactory

# Fix import by importing apply_request_delay from utils module directly
from utils import apply_request_delay  # Import apply_request_delay correctly
from utils import log_message

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
        self.system_instructions = " Respond ONLY with the raw file content. Do NOT use markdown code blocks (```) unless the target file is a markdown file (e.g., .md). Use only Latin characters in your response."  # Modified instruction

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

        logger.info(
            f"Configured providers for role '{self.role}': {', '.join(self.providers)}"
        )

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
        if provider_name in providers_list:
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
        is_markdown: bool = False,  # Add flag for markdown output
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

        logger.info(
            f"Attempting generation using providers (in order): {', '.join(all_providers)}"
        )

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
                    # FIXED: Use combined identifier instead of passing two arguments
                    await apply_request_delay(f"ai2_{self.role}")

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

                # --- Post-processing: Remove markdown code blocks if not expected ---
                if not is_markdown and isinstance(result, str):
                    # Remove ```markdown ... ``` or ``` ... ``` blocks
                    result = re.sub(
                        r"^```(?:markdown)?\s*?\n", "", result, flags=re.MULTILINE
                    )
                    result = re.sub(r"\n```\s*$", "", result, flags=re.MULTILINE)
                    result = result.strip()  # Remove leading/trailing whitespace

                # Close session after successful use
                if (
                    current_provider
                    and hasattr(current_provider, "close_session")
                    and callable(current_provider.close_session)
                ):
                    await current_provider.close_session()

                # Return result from successful provider
                logger.info(
                    f"Successfully generated with provider '{current_provider_name}'"
                )
                return result

            except Exception as provider_error:
                # Log provider error
                logger.error(
                    f"Generation error with provider '{current_provider_name}': {provider_error}"
                )
                all_errors.append(
                    f"Provider '{current_provider_name}' failed: {provider_error}"
                )

                # Close provider session on error
                if (
                    current_provider
                    and hasattr(current_provider, "close_session")
                    and callable(current_provider.close_session)
                ):
                    await current_provider.close_session()

        # If all providers failed, return information about all errors
        error_msg = (
            "Failed to generate a response with any of the available providers:\n- "
            + "\n- ".join(all_errors)
        )
        logger.error(error_msg)
        return error_msg

    async def generate_code(self, task_description: str, filename: str) -> str:
        """Generate code with enhanced pattern matching and language capabilities."""
        logger.info(f"[AI2-EXECUTOR] Generating code for: {filename}")

        # Get file extension and determine language
        file_ext = os.path.splitext(filename)[1].lower()

        # Get language-specific patterns and best practices
        code_patterns = self._get_code_patterns(file_ext)

        # Get project context from idea.md if available
        project_context = ""
        try:
            with open("repo/idea.md", "r", encoding="utf-8") as f:
                project_context = f.read()
        except FileNotFoundError:
            logger.warning(
                "[AI2-EXECUTOR] idea.md not found. Proceeding without project context."
            )

        # Enhanced system prompt for code generation
        base_prompt = self.base_prompts[0].format(filename=filename)
        system_prompt = f"""{base_prompt}
        You are an expert software developer. Follow these guidelines:
        1. Write clean, maintainable code
        2. Include proper error handling
        3. Add comprehensive comments
        4. Follow language-specific conventions
        5. Consider performance and security
        {code_patterns}
        {self.system_instructions}"""

        # Enhanced user prompt with project context
        user_prompt = f"""Project Context:
    {project_context[:1000] if project_context else 'No project context available'}
    
    Task Description:
    {task_description}
    
    Requirements:
    1. Generate complete, production-ready code
    2. Include error handling and input validation
    3. Add comprehensive comments and docstrings
    4. Follow {self._get_language_name(file_ext)} best practices
    5. Consider edge cases and security
    6. Use efficient algorithms and data structures
    
    Generate the complete implementation for '{filename}'."""

        # Apply rate limiting
        await apply_request_delay(f"ai2_{self.role}")

        # Generate with validation
        code = await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

        if code and not code.startswith("Generation error"):
            # Validate generated code
            if self._validate_generated_code(code, file_ext):
                logger.info(
                    f"[AI2-EXECUTOR] Successfully generated and validated code for {filename}"
                )
                return code
            else:
                logger.warning(
                    f"[AI2-EXECUTOR] Generated code failed validation for {filename}. Retrying..."
                )
                # Retry with stricter requirements
                user_prompt += "\nPlease fix code quality issues and ensure all validation checks pass."
                code = await self._generate_with_fallback(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )

        return code

    def _get_code_patterns(self, file_ext: str) -> str:
        """Get language-specific coding patterns and best practices."""
        patterns = {
            ".py": """
        Python Coding Patterns:
        - Use type hints for function parameters and returns
        - Use context managers (with) for resource handling
        - Implement proper exception handling with specific exceptions
        - Follow PEP 8 style guidelines
        - Use descriptive variable names and docstrings
        - Implement logging for important operations
        - Use dataclasses or named tuples where appropriate""",
            ".js": """
        JavaScript Coding Patterns:
        - Use ES6+ features appropriately
        - Implement proper error handling with try/catch
        - Use async/await for asynchronous operations
        - Follow module pattern for code organization
        - Use meaningful variable and function names
        - Add JSDoc comments for documentation
        - Implement proper event handling""",
            ".ts": """
        TypeScript Coding Patterns:
        - Use strict type checking
        - Implement interfaces and type definitions
        - Use enums for constants
        - Follow SOLID principles
        - Use generics where appropriate
        - Add TSDoc comments
        - Implement proper error handling""",
            ".go": """
        Go Coding Patterns:
        - Follow Go idioms and conventions
        - Use proper error handling (if err != nil)
        - Implement interfaces where appropriate
        - Use goroutines and channels correctly
        - Follow standard package layout
        - Add godoc comments
        - Use meaningful names and structures""",
            ".java": """
        Java Coding Patterns:
        - Follow OOP principles
        - Use proper exception handling
        - Implement interfaces appropriately
        - Follow Java naming conventions
        - Use generics where appropriate
        - Add Javadoc comments
        - Follow design patterns""",
            ".cpp": """
        C++ Coding Patterns:
        - Use RAII for resource management
        - Implement proper error handling
        - Use smart pointers
        - Follow const correctness
        - Use STL appropriately
        - Add doxygen comments
        - Consider memory management""",
        }

        return patterns.get(
            file_ext,
            """
        General Coding Patterns:
        - Use clear and consistent formatting
        - Implement proper error handling
        - Add comprehensive comments
        - Use meaningful names
        - Follow language conventions
        - Consider security implications
        - Write maintainable code""",
        )

    def _get_language_name(self, file_ext: str) -> str:
        """Get the formal name of the programming language."""
        languages = {
            ".py": "Python",
            ".js": "JavaScript",
            ".jsx": "React JavaScript",
            ".ts": "TypeScript",
            ".tsx": "React TypeScript",
            ".go": "Go",
            ".java": "Java",
            ".cpp": "C++",
            ".hpp": "C++",
            ".rb": "Ruby",
            ".php": "PHP",
        }
        return languages.get(file_ext, "the target language")

    def _validate_generated_code(self, code: str, file_ext: str) -> bool:
        """Validate generated code for quality and best practices."""
        try:
            if not code or len(code.strip()) < 10:
                return False

            # Check for basic code structure
            if "import" not in code and "package" not in code and "include" not in code:
                logger.warning("[AI2-EXECUTOR] Generated code missing imports/includes")

            # Check for error handling patterns
            error_patterns = {
                ".py": [
                    "try:",
                    "except",
                    "raise",
                    "with",
                    "finally",
                    "if not",
                    "if None",
                    "isinstance",
                ],
                ".js": [
                    "try {",
                    "catch",
                    "throw",
                    "if (",
                    "else",
                    "undefined",
                    "null",
                    "typeof",
                ],
                ".ts": [
                    "try {",
                    "catch",
                    "throw",
                    "if (",
                    "else",
                    "undefined",
                    "null",
                    "instanceof",
                ],
                ".go": ["if err != nil", "return err", "error", "panic", "recover"],
                ".java": ["try {", "catch", "throw", "Exception", "null", "instanceof"],
                ".cpp": ["try {", "catch", "throw", "nullptr", "std::exception"],
            }

            patterns = error_patterns.get(file_ext, ["try", "catch", "throw", "error"])
            has_error_handling = any(pattern in code for pattern in patterns)
            if not has_error_handling:
                logger.warning("[AI2-EXECUTOR] Generated code missing error handling")

            # Check for comments/documentation
            comment_patterns = {
                ".py": ['"""', "#"],
                ".js": ["//", "/*"],
                ".ts": ["//", "/*"],
                ".go": ["//", "/*"],
                ".java": ["//", "/*"],
                ".cpp": ["//", "/*"],
            }

            patterns = comment_patterns.get(file_ext, ["//", "/*", "#"])
            has_comments = any(pattern in code for pattern in patterns)
            if not has_comments:
                logger.warning("[AI2-EXECUTOR] Generated code missing documentation")

            # Language-specific checks
            if file_ext == ".py":
                if "def " in code and "typing" not in code:
                    logger.warning("[AI2-EXECUTOR] Python code missing type hints")
                if "class " in code and not re.search(r"class \w+\(.*\):", code):
                    logger.warning(
                        "[AI2-EXECUTOR] Python class missing explicit inheritance"
                    )

            elif file_ext in [".js", ".ts"]:
                if "async " in code and "try " not in code:
                    logger.warning("[AI2-EXECUTOR] Async code missing try/catch")
                if (
                    file_ext == ".ts"
                    and "interface " not in code
                    and "type " not in code
                ):
                    logger.warning(
                        "[AI2-EXECUTOR] TypeScript code missing type definitions"
                    )

            elif file_ext == ".go":
                if "func " in code and "error)" in code and "if err != nil" not in code:
                    logger.warning("[AI2-EXECUTOR] Go code missing error handling")

            elif file_ext == ".java":
                if "class " in code and "public " not in code:
                    logger.warning("[AI2-EXECUTOR] Java code missing access modifiers")
                if "throws " in code and "try " not in code:
                    logger.warning(
                        "[AI2-EXECUTOR] Java code missing exception handling"
                    )

            # Security checks
            security_patterns = [
                "exec(",
                "eval(",  # Code execution
                "input(",
                "prompt(",  # User input
                "SELECT ",
                "INSERT ",  # SQL
                "password",
                "secret",  # Sensitive data
                "http:",
                "https:",  # URLs
            ]

            for pattern in security_patterns:
                if pattern.lower() in code.lower():
                    logger.warning(
                        f"[AI2-EXECUTOR] Security: Found potentially sensitive pattern: {pattern}"
                    )

            return True  # Return true but log warnings for monitoring

        except Exception as e:
            logger.error(f"[AI2-EXECUTOR] Error validating generated code: {e}")
            return False

    async def generate_tests(self, code: str, filename: str) -> str:
        """Generate comprehensive tests with improved coverage and validation."""
        logger.info(f"[AI2-TESTER] Generating tests for file: {filename}")

        # Get project context from idea.md if available
        project_context = ""
        try:
            with open("repo/idea.md", "r", encoding="utf-8") as f:
                project_context = f.read()
        except FileNotFoundError:
            logger.warning(
                "[AI2-TESTER] idea.md not found. Proceeding without project context."
            )

        # Analyze file type and get language-specific test patterns
        file_ext = os.path.splitext(filename)[1].lower()
        test_patterns = self._get_test_patterns(file_ext)

        # Enhanced system prompt for test generation
        base_prompt = self.base_prompts[1].format(filename=filename)
        system_prompt = f"""{base_prompt}
        You are an expert in writing comprehensive tests. Follow these guidelines:
        1. Achieve high code coverage (aim for >80%)
        2. Test edge cases and error conditions
        3. Use appropriate mocking/stubbing
        4. Follow testing best practices for the language
        5. Include clear test descriptions
        6. Group related tests logically
        {test_patterns}
        {self.system_instructions.replace("file content", "test code")}"""

        # Enhanced user prompt with project context
        user_prompt = f"""Project Context:
    {project_context[:1000] if project_context else 'No project context available'}
    
    Code to test from '{filename}':
    ```
    {code}
    ```
    
    Generate comprehensive tests that:
    1. Test all public interfaces
    2. Cover edge cases and error conditions
    3. Include integration tests where appropriate
    4. Use proper assertions and matchers
    5. Follow {self._get_test_framework(file_ext)} conventions
    6. Include setup/teardown if needed
    
    Tests should be complete and ready to run."""

        # Apply rate limiting
        await apply_request_delay(f"ai2_{self.role}")

        # Generate tests with validation
        test_content = await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

        if test_content and not test_content.startswith("Generation error"):
            # Validate generated tests
            if self._validate_generated_tests(test_content, file_ext):
                logger.info(
                    f"[AI2-TESTER] Successfully generated and validated tests for {filename}"
                )
                # Commit tests to Git
                if await self.commit_tests_to_git(filename, test_content):
                    return test_content
                else:
                    return (
                        f"Generation error: Failed to save tests to Git for {filename}"
                    )
            else:
                logger.warning(
                    f"[AI2-TESTER] Generated tests failed validation for {filename}. Retrying..."
                )
                # Retry with stricter requirements
                user_prompt += "\nPlease fix the test quality issues and ensure comprehensive test coverage."
                test_content = await self._generate_with_fallback(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )

        return test_content

    def _get_test_patterns(self, file_ext: str) -> str:
        """Get language-specific test patterns and best practices."""
        patterns = {
            ".py": """
        Test Pattern Requirements:
        - Use pytest fixtures for setup/teardown
        - Test both success and failure paths
        - Use parametrize for multiple test cases
        - Mock external dependencies
        - Test async functions with pytest.mark.asyncio
        - Include docstrings for complex tests""",
            ".js": """
        Test Pattern Requirements:
        - Use describe/it blocks for organization
        - Test async code with async/await
        - Mock API calls and external services
        - Test React components with proper events
        - Use beforeEach/afterEach for setup
        - Include error boundary testing""",
            ".ts": """
        Test Pattern Requirements:
        - Include type checking in tests
        - Test type guards and assertions
        - Mock with TypeScript-aware mocks
        - Test null/undefined handling
        - Verify type constraints
        - Test async operations properly""",
            ".go": """
        Test Pattern Requirements:
        - Use table-driven tests
        - Test error handling thoroughly
        - Use subtests for organization
        - Mock interfaces appropriately
        - Test concurrent code safely
        - Include benchmarks if needed""",
            ".java": """
        Test Pattern Requirements:
        - Use JUnit 5 features fully
        - Include parameterized tests
        - Mock with Mockito properly
        - Test exception handling
        - Use assertj for readable assertions
        - Include integration tests""",
            ".cpp": """
        Test Pattern Requirements:
        - Use TEST/TEST_F macros properly
        - Test memory management
        - Include fixture setup/teardown
        - Mock C++ interfaces correctly
        - Test exception handling
        - Verify resource cleanup""",
        }

        return patterns.get(
            file_ext,
            """
        Test Pattern Requirements:
        - Group related tests logically
        - Include positive and negative tests
        - Test error conditions
        - Mock external dependencies
        - Verify edge cases
        - Document test purposes""",
        )

    def _get_test_framework(self, file_ext: str) -> str:
        """Get the appropriate test framework name for the file type."""
        frameworks = {
            ".py": "pytest",
            ".js": "Jest",
            ".jsx": "Jest + React Testing Library",
            ".ts": "Jest + ts-jest",
            ".tsx": "Jest + React Testing Library + TypeScript",
            ".go": "Go testing package",
            ".java": "JUnit 5",
            ".cpp": "Google Test",
            ".cs": "xUnit.net",
            ".rb": "RSpec",
            ".php": "PHPUnit",
        }
        return frameworks.get(file_ext, "appropriate testing framework")

    def _validate_generated_tests(self, tests: str, file_ext: str) -> bool:
        """Validate generated tests for quality and coverage."""
        try:
            if not tests or len(tests.strip()) < 10:
                return False

            # Check for test structure
            framework_patterns = {
                ".py": ["def test_", "assert", "@pytest"],
                ".js": ["describe(", "it(", "test(", "expect("],
                ".ts": ["describe(", "it(", "test(", "expect("],
                ".go": ["func Test", "t.Run(", "t.Error"],
                ".java": ["@Test", "assert", "@Before"],
                ".cpp": ["TEST(", "EXPECT_", "ASSERT_"],
            }

            patterns = framework_patterns.get(file_ext, ["test", "assert", "expect"])
            has_framework_patterns = any(pattern in tests for pattern in patterns)
            if not has_framework_patterns:
                logging.warning(
                    "[AI2-TESTER] Generated tests missing framework patterns"
                )

            # Check for test organization
            if not any(
                marker in tests for marker in ["describe", "class Test", "TEST_F"]
            ):
                logging.warning("[AI2-TESTER] Generated tests lack proper organization")

            # Check for assertions
            assertion_patterns = ["assert", "expect", "should", "EXPECT_"]
            has_assertions = any(pattern in tests for pattern in assertion_patterns)
            if not has_assertions:
                logging.warning("[AI2-TESTER] Generated tests missing assertions")

            # Check for test documentation
            comment_patterns = {
                ".py": ['"""', "#"],
                ".js": ["//", "/*"],
                ".ts": ["//", "/*"],
                ".java": ["//", "/*"],
                ".cpp": ["//", "/*"],
                ".go": ["//", "/*"],
            }

            patterns = comment_patterns.get(file_ext, ["//", "/*", "#"])
            has_comments = any(pattern in tests for pattern in patterns)
            if not has_comments:
                logging.warning("[AI2-TESTER] Generated tests missing documentation")

            # Additional framework-specific checks
            if file_ext == ".py":
                if "pytest" in tests and "fixture" not in tests:
                    logging.warning("[AI2-TESTER] Python tests missing fixtures")
            elif file_ext in [".js", ".ts"]:
                if "beforeEach" not in tests and "afterEach" not in tests:
                    logging.warning("[AI2-TESTER] JS/TS tests missing setup/teardown")

            return True  # Return true but log warnings for monitoring

        except Exception as e:
            logging.error(f"[AI2-TESTER] Error validating generated tests: {e}")
            return False

    async def generate_docs(self, code: str, filename: str) -> str:
        """Generate comprehensive documentation with improved context and style awareness."""
        logger.info(f"[AI2-DOCUMENTER] Generating documentation for: {filename}")

        # Get project context from idea.md if available
        project_context = ""
        try:
            with open("repo/idea.md", "r", encoding="utf-8") as f:
                project_context = f.read()
        except FileNotFoundError:
            logger.warning(
                "[AI2-DOCUMENTER] idea.md not found. Proceeding without project context."
            )

        is_markdown_file = filename.lower().endswith(".md")
        file_ext = os.path.splitext(filename)[1].lower()

        if filename == "idea.md":
            return await self._generate_idea_md(code, project_context)

        # Get language-specific documentation patterns
        doc_patterns = self._get_doc_patterns(file_ext)

        # Enhanced system prompt for documentation
        base_prompt = self.base_prompts[2].format(filename=filename)
        system_prompt = f"""{base_prompt}
        You are an expert technical writer. Follow these guidelines:
        1. Use clear, concise language
        2. Document all public interfaces thoroughly
        3. Include examples for complex functionality
        4. Explain important design decisions
        5. Follow language-specific documentation standards
        6. Link related components and concepts
        {doc_patterns}
        {self.system_instructions.replace("file content", "documentation text")}"""

        # Enhanced user prompt with project context
        user_prompt = f"""Project Context:
    {project_context[:1000] if project_context else 'No project context available'}
    
    Code to document from '{filename}':
    ```
    {code}
    ```
    
    Generate comprehensive documentation that:
    1. Follows {self._get_doc_style(file_ext)} standards
    2. Documents all public interfaces
    3. Explains complex logic and algorithms
    4. Includes examples where helpful
    5. Notes dependencies and requirements
    6. Highlights important assumptions
    
    Documentation should be complete and follow best practices."""

        # Apply rate limiting
        await apply_request_delay(f"ai2_{self.role}")

        # Generate with validation
        docs = await self._generate_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            is_markdown=is_markdown_file,
        )

        if docs and not docs.startswith("Generation error"):
            # Validate generated documentation
            if self._validate_generated_docs(docs, file_ext):
                logger.info(
                    f"[AI2-DOCUMENTER] Successfully generated and validated documentation for {filename}"
                )
                return docs
            else:
                logger.warning(
                    f"[AI2-DOCUMENTER] Generated documentation failed validation for {filename}. Retrying..."
                )
                # Retry with stricter requirements
                user_prompt += "\nPlease fix documentation quality issues and ensure comprehensive coverage."
                docs = await self._generate_with_fallback(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    is_markdown=is_markdown_file,
                )

        return docs

    async def _generate_idea_md(
        self, current_content: str, project_context: str
    ) -> str:
        """Generate or refine the idea.md project description."""
        logger.info("[AI2-DOCUMENTER] Generating/refining idea.md")

        system_prompt = """You are a project planner and technical writer.
        Generate a comprehensive project description that:
        1. Clearly defines project goals and scope
        2. Identifies target audience and use cases
        3. Outlines technical architecture and choices
        4. Lists key features and requirements
        5. Considers potential challenges
        6. Provides implementation guidance
        
        Use clear, professional Markdown formatting."""

        user_prompt = f"""Current project description:
    ```markdown
    {current_content}
    ```
    
    Project Context (if available):
    {project_context}
    
    Enhance this project description to be:
    1. More detailed and specific
    2. Well-structured and organized
    3. Implementation-focused
    4. Clear about technical decisions
    5. Comprehensive in scope
    
    Do NOT use placeholders. Provide concrete details based on the context.
    Respond with complete Markdown content."""

        return await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt, is_markdown=True
        )

    def _get_doc_patterns(self, file_ext: str) -> str:
        """Get language-specific documentation patterns and standards."""
        patterns = {
            ".py": """
        Documentation Pattern Requirements:
        - Use Google-style docstrings
        - Document parameters with types
        - Specify return types and values
        - Include usage examples
        - Document exceptions raised
        - Add module-level docstrings""",
            ".js": """
        Documentation Pattern Requirements:
        - Use JSDoc format
        - Document parameters and types
        - Specify return values
        - Include usage examples
        - Document async behaviors
        - Add module and class docs""",
            ".ts": """
        Documentation Pattern Requirements:
        - Use TSDoc format
        - Document types thoroughly
        - Specify interfaces and types
        - Include examples with types
        - Document generics usage
        - Note type constraints""",
            ".go": """
        Documentation Pattern Requirements:
        - Follow godoc format
        - Document exported items
        - Include example functions
        - Document error returns
        - Add package documentation
        - Use complete sentences""",
            ".java": """
        Documentation Pattern Requirements:
        - Use Javadoc format
        - Document all public APIs
        - Specify exceptions thrown
        - Include param/return tags
        - Document thread safety
        - Add class-level docs""",
            ".cpp": """
        Documentation Pattern Requirements:
        - Use Doxygen format
        - Document public interfaces
        - Specify memory ownership
        - Note thread safety
        - Document preconditions
        - Include usage examples""",
        }

        return patterns.get(
            file_ext,
            """
        Documentation Pattern Requirements:
        - Use consistent format
        - Document public interfaces
        - Include usage examples
        - Note important details
        - Add context and purpose
        - Follow conventions""",
        )

    def _get_doc_style(self, file_ext: str) -> str:
        """Get the appropriate documentation style for the file type."""
        styles = {
            ".py": "Google-style docstrings",
            ".js": "JSDoc",
            ".jsx": "JSDoc with React component documentation",
            ".ts": "TSDoc",
            ".tsx": "TSDoc with React component documentation",
            ".go": "godoc",
            ".java": "Javadoc",
            ".cpp": "Doxygen",
            ".hpp": "Doxygen",
            ".rb": "YARD",
            ".php": "PHPDoc",
        }
        return styles.get(file_ext, "standard documentation")

    def _validate_generated_docs(self, docs: str, file_ext: str) -> bool:
        """Validate generated documentation for quality and completeness."""
        try:
            if not docs or len(docs.strip()) < 10:
                return False

            # Check for documentation format
            doc_format_patterns = {
                ".py": ['"""', "Args:", "Returns:", "Raises:"],
                ".js": ["/**", "@param", "@returns", "@throws"],
                ".ts": ["/**", "@param", "@returns", "@throws"],
                ".java": ["/**", "@param", "@return", "@throws"],
                ".cpp": ["/**", "@param", "@return", "@throws"],
                ".go": ["// ", "Example"],
            }

            patterns = doc_format_patterns.get(
                file_ext, ["/**", "@param", "@return", "//"]
            )
            has_doc_format = any(pattern in docs for pattern in patterns)
            if not has_doc_format:
                logging.warning(
                    "[AI2-DOCUMENTER] Generated docs missing standard format"
                )

            # Check for interface documentation
            if "class" in docs or "function" in docs or "method" in docs:
                interface_patterns = ["param", "return", "arg", "throws"]
                has_interface_docs = any(
                    pattern in docs.lower() for pattern in interface_patterns
                )
                if not has_interface_docs:
                    logging.warning(
                        "[AI2-DOCUMENTER] Generated docs missing interface documentation"
                    )

            # Check for examples
            example_patterns = ["example", "usage", "Example:", "Usage:"]
            has_examples = any(pattern in docs for pattern in example_patterns)
            if not has_examples:
                logging.warning("[AI2-DOCUMENTER] Generated docs missing examples")

            # Check for overall structure
            if len(docs.split("\n")) < 3:
                logging.warning("[AI2-DOCUMENTER] Generated docs too brief")

            # Language-specific checks
            if file_ext == ".py":
                if "def " in docs and '"""' not in docs:
                    logging.warning("[AI2-DOCUMENTER] Python docs missing docstrings")
            elif file_ext in [".js", ".ts"]:
                if "function " in docs and "/**" not in docs:
                    logging.warning("[AI2-DOCUMENTER] JS/TS docs missing JSDoc blocks")

            return True  # Return true but log warnings for monitoring

        except Exception as e:
            logging.error(f"[AI2-DOCUMENTER] Error validating generated docs: {e}")
            return False

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

            logger.info(
                f"Tests for {filename} successfully added to Git: {test_filename}"
            )
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
        code_content = task_info.get(
            "code"
        )  # This will contain idea.md content for the refinement task

        # Extract filename from text if missing
        if not filename and task_description:
            match = re.search(
                r"file:\s*([^\s.,\"']+(?:\.[^\s.,\"']+)?)", task_description
            )
            if match:
                filename = match.group(1).strip()
                logger.info(f"Extracted filename '{filename}' from task description.")
            else:
                logger.warning(
                    f"Filename missing and could not be extracted from text: {task_description}"
                )
                # Set a default filename to prevent errors
                if "idea.md" in task_description:
                    filename = "idea.md"
                    logger.info(
                        "Using 'idea.md' as default filename based on task description."
                    )

        if not subtask_id:
            logger.error(f"Invalid task information: Missing ID in task.")
            return {
                "type": "status_update",
                "subtask_id": "unknown",
                "message": "Error: Missing ID in task.",
                "status": "failed",
            }

        # If role is still missing but we're running as a specific role worker, assign that role
        if not role:
            role = self.role
            logger.info(f"No role specified in task, using worker role: {self.role}")

        if not filename:
            logger.error(f"Invalid task information: {task_info}")
            return {
                "type": "status_update",
                "subtask_id": subtask_id,
                "message": "Error: Could not determine filename for task.",
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
            "file": filename,  # Keep 'file' for consistency, even for idea.md
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
                    generated_content = await self.generate_code(
                        task_description, filename
                    )

            elif role == "tester":
                report["type"] = "test_result"  # Keep this type for tester reports
                if code_content is None:
                    error_message = "Missing code for role tester"
                    logger.error(f"Missing code for tester: {task_info}")
                else:
                    # Generate and commit tests
                    generated_content = await self.generate_tests(
                        code_content, filename
                    )
                    if generated_content and not generated_content.startswith(
                        "Generation error"
                    ):
                        # Successfully generated and committed tests
                        report["content"] = generated_content  # Test code content
                        report["message"] = (
                            f"Tests for {filename} successfully generated and committed to Git"
                        )
                        report["status"] = (
                            "tests_committed"  # Specific status for tester
                        )
                    else:
                        # Handle test generation failure
                        error_message = f"Generation error for tests for {filename}: {generated_content or 'No content generated'}"
                        # Ensure report type indicates failure if tests weren't generated/committed
                        report = {
                            "type": "status_update",
                            "subtask_id": subtask_id,
                            "message": error_message,
                            "status": "failed",
                        }
                        # Set generated_content to None to avoid incorrect logging below
                        generated_content = None

            elif role == "documenter":
                report["type"] = (
                    "code"  # Use "code" type as we are updating file content (idea.md or code docs)
                )

                # For documenter tasks, handle both file documentation and idea.md
                if filename == "idea.md":
                    if code_content is None:
                        error_message = "Missing content for idea.md refinement"
                        logger.error(f"Missing content for idea.md: {task_info}")
                    else:
                        # Handle idea.md documentation specifically
                        logger.info(f"[AI2-DOCUMENTER] Generating/refining idea.md")
                        generated_content = await self._generate_idea_md(
                            code_content, ""
                        )
                else:
                    # Standard code documentation
                    if code_content is None:
                        error_message = (
                            f"Missing code content for documenter task for {filename}"
                        )
                        logger.error(f"Missing content for documenter: {task_info}")
                    else:
                        generated_content = await self.generate_docs(
                            code_content, filename
                        )

            else:
                error_message = f"Unknown role: {role}"
                logger.error(f"Unknown role: {role}")

            # Check if generation itself failed (applies to all roles)
            if isinstance(generated_content, str) and generated_content.startswith(
                "Failed to generate a response"
            ):
                error_message = generated_content
                generated_content = None  # Ensure content is None if generation failed

            # Add generated content to the report if successful and not already handled (like tester)
            if generated_content is not None and "content" not in report:
                report["content"] = generated_content

        except Exception as e:
            logger.exception(
                f"Unexpected error while processing task for {filename} ({role}): {e}"
            )
            error_message = f"Unexpected error: {e}"

        end_time = asyncio.get_event_loop().time()
        processing_time = end_time - start_time

        # Finalize report based on success/failure
        if error_message:
            # Ensure failed tasks send a status_update report
            if report.get("type") != "status_update":
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
        elif "status" not in report:  # If no error and status not set (e.g., by tester)
            # Default success status for executor/documenter if content was generated
            if "content" in report:
                report["status"] = "completed"  # Generic completion status
                log_message_data = {
                    "message": f"Task processing successfully completed for {filename} ({role})",
                    "role": role,
                    "file": filename,
                    "status": "success",
                    "processing_time": round(processing_time, 2),
                    "report_type": report.get("type"),
                }
            else:  # Should not happen if no error, but handle defensively
                report = {
                    "type": "status_update",
                    "subtask_id": subtask_id,
                    "message": f"Task processing finished for {filename} ({role}) but no content generated and no error reported.",
                    "status": "error_processing",  # Use a specific status
                }
                log_message_data = {
                    "message": f"Task processing anomaly for {filename} ({role}): No content, no error.",
                    "role": role,
                    "file": filename,
                    "status": "warning",
                    "processing_time": round(processing_time, 2),
                }
        else:  # Status already set (e.g., tests_committed)
            log_message_data = {
                "message": f"Task processing completed for {filename} ({role}) with status '{report['status']}'",
                "role": role,
                "file": filename,
                "status": "success",  # Overall processing was successful
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
                            task_id = subtask_data.get("id")
                            task_filename = subtask_data.get("filename")
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
                # Force task to have a role property matching our worker
                if not task.get("role"):
                    task["role"] = self.role
                    logger.info(
                        f"Added missing role '{self.role}' to task: {task.get('id')}"
                    )

                # Standardize file extensions and fix file formats
                if self.role in ["documenter", "tester", "executor"]:
                    filename = task.get("filename")
                    if filename:
                        # Fix duplicate test extensions (.test.test.js, etc.)
                        if filename.count(".test") > 1:
                            # Replace multiple .test occurrences with just one
                            base_name = filename.split(".test")[0]
                            remaining = filename.split(".test")[-1]
                            if remaining and remaining.startswith("."):
                                task["filename"] = f"{base_name}.test{remaining}"
                            else:
                                task["filename"] = (
                                    f"{base_name}.test.js"  # Default to JS if no extension
                                )
                            logger.info(
                                f"Fixed duplicate test extensions: {task['filename']}"
                            )

                        # Add proper extensions to test files that are missing them
                        if filename.endswith(".test") and not any(
                            filename.endswith(ext)
                            for ext in [".js", ".ts", ".py", ".java"]
                        ):
                            # Infer extension based on content or project context
                            if "react" in task.get("text", "").lower() or any(
                                filename.startswith(p)
                                for p in ["React", "component", "hook", "use"]
                            ):
                                task["filename"] = filename + ".js"
                            elif "python" in task.get("text", "").lower():
                                task["filename"] = filename + ".py"
                            else:
                                task["filename"] = filename + ".js"  # Default to JS
                            logger.info(
                                f"Added proper extension to test file: {task['filename']}"
                            )

                        # Add proper extensions to config files
                        if any(
                            filename.endswith(cfg) for cfg in ["config", ".config"]
                        ) and not any(
                            filename.endswith(ext) for ext in [".js", ".json", ".py"]
                        ):
                            if (
                                filename.startswith("webpack")
                                or filename.startswith("babel")
                                or filename.startswith("jest")
                                or filename.startswith("tailwind")
                            ):
                                task["filename"] = filename + ".js"
                                logger.info(
                                    f"Added JS extension to config file: {task['filename']}"
                                )

                        # Ensure Dockerfile has proper name without extension
                        if (
                            "dockerfile" in filename.lower()
                            and "." in filename
                            and not filename.endswith(".md")
                        ):
                            task["filename"] = "Dockerfile"
                            logger.info(f"Fixed Dockerfile name: {task['filename']}")

                # Special handling for the documenter role
                if self.role == "documenter":
                    # If documenter is generating markdown, ensure it has .md extension
                    if "markdown" in task.get("text", "").lower() and not task.get(
                        "filename", ""
                    ).endswith(".md"):
                        task["filename"] = task["filename"].replace(".test", "") + ".md"
                        logger.info(
                            f"Converted documentation file to markdown: {task['filename']}"
                        )

                    # If documenting a non-markdown file, make sure the system knows we're generating inline documentation
                    # not a markdown version of the file
                    if not task.get("filename", "").endswith(".md"):
                        # Add metadata to indicate this is for inline documentation
                        task["documentation_type"] = "inline"
                        logger.info(
                            f"Marked task for inline documentation: {task.get('filename')}"
                        )

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

    async def generate_tests_based_on_file_type(
        self, content: str, filename: str
    ) -> str:
        """Generates tests based on file type."""
        file_ext = os.path.splitext(filename)[1].lower()

        if file_ext == ".py":
            return await self.generate_python_tests(content, filename)
        elif file_ext == ".js":
            return await self.generate_js_tests(content, filename)
        elif file_ext == ".ts":
            return await self.generate_ts_tests(content, filename)
        elif file_ext in [".html", ".htm"]:
            return await self.generate_html_tests(content, filename)
        elif file_ext == ".css":
            return await self.generate_css_tests(content, filename)
        elif file_ext == ".scss":
            return await self.generate_scss_tests(content, filename)
        elif file_ext in [".jsx", ".tsx"]:
            return await self.generate_react_tests(content, filename)
        elif file_ext == ".vue":
            return await self.generate_vue_tests(content, filename)
        elif file_ext == ".java":
            return await self.generate_java_tests(content, filename)
        elif file_ext in [".cpp", ".c", ".hpp", ".h"]:
            return await self.generate_cpp_tests(content, filename)
        elif file_ext == ".go":
            return await self.generate_go_tests(content, filename)
        elif file_ext == ".rs":
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

        test_filename = filename.replace(".jsx", ".test.jsx").replace(
            ".tsx", ".test.tsx"
        )

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

    async def _generate_test_with_fallback(
        self, prompt: str, test_filename: str
    ) -> str:
        """Common method for generating tests with fallback providers."""
        for provider_name in self.providers:
            try:
                log_message(
                    f"[AI2-TESTER] Attempting to generate tests with provider '{provider_name}'"
                )
                provider = await self._get_provider(provider_name)
                if not provider:
                    continue

                test_content = await provider.generate(prompt=prompt)
                if test_content and len(test_content.strip()) > 0:
                    # Check if the generated text contains test code
                    if (
                        "test(" in test_content
                        or "it(" in test_content
                        or "describe(" in test_content
                    ):
                        return test_content
                    else:
                        log_message(
                            f"[AI2-TESTER] Provider '{provider_name}' generated content, but it does not contain tests"
                        )
                else:
                    log_message(
                        f"[AI2-TESTER] Provider '{provider_name}' returned empty content"
                    )
            except Exception as e:
                log_message(
                    f"[AI2-TESTER] Error generating tests with provider '{provider_name}': {e}"
                )

        # If all providers failed to generate quality tests, return a template test
        return self._generate_template_test(test_filename)

    async def _generate_template_test(self, test_filename: str) -> str:
        """Generates a template test when all providers failed to create quality tests."""
        file_ext = os.path.splitext(test_filename)[1].lower()
        base_name = os.path.basename(test_filename)
        component_name = (
            base_name.split(".")[0].replace("_test", "").replace("test_", "")
        )

        if file_ext == ".js" or file_ext == ".jsx":
            return f"""# Basic test template for {test_filename}
import {{ render, screen }} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

describe('{component_name}', () => {{
  test('should render correctly', () => {{
    # Add proper test implementation when component is available
    expect(true).toBe(true);
  }});
  
  test('should handle user interactions', () => {{
    # Add interaction tests
    expect(true).toBe(true);
  }});
}});
"""
        elif file_ext == ".tsx":
            return f"""# Basic TypeScript test template for {test_filename}
import {{ render, screen }} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

describe('{component_name}', () => {{
  test('should render correctly', () => {{
    # Add proper test implementation when component is available
    expect(true).toBe(true);
  }});
  
  test('should handle user interactions', () => {{
    # Add interaction tests
    expect(true).toBe(true);
  }});
}});
"""
        elif file_ext == ".py":
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
            return f"""# Basic test template for {test_filename}
describe('Test {component_name}', () => {{
  test('basic functionality', () => {{
    # Add implementation when the component is available
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

        return await self._generate_with_fallback(
            system_prompt="You are a Python testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

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

        return await self._generate_with_fallback(
            system_prompt="You are a JavaScript testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

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

        return await self._generate_with_fallback(
            system_prompt="You are a TypeScript testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

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

        return await self._generate_with_fallback(
            system_prompt="You are a Java testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

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

        return await self._generate_with_fallback(
            system_prompt="You are a C++ testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

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

        return await self._generate_with_fallback(
            system_prompt="You are a Go testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

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

        return await self._generate_with_fallback(
            system_prompt="You are a Rust testing expert. Generate unit tests for the provided code.",
            user_prompt=prompt,
        )

    async def generate_generic_tests(
        self, provider, content: str, filename: str
    ) -> str:
        """Generate tests for files of unknown type."""
        log_message(
            f"[AI2-TESTER] Generating tests for file of unknown type: {filename}"
        )

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

        # If provider is passed, use it directly, otherwise use _generate_with_fallback
        if provider:
            system_prompt = "You are a testing expert. Generate appropriate tests for the provided code file."
            return await provider.generate(prompt=prompt, system_prompt=system_prompt)
        else:
            return await self._generate_with_fallback(
                system_prompt="You are a testing expert. Generate appropriate tests for the provided code file.",
                user_prompt=prompt,
            )

    def get_file_type(self, file_ext):
        """Determine the file type based on the file extension."""
        file_type_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".html": "HTML",
            ".htm": "HTML",
            ".css": "CSS",
            ".scss": "SCSS",
            ".jsx": "React",
            ".tsx": "React TypeScript",
            ".vue": "Vue",
            ".java": "Java",
            ".cpp": "C++",
            ".c": "C",
            ".hpp": "C++ Header",
            ".h": "C/C++ Header",
            ".go": "Go",
            ".rs": "Rust",
            ".md": "Markdown",
            ".png": "Image (PNG)",
            ".jpg": "Image (JPEG)",
            ".jpeg": "Image (JPEG)",
            ".gif": "Image (GIF)",
            ".svg": "Image (SVG)",
            ".mp3": "Audio (MP3)",
            ".wav": "Audio (WAV)",
            ".ogg": "Audio (OGG)",
            ".mp4": "Video (MP4)",
            ".yml": "YAML",
            ".yaml": "YAML",
            ".json": "JSON",
            ".xml": "XML",
            ".csv": "CSV",
            ".txt": "Text",
            "": "No Extension (e.g., Dockerfile)",
        }
        return file_type_map.get(file_ext.lower(), f"Unknown ({file_ext})")

    def get_test_file_path(self, file_path):
        """Convert a file path to its corresponding test file path.

        This method ensures that all test files are created within the repository directory.

        Args:
            file_path: Original file path

        Returns:
            Path to the corresponding test file
        """
        # Ensure we're working with the repo path
        repo_path = os.path.join(os.getcwd(), "repo")

        # Get the root directories in the repo to identify project folders
        try:
            repo_dirs = [
                d
                for d in os.listdir(repo_path)
                if os.path.isdir(os.path.join(repo_path, d)) and not d.startswith(".")
            ]
        except Exception as e:
            logger.warning(f"Error listing repo directories: {e}. Using empty list.")
            repo_dirs = []

        # Check if file_path already has repo/ at the beginning
        if file_path.startswith("repo/"):
            # Path already has repo/ prefix, use as is
            test_file_path = file_path
        else:
            # See if the path starts with any of the project directories
            project_prefix = None
            for project_dir in repo_dirs:
                if file_path.startswith(f"{project_dir}/"):
                    project_prefix = project_dir
                    break

            if project_prefix:
                # Path starts with a project directory, put it in the repo
                test_file_path = os.path.join(repo_path, file_path)
            elif "/" in file_path:
                # Path contains subdirectories but doesn't match a known project
                # This is likely a new project directory structure, put it in repo
                test_file_path = os.path.join(repo_path, file_path)
            else:
                # Simple filename with no directory structure
                test_file_path = os.path.join(repo_path, file_path)

        # Log the file path transformation
        logger.info(
            f"[AI2-TESTER] Converting file path '{file_path}' to test path '{test_file_path}'"
        )

        # Now determine the appropriate test filename based on extension
        base_name, ext = os.path.splitext(test_file_path)

        if ext == ".py":
            return f"{base_name}_test.py"
        elif ext == ".js":
            return f"{base_name}.test.js"
        elif ext == ".ts":
            return f"{base_name}.spec.ts"
        elif ext == ".jsx":
            return f"{base_name}.test.jsx"
        elif ext == ".tsx":
            return f"{base_name}.test.tsx"
        elif ext == ".vue":
            return f"{base_name}.spec.js"
        elif ext == ".html":
            return f"{base_name}_test.html"
        elif ext == ".css":
            return f"{base_name}_test.css"
        elif ext == ".md":
            # For markdown files, create a test for validating the markdown syntax
            return f"{base_name}_test.md"
        else:
            return f"{base_name}_test{ext}"


async def run_ai2_tester(providers=None):
    """Run the AI2 tester with the given providers."""
    if not providers:
        # Default providers from configuration
        ai_config = config.get("ai_config", {}).get("ai2", {})
        providers = ai_config.get("providers", {}).get(
            "tester", ["codestral", "groq", "gemini"]
        )

    logger.info(f"Configured providers for role 'tester': {', '.join(providers)}")
    processor = TaskProcessor(providers)

    # Example task processing loop
    while True:
        try:
            # Fetch task from queue or API
            task = await fetch_task("tester")
            if task:
                await processor.process_task(task)
            else:
                # No task available, wait a bit
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in AI2 tester: {str(e)}", exc_info=True)
            await asyncio.sleep(10)


async def fetch_task(role):
    """Fetch a task for the given role from the API."""
    api_url = f"{MCP_API_URL}/task/{role}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("subtask")
                else:
                    logger.warning(f"Failed to fetch task: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching task: {str(e)}")
        return None


class TaskProcessor:
    """
    Processes testing tasks for different file types.
    This is the replacement for functionality that was in ai2_tester.py.
    """

    def __init__(self, providers):
        self.providers = providers

    def get_file_type(self, file_ext):
        """Determine the file type based on the file extension."""
        file_type_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".html": "HTML",
            ".htm": "HTML",
            ".css": "CSS",
            ".scss": "SCSS",
            ".jsx": "React",
            ".tsx": "React TypeScript",
            ".vue": "Vue",
            ".java": "Java",
            ".cpp": "C++",
            ".c": "C",
            ".hpp": "C++ Header",
            ".h": "C/C++ Header",
            ".go": "Go",
            ".rs": "Rust",
        }
        return file_type_map.get(file_ext)

    async def process_task(self, task):
        """Process a testing task."""
        task_id = task.get("id")
        # --- CHANGE: Use 'filename' instead of 'file_path' ---
        filename = task.get("filename")
        # --- END CHANGE ---

        if not filename:
            # --- CHANGE: Update error message to reflect 'filename' ---
            logger.error(f"No filename specified in task: {task}")
            # --- END CHANGE ---
            return

        logger.info(f"Received task: ID={task_id}, File={filename}")

        try:
            file_ext = os.path.splitext(filename)[1].lower()
            file_type = self.get_file_type(file_ext)

            if file_type:
                log_message(
                    f"[AI2-TESTER] Generating tests for {file_type} file: {filename}"
                )

                # Select provider
                provider = None
                provider_name = None

                try:
                    for provider_option in self.providers:
                        provider_name = provider_option
                        log_message(
                            f"[AI2-TESTER] Attempting to generate tests with provider '{provider_name}'"
                        )

                        try:
                            # Use ProviderFactory instead of create_provider
                            provider = ProviderFactory.create_provider(provider_name)

                            # --- CHANGE: Get code content from task dictionary ---
                            # Read the file content
                            # with open(file_path, 'r', encoding='utf-8') as f:
                            #     file_content = f.read()
                            file_content = task.get("code")  # Get code from task
                            if file_content is None:
                                logger.error(
                                    f"Missing 'code' content in tester task: {task}"
                                )
                                # Optionally, try reading from file as fallback?
                                # For now, raise error to indicate missing data.
                                raise ValueError(
                                    f"Missing 'code' content in tester task for {filename}"
                                )
                            # --- END CHANGE ---

                            # Generate tests based on file type
                            if file_ext in [".html", ".htm"]:
                                test_content = await self.generate_html_tests(
                                    provider, file_content, filename
                                )
                            elif file_ext == ".css":
                                test_content = await self.generate_css_tests(
                                    provider, file_content, filename
                                )
                            elif file_ext == ".py":
                                test_content = await self.generate_python_tests(
                                    provider, file_content, filename
                                )
                            elif file_ext == ".js":
                                test_content = await self.generate_js_tests(
                                    provider, file_content, filename
                                )
                            elif file_ext == ".ts":
                                test_content = await self.generate_ts_tests(
                                    provider, file_content, filename
                                )
                            else:
                                test_content = await self.generate_generic_tests(
                                    provider, file_content, filename
                                )

                            if test_content and len(test_content.strip()) > 0:
                                # Write tests to file
                                test_file_path = self.get_test_file_path(filename)
                                os.makedirs(
                                    os.path.dirname(test_file_path), exist_ok=True
                                )
                                with open(test_file_path, "w", encoding="utf-8") as f:
                                    f.write(test_content)

                                log_message(
                                    f"[AI2-TESTER] Tests generated and saved to {test_file_path}"
                                )

                                # Successfully processed
                                break
                            else:
                                raise Exception("Provider returned empty test content")

                        except Exception as e:
                            logger.warning(
                                f"Provider '{provider_name}' failed: {str(e)}"
                            )
                            continue
                        finally:
                            # Ensure provider is closed properly - MAKE SURE we close any provider resources
                            if provider:
                                # Try both close_session and close methods
                                if hasattr(provider, "close_session") and callable(
                                    getattr(provider, "close_session")
                                ):
                                    try:
                                        await provider.close_session()
                                    except Exception as e:
                                        logger.warning(
                                            f"Error closing provider session: {e}"
                                        )
                                elif hasattr(provider, "close") and callable(
                                    getattr(provider, "close")
                                ):
                                    try:
                                        await provider.close()
                                    except Exception as e:
                                        logger.warning(f"Error closing provider: {e}")

                    if not provider:
                        raise Exception("All providers failed")

                finally:
                    # No additional cleanup needed here - moved to within the provider loop
                    pass

                # Send the report
                report_data = {
                    "message": f"Task processing successfully completed for {filename} (tester)",
                    "role": "tester",
                    "file": filename,
                    "status": "success",
                    "processing_time": 5.0,  # Placeholder
                    "report_type": "test_result",
                }
                log_message(json.dumps(report_data))

            else:
                logger.warning(f"Unsupported file type for testing: {file_ext}")

        except Exception as e:
            logger.error(f"Error processing task: {str(e)}", exc_info=True)
            report_data = {
                "message": f"Task processing failed for {filename} (tester)",
                "role": "tester",
                "file": filename,
                "status": "error",
                "error_message": str(e),
                "report_type": "error",
            }
            log_message(json.dumps(report_data))

    def get_test_file_path(self, file_path):
        """Convert a file path to its corresponding test file path.

        This method ensures that all test files are created within the repository directory.
        """
        # Ensure we're working with the repo path
        repo_path = os.path.join(os.getcwd(), "repo")

        # Get the root directories in the repo to identify project folders
        try:
            repo_dirs = [
                d
                for d in os.listdir(repo_path)
                if os.path.isdir(os.path.join(repo_path, d)) and not d.startswith(".")
            ]
        except Exception as e:
            logger.warning(f"Error listing repo directories: {e}. Using empty list.")
            repo_dirs = []

        # Check if file_path already has repo/ at the beginning
        if file_path.startswith("repo/"):
            # Path already has repo/ prefix, use as is
            test_file_path = file_path
        else:
            # See if the path starts with any of the project directories
            project_prefix = None
            for project_dir in repo_dirs:
                if file_path.startswith(f"{project_dir}/"):
                    project_prefix = project_dir
                    break

            if project_prefix:
                # Path starts with a project directory, put it in the repo
                test_file_path = os.path.join(repo_path, file_path)
            elif "/" in file_path:
                # Path contains subdirectories but doesn't match a known project
                # This is likely a new project directory structure, put it in repo
                test_file_path = os.path.join(repo_path, file_path)
            else:
                # Simple filename with no directory structure
                test_file_path = os.path.join(repo_path, file_path)

        # Log the file path transformation
        logger.info(
            f"[AI2-TESTER] Converting file path '{file_path}' to test path '{test_file_path}'"
        )

        # Now determine the appropriate test filename based on extension
        base_name, ext = os.path.splitext(test_file_path)

        if ext == ".py":
            return f"{base_name}_test.py"
        elif ext == ".js":
            return f"{base_name}.test.js"
        elif ext == ".ts":
            return f"{base_name}.spec.ts"
        elif ext == ".jsx":
            return f"{base_name}.test.jsx"
        elif ext == ".tsx":
            return f"{base_name}.test.tsx"
        elif ext == ".vue":
            return f"{base_name}.spec.js"
        elif ext == ".html":
            return f"{base_name}_test.html"
        elif ext == ".css":
            return f"{base_name}_test.css"
        elif ext == ".md":
            # For markdown files, create a test for validating the markdown syntax
            return f"{base_name}_test.md"
        else:
            return f"{base_name}_test{ext}"

    async def generate_html_tests(self, provider, content, file_path):
        """Generate tests for HTML files."""
        prompt = f"""
Generate tests for the HTML file using tools like Jest + Testing Library, or a similar testing framework.
For HTML specifically, consider:
1. Structure validation
2. Accessibility testing
3. Responsive design tests

HTML content:
```html
{content}
```

Output: JavaScript tests for this HTML file.
"""
        system_prompt = "You are an HTML testing expert. Generate complete, working tests for the provided HTML file."

        return await provider.generate(prompt=prompt, system_prompt=system_prompt)

    async def generate_css_tests(self, provider, content, file_path):
        """Generate tests for CSS files."""
        prompt = f"""
Generate tests for the CSS file using tools like Jest + CSS testing utilities.
For CSS specifically, consider:
1. Style application verification
2. Responsive design breakpoints
3. Visual regression tests

CSS content:
```css
{content}
```

Output: JavaScript tests for this CSS file.
"""
        system_prompt = "You are a CSS testing expert. Generate complete, working tests for the provided CSS file."

        return await provider.generate(prompt=prompt, system_prompt=system_prompt)

    async def generate_python_tests(self, provider, content, file_path):
        """Generate tests for Python files."""
        prompt = f"""
Generate tests for the Python file using pytest or unittest.
For Python specifically, consider:
1. Function/method testing
2. Edge cases
3. Exception handling

Python content:
```python
{content}
```

Output: Python tests for this Python file.
"""
        system_prompt = "You are a Python testing expert. Generate complete, working pytest tests for the provided Python file."

        return await provider.generate(prompt=prompt, system_prompt=system_prompt)

    async def generate_js_tests(self, provider, content, file_path):
        """Generate tests for JavaScript files."""
        prompt = f"""
Generate tests for the JavaScript file using Jest, Mocha, or a similar testing framework.
For JavaScript specifically, consider:
1. Function testing
2. Asynchronous code testing
3. DOM manipulation (if applicable)

JavaScript content:
```javascript
{content}
```

Output: JavaScript tests for this JavaScript file.
"""
        system_prompt = "You are a JavaScript testing expert. Generate complete, working tests for the provided JavaScript file."

        return await provider.generate(prompt=prompt, system_prompt=system_prompt)

    async def generate_ts_tests(self, provider, content, file_path):
        """Generate tests for TypeScript files."""
        prompt = f"""
Generate tests for the TypeScript file using Jest, Mocha, or a similar testing framework with TypeScript support.
For TypeScript specifically, consider:
1. Type checking in tests
2. Function testing
3. Asynchronous code testing

TypeScript content:
```typescript
{content}
```

Output: TypeScript tests for this TypeScript file.
"""
        system_prompt = "You are a TypeScript testing expert. Generate complete, working tests for the provided TypeScript file."

        return await provider.generate(prompt=prompt, system_prompt=system_prompt)

    async def generate_generic_tests(
        self, provider, content: str, filename: str
    ) -> str:
        """Generate tests for files of unknown type."""
        log_message(
            f"[AI2-TESTER] Generating tests for file of unknown type: {filename}"
        )

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

        # If provider is passed, use it directly, otherwise use _generate_with_fallback
        if provider:
            system_prompt = "You are a testing expert. Generate appropriate tests for the provided code file."
            return await provider.generate(prompt=prompt, system_prompt=system_prompt)
        else:
            return await self._generate_with_fallback(
                system_prompt="You are a testing expert. Generate appropriate tests for the provided code file.",
                user_prompt=prompt,
            )


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

    if args.role == "tester":
        # Configuration
        ai_config = config.get("ai_config", {}).get("ai2", {})
        providers = ai_config.get("providers", {}).get(
            "tester", ["codestral", "groq", "gemini"]
        )
        logger.info(
            f"AI2-TESTER - Provider for role 'tester' configured: {providers[0]}"
        )
        logger.info(
            f"AI2-TESTER - Configured providers for role 'tester': {', '.join(providers)}"
        )
        logger.info(f"AI2 worker (tester) started.")

        # Run tester
        asyncio.run(run_ai2_tester(providers))
    else:
        # Run standard AI2 worker for executor or documenter
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


class CodeValidator:
    """Advanced code validation and pattern matching for AI2"""

    def __init__(self):
        self.test_generators = {
            "python": self._generate_python_tests,
            "javascript": self._generate_js_tests,
            "typescript": self._generate_ts_tests,
            "go": self._generate_go_tests,
            "java": self._generate_java_tests,
            "rust": self._generate_rust_tests,
        }
        self.validators = {
            "python": self._validate_python,
            "javascript": self._validate_javascript,
            "typescript": self._validate_typescript,
            "go": self._validate_go,
            "java": self._validate_java,
            "rust": self._validate_rust,
        }
        self.code_metrics = CodeQualityAnalyzer()

    async def validate_code(
        self, code: str, language: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate generated code against multiple criteria"""
        if language not in self.validators:
            logger.error(f"Unsupported language for validation: {language}")
            return {"valid": False, "errors": [f"Unsupported language: {language}"]}

        results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "metrics": {},
            "test_coverage": 0.0,
        }

        # Run language-specific validation
        validation_result = await self.validators[language](code, context)
        results.update(validation_result)

        # Generate and run tests
        test_result = await self.generate_and_run_tests(code, language, context)
        results["test_coverage"] = test_result.get("coverage", 0.0)
        results["test_results"] = test_result.get("results", [])

        # Calculate code quality metrics
        metrics = await self.code_metrics.analyze(code, language)
        results["metrics"] = metrics

        # Check for potential security issues
        security_issues = await self._check_security(code, language)
        if security_issues:
            results["warnings"].extend(security_issues)

        # Check for performance concerns
        perf_issues = await self._check_performance(code, language)
        if perf_issues:
            results["warnings"].extend(perf_issues)

        return results

    async def _validate_python(
        self, code: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Python-specific validation"""
        result = {"valid": True, "errors": [], "warnings": []}

        try:
            # Check syntax
            compile(code, "<string>", "exec")

            # Check type hints if enabled in context
            if context.get("type_checking", True):
                await self._check_python_types(code, result)

            # Check style (PEP 8)
            style_issues = await self._check_python_style(code)
            if style_issues:
                result["warnings"].extend(style_issues)

            # Check imports
            import_issues = await self._check_python_imports(code, context)
            if import_issues:
                result["warnings"].extend(import_issues)

        except SyntaxError as e:
            result["valid"] = False
            result["errors"].append(f"Syntax error: {str(e)}")
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Validation error: {str(e)}")

        return result

    async def _generate_python_tests(self, code: str, context: Dict[str, Any]) -> str:
        """Generate Python unit tests for the given code"""
        test_code = []

        # Extract classes and functions
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                test_cases = await self._generate_test_cases(node, code)
                test_code.extend(test_cases)

        return "\n".join(test_code)

    async def _generate_test_cases(self, node: ast.AST, code: str) -> List[str]:
        """Generate test cases for a Python class or function"""
        test_cases = []

        if isinstance(node, ast.ClassDef):
            # Generate class test cases
            test_cases.extend(await self._generate_class_tests(node))
        elif isinstance(node, ast.FunctionDef):
            # Generate function test cases
            test_cases.extend(await self._generate_function_tests(node))

        return test_cases

    async def _generate_class_tests(self, node: ast.ClassDef) -> List[str]:
        """Generate test cases for a Python class"""
        test_cases = []

        # Generate class setup
        test_cases.append(
            f"""
class Test{node.name}(unittest.TestCase):
    def setUp(self):
        self.instance = {node.name}()
"""
        )

        # Generate method tests
        for method in [n for n in node.body if isinstance(n, ast.FunctionDef)]:
            if not method.name.startswith("_"):  # Skip private methods
                test_cases.extend(await self._generate_method_test(method))

        return test_cases

    async def _generate_method_test(self, node: ast.FunctionDef) -> List[str]:
        """Generate test cases for a class method"""
        test_cases = []

        # Generate positive test case
        test_cases.append(
            f"""
    def test_{node.name}_valid(self):
        # TODO: Add test implementation
        pass
"""
        )

        # Generate negative test case
        test_cases.append(
            f"""
    def test_{node.name}_invalid(self):
        # TODO: Add test implementation
        pass
"""
        )

        return test_cases

    async def _generate_function_tests(self, node: ast.FunctionDef) -> List[str]:
        """Generate test cases for a standalone function"""
        test_cases = []

        # Generate test function
        test_cases.append(
            f"""
def test_{node.name}():
    # TODO: Add test implementation
    pass
"""
        )

        return test_cases

    async def _check_security(self, code: str, language: str) -> List[str]:
        """Check for security vulnerabilities in the code"""
        security_issues = []

        # Common security patterns to check
        patterns = {
            "sql_injection": r'execute\s*\(\s*[\'"].*?\%.*?[\'"]\s*\)',
            "command_injection": r"exec\s*\(\s*.*?\+.*?\s*\)",
            "xss": r"innerHTML\s*=",
            "hardcoded_secrets": r'password\s*=\s*[\'"][^\'"]+[\'"]',
        }

        for issue_type, pattern in patterns.items():
            if re.search(pattern, code):
                security_issues.append(f"Potential {issue_type} vulnerability detected")

        return security_issues

    async def _check_performance(self, code: str, language: str) -> List[str]:
        """Check for performance issues in the code"""
        performance_issues = []

        # Check for nested loops
        if re.search(r"for.*?\{.*?for.*?\{.*?\}", code, re.DOTALL):
            performance_issues.append("Nested loops detected - consider optimization")

        # Check for large object creation in loops
        if re.search(r"for.*?\{.*?new\s+\w+.*?\}", code, re.DOTALL):
            performance_issues.append(
                "Object creation inside loop - consider moving outside"
            )

        return performance_issues

    async def _check_python_types(self, code: str, result: Dict[str, Any]) -> None:
        """Check Python type hints"""
        try:
            import mypy.api

            out, err, exit_code = mypy.api.run(["-c", code])
            if exit_code != 0:
                result["warnings"].append(f"Type checking issues: {out}")
        except ImportError:
            result["warnings"].append("mypy not available for type checking")

    async def _check_python_style(self, code: str) -> List[str]:
        """Check Python code style (PEP 8)"""
        style_issues = []
        try:
            import pycodestyle

            style_guide = pycodestyle.StyleGuide(quiet=True)
            result = style_guide.input_file(io.StringIO(code))
            if result.total_errors > 0:
                style_issues.append(f"Found {result.total_errors} style issues")
        except ImportError:
            style_issues.append("pycodestyle not available for style checking")
        return style_issues

    async def _check_python_imports(
        self, code: str, context: Dict[str, Any]
    ) -> List[str]:
        """Check Python imports"""
        import_issues = []
        allowed_imports = context.get("allowed_imports", set())
        tree = ast.parse(code)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name not in allowed_imports:
                        import_issues.append(f"Unauthorized import: {name.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module not in allowed_imports:
                    import_issues.append(f"Unauthorized import: {node.module}")

        return import_issues


class CodeQualityAnalyzer:
    """Analyzes code quality metrics"""

    def __init__(self):
        self.metrics = {
            "cyclomatic_complexity": self._calculate_cyclomatic_complexity,
            "maintainability_index": self._calculate_maintainability_index,
            "code_duplication": self._detect_code_duplication,
        }

    async def analyze(self, code: str, language: str) -> Dict[str, Any]:
        """Analyze code quality metrics"""
        results = {}

        for metric_name, calculator in self.metrics.items():
            try:
                results[metric_name] = await calculator(code, language)
            except Exception as e:
                logger.error(f"Error calculating {metric_name}: {e}")
                results[metric_name] = None

        return results

    async def _calculate_cyclomatic_complexity(self, code: str, language: str) -> int:
        """Calculate cyclomatic complexity"""
        complexity = 1  # Base complexity

        # Count decision points
        decision_patterns = [
            r"\bif\b",
            r"\belse\b",
            r"\bfor\b",
            r"\bwhile\b",
            r"\bcase\b",
            r"\bcatch\b",
        ]

        for pattern in decision_patterns:
            complexity += len(re.findall(pattern, code))

        return complexity

    async def _calculate_maintainability_index(self, code: str, language: str) -> float:
        """Calculate maintainability index"""
        # Halstead Volume calculation (simplified)
        operators = len(re.findall(r"[+\-*/=<>!&|]", code))
        operands = len(re.findall(r"\b[a-zA-Z_]\w*\b", code))

        # Lines of code
        loc = len(code.splitlines())

        # Cyclomatic complexity
        cc = await self._calculate_cyclomatic_complexity(code, language)

        # Maintainability Index formula
        mi = (
            171
            - 5.2 * math.log(operators + operands)
            - 0.23 * cc
            - 16.2 * math.log(loc)
        )
        return max(0, min(100, mi))

    async def _detect_code_duplication(
        self, code: str, language: str
    ) -> Dict[str, Any]:
        """Detect code duplication"""
        MIN_DUPLICATE_LENGTH = 5  # Minimum lines to consider as duplication

        lines = code.splitlines()
        duplicates = []

        for i in range(len(lines)):
            for j in range(i + MIN_DUPLICATE_LENGTH, len(lines)):
                # Compare sequence of lines
                sequence_length = 0
                while (
                    i + sequence_length < len(lines)
                    and j + sequence_length < len(lines)
                    and lines[i + sequence_length] == lines[j + sequence_length]
                ):
                    sequence_length += 1

                if sequence_length >= MIN_DUPLICATE_LENGTH:
                    duplicates.append(
                        {
                            "start1": i,
                            "start2": j,
                            "length": sequence_length,
                            "content": "\n".join(lines[i : i + sequence_length]),
                        }
                    )

        return {"duplicate_blocks": len(duplicates), "details": duplicates}

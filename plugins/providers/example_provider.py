"""
Example Provider Plugin for AI-SYSTEMS

This is a template that demonstrates how to create a custom provider plugin.
To create your own provider:
1. Copy this file to plugins/providers/your_provider_name.py
2. Update the class name and implementation
3. Restart the API server

Your provider will be automatically discovered and available for use in AI-SYSTEMS.
"""

import logging
import os
from typing import Any, Dict, List, Optional

# Import the BaseProvider class from the parent directory
from providers import BaseProvider

# Set up logging
logger = logging.getLogger(__name__)


class ExampleProvider(BaseProvider):
    """Example provider plugin for AI-SYSTEMS."""

    # Optional: Set a custom provider_type - if not set, lowercase class name without 'Provider' suffix will be used
    provider_type = "example"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the provider with configuration.

        Args:
            config: Configuration dictionary from config.json or provider factory
        """
        super().__init__(config)
        self.name = "example"  # Set a name for logging

        # Get API key from config or environment variable
        self.api_key = self.config.get("api_key") or os.environ.get("EXAMPLE_API_KEY")

        # Get endpoint from config or use default
        self.endpoint = self.config.get("endpoint") or "https://api.example.com/v1"

        # Initialize any other needed properties
        self._client = None

        # Call setup to initialize the provider
        self.setup()

    def setup(self) -> None:
        """Set up the provider and check availability."""
        # Check if API key is available
        if not self.api_key:
            logger.warning(
                "API key for Example Provider not found in config or EXAMPLE_API_KEY"
            )
        else:
            logger.info("Example Provider API key found")

        # Perform any other setup needed
        logger.info(f"Example Provider configured with endpoint: {self.endpoint}")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Generate a response to the prompt.

        Args:
            prompt: The main user prompt
            system_prompt: System instructions (optional)
            model: The model to use (optional, falls back to config)
            max_tokens: Maximum tokens in response (optional)
            temperature: Creativity parameter (optional)

        Returns:
            The generated text response
        """
        # Return error if not properly configured
        if not self.api_key:
            return "Error: Example Provider API key not set."

        # Get parameters, falling back to configuration defaults
        model_to_use = model or self.get_default_model() or "example-model"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens", 2000)
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        # Prepare the request
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            # This is where you would implement the actual API call to your LLM provider
            # For example:
            # session = await self.get_client_session()  # BaseProvider handles session management
            # async with session.post(f"{self.endpoint}/completions", json=payload, headers=headers) as response:
            #     response_data = await response.json()
            #     return response_data["choices"][0]["message"]["content"]

            # Placeholder implementation for this example
            logger.info(
                f"Example Provider would call model {model_to_use} with {len(messages)} messages"
            )
            return f"This is a simulated response from Example Provider using model '{model_to_use}'"

        except Exception as e:
            logger.error(f"Error generating response with Example Provider: {e}")
            return f"Error: {str(e)}"

    async def get_available_models(self) -> List[str]:
        """Get a list of available models for this provider.

        Returns:
            List of model names
        """
        # In a real implementation, you might query the API for available models
        # For this example, we just return a static list
        models = ["example-basic", "example-advanced", "example-large"]

        # Add the default model if it's not in the list
        default_model = self.get_default_model()
        if default_model and default_model not in models:
            models.append(default_model)

        return models

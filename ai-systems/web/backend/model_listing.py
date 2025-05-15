#!/usr/bin/env python3
"""
Model Listing Utility for AI-SYSTEMS
Fetches and lists available models from various AI providers
"""

import os
import json
import aiohttp
import asyncio
import logging
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ModelLister:
    """Utility class to list available models from various AI providers"""
    
    def __init__(self):
        # Provider base URLs
        self.providers = {
            "ollama_local": "http://localhost:11434",
            "ollama_remote": "http://46.219.108.236:11434",
            "huggingface": "https://huggingface.co/api",
            "replicate": "https://api.replicate.com/v1",
            "perplexity": "https://api.perplexity.ai",
            "anyscale": "https://api.endpoints.anyscale.com/v1",
            "deepinfra": "https://deepinfra.com/api/v1",
            "fireworks": "https://api.fireworks.ai/inference/v1",
            "grok": "https://api.grok.ai/v1",
            "codestral": "https://api.codestral.com/v1"
        }
        
        # Load API keys from environment variables
        self.api_keys = {
            "huggingface": os.getenv("HUGGINGFACE_API_KEY"),
            "replicate": os.getenv("REPLICATE_API_KEY"),
            "perplexity": os.getenv("PERPLEXITY_API_KEY"),
            "anyscale": os.getenv("ANYSCALE_API_KEY"),
            "deepinfra": os.getenv("DEEPINFRA_API_KEY"),
            "fireworks": os.getenv("FIREWORKS_API_KEY"),
            "grok": os.getenv("GROK_API_KEY"),
            "codestral": os.getenv("CODESTRAL_API_KEY")
        }
        
        # Support for multiple API keys
        self._load_multiple_api_keys()
    
    def _load_multiple_api_keys(self):
        """Load multiple API keys for each provider (e.g., CODESTRAL_API_KEY, CODESTRAL2_API_KEY, etc.)"""
        for provider in self.api_keys.keys():
            provider_keys = []
            # Add the primary key if it exists
            if self.api_keys[provider]:
                provider_keys.append(self.api_keys[provider])
            
            # Check for additional numbered keys
            i = 2
            while True:
                key_name = f"{provider.upper()}{i}_API_KEY"
                key_value = os.getenv(key_name)
                if key_value:
                    provider_keys.append(key_value)
                    i += 1
                else:
                    break
            
            # Replace single key with list of keys
            if provider_keys:
                self.api_keys[provider] = provider_keys
    
    async def verify_ollama_availability(self, provider: str) -> Dict[str, Any]:
        """Verify if an Ollama provider (local or remote) is available by checking /api/tags endpoint"""
        if provider not in ["ollama_local", "ollama_remote"]:
            return {"available": False, "error": f"Invalid Ollama provider: {provider}"}
        
        base_url = self.providers[provider]
        endpoint = f"{base_url}/api/tags"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, timeout=5) as response:
                    if response.status == 200:
                        return {
                            "available": True,
                            "status_code": response.status,
                            "provider": provider
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "available": False,
                            "status_code": response.status,
                            "error": f"Server responded with error: {error_text}",
                            "provider": provider
                        }
        except asyncio.TimeoutError:
            logger.error(f"Timeout connecting to {provider} at {endpoint}")
            return {
                "available": False,
                "error": "Connection timeout",
                "provider": provider
            }
        except Exception as e:
            logger.error(f"Error verifying {provider} availability: {str(e)}")
            return {
                "available": False,
                "error": f"Connection error: {str(e)}",
                "provider": provider
            }
    
    async def list_ollama_models(self, provider: str) -> Dict[str, Any]:
        """List models available from an Ollama provider (local or remote)"""
        if provider not in ["ollama_local", "ollama_remote"]:
            return {"error": f"Invalid Ollama provider: {provider}"}
        
        # First verify if the Ollama endpoint is available
        availability = await self.verify_ollama_availability(provider)
        if not availability["available"]:
            return {
                "provider": provider,
                "error": f"Ollama endpoint unavailable: {availability.get('error', 'Unknown error')}",
                "status": "error",
                "available": False
            }
        
        base_url = self.providers[provider]
        endpoint = f"{base_url}/api/tags"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": provider,
                            "models": data.get("models", []),
                            "count": len(data.get("models", [])),
                            "status": "success",
                            "available": True
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": provider,
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status,
                            "available": False
                        }
        except Exception as e:
            logger.error(f"Error fetching Ollama models from {provider}: {str(e)}")
            return {
                "provider": provider,
                "error": f"Connection error: {str(e)}",
                "status": "error",
                "available": False
            }
    
    async def list_huggingface_models(self, filter_query: str = None) -> Dict[str, Any]:
        """List models available from Hugging Face"""
        if not self.api_keys.get("huggingface"):
            return {"provider": "huggingface", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["huggingface"]
        endpoint = f"{base_url}/models"
        params = {"full": "true"}
        
        if filter_query:
            params["search"] = filter_query
        
        headers = {"Authorization": f"Bearer {self.api_keys['huggingface'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "huggingface",
                            "models": data,
                            "count": len(data),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "huggingface",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Hugging Face models: {str(e)}")
            return {
                "provider": "huggingface",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_replicate_models(self) -> Dict[str, Any]:
        """List models available from Replicate"""
        if not self.api_keys.get("replicate"):
            return {"provider": "replicate", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["replicate"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Token {self.api_keys['replicate'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "replicate",
                            "models": data.get("results", []),
                            "count": len(data.get("results", [])),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "replicate",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Replicate models: {str(e)}")
            return {
                "provider": "replicate",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_anyscale_models(self) -> Dict[str, Any]:
        """List models available from Anyscale"""
        if not self.api_keys.get("anyscale"):
            return {"provider": "anyscale", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["anyscale"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_keys['anyscale'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "anyscale",
                            "models": data.get("data", []),
                            "count": len(data.get("data", [])),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "anyscale",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Anyscale models: {str(e)}")
            return {
                "provider": "anyscale",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_deepinfra_models(self) -> Dict[str, Any]:
        """List models available from DeepInfra"""
        if not self.api_keys.get("deepinfra"):
            return {"provider": "deepinfra", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["deepinfra"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_keys['deepinfra'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "deepinfra",
                            "models": data,
                            "count": len(data),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "deepinfra",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching DeepInfra models: {str(e)}")
            return {
                "provider": "deepinfra",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_fireworks_models(self) -> Dict[str, Any]:
        """List models available from Fireworks"""
        if not self.api_keys.get("fireworks"):
            return {"provider": "fireworks", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["fireworks"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_keys['fireworks'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "fireworks",
                            "models": data.get("data", []),
                            "count": len(data.get("data", [])),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "fireworks",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Fireworks models: {str(e)}")
            return {
                "provider": "fireworks",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_perplexity_models(self) -> Dict[str, Any]:
        """List models available from Perplexity AI"""
        if not self.api_keys.get("perplexity"):
            return {"provider": "perplexity", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["perplexity"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_keys['perplexity'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "perplexity",
                            "models": data.get("models", []),
                            "count": len(data.get("models", [])),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "perplexity",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Perplexity models: {str(e)}")
            return {
                "provider": "perplexity",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_grok_models(self) -> Dict[str, Any]:
        """List models available from Grok AI"""
        if not self.api_keys.get("grok"):
            return {"provider": "grok", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["grok"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_keys['grok'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "grok",
                            "models": data.get("data", []),
                            "count": len(data.get("data", [])),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "grok",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Grok models: {str(e)}")
            return {
                "provider": "grok",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def list_codestral_models(self) -> Dict[str, Any]:
        """List models available from Codestral"""
        if not self.api_keys.get("codestral"):
            return {"provider": "codestral", "error": "API key not found", "status": "error"}
        
        base_url = self.providers["codestral"]
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_keys['codestral'][0]}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "provider": "codestral",
                            "models": data.get("data", []),
                            "count": len(data.get("data", [])),
                            "status": "success"
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "provider": "codestral",
                            "error": f"Failed to fetch models: {error_text}",
                            "status": "error",
                            "status_code": response.status
                        }
        except Exception as e:
            logger.error(f"Error fetching Codestral models: {str(e)}")
            return {
                "provider": "codestral",
                "error": f"Connection error: {str(e)}",
                "status": "error"
            }
    
    async def verify_all_ollama_endpoints(self) -> Dict[str, Dict[str, Any]]:
        """Verify availability of all Ollama endpoints"""
        tasks = [
            self.verify_ollama_availability("ollama_local"),
            self.verify_ollama_availability("ollama_remote")
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        availability_results = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in Ollama availability check: {str(result)}")
                continue
                
            provider = result.get("provider")
            if provider:
                availability_results[provider] = result
        
        return {
            "endpoints": availability_results,
            "timestamp": asyncio.get_event_loop().time()
        }
    
    async def list_all_models(self) -> Dict[str, List[Dict[str, Any]]]:
        """List models from all configured providers"""
        tasks = [
            self.list_ollama_models("ollama_local"),
            self.list_ollama_models("ollama_remote"),
            self.list_huggingface_models(),
            self.list_replicate_models(),
            self.list_anyscale_models(),
            self.list_deepinfra_models(),
            self.list_fireworks_models(),
            self.list_perplexity_models(),
            self.list_grok_models(),
            self.list_codestral_models()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        provider_results = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in provider request: {str(result)}")
                continue
                
            provider = result.get("provider")
            if provider:
                provider_results[provider] = result
        
        return {
            "providers": provider_results,
            "count": len(provider_results),
            "timestamp": asyncio.get_event_loop().time()
        }

# Command-line interface
async def main():
    """Command-line interface for the model lister"""
    import argparse
    
    parser = argparse.ArgumentParser(description="List models from AI providers")
    parser.add_argument("--provider", type=str, help="Provider to list models from (e.g., ollama_local)")
    parser.add_argument("--all", action="store_true", help="List models from all providers")
    parser.add_argument("--verify-ollama", action="store_true", help="Verify Ollama endpoints availability")
    parser.add_argument("--output", type=str, help="Output file path (JSON)")
    
    args = parser.parse_args()
    lister = ModelLister()
    
    if args.verify_ollama:
        results = await lister.verify_all_ollama_endpoints()
        output = results
    elif args.all:
        results = await lister.list_all_models()
        output = results
    elif args.provider:
        if args.provider.startswith("ollama"):
            results = await lister.list_ollama_models(args.provider)
        elif args.provider == "huggingface":
            results = await lister.list_huggingface_models()
        elif args.provider == "replicate":
            results = await lister.list_replicate_models()
        elif args.provider == "anyscale":
            results = await lister.list_anyscale_models()
        elif args.provider == "deepinfra":
            results = await lister.list_deepinfra_models()
        elif args.provider == "fireworks":
            results = await lister.list_fireworks_models()
        elif args.provider == "perplexity":
            results = await lister.list_perplexity_models()
        elif args.provider == "grok":
            results = await lister.list_grok_models()
        elif args.provider == "codestral":
            results = await lister.list_codestral_models()
        else:
            print(f"Unknown provider: {args.provider}")
            return
        
        output = results
    else:
        parser.print_help()
        return
    
    # Output results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"Results written to {args.output}")
    else:
        print(json.dumps(output, indent=2))

if __name__ == "__main__":
    asyncio.run(main())

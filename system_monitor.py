#!/usr/bin/env python3
"""
System Monitor for AI-SYSTEMS

This script monitors:
1. System resources (CPU, memory, disk usage)
2. AI provider API usage and rate limits
3. GitHub integration status and workflow runs
4. Service health checks

It provides metrics via Prometheus and can alert on critical issues.
"""

import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import aiohttp
import psutil
from dotenv import load_dotenv
from prometheus_client import Counter, Gauge, start_http_server

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/system_monitor.log"),
    ],
)
logger = logging.getLogger("system_monitor")

# Constants
CHECK_INTERVAL = 60  # seconds
GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_REPO = os.getenv("GITHUB_REPO_TO_MONITOR", "oleg121203/AI-SYSTEMS-REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "Oleg Kizyma")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "oleg1203@gmail.com")
MAIN_BRANCH = os.getenv("MAIN_BRANCH", "master")

# Prometheus metrics
SYSTEM_CPU_USAGE = Gauge("system_cpu_usage", "CPU usage percentage")
SYSTEM_MEMORY_USAGE = Gauge("system_memory_usage", "Memory usage percentage")
SYSTEM_DISK_USAGE = Gauge("system_disk_usage", "Disk usage percentage")
API_CALLS_TOTAL = Counter(
    "api_calls_total", "Total API calls made", ["provider", "api_key_index"]
)
API_ERRORS_TOTAL = Counter(
    "api_errors_total", "Total API errors encountered", ["provider", "api_key_index"]
)
GITHUB_WORKFLOW_RUNS = Counter(
    "github_workflow_runs", "GitHub workflow runs", ["status", "conclusion"]
)
GITHUB_INTEGRATION_STATUS = Gauge(
    "github_integration_status", "GitHub integration status (1=OK, 0=Error)"
)
SERVICE_HEALTH = Gauge("service_health", "Service health status (1=OK, 0=Error)", ["service"])

class APIKeyManager:
    """Manages multiple API keys for each provider and tracks usage/rate limits"""

    def __init__(self):
        self.api_keys: Dict[str, List[str]] = {}
        self.usage_counts: Dict[str, Dict[int, int]] = {}
        self.rate_limits: Dict[str, Dict[int, Dict[str, Any]]] = {}
        self.load_api_keys_from_env()

    def load_api_keys_from_env(self):
        """Load API keys from environment variables with support for multiple keys per provider"""
        # List of providers to check for
        providers = [
            "OPENAI", "ANTHROPIC", "CODESTRAL", "GEMINI", "GROQ", 
            "COHERE", "TOGETHER", "MISTRAL", "GEMINI3", "GEMINI4"
        ]
        
        for provider in providers:
            # Check for the base key
            base_key = f"{provider}_API_KEY"
            keys = []
            
            # Add the base key if it exists
            if os.getenv(base_key):
                keys.append(os.getenv(base_key))
            
            # Check for numbered variants (e.g., CODESTRAL2_API_KEY)
            for i in range(2, 10):  # Check for keys with suffixes 2-9
                numbered_key = f"{provider}{i}_API_KEY"
                if os.getenv(numbered_key):
                    keys.append(os.getenv(numbered_key))
            
            if keys:
                self.api_keys[provider.lower()] = keys
                self.usage_counts[provider.lower()] = {i: 0 for i in range(len(keys))}
                self.rate_limits[provider.lower()] = {i: {"reset_at": None, "limit": None, "remaining": None} for i in range(len(keys))}
        
        logger.info(f"Loaded API keys for providers: {list(self.api_keys.keys())}")
        logger.info(f"Number of API keys per provider: {[(p, len(keys)) for p, keys in self.api_keys.items()]}")

    def record_api_call(self, provider: str, key_index: int = 0, error: bool = False):
        """Record an API call for a specific provider and key index"""
        if provider.lower() in self.usage_counts and key_index in self.usage_counts[provider.lower()]:
            self.usage_counts[provider.lower()][key_index] += 1
            API_CALLS_TOTAL.labels(provider=provider.lower(), api_key_index=key_index).inc()
            if error:
                API_ERRORS_TOTAL.labels(provider=provider.lower(), api_key_index=key_index).inc()

    def update_rate_limit(self, provider: str, key_index: int, limit: Optional[int], remaining: Optional[int], reset_at: Optional[datetime]):
        """Update rate limit information for a provider and key index"""
        if provider.lower() in self.rate_limits and key_index in self.rate_limits[provider.lower()]:
            self.rate_limits[provider.lower()][key_index] = {
                "limit": limit,
                "remaining": remaining,
                "reset_at": reset_at
            }

    def get_best_key_index(self, provider: str) -> int:
        """Get the best key index to use based on usage and rate limits"""
        if provider.lower() not in self.api_keys or not self.api_keys[provider.lower()]:
            return 0
        
        # If we have rate limit info, use the key with the most remaining calls
        provider_rate_limits = self.rate_limits.get(provider.lower(), {})
        valid_keys = []
        
        for idx in range(len(self.api_keys[provider.lower()])):
            rate_info = provider_rate_limits.get(idx, {})
            
            # If we have rate limit info and it's not expired
            if (rate_info.get("remaining") is not None and 
                rate_info.get("reset_at") is not None and 
                rate_info["reset_at"] > datetime.now()):
                
                if rate_info["remaining"] > 0:
                    valid_keys.append((idx, rate_info["remaining"]))
            else:
                # If we don't have rate info, just use usage count
                valid_keys.append((idx, -self.usage_counts[provider.lower()].get(idx, 0)))
        
        if valid_keys:
            # Sort by remaining calls (or negative usage count) descending
            valid_keys.sort(key=lambda x: x[1], reverse=True)
            return valid_keys[0][0]
        
        # If no valid keys, use round-robin based on usage
        usage_counts = self.usage_counts.get(provider.lower(), {})
        if usage_counts:
            return min(usage_counts.items(), key=lambda x: x[1])[0]
        
        return 0

    def get_api_key(self, provider: str) -> Optional[str]:
        """Get the best API key to use for a provider"""
        if provider.lower() not in self.api_keys or not self.api_keys[provider.lower()]:
            return None
        
        idx = self.get_best_key_index(provider)
        return self.api_keys[provider.lower()][idx]

    def get_usage_report(self) -> Dict[str, Any]:
        """Get a report of API key usage"""
        report = {}
        for provider, keys in self.api_keys.items():
            provider_report = []
            for idx in range(len(keys)):
                key_info = {
                    "index": idx,
                    "usage_count": self.usage_counts.get(provider, {}).get(idx, 0),
                }
                
                rate_info = self.rate_limits.get(provider, {}).get(idx, {})
                if rate_info.get("reset_at"):
                    key_info.update({
                        "limit": rate_info.get("limit"),
                        "remaining": rate_info.get("remaining"),
                        "reset_at": rate_info.get("reset_at").isoformat() if rate_info.get("reset_at") else None,
                        "time_to_reset": str(rate_info.get("reset_at") - datetime.now()) if rate_info.get("reset_at") else None
                    })
                
                provider_report.append(key_info)
            
            report[provider] = provider_report
        
        return report

class GitHubMonitor:
    """Monitors GitHub repository and workflow status"""

    def __init__(self, repo: str = GITHUB_REPO, token: str = GITHUB_TOKEN):
        self.repo = repo
        self.token = token
        self.api_base_url = GITHUB_API_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
        self.processed_run_ids: Set[int] = set()
        self.enabled = bool(self.repo and self.token)
        
        if not self.enabled:
            logger.warning("GitHub monitoring disabled: missing repo or token")

    async def initialize(self):
        """Initialize the GitHub monitor"""
        if not self.enabled:
            return False
        
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "AI-SYSTEMS GitHub Monitor",
            }
        )
        
        # Test connection
        try:
            repo_info = await self.get_repo_info()
            if "id" in repo_info:
                logger.info(f"GitHub monitor initialized for {self.repo}")
                GITHUB_INTEGRATION_STATUS.set(1)
                return True
            else:
                logger.error(f"Failed to initialize GitHub monitor: {repo_info.get('message', 'Unknown error')}")
                GITHUB_INTEGRATION_STATUS.set(0)
                return False
        except Exception as e:
            logger.error(f"Error initializing GitHub monitor: {e}")
            GITHUB_INTEGRATION_STATUS.set(0)
            return False

    async def close(self):
        """Close the session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_repo_info(self) -> Dict[str, Any]:
        """Get information about the repository"""
        if not self.enabled or not self.session:
            return {"error": "GitHub monitoring not enabled or initialized"}
        
        url = f"{self.api_base_url}/repos/{self.repo}"
        
        try:
            async with self.session.get(url) as response:
                return await response.json()
        except Exception as e:
            logger.error(f"Error getting repo info: {e}")
            return {"error": str(e)}

    async def check_workflow_runs(self) -> Dict[str, Any]:
        """Check the status of workflow runs"""
        if not self.enabled or not self.session:
            return {"error": "GitHub monitoring not enabled or initialized"}
        
        url = f"{self.api_base_url}/repos/{self.repo}/actions/runs"
        
        try:
            async with self.session.get(url, params={"per_page": 10}) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    result = {
                        "total_count": data.get("total_count", 0),
                        "runs": []
                    }
                    
                    for run in data.get("workflow_runs", []):
                        run_id = run.get("id")
                        status = run.get("status")
                        conclusion = run.get("conclusion")
                        
                        # Record metrics
                        GITHUB_WORKFLOW_RUNS.labels(
                            status=status or "unknown", 
                            conclusion=conclusion or "unknown"
                        ).inc()
                        
                        # Process new runs
                        if run_id and run_id not in self.processed_run_ids:
                            self.processed_run_ids.add(run_id)
                            logger.info(f"New workflow run: ID {run_id}, Status: {status}, Conclusion: {conclusion}")
                            
                            # If the run failed, we might want to analyze it further
                            if conclusion in ["failure", "timed_out", "cancelled"]:
                                await self.analyze_workflow_run(run_id)
                        
                        result["runs"].append({
                            "id": run_id,
                            "name": run.get("name"),
                            "status": status,
                            "conclusion": conclusion,
                            "created_at": run.get("created_at"),
                            "updated_at": run.get("updated_at"),
                            "url": run.get("html_url")
                        })
                    
                    return result
                else:
                    error_msg = await response.text()
                    logger.error(f"Error checking workflow runs: {response.status} - {error_msg}")
                    return {"error": f"API error: {response.status}", "details": error_msg}
        except Exception as e:
            logger.error(f"Exception in check_workflow_runs: {e}")
            return {"error": str(e)}

    async def analyze_workflow_run(self, run_id: int) -> Dict[str, Any]:
        """Analyze a workflow run to determine if it needs fixing"""
        if not self.enabled or not self.session:
            return {"error": "GitHub monitoring not enabled or initialized"}
        
        url = f"{self.api_base_url}/repos/{self.repo}/actions/runs/{run_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    run_data = await response.json()
                    
                    # Get the logs if available
                    logs_url = f"{self.api_base_url}/repos/{self.repo}/actions/runs/{run_id}/logs"
                    logs_content = None
                    
                    try:
                        async with self.session.get(logs_url, headers={"Accept": "application/vnd.github.v3.raw"}) as logs_response:
                            if logs_response.status == 200:
                                logs_content = await logs_response.read()
                                # Note: This is usually a zip file that would need to be processed
                    except Exception as logs_e:
                        logger.error(f"Error getting logs for run {run_id}: {logs_e}")
                    
                    analysis = {
                        "run_id": run_id,
                        "status": run_data.get("status"),
                        "conclusion": run_data.get("conclusion"),
                        "name": run_data.get("name"),
                        "url": run_data.get("html_url"),
                        "logs_available": logs_content is not None,
                        "needs_fixing": run_data.get("conclusion") in ["failure", "timed_out", "cancelled"],
                        "jobs": []
                    }
                    
                    # Get job details
                    jobs_url = f"{self.api_base_url}/repos/{self.repo}/actions/runs/{run_id}/jobs"
                    try:
                        async with self.session.get(jobs_url) as jobs_response:
                            if jobs_response.status == 200:
                                jobs_data = await jobs_response.json()
                                for job in jobs_data.get("jobs", []):
                                    analysis["jobs"].append({
                                        "id": job.get("id"),
                                        "name": job.get("name"),
                                        "status": job.get("status"),
                                        "conclusion": job.get("conclusion"),
                                        "steps": [
                                            {
                                                "name": step.get("name"),
                                                "status": step.get("status"),
                                                "conclusion": step.get("conclusion")
                                            }
                                            for step in job.get("steps", [])
                                        ]
                                    })
                    except Exception as jobs_e:
                        logger.error(f"Error getting jobs for run {run_id}: {jobs_e}")
                    
                    return analysis
                else:
                    error_msg = await response.text()
                    logger.error(f"Error analyzing workflow run {run_id}: {response.status} - {error_msg}")
                    return {"error": f"API error: {response.status}", "details": error_msg}
        except Exception as e:
            logger.error(f"Exception in analyze_workflow_run: {e}")
            return {"error": str(e)}

    async def create_or_update_file(self, path: str, content: str, message: str, branch: str = MAIN_BRANCH) -> Dict[str, Any]:
        """Create or update a file in the repository"""
        if not self.enabled or not self.session:
            return {"error": "GitHub monitoring not enabled or initialized"}
        
        url = f"{self.api_base_url}/repos/{self.repo}/contents/{path}"
        
        # First check if file already exists
        sha = None
        try:
            async with self.session.get(f"{url}?ref={branch}") as response:
                if response.status == 200:
                    file_info = await response.json()
                    sha = file_info.get("sha")
        except Exception:
            # File probably doesn't exist, which is fine
            pass
        
        # Prepare request payload
        import base64
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": message,
            "content": encoded_content,
            "branch": branch,
            "committer": {
                "name": GIT_USER_NAME,
                "email": GIT_USER_EMAIL
            }
        }
        
        if sha:
            payload["sha"] = sha
        
        try:
            async with self.session.put(url, json=payload) as response:
                response_json = await response.json()
                if response.status in (200, 201):
                    logger.info(f"Successfully {'updated' if sha else 'created'} file {path}")
                    return response_json
                else:
                    logger.error(f"Failed to {'update' if sha else 'create'} file: {response.status} - {response_json}")
                    return {"error": f"API error: {response.status}", "details": response_json}
        except Exception as e:
            logger.error(f"Exception in create_or_update_file: {e}")
            return {"error": str(e)}

    async def trigger_workflow(self, workflow_file: str, ref: str = MAIN_BRANCH, inputs: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Trigger a GitHub Actions workflow"""
        if not self.enabled or not self.session:
            return {"error": "GitHub monitoring not enabled or initialized"}
        
        url = f"{self.api_base_url}/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches"
        
        payload = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs
        
        try:
            async with self.session.post(url, json=payload) as response:
                if response.status == 204:  # No content is the success response
                    logger.info(f"Successfully triggered workflow {workflow_file}")
                    return {"success": True, "workflow": workflow_file}
                else:
                    error_msg = await response.text()
                    logger.error(f"Failed to trigger workflow: {response.status} - {error_msg}")
                    return {"error": f"API error: {response.status}", "details": error_msg}
        except Exception as e:
            logger.error(f"Exception in trigger_workflow: {e}")
            return {"error": str(e)}

class SystemMonitor:
    """Main system monitor class that coordinates all monitoring activities"""

    def __init__(self):
        self.api_key_manager = APIKeyManager()
        self.github_monitor = GitHubMonitor()
        self.session: Optional[aiohttp.ClientSession] = None
        self.service_endpoints = {
            "ai_core": "http://localhost:7875",
            "development_agents": "http://localhost:7876",
            "project_manager": "http://localhost:7877",
            "frontend": "http://localhost:3000"
        }
        self.running = False
        self.load_config()

    def load_config(self):
        """Load configuration from config.json"""
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
            
            # Update service endpoints from config
            if "services" in config:
                for service, info in config["services"].items():
                    if "url" in info:
                        self.service_endpoints[service] = info["url"]
            
            logger.info(f"Loaded configuration with services: {list(self.service_endpoints.keys())}")
        except Exception as e:
            logger.error(f"Error loading config.json: {e}")

    async def initialize(self):
        """Initialize all components"""
        self.session = aiohttp.ClientSession()
        await self.github_monitor.initialize()
        logger.info("System monitor initialized")

    async def close(self):
        """Close all components"""
        if self.session:
            await self.session.close()
        await self.github_monitor.close()
        logger.info("System monitor closed")

    async def check_system_resources(self) -> Dict[str, float]:
        """Check system resources (CPU, memory, disk)"""
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Update Prometheus metrics
        SYSTEM_CPU_USAGE.set(cpu_percent)
        SYSTEM_MEMORY_USAGE.set(memory.percent)
        SYSTEM_DISK_USAGE.set(disk.percent)
        
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_percent": disk.percent
        }

    async def check_service_health(self) -> Dict[str, bool]:
        """Check the health of all services"""
        results = {}
        
        for service, url in self.service_endpoints.items():
            try:
                health_url = f"{url}/health"
                async with self.session.get(health_url, timeout=5) as response:
                    is_healthy = response.status == 200
                    results[service] = is_healthy
                    SERVICE_HEALTH.labels(service=service).set(1 if is_healthy else 0)
            except Exception:
                results[service] = False
                SERVICE_HEALTH.labels(service=service).set(0)
        
        return results

    async def check_api_providers(self) -> Dict[str, Any]:
        """Check the status of API providers"""
        # For now, just return the usage report
        return self.api_key_manager.get_usage_report()

    async def monitor_once(self) -> Dict[str, Any]:
        """Run one iteration of the monitoring loop"""
        try:
            system_resources = await self.check_system_resources()
            service_health = await self.check_service_health()
            api_providers = await self.check_api_providers()
            github_status = await self.github_monitor.check_workflow_runs()
            
            report = {
                "timestamp": datetime.now().isoformat(),
                "system_resources": system_resources,
                "service_health": service_health,
                "api_providers": api_providers,
                "github_status": github_status
            }
            
            # Check for critical issues
            critical_issues = []
            
            # Check system resources
            if system_resources["cpu_percent"] > 90:
                critical_issues.append(f"High CPU usage: {system_resources['cpu_percent']}%")
            if system_resources["memory_percent"] > 90:
                critical_issues.append(f"High memory usage: {system_resources['memory_percent']}%")
            if system_resources["disk_percent"] > 90:
                critical_issues.append(f"High disk usage: {system_resources['disk_percent']}%")
            
            # Check service health
            for service, is_healthy in service_health.items():
                if not is_healthy:
                    critical_issues.append(f"Service {service} is not healthy")
            
            # Check GitHub status
            if isinstance(github_status, dict) and "error" in github_status:
                critical_issues.append(f"GitHub error: {github_status['error']}")
            
            if critical_issues:
                report["critical_issues"] = critical_issues
                logger.warning(f"Critical issues detected: {', '.join(critical_issues)}")
            
            # Check if we should trigger a release
            if await self.check_release_conditions():
                release_result = await self.trigger_automated_release()
                report["release_triggered"] = release_result
        
            return report
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}", exc_info=True)
            return {"error": str(e)}

    async def handle_critical_issues(self, issues: List[str]):
        """Handle critical issues by taking appropriate actions"""
        for issue in issues:
            logger.warning(f"Handling critical issue: {issue}")
            
            # Implement specific handling logic based on the issue
            if "GitHub error" in issue:
                # Try to reinitialize GitHub monitor
                await self.github_monitor.close()
                await self.github_monitor.initialize()
            
            # Add more issue handling logic as needed

    def stop(self):
        """Stop the monitoring loop"""
        self.running = False

    async def trigger_automated_release(self, version_type: str = "patch", environment: str = "staging") -> Dict[str, Any]:
        """
        Trigger an automated release when conditions are met.
        
        This method calls the trigger_release.py script to initiate a GitHub Actions workflow
        that will test, build, and deploy the application.
        
        Args:
            version_type: Type of version bump (patch, minor, major)
            environment: Deployment environment (staging, production)
        
        Returns:
            Dict with the result of the release trigger
        """
        logger.info(f"Triggering automated release: {version_type} for {environment}")
        
        try:
            # First approach: Use the trigger_release.py script directly
            script_path = Path(__file__).parent / "trigger_release.py"
            
            if script_path.exists():
                # Execute the script as a subprocess
                cmd = [
                    sys.executable, 
                    str(script_path), 
                    f"--version={version_type}", 
                    f"--environment={environment}"
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    try:
                        result = json.loads(stdout.decode().strip())
                        logger.info(f"Release trigger successful: {result}")
                        return result
                    except json.JSONDecodeError:
                        logger.warning(f"Could not parse release trigger output: {stdout.decode()}")
                        return {
                            "success": True,
                            "message": "Release triggered, but output could not be parsed",
                            "raw_output": stdout.decode()
                        }
                else:
                    logger.error(f"Release trigger failed: {stderr.decode()}")
                    return {
                        "success": False,
                        "error": f"Release trigger failed with exit code {process.returncode}",
                        "stderr": stderr.decode()
                    }
            else:
                # Alternative approach: Use the trigger_release function directly
                # Import the function here to avoid circular imports
                from trigger_release import trigger_release as tr_func
                
                result = await tr_func(
                    version_type=version_type,
                    environment=environment,
                    create_release=True,
                    message=f"Automated release triggered by system monitor at {datetime.now().isoformat()}"
                )
                
                logger.info(f"Release trigger result: {result}")
                return result
                
        except Exception as e:
            logger.error(f"Error triggering release: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def check_release_conditions(self) -> bool:
        """
        Check if conditions are met to trigger an automated release.
        
        Returns:
            True if a release should be triggered, False otherwise
        """
        # Check GitHub workflow status
        github_status = await self.github_monitor.check_workflow_runs()
        
        # Check if there are any critical issues
        report = await self.monitor_once()
        has_critical_issues = "critical_issues" in report and len(report["critical_issues"]) > 0
        
        # Check if all services are healthy
        all_services_healthy = all(report.get("service_health", {}).values())
        
        # Check if there are any recent successful test runs
        has_successful_tests = False
        if isinstance(github_status, dict) and "runs" in github_status:
            for run in github_status["runs"]:
                if run.get("name", "").lower().startswith("test") and run.get("conclusion") == "success":
                    has_successful_tests = True
                    break
        
        # Determine if we should trigger a release
        should_release = (
            not has_critical_issues and 
            all_services_healthy and 
            has_successful_tests
        )
        
        if should_release:
            logger.info("Release conditions met: No critical issues, all services healthy, and successful tests")
        else:
            logger.info(
                f"Release conditions not met: Critical issues: {has_critical_issues}, "
                f"All services healthy: {all_services_healthy}, "
                f"Successful tests: {has_successful_tests}"
            )
        
        return should_release

    async def run(self):
        """Run the monitoring loop"""
        self.running = True
        
        while self.running:
            report = await self.monitor_once()
            
            # Save report to file
            try:
                os.makedirs("logs/reports", exist_ok=True)
                report_file = f"logs/reports/monitor_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(report_file, "w") as f:
                    json.dump(report, f, indent=2)
            except Exception as e:
                logger.error(f"Error saving report: {e}")
            
            # Handle critical issues if needed
            if "critical_issues" in report:
                await self.handle_critical_issues(report["critical_issues"])
            
            await asyncio.sleep(CHECK_INTERVAL)

async def main():
    """Main entry point"""
    # Start Prometheus metrics server
    start_http_server(8000)
    logger.info("Started Prometheus metrics server on port 8000")
    
    # Initialize and run the system monitor
    monitor = SystemMonitor()
    await monitor.initialize()
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
    finally:
        await monitor.close()

if __name__ == "__main__":
    asyncio.run(main())

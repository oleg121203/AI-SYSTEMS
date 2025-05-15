#!/usr/bin/env python3
"""
Trigger Release Script for AI-SYSTEMS

This script triggers an automated release through the GitHub API.
It can be called by the system monitor or manually to initiate a release.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Optional

import aiohttp
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/trigger_release.log"),
    ],
)
logger = logging.getLogger("trigger_release")

# Constants
GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_REPO = os.getenv("GITHUB_REPO_TO_MONITOR", "oleg121203/AI-SYSTEMS-REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "Oleg Kizyma")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "oleg1203@gmail.com")

async def trigger_release(
    version_type: str = "patch",
    environment: str = "staging",
    create_release: bool = True,
    message: str = "Automated release triggered by AI-SYSTEMS",
) -> Dict:
    """
    Trigger a release by dispatching a repository event to GitHub Actions.
    
    Args:
        version_type: Type of version bump (patch, minor, major)
        environment: Deployment environment (staging, production)
        create_release: Whether to create a GitHub release
        message: Release message
        
    Returns:
        Dict with the response from the GitHub API
    """
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN environment variable not set")
        return {"error": "GITHUB_TOKEN environment variable not set"}
    
    if not GITHUB_REPO:
        logger.error("GITHUB_REPO_TO_MONITOR environment variable not set")
        return {"error": "GITHUB_REPO_TO_MONITOR environment variable not set"}
    
    url = f"{GITHUB_API_BASE_URL}/repos/{GITHUB_REPO}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    
    payload = {
        "event_type": "automated-release",
        "client_payload": {
            "version": version_type,
            "environment": environment,
            "create_release": create_release,
            "message": message,
            "triggered_at": datetime.now().isoformat(),
            "triggered_by": "system_monitor",
        }
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 204:  # GitHub returns 204 No Content on success
                    logger.info(f"Successfully triggered release workflow: {version_type} for {environment}")
                    return {
                        "success": True,
                        "message": f"Release workflow triggered: {version_type} for {environment}",
                        "status_code": response.status,
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to trigger release workflow: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"API error: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"Exception in trigger_release: {e}")
            return {"success": False, "error": str(e)}

async def check_workflow_status(workflow_id: Optional[str] = None) -> Dict:
    """
    Check the status of a workflow run.
    
    Args:
        workflow_id: ID of the workflow run to check (if None, checks the latest run)
        
    Returns:
        Dict with the workflow status
    """
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN environment variable not set")
        return {"error": "GITHUB_TOKEN environment variable not set"}
    
    if not GITHUB_REPO:
        logger.error("GITHUB_REPO_TO_MONITOR environment variable not set")
        return {"error": "GITHUB_REPO_TO_MONITOR environment variable not set"}
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # If workflow_id is provided, check that specific workflow
    if workflow_id:
        url = f"{GITHUB_API_BASE_URL}/repos/{GITHUB_REPO}/actions/runs/{workflow_id}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "workflow_id": workflow_id,
                            "status": data.get("status"),
                            "conclusion": data.get("conclusion"),
                            "html_url": data.get("html_url"),
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to check workflow status: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"API error: {response.status}",
                            "details": error_text,
                        }
            except Exception as e:
                logger.error(f"Exception in check_workflow_status: {e}")
                return {"success": False, "error": str(e)}
    
    # Otherwise, get the latest workflow run
    url = f"{GITHUB_API_BASE_URL}/repos/{GITHUB_REPO}/actions/runs"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    workflow_runs = data.get("workflow_runs", [])
                    
                    if not workflow_runs:
                        return {
                            "success": True,
                            "message": "No workflow runs found",
                            "workflow_runs": [],
                        }
                    
                    # Get the latest run
                    latest_run = workflow_runs[0]
                    
                    return {
                        "success": True,
                        "workflow_id": latest_run.get("id"),
                        "status": latest_run.get("status"),
                        "conclusion": latest_run.get("conclusion"),
                        "html_url": latest_run.get("html_url"),
                        "created_at": latest_run.get("created_at"),
                        "updated_at": latest_run.get("updated_at"),
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to list workflow runs: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"API error: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"Exception in check_workflow_status: {e}")
            return {"success": False, "error": str(e)}

async def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Trigger an automated release for AI-SYSTEMS")
    parser.add_argument(
        "--version",
        choices=["patch", "minor", "major"],
        default="patch",
        help="Type of version bump (default: patch)",
    )
    parser.add_argument(
        "--environment",
        choices=["staging", "production"],
        default="staging",
        help="Deployment environment (default: staging)",
    )
    parser.add_argument(
        "--no-release",
        action="store_false",
        dest="create_release",
        help="Don't create a GitHub release",
    )
    parser.add_argument(
        "--message",
        default="Automated release triggered by AI-SYSTEMS",
        help="Release message",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the status of the latest workflow run instead of triggering a new one",
    )
    parser.add_argument(
        "--workflow-id",
        help="ID of the workflow run to check (only used with --check)",
    )
    
    args = parser.parse_args()
    
    if args.check:
        result = await check_workflow_status(args.workflow_id)
        print(json.dumps(result, indent=2))
    else:
        result = await trigger_release(
            version_type=args.version,
            environment=args.environment,
            create_release=args.create_release,
            message=args.message,
        )
        print(json.dumps(result, indent=2))
    
    return 0 if result.get("success", False) else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

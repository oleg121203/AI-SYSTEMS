#!/usr/bin/env python3
"""
Test GitHub Integration for AI-SYSTEMS

This script tests the GitHub integration with the repository at
https://github.com/oleg121203/AI-SYSTEMS-REPO.git to ensure it's working correctly.
It also tests multiple API keys if available.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent))

# Import our modules
from github_integration import GitHubIntegration
from trigger_release import check_workflow_status, trigger_release

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("test_github_integration")

# Constants
GITHUB_REPO = os.getenv("GITHUB_REPO_TO_MONITOR", "oleg121203/AI-SYSTEMS-REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Check for multiple API keys
def get_all_github_tokens():
    """Get all available GitHub tokens from environment variables"""
    tokens = []
    # Add the primary token if available
    if GITHUB_TOKEN:
        tokens.append(("Primary", GITHUB_TOKEN))
    
    # Check for numbered tokens (GITHUB_TOKEN2, GITHUB_TOKEN3, etc.)
    for i in range(2, 10):  # Check for up to 9 additional tokens
        token_name = f"GITHUB_TOKEN{i}"
        token = os.getenv(token_name)
        if token:
            tokens.append((f"Token {i}", token))
    
    return tokens

GITHUB_TOKENS = get_all_github_tokens()
TEST_FILE_PATH = "test_file.md"
TEST_FILE_CONTENT = f"""# Test File

This file was created by the GitHub integration test script.

Test timestamp: {datetime.now().isoformat()}

Repository: {GITHUB_REPO}
"""

async def test_github_integration():
    """Test the GitHubIntegration class with all available tokens"""
    logger.info("Testing GitHub integration...")
    
    if not GITHUB_TOKENS:
        logger.error("No GitHub tokens available. Set GITHUB_TOKEN in your .env file.")
        return False
    
    logger.info(f"Found {len(GITHUB_TOKENS)} GitHub tokens to test")
    
    # Test each token
    results = []
    for token_name, token in GITHUB_TOKENS:
        logger.info(f"Testing with {token_name}...")
        
        # Initialize GitHub integration with this token
        github = GitHubIntegration(token=token, repo=GITHUB_REPO)
        
        # Initialize the session
        success = await github.initialize()
        if not success:
            logger.error(f"{token_name}: Failed to initialize GitHub integration")
            results.append((token_name, False, "Failed to initialize"))
            continue
        
        # Get repository info
        repo_info = await github.get_repo_info()
        if "error" in repo_info:
            logger.error(f"{token_name}: Failed to get repository info: {repo_info['error']}")
            results.append((token_name, False, f"Failed to get repo info: {repo_info.get('error')}"))
            await github.close()
            continue
        
        logger.info(f"{token_name}: Successfully connected to repository: {repo_info.get('full_name')}")
        
        # Create or update a test file with token-specific content
        test_content = TEST_FILE_CONTENT + f"\nTested with: {token_name}\n"
        file_result = await github.create_or_update_file(
            path=f"{token_name.lower().replace(' ', '_')}_{TEST_FILE_PATH}",
            content=test_content,
            message=f"Test commit from GitHub integration test script using {token_name}",
        )
        
        if "error" in file_result:
            logger.error(f"{token_name}: Failed to create/update file: {file_result['error']}")
            results.append((token_name, False, f"Failed to create/update file: {file_result.get('error')}"))
            await github.close()
            continue
        
        logger.info(f"{token_name}: Successfully created/updated test file")
        results.append((token_name, True, "All tests passed"))
        
        # Close the session
        await github.close()
    
    # Print summary
    logger.info("\n=== GitHub Integration Test Results ===")
    all_passed = True
    for token_name, success, message in results:
        status = "PASS" if success else "FAIL"
        logger.info(f"{token_name}: {status} - {message}")
        if not success:
            all_passed = False
    
    return all_passed

async def test_trigger_release():
    """Test the trigger_release functionality"""
    logger.info("Testing release trigger...")
    
    # Check current workflow status
    status_before = await check_workflow_status()
    logger.info(f"Current workflow status: {json.dumps(status_before, indent=2)}")
    
    # Trigger a test release
    result = await trigger_release(
        version_type="patch",
        environment="staging",
        create_release=False,  # Don't create an actual release for testing
        message="Test release triggered by test_github_integration.py",
    )
    
    if not result.get("success", False):
        logger.error(f"Failed to trigger release: {result.get('error', 'Unknown error')}")
        return False
    
    logger.info(f"Successfully triggered release: {result.get('message', '')}")
    
    # Wait a bit for the workflow to start
    logger.info("Waiting for workflow to start...")
    await asyncio.sleep(5)
    
    # Check workflow status after trigger
    status_after = await check_workflow_status()
    logger.info(f"Updated workflow status: {json.dumps(status_after, indent=2)}")
    
    return True

async def test_system_monitor_integration():
    """Test the system monitor's ability to trigger releases"""
    logger.info("Testing system monitor integration...")
    
    try:
        # Import the system monitor
        from system_monitor import SystemMonitor
        
        # Initialize the system monitor
        monitor = SystemMonitor()
        await monitor.initialize()
        
        # Check release conditions
        should_release = await monitor.check_release_conditions()
        logger.info(f"Release conditions met: {should_release}")
        
        # Manually trigger a release for testing
        result = await monitor.trigger_automated_release(
            version_type="patch",
            environment="staging",
        )
        
        if not result.get("success", False):
            logger.error(f"Failed to trigger release via system monitor: {result.get('error', 'Unknown error')}")
            return False
        
        logger.info(f"Successfully triggered release via system monitor: {result.get('message', '')}")
        
        # Close the monitor
        await monitor.close()
        
        return True
    except Exception as e:
        logger.error(f"Error testing system monitor integration: {e}", exc_info=True)
        return False

async def main():
    """Run all tests"""
    # Define the tests to run
    tests = [
        ("GitHub Integration", test_github_integration, True),  # Required test
        ("Release Trigger", test_trigger_release, False),  # Optional test
        ("System Monitor Integration", test_system_monitor_integration, False),  # Optional test
    ]
    
    results = {}
    start_time = datetime.now()
    
    logger.info(f"Starting tests at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Testing GitHub integration with repository: {GITHUB_REPO}")
    logger.info(f"Found {len(GITHUB_TOKENS)} GitHub tokens to test")
    
    # Run each test
    for name, test_func, required in tests:
        logger.info(f"\n=== Running test: {name} {'(REQUIRED)' if required else '(OPTIONAL)'} ===")
        try:
            success = await test_func()
            status = "PASS" if success else "FAIL"
            results[name] = {
                "status": status,
                "required": required,
                "error": None
            }
            logger.info(f"Test {name} completed with status: {status}")
        except Exception as e:
            logger.error(f"Exception in {name} test: {e}", exc_info=True)
            results[name] = {
                "status": "ERROR",
                "required": required,
                "error": str(e)
            }
    
    # Calculate test duration
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # Print summary
    logger.info(f"\n=== Test Results Summary ({end_time.strftime('%Y-%m-%d %H:%M:%S')}) ===")
    logger.info(f"Duration: {duration:.2f} seconds")
    
    # Count results by category
    total = len(results)
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    failed = sum(1 for r in results.values() if r["status"] == "FAIL")
    errors = sum(1 for r in results.values() if r["status"] == "ERROR")
    
    logger.info(f"Total tests: {total}, Passed: {passed}, Failed: {failed}, Errors: {errors}")
    
    # Print detailed results
    for name, result in results.items():
        status_str = result["status"]
        if result["required"]:
            status_str += " (REQUIRED)"
        if result["error"]:
            status_str += f" - {result['error']}"
        logger.info(f"{name}: {status_str}")
    
    # Return success if all required tests passed
    required_success = all(
        result["status"] == "PASS" 
        for name, result in results.items() 
        if result["required"]
    )
    
    if required_success:
        logger.info("\nAll required tests passed successfully!")
    else:
        logger.error("\nSome required tests failed. See details above.")
    
    return required_success

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

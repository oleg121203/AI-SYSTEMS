#!/usr/bin/env python3
"""
Repository Synchronization Script

This script manages two repositories:
1. Main development workspace: /Users/olegkizima/workspace/AI-SYSTEMS/
2. Production repository: /Users/olegkizima/workspace/AI-SYSTEMS-REPO

It allows for synchronizing code between the two repositories and making commits
to the production repository based on changes in the development workspace.
"""

import os
import sys
import subprocess
import argparse
import logging
from datetime import datetime
from pathlib import Path
import shutil
import re
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/repo_sync.log")
    ]
)
logger = logging.getLogger("repo-sync")

# Load environment variables
load_dotenv()

# Repository paths
DEV_REPO_PATH = os.path.abspath(os.path.dirname(__file__))
PROD_REPO_PATH = os.path.expanduser("~/workspace/AI-SYSTEMS-REPO")

# Git configuration
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "Oleg Kizyma")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "oleg1203@gmail.com")

# Files and directories to exclude from sync
EXCLUDE_PATTERNS = [
    ".git",
    ".env",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "node_modules",
    "venv",
    ".venv",
    "logs/*.log",
    "tmp",
    "dist",
    "build",
    ".idea",
    ".vscode"
]

def run_command(cmd, cwd=None, capture_output=True):
    """Run a shell command and return the result"""
    logger.debug(f"Running command: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or DEV_REPO_PATH,
            capture_output=capture_output,
            text=True,
            check=True
        )
        return result.stdout if capture_output else None
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e.stderr}")
        raise

def check_repos():
    """Check if both repositories exist and are valid git repositories"""
    # Check dev repo
    if not os.path.exists(os.path.join(DEV_REPO_PATH, ".git")):
        logger.error(f"Development repository at {DEV_REPO_PATH} is not a git repository")
        return False
    
    # Check prod repo
    if not os.path.exists(PROD_REPO_PATH):
        logger.info(f"Production repository at {PROD_REPO_PATH} does not exist, creating it")
        os.makedirs(PROD_REPO_PATH, exist_ok=True)
        
        # Clone the repository if it doesn't exist
        try:
            run_command(["git", "clone", "https://github.com/oleg121203/AI-SYSTEMS-REPO.git", PROD_REPO_PATH])
        except subprocess.CalledProcessError:
            # If clone fails, initialize a new repository
            run_command(["git", "init"], cwd=PROD_REPO_PATH)
            run_command(["git", "remote", "add", "origin", "https://github.com/oleg121203/AI-SYSTEMS-REPO.git"], cwd=PROD_REPO_PATH)
    elif not os.path.exists(os.path.join(PROD_REPO_PATH, ".git")):
        logger.error(f"Production repository at {PROD_REPO_PATH} is not a git repository")
        return False
    
    # Configure git user for both repositories
    for repo_path in [DEV_REPO_PATH, PROD_REPO_PATH]:
        run_command(["git", "config", "user.name", GIT_USER_NAME], cwd=repo_path)
        run_command(["git", "config", "user.email", GIT_USER_EMAIL], cwd=repo_path)
    
    return True

def should_exclude(path):
    """Check if a path should be excluded from sync"""
    for pattern in EXCLUDE_PATTERNS:
        if re.match(f"^{pattern.replace('*', '.*')}$", os.path.basename(path)):
            return True
        if "*" in pattern and re.match(f".*{pattern.replace('*', '.*')}.*", str(path)):
            return True
    return False

def sync_repo(source_path, dest_path):
    """Synchronize repository contents from source to destination"""
    logger.info(f"Syncing from {source_path} to {dest_path}")
    
    # Walk through the source directory
    for root, dirs, files in os.walk(source_path):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]
        
        # Create relative path
        rel_path = os.path.relpath(root, source_path)
        if rel_path == ".":
            rel_path = ""
        
        # Create corresponding directory in destination
        dest_dir = os.path.join(dest_path, rel_path)
        os.makedirs(dest_dir, exist_ok=True)
        
        # Copy files
        for file in files:
            src_file = os.path.join(root, file)
            if should_exclude(src_file):
                continue
                
            dest_file = os.path.join(dest_dir, file)
            try:
                shutil.copy2(src_file, dest_file)
                logger.debug(f"Copied: {src_file} -> {dest_file}")
            except Exception as e:
                logger.error(f"Error copying {src_file}: {e}")

def commit_changes(commit_message=None):
    """Commit changes to the production repository"""
    if not commit_message:
        commit_message = f"Sync changes from development repository {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    try:
        # Add all changes
        run_command(["git", "add", "."], cwd=PROD_REPO_PATH)
        
        # Check if there are changes to commit
        status = run_command(["git", "status", "--porcelain"], cwd=PROD_REPO_PATH)
        if not status.strip():
            logger.info("No changes to commit")
            return False
        
        # Commit changes
        run_command(["git", "commit", "-m", commit_message], cwd=PROD_REPO_PATH)
        logger.info(f"Committed changes with message: {commit_message}")
        return True
    except Exception as e:
        logger.error(f"Error committing changes: {e}")
        return False

def push_changes():
    """Push changes to the remote repository"""
    try:
        run_command(["git", "push", "origin", "main"], cwd=PROD_REPO_PATH)
        logger.info("Pushed changes to remote repository")
        return True
    except Exception as e:
        logger.error(f"Error pushing changes: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Synchronize repositories and manage git operations")
    parser.add_argument("--sync", action="store_true", help="Synchronize development repo to production repo")
    parser.add_argument("--commit", action="store_true", help="Commit changes to production repo")
    parser.add_argument("--push", action="store_true", help="Push changes to remote repository")
    parser.add_argument("--all", action="store_true", help="Perform sync, commit, and push")
    parser.add_argument("--message", "-m", help="Commit message")
    
    args = parser.parse_args()
    
    # Check repositories
    if not check_repos():
        logger.error("Repository check failed, exiting")
        sys.exit(1)
    
    # Determine actions to take
    do_sync = args.sync or args.all
    do_commit = args.commit or args.all
    do_push = args.push or args.all
    
    # Execute actions
    if do_sync:
        sync_repo(DEV_REPO_PATH, PROD_REPO_PATH)
    
    if do_commit:
        if not commit_changes(args.message):
            if do_push:
                logger.warning("No changes to commit, skipping push")
                do_push = False
    
    if do_push:
        push_changes()
    
    logger.info("Repository operations completed successfully")

if __name__ == "__main__":
    main()

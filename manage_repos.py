#!/usr/bin/env python3
"""
Repository Management Script for AI-SYSTEMS

This script helps manage the integration between the main AI-SYSTEMS repository
and the secondary AI-SYSTEMS-REPO repository where generated code is stored.
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Default repository paths and URLs
MAIN_REPO_PATH = os.path.dirname(os.path.abspath(__file__))
SECONDARY_REPO_PATH = os.path.join(MAIN_REPO_PATH, "mcp_api", "repo")
SECONDARY_REPO_EXTERNAL_PATH = os.path.expanduser("~/workspace/AI-SYSTEMS-REPO")

# GitHub repository information
GITHUB_USER = os.getenv("GIT_USER_NAME", "Oleg Kizyma")
GITHUB_EMAIL = os.getenv("GIT_USER_EMAIL", "oleg1203@gmail.com")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
MAIN_REPO_URL = "https://github.com/oleg121203/AI-SYSTEMS.git"
SECONDARY_REPO_URL = "https://github.com/oleg121203/AI-SYSTEMS-REPO.git"

def run_command(cmd, cwd=None, check=True):
    """Run a shell command and return its output"""
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            check=check, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(cmd)}")
        print(f"Error message: {e.stderr}")
        if check:
            sys.exit(1)
        return None

def setup_git_config():
    """Set up Git configuration with user information"""
    run_command(["git", "config", "--global", "user.name", GITHUB_USER])
    run_command(["git", "config", "--global", "user.email", GITHUB_EMAIL])
    print(f"Git configured with user: {GITHUB_USER} <{GITHUB_EMAIL}>")

def setup_nested_repo():
    """Set up the nested repository in mcp_api/repo"""
    # Check if the nested repo directory exists
    if not os.path.exists(SECONDARY_REPO_PATH):
        os.makedirs(SECONDARY_REPO_PATH, exist_ok=True)
    
    # Check if it's already a Git repository
    if not os.path.exists(os.path.join(SECONDARY_REPO_PATH, ".git")):
        print(f"Initializing Git repository in {SECONDARY_REPO_PATH}")
        run_command(["git", "init"], cwd=SECONDARY_REPO_PATH)
    
    # Set up remote
    try:
        remotes = run_command(["git", "remote"], cwd=SECONDARY_REPO_PATH)
        if "origin" not in remotes.split():
            run_command(["git", "remote", "add", "origin", SECONDARY_REPO_URL], cwd=SECONDARY_REPO_PATH)
        else:
            run_command(["git", "remote", "set-url", "origin", SECONDARY_REPO_URL], cwd=SECONDARY_REPO_PATH)
        print(f"Remote 'origin' set to {SECONDARY_REPO_URL}")
    except Exception as e:
        print(f"Error setting up remote: {e}")
    
    # Create basic structure if needed
    if not os.listdir(SECONDARY_REPO_PATH) or len(os.listdir(SECONDARY_REPO_PATH)) <= 1:  # Only .git directory
        print("Creating basic repository structure")
        generated_code_dir = os.path.join(SECONDARY_REPO_PATH, "generated_code")
        os.makedirs(generated_code_dir, exist_ok=True)
        
        # Create README.md
        readme_path = os.path.join(SECONDARY_REPO_PATH, "README.md")
        with open(readme_path, "w") as f:
            f.write(f"""# AI-SYSTEMS-REPO

This repository is used by the AI-SYSTEMS software to store and manage generated code and other files. 
The main AI-SYSTEMS software automatically commits to this repository as part of its workflow.

## Structure

- `generated_code/`: Directory for AI-generated code files
- Other directories will be created as needed by the AI-SYSTEMS software

## Integration

This repository works in conjunction with the main [AI-SYSTEMS]({MAIN_REPO_URL}) repository, 
which contains the core software and workflows.
""")
        
        # Create .gitignore
        gitignore_path = os.path.join(SECONDARY_REPO_PATH, ".gitignore")
        with open(gitignore_path, "w") as f:
            f.write("""# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
*.egg-info/
.installed.cfg
*.egg

# Virtual Environments
venv/
ENV/
.env

# IDE files
.idea/
.vscode/
*.swp
*.swo

# OS specific files
.DS_Store
Thumbs.db

# Logs
logs/
*.log

# Temporary files
tmp/
temp/
""")
        
        # Create .gitkeep in generated_code directory
        with open(os.path.join(generated_code_dir, ".gitkeep"), "w") as f:
            pass
        
        # Commit the changes
        run_command(["git", "add", "."], cwd=SECONDARY_REPO_PATH)
        try:
            run_command(["git", "commit", "-m", "Initial repository structure setup"], cwd=SECONDARY_REPO_PATH)
            print("Created and committed initial repository structure")
        except:
            print("No changes to commit or commit failed")

def setup_external_repo():
    """Set up the external repository at ~/workspace/AI-SYSTEMS-REPO"""
    # Check if the external repo directory exists
    if not os.path.exists(SECONDARY_REPO_EXTERNAL_PATH):
        os.makedirs(SECONDARY_REPO_EXTERNAL_PATH, exist_ok=True)
        print(f"Created directory: {SECONDARY_REPO_EXTERNAL_PATH}")
    
    # Check if it's already a Git repository
    if not os.path.exists(os.path.join(SECONDARY_REPO_EXTERNAL_PATH, ".git")):
        print(f"Cloning repository to {SECONDARY_REPO_EXTERNAL_PATH}")
        run_command(["git", "clone", SECONDARY_REPO_URL, SECONDARY_REPO_EXTERNAL_PATH])
    else:
        print(f"Updating repository in {SECONDARY_REPO_EXTERNAL_PATH}")
        run_command(["git", "fetch", "origin"], cwd=SECONDARY_REPO_EXTERNAL_PATH)
        run_command(["git", "pull", "origin", "main"], cwd=SECONDARY_REPO_EXTERNAL_PATH, check=False)

def sync_repos():
    """Synchronize the nested repository with the external repository"""
    if not os.path.exists(SECONDARY_REPO_PATH) or not os.path.exists(SECONDARY_REPO_EXTERNAL_PATH):
        print("Both repositories must exist to sync")
        return
    
    # Pull latest changes from external repo
    run_command(["git", "pull", "origin", "main"], cwd=SECONDARY_REPO_EXTERNAL_PATH, check=False)
    
    # Copy files from external repo to nested repo
    print("Syncing files from external repo to nested repo")
    for item in os.listdir(SECONDARY_REPO_EXTERNAL_PATH):
        if item == ".git":
            continue
        
        source = os.path.join(SECONDARY_REPO_EXTERNAL_PATH, item)
        dest = os.path.join(SECONDARY_REPO_PATH, item)
        
        if os.path.isdir(source):
            run_command(["cp", "-r", source, SECONDARY_REPO_PATH])
        else:
            run_command(["cp", source, dest])
    
    # Commit and push changes in nested repo
    run_command(["git", "add", "."], cwd=SECONDARY_REPO_PATH)
    try:
        run_command(["git", "commit", "-m", "Sync with external repository"], cwd=SECONDARY_REPO_PATH)
        print("Changes committed in nested repo")
    except:
        print("No changes to commit in nested repo")

def main():
    parser = argparse.ArgumentParser(description="Manage AI-SYSTEMS repositories")
    parser.add_argument("--setup-git", action="store_true", help="Set up Git configuration")
    parser.add_argument("--setup-nested", action="store_true", help="Set up nested repository in mcp_api/repo")
    parser.add_argument("--setup-external", action="store_true", help="Set up external repository at ~/workspace/AI-SYSTEMS-REPO")
    parser.add_argument("--sync", action="store_true", help="Synchronize repositories")
    parser.add_argument("--all", action="store_true", help="Perform all setup and sync operations")
    
    args = parser.parse_args()
    
    if args.all or args.setup_git:
        setup_git_config()
    
    if args.all or args.setup_nested:
        setup_nested_repo()
    
    if args.all or args.setup_external:
        setup_external_repo()
    
    if args.all or args.sync:
        sync_repos()
    
    if not any(vars(args).values()):
        parser.print_help()

if __name__ == "__main__":
    main()

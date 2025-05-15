#!/usr/bin/env python3
import os
import requests
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get GitHub credentials from environment variables
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_OWNER = "oleg121203"  # GitHub username
REPO_NAME = "AI-SYSTEMS-REPO"    # Repository name

if not GITHUB_TOKEN:
    print("Error: GITHUB_TOKEN not found in .env file")
    print("Please add your GitHub personal access token to the .env file as GITHUB_TOKEN=your_token")
    sys.exit(1)

def set_default_branch(branch_name="main"):
    """Set the default branch for the repository."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "default_branch": branch_name
    }
    
    response = requests.patch(url, headers=headers, json=data)
    
    if response.status_code == 200:
        print(f"Successfully set {branch_name} as the default branch")
    else:
        print(f"Failed to set default branch: {response.status_code}")
        print(response.json())

if __name__ == "__main__":
    # Default to 'main' if no argument is provided
    branch_name = sys.argv[1] if len(sys.argv) > 1 else "main"
    set_default_branch(branch_name)

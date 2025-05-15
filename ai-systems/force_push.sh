#!/bin/bash

# Force Push Script for AI-SYSTEMS
# This script force pushes the local repository to GitHub

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}WARNING: This script will overwrite the remote repository with your local changes.${NC}"
echo -e "${RED}All changes on the remote repository that are not in your local repository will be lost.${NC}"
read -p "Are you sure you want to continue? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Force push cancelled.${NC}"
    exit 0
fi

# Load environment variables
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
    echo -e "${GREEN}Environment variables loaded from .env file${NC}"
else
    echo -e "${RED}Error: .env file not found.${NC}"
    exit 1
fi

# Check if repository path is set
if [ -z "$REPOSITORY_PATH" ]; then
    echo -e "${RED}Error: REPOSITORY_PATH is not set in .env file${NC}"
    exit 1
else
    REPO_PATH=$(eval echo $REPOSITORY_PATH)
    echo -e "${YELLOW}Repository path: $REPO_PATH${NC}"
fi

# Check if it's a Git repository
if [ ! -d "$REPO_PATH/.git" ]; then
    echo -e "${RED}Error: Git repository is not initialized. Please run setup.sh first.${NC}"
    exit 1
fi

# Move to repository directory
cd "$REPO_PATH" || exit 1

# Get current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo -e "${YELLOW}Current branch: $CURRENT_BRANCH${NC}"

# Check if GitHub token is set
if [ -z "$GITHUB_TOKEN" ] || [ -z "$GITHUB_REPO" ]; then
    echo -e "${RED}Error: GITHUB_TOKEN or GITHUB_REPO not set in .env file${NC}"
    exit 1
fi

# Set the remote URL with token for authentication
REPO_URL="https://${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"

# Update remote URL if needed
echo -e "${YELLOW}Updating remote URL...${NC}"
if git remote -v | grep -q origin; then
    git remote set-url origin "$REPO_URL"
else
    git remote add origin "$REPO_URL"
fi

# Force push to remote repository
echo -e "${YELLOW}Force pushing to remote repository...${NC}"
if git push -f origin "$CURRENT_BRANCH"; then
    echo -e "${GREEN}Force push successful!${NC}"
else
    echo -e "${RED}Force push failed.${NC}"
    exit 1
fi

echo -e "\n${GREEN}Repository force push complete!${NC}"
echo -e "${YELLOW}Remote repository now matches your local repository.${NC}"

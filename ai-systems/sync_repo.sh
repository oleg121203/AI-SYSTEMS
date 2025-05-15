#!/bin/bash

# Sync Repository Script for AI-SYSTEMS
# This script synchronizes the local repository with the remote GitHub repository

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Synchronizing AI-SYSTEMS repository...${NC}"

# Load environment variables
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
    echo -e "${GREEN}Environment variables loaded from .env file${NC}"
else
    echo -e "${RED}Error: .env file not found. Please run setup.sh first.${NC}"
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

# Check if repository directory exists
if [ ! -d "$REPO_PATH" ]; then
    echo -e "${RED}Error: Repository directory does not exist. Please run setup.sh first.${NC}"
    exit 1
fi

# Check if it's a Git repository
if [ ! -d "$REPO_PATH/.git" ]; then
    echo -e "${RED}Error: Git repository is not initialized. Please run setup.sh first.${NC}"
    exit 1
fi

# Check if GitHub token and repo are set
if [ -z "$GITHUB_TOKEN" ] || [ -z "$GITHUB_REPO" ]; then
    echo -e "${RED}Error: GITHUB_TOKEN or GITHUB_REPO not set in .env file${NC}"
    exit 1
fi

# Set the remote URL with token for authentication
cd "$REPO_PATH" || exit 1
REPO_URL="https://${GITHUB_TOKEN}@github.com/${GITHUB_REPO}.git"

# Check if remote exists
REMOTE_EXISTS=$(git remote -v | grep -c origin)
if [ "$REMOTE_EXISTS" -eq 0 ]; then
    echo -e "${YELLOW}Adding remote repository...${NC}"
    git remote add origin "$REPO_URL"
else
    echo -e "${YELLOW}Updating remote repository URL...${NC}"
    git remote set-url origin "$REPO_URL"
fi

# Fetch from remote
echo -e "${YELLOW}Fetching from remote repository...${NC}"
git fetch origin

# Check if remote repo exists and has commits
REMOTE_BRANCHES=$(git ls-remote --heads origin)
if echo "$REMOTE_BRANCHES" | grep -q "refs/heads/main"; then
    REMOTE_BRANCH="main"
elif echo "$REMOTE_BRANCHES" | grep -q "refs/heads/master"; then
    REMOTE_BRANCH="master"
else
    echo -e "${YELLOW}Remote repository appears to be empty.${NC}"
    REMOTE_BRANCH=""
fi

# Get current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo -e "${YELLOW}Current branch: $CURRENT_BRANCH${NC}"

# If remote has content, try to sync
if [ -n "$REMOTE_BRANCH" ]; then
    echo -e "${YELLOW}Remote branch found: $REMOTE_BRANCH${NC}"
    
    # Check if there are local commits
    LOCAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    
    if [ "$LOCAL_COMMITS" -gt 0 ]; then
        echo -e "${YELLOW}Local repository has $LOCAL_COMMITS commits${NC}"
        
        # If the remote branch already exists, fetch it first
        git fetch origin "$REMOTE_BRANCH" || true
        
        # Check if remote branch exists locally
        if git show-ref --verify --quiet "refs/heads/$REMOTE_BRANCH"; then
            echo -e "${YELLOW}Local $REMOTE_BRANCH branch already exists${NC}"
        else
            # If branches have different names, create tracking branch
            if [ "$CURRENT_BRANCH" != "$REMOTE_BRANCH" ]; then
                echo -e "${YELLOW}Creating local $REMOTE_BRANCH branch...${NC}"
                git checkout -b "$REMOTE_BRANCH" 2>/dev/null || git checkout "$REMOTE_BRANCH"
            fi
        fi
        
        echo -e "${YELLOW}Would you like to (f)etch only, (p)ull changes, or (o)verwrite remote? [f/p/o]: ${NC}"
        read -n 1 -r
        echo ""
        
        if [[ $REPLY =~ ^[Pp]$ ]]; then
            # Try to pull (with rebase to avoid merge commits)
            echo -e "${YELLOW}Pulling changes from remote repository...${NC}"
            if git pull --rebase origin "$REMOTE_BRANCH"; then
                echo -e "${GREEN}Successfully pulled changes${NC}"
            else
                echo -e "${RED}Pull failed. You may need to resolve conflicts manually.${NC}"
                git rebase --abort 2>/dev/null
                echo -e "${YELLOW}Trying to merge instead...${NC}"
                if git pull origin "$REMOTE_BRANCH"; then
                    echo -e "${GREEN}Merge successful${NC}"
                else
                    echo -e "${RED}Merge failed. Manual intervention required.${NC}"
                    exit 1
                fi
            fi
        elif [[ $REPLY =~ ^[Oo]$ ]]; then
            # Force push local changes to overwrite remote
            echo -e "${YELLOW}Force pushing local changes to overwrite remote repository...${NC}"
            git push -f origin "$CURRENT_BRANCH:$REMOTE_BRANCH"
        else
            echo -e "${YELLOW}Fetching only, no changes applied.${NC}"
        fi
    else
        # If no local commits, just checkout the remote branch
        echo -e "${YELLOW}No local commits found. Checking out remote branch...${NC}"
        git checkout -b "$REMOTE_BRANCH" origin/"$REMOTE_BRANCH" || git checkout "$REMOTE_BRANCH"
    fi
    
    # Push local changes if any
    echo -e "${YELLOW}Would you like to push local changes to remote repository? (y/n) ${NC}"
    read -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Pushing local changes to remote repository...${NC}"
        git push -u origin "$CURRENT_BRANCH" || git push -u origin "$REMOTE_BRANCH"
    else
        echo -e "${YELLOW}Skipping push to remote repository.${NC}"
    fi
else
    # If remote is empty, push the current branch
    echo -e "${YELLOW}Would you like to push the current branch to remote repository? (y/n) ${NC}"
    read -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Pushing current branch to remote repository...${NC}"
        git push -u origin "$CURRENT_BRANCH"
    else
        echo -e "${YELLOW}Skipping push to remote repository.${NC}"
    fi
fi

echo -e "\n${GREEN}Repository synchronization complete!${NC}"

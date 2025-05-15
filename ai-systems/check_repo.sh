#!/bin/bash

# Check Repository Script for AI-SYSTEMS
# This script verifies the AI-SYSTEMS repository setup and configuration

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Checking AI-SYSTEMS configuration...${NC}"

# Load environment variables
if [ -f ".env" ]; then
    source .env
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
if [ -d "$REPO_PATH" ]; then
    echo -e "${GREEN}Repository directory exists${NC}"
else
    echo -e "${RED}Error: Repository directory does not exist. Please run setup.sh first.${NC}"
    exit 1
fi

# Check if it's a Git repository
if [ -d "$REPO_PATH/.git" ]; then
    echo -e "${GREEN}Git repository is properly initialized${NC}"
else
    echo -e "${RED}Error: Git repository is not initialized. Please run setup.sh first.${NC}"
    exit 1
fi

# Check Git user configuration
GIT_USER=$(cd $REPO_PATH && git config user.name)
GIT_EMAIL=$(cd $REPO_PATH && git config user.email)

if [ -n "$GIT_USER" ]; then
    echo -e "${GREEN}Git user name: $GIT_USER${NC}"
else
    echo -e "${RED}Warning: Git user name is not configured${NC}"
fi

if [ -n "$GIT_EMAIL" ]; then
    echo -e "${GREEN}Git user email: $GIT_EMAIL${NC}"
else
    echo -e "${RED}Warning: Git user email is not configured${NC}"
fi

# Check if logs directory exists
if [ -d "./logs" ]; then
    echo -e "${GREEN}Logs directory exists${NC}"
else
    echo -e "${RED}Error: Logs directory does not exist. Please run setup.sh first.${NC}"
    exit 1
fi

# Check GitHub integration
if [ -n "$GITHUB_TOKEN" ] && [ -n "$GITHUB_REPO" ]; then
    echo -e "${GREEN}GitHub integration configured:${NC}"
    echo -e "${GREEN}  - Repository: $GITHUB_REPO${NC}"
    
    # Check remote repository
    REMOTE_URL=$(cd $REPO_PATH && git remote get-url origin 2>/dev/null)
    if [ -n "$REMOTE_URL" ]; then
        echo -e "${GREEN}  - Remote URL: $REMOTE_URL${NC}"
    else
        echo -e "${YELLOW}Warning: Remote repository not configured${NC}"
    fi
else
    echo -e "${YELLOW}Warning: GitHub integration not fully configured${NC}"
    echo -e "${YELLOW}  - GITHUB_TOKEN: ${GITHUB_TOKEN:+set}${GITHUB_TOKEN:-not set}${NC}"
    echo -e "${YELLOW}  - GITHUB_REPO: ${GITHUB_REPO:-not set}${NC}"
fi

echo -e "\n${GREEN}Configuration check complete!${NC}"
echo -e "${YELLOW}If you found any issues, please run ./setup.sh to fix them.${NC}"

#!/bin/bash

# Reset Repository Script for AI-SYSTEMS
# This script resets the local repository to a clean state

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}WARNING: This script will reset your local AI-SYSTEMS repository.${NC}"
echo -e "${YELLOW}All uncommitted changes and local commits will be lost.${NC}"
read -p "Are you sure you want to continue? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Reset cancelled.${NC}"
    exit 0
fi

echo -e "${GREEN}Resetting AI-SYSTEMS repository...${NC}"

# Load environment variables
if [ -f ".env" ]; then
    source .env
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

# Reset repository directory
if [ -d "$REPO_PATH" ]; then
    echo -e "${YELLOW}Removing existing repository directory...${NC}"
    rm -rf "$REPO_PATH"
fi

echo -e "${YELLOW}Creating new repository directory...${NC}"
mkdir -p "$REPO_PATH"

# Run setup script to initialize the repository
echo -e "${YELLOW}Initializing repository with setup script...${NC}"
./setup.sh

echo -e "\n${GREEN}Repository reset complete!${NC}"
echo -e "${GREEN}A fresh repository has been created at: $REPO_PATH${NC}"

#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print header
echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}    AI-SYSTEMS Virtual Environment Setup${NC}"
echo -e "${GREEN}====================================${NC}"

# Get the directory of this script
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo -e "${YELLOW}Root directory: ${ROOT_DIR}${NC}"

# Ensure Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${BLUE}Python version: ${PYTHON_VERSION}${NC}"

# Create virtual environment if it doesn't exist
VENV_DIR="${ROOT_DIR}/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo -e "${RED}Failed to create virtual environment.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Virtual environment created.${NC}"
else
    echo -e "${BLUE}Using existing virtual environment.${NC}"
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source "${VENV_DIR}/bin/activate"

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install --upgrade pip
pip install -r "${ROOT_DIR}/requirements.txt"
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to install dependencies.${NC}"
    exit 1
fi

# Install additional dependencies for specific components
for component in ai-core development-agents project-manager cmp; do
    COMPONENT_DIR="${ROOT_DIR}/ai-systems/${component}"
    REQUIREMENTS_FILE="${COMPONENT_DIR}/requirements.txt"
    
    if [ -f "$REQUIREMENTS_FILE" ]; then
        echo -e "${YELLOW}Installing dependencies for ${component}...${NC}"
        pip install -r "$REQUIREMENTS_FILE"
    fi
done

echo -e "${GREEN}-----------------------------------${NC}"
echo -e "${GREEN}Virtual environment setup complete.${NC}"
echo -e "${GREEN}To activate the environment, run:${NC}"
echo -e "${BLUE}source ${VENV_DIR}/bin/activate${NC}"
echo -e "${GREEN}-----------------------------------${NC}"

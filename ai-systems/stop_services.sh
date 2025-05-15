#!/bin/bash

# Stop script for AI-SYSTEMS
# This script stops all the services started by run_services.sh

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Stopping AI-SYSTEMS services from ai-systems directory...${NC}"

# Determine the root directory
ROOT_DIR="$(dirname "$(pwd)")"
echo -e "${YELLOW}Using root directory: ${ROOT_DIR}${NC}"

# Check if PID files exist
if [ ! -f "${ROOT_DIR}/.ai_core.pid" ] || [ ! -f "${ROOT_DIR}/.dev_agents.pid" ] || [ ! -f "${ROOT_DIR}/.project_manager.pid" ] || [ ! -f "${ROOT_DIR}/.cmp.pid" ] || [ ! -f "${ROOT_DIR}/.git_service.pid" ] || [ ! -f "${ROOT_DIR}/.web_backend.pid" ] || [ ! -f "${ROOT_DIR}/.web_frontend.pid" ]; then
    echo -e "${YELLOW}Warning: Some PID files not found. Services may not be running.${NC}"
fi

# Stop AI Core
if [ -f "${ROOT_DIR}/.ai_core.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.ai_core.pid")
    echo -e "${YELLOW}Stopping AI Core (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop AI Core.${NC}"
    rm "${ROOT_DIR}/.ai_core.pid"
fi

# Stop Development Agents
if [ -f "${ROOT_DIR}/.dev_agents.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.dev_agents.pid")
    echo -e "${YELLOW}Stopping Development Agents (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop Development Agents.${NC}"
    rm "${ROOT_DIR}/.dev_agents.pid"
fi

# Stop Project Manager
if [ -f "${ROOT_DIR}/.project_manager.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.project_manager.pid")
    echo -e "${YELLOW}Stopping Project Manager (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop Project Manager.${NC}"
    rm "${ROOT_DIR}/.project_manager.pid"
fi

# Stop CMP
if [ -f "${ROOT_DIR}/.cmp.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.cmp.pid")
    echo -e "${YELLOW}Stopping CMP (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop CMP.${NC}"
    rm "${ROOT_DIR}/.cmp.pid"
fi

# Stop Git Service
if [ -f "${ROOT_DIR}/.git_service.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.git_service.pid")
    echo -e "${YELLOW}Stopping Git Service (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop Git Service.${NC}"
    rm "${ROOT_DIR}/.git_service.pid"
fi

# Stop Web Backend
if [ -f "${ROOT_DIR}/.web_backend.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.web_backend.pid")
    echo -e "${YELLOW}Stopping Web Backend (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop Web Backend.${NC}"
    rm "${ROOT_DIR}/.web_backend.pid"
fi

# Stop Web Frontend
if [ -f "${ROOT_DIR}/.web_frontend.pid" ]; then
    PID=$(cat "${ROOT_DIR}/.web_frontend.pid")
    echo -e "${YELLOW}Stopping Web Frontend (PID: $PID)...${NC}"
    kill $PID 2>/dev/null || echo -e "${RED}Failed to stop Web Frontend.${NC}"
    rm "${ROOT_DIR}/.web_frontend.pid"
fi

# Additional fallback to kill processes by port if PID files failed
echo -e "${YELLOW}Performing additional process cleanup by port detection...${NC}"

# Function to kill process by port if running
kill_by_port() {
    local port=$1
    local service_name=$2

    local pid=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo -e "${YELLOW}Found $service_name still running on port $port (PID: $pid). Stopping...${NC}"
        kill $pid 2>/dev/null || kill -9 $pid 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${YELLOW}Successfully stopped $service_name.${NC}"
        else
            echo -e "${RED}Failed to stop $service_name on port $port.${NC}"
        fi
    fi
}

# Check common service ports
kill_by_port 7871 "AI Core"
kill_by_port 7872 "Development Agents"
kill_by_port 7873 "Project Manager"
kill_by_port 7874 "CMP"
kill_by_port 7875 "Git Service"
kill_by_port 8000 "Web Backend"
kill_by_port 3000 "Web Frontend"

echo -e "${GREEN}All services stopped.${NC}"

#!/bin/bash

# Improved Stop Script for AI-SYSTEMS
# This script stops all AI-SYSTEMS services, whether running in Docker or directly on the host

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== AI-SYSTEMS Service Manager - Stop Services ===${NC}"
echo -e "${GREEN}Stopping all AI-SYSTEMS services...${NC}"

# Determine the root directory
ROOT_DIR="$(dirname "$(pwd)")"
echo -e "${YELLOW}Using root directory: ${ROOT_DIR}${NC}"

# Function to stop Docker containers
stop_docker_services() {
    echo -e "\n${YELLOW}Checking for Docker containers...${NC}"
    
    # Check if Docker is running
    if ! docker info &>/dev/null; then
        echo -e "${YELLOW}Docker is not running. Skipping Docker container checks.${NC}"
        return
    fi
    
    # Check if docker-compose is available
    if ! command -v docker-compose &>/dev/null; then
        echo -e "${YELLOW}docker-compose command not found. Skipping Docker container checks.${NC}"
        return
    fi
    
    # Check if any AI-SYSTEMS containers are running
    if docker ps --format '{{.Names}}' | grep -q 'ai-systems'; then
        echo -e "${GREEN}Found running AI-SYSTEMS Docker containers. Stopping...${NC}"
        
        # Go to the directory with docker-compose.yml
        cd "$(pwd)"
        
        # Stop all containers defined in docker-compose.yml
        echo -e "${YELLOW}Stopping Docker containers with docker-compose down...${NC}"
        docker-compose down
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}Successfully stopped all Docker containers.${NC}"
        else
            echo -e "${RED}Failed to stop Docker containers with docker-compose down.${NC}"
            
            # Fallback: try to stop containers manually
            echo -e "${YELLOW}Attempting to stop containers manually...${NC}"
            docker stop $(docker ps -q --filter "name=ai-systems") 2>/dev/null
            
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}Successfully stopped containers manually.${NC}"
            else
                echo -e "${RED}Failed to stop containers manually. Some containers may still be running.${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}No running AI-SYSTEMS Docker containers found.${NC}"
    fi
}

# Function to stop processes by PID files
stop_pid_processes() {
    echo -e "\n${YELLOW}Checking for PID files...${NC}"
    
    # Define service names and their PID files
    service_names=("AI_Core" "Development_Agents" "Project_Manager" "CMP" "Git_Service" "Web_Backend" "Web_Frontend")
    pid_files=(
        "${ROOT_DIR}/.ai_core.pid"
        "${ROOT_DIR}/.dev_agents.pid"
        "${ROOT_DIR}/.project_manager.pid"
        "${ROOT_DIR}/.cmp.pid"
        "${ROOT_DIR}/.git_service.pid"
        "${ROOT_DIR}/.web_backend.pid"
        "${ROOT_DIR}/.web_frontend.pid"
    )
    display_names=(
        "AI Core"
        "Development Agents"
        "Project Manager"
        "CMP"
        "Git Service"
        "Web Backend"
        "Web Frontend"
    )
    
    pid_files_found=false
    
    # Stop each service if PID file exists
    for i in ${!service_names[@]}; do
        service_name=${service_names[$i]}
        display_name=${display_names[$i]}
        pid_file=${pid_files[$i]}
        
        if [ -f "$pid_file" ]; then
            pid_files_found=true
            PID=$(cat "$pid_file")
            echo -e "${YELLOW}Stopping $display_name (PID: $PID)...${NC}"
            
            # Check if process is still running
            if ps -p $PID > /dev/null 2>&1; then
                kill $PID 2>/dev/null
                sleep 1
                
                # If process is still running, force kill
                if ps -p $PID > /dev/null 2>&1; then
                    echo -e "${YELLOW}$display_name still running. Force killing...${NC}"
                    kill -9 $PID 2>/dev/null
                    
                    if [ $? -eq 0 ]; then
                        echo -e "${GREEN}Successfully force killed $display_name.${NC}"
                    else
                        echo -e "${RED}Failed to force kill $display_name.${NC}"
                    fi
                else
                    echo -e "${GREEN}Successfully stopped $display_name.${NC}"
                fi
            else
                echo -e "${YELLOW}Process for $display_name (PID: $PID) not found. It may have already been stopped.${NC}"
            fi
            
            # Remove PID file
            rm "$pid_file"
        fi
    done
    
    if [ "$pid_files_found" = false ]; then
        echo -e "${YELLOW}No PID files found. Services may not be running or are running in Docker.${NC}"
    fi
}

# Function to kill processes by port
kill_by_port() {
    echo -e "\n${YELLOW}Performing additional process cleanup by port detection...${NC}"
    
    # Define service names and their ports
    service_ports=(
        7861  # AI Core
        7862  # Development Agents
        7863  # Project Manager
        7864  # CMP
        7865  # Git Service
        8001  # Web Backend
        3000  # Web Frontend
    )
    
    processes_found=false
    
    # Check each port
    for i in ${!service_ports[@]}; do
        port=${service_ports[$i]}
        display_name=${display_names[$i]}
        
        # Find process using this port
        pid=$(lsof -ti:$port 2>/dev/null)
        
        if [ -n "$pid" ]; then
            processes_found=true
            echo -e "${YELLOW}Found $display_name still running on port $port (PID: $pid). Stopping...${NC}"
            
            # Try graceful kill first
            kill $pid 2>/dev/null
            sleep 1
            
            # Check if process is still running
            if lsof -ti:$port > /dev/null 2>&1; then
                echo -e "${YELLOW}$display_name still running. Force killing...${NC}"
                kill -9 $pid 2>/dev/null
                
                if lsof -ti:$port > /dev/null 2>&1; then
                    echo -e "${RED}Failed to stop $display_name on port $port.${NC}"
                else
                    echo -e "${GREEN}Successfully stopped $display_name.${NC}"
                fi
            else
                echo -e "${GREEN}Successfully stopped $display_name.${NC}"
            fi
        fi
    done
    
    if [ "$processes_found" = false ]; then
        echo -e "${YELLOW}No processes found running on service ports.${NC}"
    fi
}

# Main execution flow
# 1. First stop Docker containers
stop_docker_services

# 2. Then stop processes identified by PID files
stop_pid_processes

# 3. Finally, kill any remaining processes by port
kill_by_port

echo -e "\n${GREEN}All services stopped.${NC}"
echo -e "${BLUE}=== AI-SYSTEMS Service Manager - Complete ===${NC}"

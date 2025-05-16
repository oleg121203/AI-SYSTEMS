#!/bin/bash

# AI-SYSTEMS Launcher - Quick access to management interfaces
# This script provides a simple way to launch either the CLI or web interface

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Determine the root directory
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Function to display header
display_header() {
  clear
  echo -e "${BLUE}${BOLD}============================================${NC}"
  echo -e "${BLUE}${BOLD}           AI-SYSTEMS LAUNCHER             ${NC}"
  echo -e "${BLUE}${BOLD}============================================${NC}"
  echo -e "${CYAN}Current directory: ${ROOT_DIR}${NC}"
  echo -e "${CYAN}Date: $(date)${NC}"
  echo
}

# Function to start CLI interface
start_cli() {
  echo -e "${GREEN}Starting Command Line Interface...${NC}"
  bash "${ROOT_DIR}/ai-systems-manager.sh"
}

# Function to start web interface
start_web_interface() {
  echo -e "${GREEN}Starting Web Interface...${NC}"
  
  # Check if Node.js is installed
  if ! command -v node &>/dev/null; then
    echo -e "${YELLOW}Node.js is not installed. Please install Node.js first.${NC}"
    return 1
  fi
  
  # Check if dependencies are installed
  if [ ! -d "${ROOT_DIR}/ai-systems-web-manager/node_modules" ]; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    cd "${ROOT_DIR}/ai-systems-web-manager" && npm install
  fi
  
  # Check if port 3030 is already in use
  if lsof -i:3030 > /dev/null 2>&1; then
    echo -e "${YELLOW}Port 3030 is already in use. Would you like to:${NC}"
    echo "1. Stop the existing process and start a new one"
    echo "2. Use a different port"
    echo "3. Cancel"
    
    read -p "Enter your choice [1-3]: " port_choice
    
    case $port_choice in
      1)
        echo -e "${YELLOW}Stopping existing process on port 3030...${NC}"
        kill $(lsof -t -i:3030) 2>/dev/null
        sleep 2
        
        # Double-check if the port is now available
        if lsof -i:3030 > /dev/null 2>&1; then
          echo -e "${RED}Failed to stop the process. Please stop it manually and try again.${NC}"
          return 1
        fi
        
        echo -e "${GREEN}Process stopped successfully.${NC}"
        PORT=3030
        ;;
      2)
        # Find an available port starting from 3031
        PORT=3031
        while lsof -i:$PORT > /dev/null 2>&1; do
          PORT=$((PORT+1))
          if [ $PORT -gt 3050 ]; then
            echo -e "${RED}Could not find an available port in range 3031-3050.${NC}"
            return 1
          fi
        done
        echo -e "${GREEN}Using available port: $PORT${NC}"
        ;;
      3)
        echo -e "${YELLOW}Operation cancelled.${NC}"
        return 0
        ;;
      *)
        echo -e "${RED}Invalid option. Exiting.${NC}"
        return 1
        ;;
    esac
  else
    PORT=3031
  fi
  
  # Kill any existing processes on port 3031
  echo -e "${YELLOW}Checking for existing processes on port 3031...${NC}"
  lsof -i :3031 | grep LISTEN | awk '{print $2}' | xargs kill -9 2>/dev/null
  sleep 1
  
  echo -e "${GREEN}Launching web interface on http://localhost:$PORT${NC}"
  echo -e "${YELLOW}Press Ctrl+C to stop the web interface${NC}"
  
  # If using a different port, temporarily modify the server.js file
  if [ $PORT -ne 3030 ]; then
    # Create a backup of the original server.js
    cp "${ROOT_DIR}/ai-systems-web-manager/server.js" "${ROOT_DIR}/ai-systems-web-manager/server.js.bak"
    
    # Replace the port in server.js
    sed -i '' "s/const PORT = process.env.PORT || 3030;/const PORT = process.env.PORT || $PORT;/" "${ROOT_DIR}/ai-systems-web-manager/server.js"
    
    # Start the server
    cd "${ROOT_DIR}/ai-systems-web-manager" && npm start
    
    # Restore the original server.js when the server is stopped
    trap "mv \"${ROOT_DIR}/ai-systems-web-manager/server.js.bak\" \"${ROOT_DIR}/ai-systems-web-manager/server.js\"" EXIT
  else
    # Start with the default port
    cd "${ROOT_DIR}/ai-systems-web-manager" && npm start
  fi
}

# Main function
main() {
  display_header
  
  echo -e "${YELLOW}Please select an interface:${NC}"
  echo "1. Command Line Interface (CLI)"
  echo "2. Web Interface"
  echo "3. Exit"
  echo
  
  # Get user choice with proper validation
  while true; do
    read -p "Enter your choice [1-3]: " choice
    
    case $choice in
      1)
        start_cli
        break
        ;;
      2)
        start_web_interface
        break
        ;;
      3)
        echo -e "${GREEN}Exiting. Goodbye!${NC}"
        exit 0
        ;;
      *)
        echo -e "${RED}Invalid option. Please enter 1, 2, or 3.${NC}"
        ;;
    esac
  done
}

# Run the main function
main

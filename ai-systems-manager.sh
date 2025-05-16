#!/bin/bash

# AI-SYSTEMS Manager - Unified Management Script
# This script provides a central interface to manage all AI-SYSTEMS operations

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
AI_SYSTEMS_DIR="${ROOT_DIR}/ai-systems"

# Check if the script is run with root privileges
check_root() {
  if [ "$(id -u)" -eq 0 ]; then
    echo -e "${RED}This script should not be run as root!${NC}"
    exit 1
  fi
}

# Display the header
display_header() {
  clear
  echo -e "${BLUE}${BOLD}============================================${NC}"
  echo -e "${BLUE}${BOLD}         AI-SYSTEMS MANAGEMENT TOOL         ${NC}"
  echo -e "${BLUE}${BOLD}============================================${NC}"
  echo -e "${CYAN}Current directory: ${ROOT_DIR}${NC}"
  echo -e "${CYAN}Date: $(date)${NC}"
  echo
}

# Function to check if Docker is running
check_docker() {
  if ! docker info &>/dev/null; then
    echo -e "${RED}Docker is not running. Please start Docker first.${NC}"
    return 1
  fi
  return 0
}

# Function to check if docker-compose is available
check_docker_compose() {
  if ! command -v docker-compose &>/dev/null; then
    echo -e "${RED}docker-compose command not found. Please install docker-compose first.${NC}"
    return 1
  fi
  return 0
}

# Function to start services
start_services() {
  display_header
  echo -e "${GREEN}Starting AI-SYSTEMS services...${NC}"
  
  # Check if we should use Docker or direct start
  if [ "$1" == "docker" ]; then
    if ! check_docker; then return 1; fi
    if ! check_docker_compose; then return 1; fi
    
    echo -e "${YELLOW}Starting services using Docker...${NC}"
    cd "${AI_SYSTEMS_DIR}" || {
      echo -e "${RED}ai-systems directory not found.${NC}"
      return 1
    }
    
    # Check if a specific profile was requested
    if [ -n "$2" ]; then
      echo -e "${YELLOW}Using profile: $2${NC}"
      docker-compose --profile "$2" up -d
    else
      echo -e "${YELLOW}Starting all services...${NC}"
      docker-compose up -d
    fi
  else
    echo -e "${YELLOW}Starting services directly...${NC}"
    bash "${AI_SYSTEMS_DIR}/run_services.sh"
  fi
  
  echo -e "${GREEN}Services started successfully.${NC}"
  read -p "Press Enter to continue..."
  return 0
}

# Function to stop services
stop_services() {
  display_header
  echo -e "${GREEN}Stopping AI-SYSTEMS services...${NC}"
  
  bash "${AI_SYSTEMS_DIR}/stop_services.sh"
  
  echo -e "${GREEN}Services stopped successfully.${NC}"
  read -p "Press Enter to continue..."
  return 0
}

# Function to test Docker profiles
test_profiles() {
  display_header
  echo -e "${GREEN}Testing Docker Compose profiles...${NC}"
  
  if ! check_docker; then return 1; fi
  if ! check_docker_compose; then return 1; fi
  
  bash "${AI_SYSTEMS_DIR}/test_profiles.sh"
  
  read -p "Press Enter to continue..."
  return 0
}

# Function to monitor performance
monitor_performance() {
  display_header
  echo -e "${GREEN}Monitoring system performance...${NC}"
  
  if ! check_docker; then return 1; fi
  
  bash "${AI_SYSTEMS_DIR}/monitor_performance.sh"
  
  read -p "Press Enter to continue..."
  return 0
}

# Function to backup volumes
backup_volumes() {
  display_header
  echo -e "${GREEN}Managing Docker volume backups...${NC}"
  
  if ! check_docker; then return 1; fi
  
  bash "${AI_SYSTEMS_DIR}/backup_volumes.sh"
  
  read -p "Press Enter to continue..."
  return 0
}

# Function to manage Git repository
manage_git() {
  display_header
  echo -e "${GREEN}Git Repository Management${NC}"
  
  local git_menu=true
  
  while $git_menu; do
    echo -e "\n${BLUE}Git Management Options:${NC}"
    echo "1. Check repository status"
    echo "2. Sync repository"
    echo "3. Force push changes"
    echo "4. Reset repository"
    echo "5. Return to main menu"
    
    read -p "Enter your choice [1-5]: " git_choice
    
    case $git_choice in
      1)
        bash "${AI_SYSTEMS_DIR}/check_repo.sh"
        ;;
      2)
        bash "${AI_SYSTEMS_DIR}/sync_repo.sh"
        ;;
      3)
        bash "${AI_SYSTEMS_DIR}/force_push.sh"
        ;;
      4)
        bash "${AI_SYSTEMS_DIR}/reset_repo.sh"
        ;;
      5)
        git_menu=false
        ;;
      *)
        echo -e "${RED}Invalid option. Please try again.${NC}"
        ;;
    esac
    
    if $git_menu; then
      read -p "Press Enter to continue..."
    fi
  done
}

# Function to clean and rebuild Docker containers
docker_clean_rebuild() {
  display_header
  echo -e "${GREEN}Cleaning and rebuilding Docker containers...${NC}"
  
  if ! check_docker; then return 1; fi
  if ! check_docker_compose; then return 1; fi
  
  bash "${AI_SYSTEMS_DIR}/docker_clean_rebuild.sh"
  
  read -p "Press Enter to continue..."
  return 0
}

# Function to start the web management interface
start_web_interface() {
  display_header
  echo -e "${GREEN}Starting Web Management Interface...${NC}"
  
  # Check if the web interface directory exists
  if [ ! -d "${ROOT_DIR}/ai-systems-web-manager" ]; then
    echo -e "${YELLOW}Web interface not found. Setting it up...${NC}"
    setup_web_interface
  fi
  
  # Start the web interface
  cd "${ROOT_DIR}/ai-systems-web-manager" || {
    echo -e "${RED}Web interface directory not found.${NC}"
    return 1
  }
  
  # Check if Node.js is installed
  if ! command -v node &>/dev/null; then
    echo -e "${RED}Node.js is not installed. Please install Node.js first.${NC}"
    return 1
  }
  
  echo -e "${YELLOW}Starting web interface on http://localhost:3030${NC}"
  echo -e "${YELLOW}Press Ctrl+C to stop the web interface${NC}"
  
  npm start
  
  read -p "Press Enter to continue..."
  return 0
}

# Function to setup the web interface
setup_web_interface() {
  display_header
  echo -e "${GREEN}Setting up Web Management Interface...${NC}"
  
  # Create web interface directory if it doesn't exist
  mkdir -p "${ROOT_DIR}/ai-systems-web-manager"
  
  # We'll create the web interface files in a separate function
  create_web_interface_files
  
  echo -e "${GREEN}Web interface setup complete.${NC}"
  read -p "Press Enter to continue..."
  return 0
}

# Main menu
main_menu() {
  local exit_script=false
  
  while ! $exit_script; do
    display_header
    
    echo -e "${BLUE}Main Menu:${NC}"
    echo "1. Start Services (Direct)"
    echo "2. Start Services (Docker)"
    echo "3. Stop All Services"
    echo "4. Test Docker Profiles"
    echo "5. Monitor System Performance"
    echo "6. Backup Volume Management"
    echo "7. Git Repository Management"
    echo "8. Clean and Rebuild Docker"
    echo "9. Web Management Interface"
    echo "0. Exit"
    
    read -p "Enter your choice [0-9]: " choice
    
    case $choice in
      1)
        start_services "direct"
        ;;
      2)
        echo -e "\n${BLUE}Available profiles:${NC}"
        echo "1. infrastructure - Core infrastructure services"
        echo "2. ai - AI services"
        echo "3. web - Web frontend and backend"
        echo "4. management - Management services"
        echo "5. monitoring - Monitoring services"
        echo "6. full - All services"
        echo "7. No profile (start all)"
        
        read -p "Select profile [1-7]: " profile_choice
        
        case $profile_choice in
          1) start_services "docker" "infrastructure" ;;
          2) start_services "docker" "ai" ;;
          3) start_services "docker" "web" ;;
          4) start_services "docker" "management" ;;
          5) start_services "docker" "monitoring" ;;
          6) start_services "docker" "full" ;;
          7) start_services "docker" ;;
          *) echo -e "${RED}Invalid profile choice.${NC}" ;;
        esac
        ;;
      3)
        stop_services
        ;;
      4)
        test_profiles
        ;;
      5)
        monitor_performance
        ;;
      6)
        backup_volumes
        ;;
      7)
        manage_git
        ;;
      8)
        docker_clean_rebuild
        ;;
      9)
        start_web_interface
        ;;
      0)
        echo -e "${GREEN}Exiting AI-SYSTEMS Manager. Goodbye!${NC}"
        exit_script=true
        ;;
      *)
        echo -e "${RED}Invalid option. Please try again.${NC}"
        read -p "Press Enter to continue..."
        ;;
    esac
  done
}

# Check if the script is run with root privileges
check_root

# Start the main menu
main_menu

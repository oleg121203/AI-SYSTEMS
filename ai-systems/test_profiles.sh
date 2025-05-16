#!/bin/bash
# Script to test different Docker Compose profiles

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== AI-SYSTEMS Docker Compose Profile Testing ===${NC}"

# Function to test a profile
test_profile() {
    local profile=$1
    echo -e "\n${YELLOW}Testing profile: ${profile}${NC}"
    
    # Stop all containers first
    echo "Stopping all containers..."
    docker-compose down
    
    # Start containers with the specified profile
    echo "Starting containers with profile: ${profile}..."
    docker-compose --profile ${profile} up -d
    
    # Wait for containers to start
    echo "Waiting for containers to initialize (30 seconds)..."
    sleep 30
    
    # List running containers
    echo -e "\n${GREEN}Running containers for profile '${profile}':${NC}"
    docker-compose ps
    
    # Check health status
    echo -e "\n${GREEN}Health status for profile '${profile}':${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}" | grep -i ${profile}
    
    # Optional: Test specific endpoints
    if [[ "$profile" == "web" || "$profile" == "full" ]]; then
        echo -e "\n${GREEN}Testing web endpoints:${NC}"
        curl -s http://localhost:8001/health | jq || echo "Web backend not responding"
    fi
    
    if [[ "$profile" == "ai" || "$profile" == "full" ]]; then
        echo -e "\n${GREEN}Testing AI endpoints:${NC}"
        curl -s http://localhost:7861/health | jq || echo "AI Core not responding"
    fi
    
    echo -e "\n${YELLOW}Press Enter to continue to the next profile...${NC}"
    read
}

# Test each profile
echo -e "\n${BLUE}Available profiles to test:${NC}"
echo "1. infrastructure - Core infrastructure services"
echo "2. web - Web frontend and backend"
echo "3. ai - AI services"
echo "4. management - Project management services"
echo "5. monitoring - Monitoring services"
echo "6. full - All services"
echo "7. custom - Test a custom combination of profiles"
echo "8. quit - Exit the script"

while true; do
    echo -e "\n${YELLOW}Enter the number of the profile to test:${NC}"
    read choice
    
    case $choice in
        1)
            test_profile "infrastructure"
            ;;
        2)
            test_profile "web"
            ;;
        3)
            test_profile "ai"
            ;;
        4)
            test_profile "management"
            ;;
        5)
            test_profile "monitoring"
            ;;
        6)
            test_profile "full"
            ;;
        7)
            echo -e "${YELLOW}Enter the profiles to test (space-separated, e.g., 'web ai'):${NC}"
            read custom_profiles
            for profile in $custom_profiles; do
                docker-compose --profile $profile config --services
            done
            echo -e "${YELLOW}Start these services? (y/n)${NC}"
            read confirm
            if [[ "$confirm" == "y" ]]; then
                docker-compose down
                docker-compose $(for p in $custom_profiles; do echo "--profile $p"; done) up -d
                sleep 30
                docker-compose ps
            fi
            ;;
        8)
            echo -e "${BLUE}Exiting...${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice. Please try again.${NC}"
            ;;
    esac
done

#!/bin/bash
# Script to monitor Docker container performance

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== AI-SYSTEMS Performance Monitoring ===${NC}"

# Function to monitor container stats
monitor_stats() {
    local duration=$1
    local interval=5  # seconds between measurements
    local iterations=$((duration / interval))
    
    echo -e "\n${YELLOW}Monitoring container performance for ${duration} seconds...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop monitoring early${NC}\n"
    
    # Create a temporary file to store stats
    local temp_file=$(mktemp)
    
    # Headers for the stats
    echo "TIMESTAMP,CONTAINER,CPU%,MEM_USAGE,MEM%,NET_IN,NET_OUT" > $temp_file
    
    # Monitor for the specified duration
    for ((i=1; i<=$iterations; i++)); do
        local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
        
        # Get stats for all containers
        docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}}" | \
        while IFS= read -r line; do
            # Extract network I/O values
            net_io=$(echo $line | cut -d',' -f5)
            net_in=$(echo $net_io | cut -d'/' -f1 | tr -d ' ')
            net_out=$(echo $net_io | cut -d'/' -f2 | tr -d ' ')
            
            # Format the line with timestamp and separated network values
            container=$(echo $line | cut -d',' -f1)
            cpu=$(echo $line | cut -d',' -f2)
            mem_usage=$(echo $line | cut -d',' -f3)
            mem_perc=$(echo $line | cut -d',' -f4)
            
            echo "$timestamp,$container,$cpu,$mem_usage,$mem_perc,$net_in,$net_out" >> $temp_file
            
            # Print current stats
            echo -e "${GREEN}$container${NC}: CPU: $cpu, MEM: $mem_usage ($mem_perc), NET: $net_in / $net_out"
        done
        
        echo -e "\nIteration $i/$iterations - $(date +"%H:%M:%S")"
        
        # Wait for the next interval if not the last iteration
        if [ $i -lt $iterations ]; then
            sleep $interval
            echo -e "-----------------------------------"
        fi
    done
    
    echo -e "\n${YELLOW}Monitoring complete. Stats saved to performance_stats_$(date +"%Y%m%d_%H%M%S").csv${NC}"
    cp $temp_file "performance_stats_$(date +"%Y%m%d_%H%M%S").csv"
    rm $temp_file
}

# Function to run a load test on the API
run_load_test() {
    local endpoint=$1
    local requests=$2
    local concurrency=$3
    
    echo -e "\n${YELLOW}Running load test on $endpoint with $requests requests, $concurrency concurrent...${NC}"
    
    # Check if ab (Apache Bench) is installed
    if ! command -v ab &> /dev/null; then
        echo "Apache Bench (ab) is not installed. Please install it to run load tests."
        return 1
    fi
    
    # Run the load test
    ab -n $requests -c $concurrency -H "Accept: application/json" $endpoint
}

# Main menu
while true; do
    echo -e "\n${BLUE}Performance Monitoring Options:${NC}"
    echo "1. Monitor container stats (30 seconds)"
    echo "2. Monitor container stats (2 minutes)"
    echo "3. Monitor container stats (5 minutes)"
    echo "4. Run load test on web backend health endpoint"
    echo "5. Run load test on AI core health endpoint"
    echo "6. Compare network profiles performance"
    echo "7. Exit"
    
    echo -e "\n${YELLOW}Enter your choice:${NC}"
    read choice
    
    case $choice in
        1)
            monitor_stats 30
            ;;
        2)
            monitor_stats 120
            ;;
        3)
            monitor_stats 300
            ;;
        4)
            run_load_test "http://localhost:8001/health" 1000 10
            ;;
        5)
            run_load_test "http://localhost:7861/health" 1000 10
            ;;
        6)
            echo -e "\n${YELLOW}This will compare performance across different network configurations.${NC}"
            echo "The test will:"
            echo "1. Run with the optimized network configuration"
            echo "2. Temporarily modify docker-compose.yml to use default networking"
            echo "3. Run the same tests and compare results"
            echo -e "${YELLOW}Do you want to proceed? (y/n)${NC}"
            read confirm
            
            if [[ "$confirm" == "y" ]]; then
                # First test with optimized networking
                echo -e "\n${BLUE}Testing with optimized network configuration...${NC}"
                docker-compose down
                docker-compose --profile web up -d
                sleep 30
                monitor_stats 60
                optimized_stats="performance_stats_optimized.csv"
                mv "performance_stats_$(ls -t performance_stats_*.csv | head -1 | cut -d'_' -f3-)" $optimized_stats
                
                # Backup current docker-compose.yml
                cp docker-compose.yml docker-compose.yml.bak
                
                # Modify docker-compose.yml to use default networking
                echo -e "\n${BLUE}Temporarily modifying docker-compose.yml to use default networking...${NC}"
                sed -i.bak '/networks:/,/subnet:/d' docker-compose.yml
                sed -i.bak '/networks:/d' docker-compose.yml
                
                # Test with default networking
                echo -e "\n${BLUE}Testing with default network configuration...${NC}"
                docker-compose down
                docker-compose --profile web up -d
                sleep 30
                monitor_stats 60
                default_stats="performance_stats_default.csv"
                mv "performance_stats_$(ls -t performance_stats_*.csv | head -1 | cut -d'_' -f3-)" $default_stats
                
                # Restore original docker-compose.yml
                mv docker-compose.yml.bak docker-compose.yml
                
                # Compare results
                echo -e "\n${BLUE}Comparison complete. Results saved to:${NC}"
                echo "- Optimized network: $optimized_stats"
                echo "- Default network: $default_stats"
                
                # Restart with optimized networking
                docker-compose down
                docker-compose --profile web up -d
            fi
            ;;
        7)
            echo -e "${BLUE}Exiting...${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice. Please try again.${NC}"
            ;;
    esac
done

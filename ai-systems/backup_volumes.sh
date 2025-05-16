#!/bin/bash
# Script to backup Docker volumes for AI-SYSTEMS

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default backup directory
BACKUP_DIR="${BACKUP_DIR:-/Users/olegkizima/workspace/AI-SYSTEMS/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo -e "${BLUE}=== AI-SYSTEMS Volume Backup Tool ===${NC}"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Function to backup a Docker volume
backup_volume() {
    local volume_name=$1
    local backup_file="$BACKUP_DIR/${volume_name}_${TIMESTAMP}.tar.gz"
    
    echo -e "\n${YELLOW}Backing up volume: ${volume_name}${NC}"
    
    # Check if volume exists
    if ! docker volume inspect "$volume_name" &>/dev/null; then
        echo -e "${RED}Volume $volume_name does not exist. Skipping.${NC}"
        return 1
    fi
    
    # Create a temporary container to access the volume
    echo "Creating temporary container to access volume..."
    docker run --rm -v "$volume_name":/data -v "$BACKUP_DIR":/backup \
        alpine:latest tar -czf "/backup/${volume_name}_${TIMESTAMP}.tar.gz" -C /data .
    
    echo -e "${GREEN}Volume $volume_name backed up to $backup_file${NC}"
    return 0
}

# Function to restore a Docker volume
restore_volume() {
    local volume_name=$1
    local backup_file=$2
    
    echo -e "\n${YELLOW}Restoring volume: ${volume_name} from ${backup_file}${NC}"
    
    # Check if backup file exists
    if [ ! -f "$backup_file" ]; then
        echo -e "${RED}Backup file $backup_file does not exist. Aborting.${NC}"
        return 1
    fi
    
    # Check if volume exists
    if ! docker volume inspect "$volume_name" &>/dev/null; then
        echo -e "${YELLOW}Volume $volume_name does not exist. Creating...${NC}"
        docker volume create "$volume_name"
    else
        echo -e "${YELLOW}Volume $volume_name exists. Data will be overwritten.${NC}"
        echo -e "${YELLOW}Do you want to continue? (y/n)${NC}"
        read confirm
        if [[ "$confirm" != "y" ]]; then
            echo "Restore aborted."
            return 1
        fi
    fi
    
    # Create a temporary container to restore the volume
    echo "Creating temporary container to restore volume..."
    docker run --rm -v "$volume_name":/data -v "$(dirname "$backup_file")":/backup \
        alpine:latest sh -c "rm -rf /data/* /data/..?* /data/.[!.]* ; tar -xzf /backup/$(basename "$backup_file") -C /data"
    
    echo -e "${GREEN}Volume $volume_name restored from $backup_file${NC}"
    return 0
}

# Function to list available backups
list_backups() {
    echo -e "\n${YELLOW}Available backups in $BACKUP_DIR:${NC}"
    
    if [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo "No backups found."
        return
    fi
    
    # List backups by volume
    echo -e "\n${GREEN}Backups by volume:${NC}"
    for volume in postgres_data redis_data rabbitmq_data logs_volume; do
        echo -e "\n${BLUE}$volume:${NC}"
        ls -lh "$BACKUP_DIR" | grep "$volume" | awk '{print $9, "(" $5 ")", "created on", $6, $7, $8}'
    done
}

# Function to setup scheduled backups
setup_scheduled_backups() {
    echo -e "\n${YELLOW}Setting up scheduled backups${NC}"
    echo "This will add a cron job to run backups automatically."
    
    # Check if crontab is available
    if ! command -v crontab &>/dev/null; then
        echo -e "${RED}crontab command not found. Cannot setup scheduled backups.${NC}"
        return 1
    fi
    
    echo -e "\n${YELLOW}Select backup frequency:${NC}"
    echo "1. Daily (at 2 AM)"
    echo "2. Weekly (Sunday at 2 AM)"
    echo "3. Monthly (1st of month at 2 AM)"
    echo "4. Custom (specify your own cron schedule)"
    
    read -p "Enter your choice (1-4): " choice
    
    case $choice in
        1)
            schedule="0 2 * * *"
            description="daily at 2 AM"
            ;;
        2)
            schedule="0 2 * * 0"
            description="weekly on Sunday at 2 AM"
            ;;
        3)
            schedule="0 2 1 * *"
            description="monthly on the 1st at 2 AM"
            ;;
        4)
            echo -e "${YELLOW}Enter custom cron schedule (e.g., '0 2 * * *' for daily at 2 AM):${NC}"
            read schedule
            description="custom schedule: $schedule"
            ;;
        *)
            echo -e "${RED}Invalid choice. Aborting.${NC}"
            return 1
            ;;
    esac
    
    # Create the backup script
    CRON_SCRIPT="$BACKUP_DIR/scheduled_backup.sh"
    
    cat > "$CRON_SCRIPT" << EOF
#!/bin/bash
# Automated backup script for AI-SYSTEMS volumes

BACKUP_DIR="$BACKUP_DIR"
TIMESTAMP=\$(date +"%Y%m%d_%H%M%S")
RETENTION_DAYS=30  # Keep backups for 30 days

# Create backup directory if it doesn't exist
mkdir -p "\$BACKUP_DIR"

# Backup each volume
for volume in ai-systems_postgres_data ai-systems_redis_data ai-systems_rabbitmq_data ai-systems_logs_volume; do
    # Create a temporary container to access the volume
    docker run --rm -v "\$volume":/data -v "\$BACKUP_DIR":/backup \
        alpine:latest tar -czf "/backup/\${volume}_\${TIMESTAMP}.tar.gz" -C /data .
done

# Clean up old backups (older than RETENTION_DAYS)
find "\$BACKUP_DIR" -name "*.tar.gz" -type f -mtime +\$RETENTION_DAYS -delete
EOF
    
    chmod +x "$CRON_SCRIPT"
    
    # Add to crontab
    (crontab -l 2>/dev/null || echo "") | grep -v "$CRON_SCRIPT" > /tmp/crontab.tmp
    echo "$schedule $CRON_SCRIPT >> $BACKUP_DIR/backup.log 2>&1" >> /tmp/crontab.tmp
    crontab /tmp/crontab.tmp
    rm /tmp/crontab.tmp
    
    echo -e "${GREEN}Scheduled backups set up to run $description${NC}"
    echo -e "${GREEN}Backup script created at: $CRON_SCRIPT${NC}"
    echo -e "${GREEN}Backups will be stored in: $BACKUP_DIR${NC}"
    echo -e "${GREEN}Backups older than 30 days will be automatically deleted${NC}"
}

# Function to perform a full backup of all volumes
backup_all_volumes() {
    echo -e "\n${YELLOW}Backing up all volumes...${NC}"
    
    # Check if Docker is running
    if ! docker info &>/dev/null; then
        echo -e "${RED}Docker is not running. Please start Docker and try again.${NC}"
        return 1
    fi
    
    # Create a backup directory for this session
    local session_dir="$BACKUP_DIR/full_backup_$TIMESTAMP"
    mkdir -p "$session_dir"
    
    # Backup each volume
    local volumes=("ai-systems_postgres_data" "ai-systems_redis_data" "ai-systems_rabbitmq_data" "ai-systems_logs_volume")
    local success=true
    
    for volume in "${volumes[@]}"; do
        if ! backup_volume "$volume"; then
            success=false
        fi
    done
    
    if $success; then
        echo -e "\n${GREEN}All volumes backed up successfully to $BACKUP_DIR${NC}"
        # Create a manifest file with backup information
        cat > "$BACKUP_DIR/backup_manifest_$TIMESTAMP.txt" << EOF
AI-SYSTEMS Backup Manifest
Timestamp: $(date)
Volumes backed up:
$(for v in "${volumes[@]}"; do echo "- $v"; done)
EOF
    else
        echo -e "\n${YELLOW}Some volumes could not be backed up. Check the logs above.${NC}"
    fi
}

# Main menu
while true; do
    echo -e "\n${BLUE}AI-SYSTEMS Volume Backup Tool${NC}"
    echo -e "${BLUE}================================${NC}"
    echo "1. Backup all volumes"
    echo "2. Backup specific volume"
    echo "3. Restore volume from backup"
    echo "4. List available backups"
    echo "5. Setup scheduled backups"
    echo "6. Exit"
    
    echo -e "\n${YELLOW}Enter your choice:${NC}"
    read choice
    
    case $choice in
        1)
            backup_all_volumes
            ;;
        2)
            echo -e "\n${YELLOW}Available volumes:${NC}"
            echo "1. postgres_data"
            echo "2. redis_data"
            echo "3. rabbitmq_data"
            echo "4. logs_volume"
            echo -e "\n${YELLOW}Enter volume number:${NC}"
            read volume_choice
            
            case $volume_choice in
                1) backup_volume "ai-systems_postgres_data" ;;
                2) backup_volume "ai-systems_redis_data" ;;
                3) backup_volume "ai-systems_rabbitmq_data" ;;
                4) backup_volume "ai-systems_logs_volume" ;;
                *) echo -e "${RED}Invalid choice.${NC}" ;;
            esac
            ;;
        3)
            list_backups
            echo -e "\n${YELLOW}Enter the full backup filename to restore:${NC}"
            read backup_file
            
            if [[ $backup_file == *"postgres_data"* ]]; then
                restore_volume "ai-systems_postgres_data" "$BACKUP_DIR/$backup_file"
            elif [[ $backup_file == *"redis_data"* ]]; then
                restore_volume "ai-systems_redis_data" "$BACKUP_DIR/$backup_file"
            elif [[ $backup_file == *"rabbitmq_data"* ]]; then
                restore_volume "ai-systems_rabbitmq_data" "$BACKUP_DIR/$backup_file"
            elif [[ $backup_file == *"logs_volume"* ]]; then
                restore_volume "ai-systems_logs_volume" "$BACKUP_DIR/$backup_file"
            else
                echo -e "${RED}Invalid backup file.${NC}"
            fi
            ;;
        4)
            list_backups
            ;;
        5)
            setup_scheduled_backups
            ;;
        6)
            echo -e "${BLUE}Exiting...${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice. Please try again.${NC}"
            ;;
    esac
done

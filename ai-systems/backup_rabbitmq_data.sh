#!/bin/bash
# Script to backup RabbitMQ data before recreating the volume

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
VOLUME_NAME="ai-systems_rabbitmq_data"

echo -e "${BLUE}=== AI-SYSTEMS RabbitMQ Data Backup ===${NC}"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo -e "\n${YELLOW}Backing up volume: ${VOLUME_NAME}${NC}"

# Check if volume exists
if ! docker volume inspect "$VOLUME_NAME" &>/dev/null; then
    echo -e "${RED}Volume $VOLUME_NAME does not exist. Nothing to backup.${NC}"
    exit 1
fi

# Create a backup file path
BACKUP_FILE="$BACKUP_DIR/${VOLUME_NAME}_${TIMESTAMP}.tar.gz"

# Create a temporary container to access the volume
echo "Creating temporary container to access volume..."
docker run --rm -v "$VOLUME_NAME":/data -v "$BACKUP_DIR":/backup \
    alpine:latest tar -czf "/backup/$(basename $BACKUP_FILE)" -C /data .

echo -e "${GREEN}Volume $VOLUME_NAME backed up to $BACKUP_FILE${NC}"

echo -e "\n${YELLOW}You can now safely recreate the volume.${NC}"
echo -e "${YELLOW}To restore this backup later, use:${NC}"
echo -e "docker volume create $VOLUME_NAME"
echo -e "docker run --rm -v $VOLUME_NAME:/data -v $BACKUP_DIR:/backup alpine:latest sh -c \"cd /data && tar -xzf /backup/$(basename $BACKUP_FILE) --strip-components=0\""

echo -e "\n${GREEN}Backup completed successfully.${NC}"
echo -e "${BLUE}=== AI-SYSTEMS RabbitMQ Data Backup Complete ===${NC}"

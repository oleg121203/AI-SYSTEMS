#!/bin/bash

echo "=== Starting Full Docker Clean & Rebuild ==="
echo ""

# Get the directory where docker-compose.yml exists
COMPOSE_DIR="/Users/olegkizima/workspace/AI-SYSTEMS/ai-systems"

# 1. Stop and remove all containers
echo "[1/5] Stopping and removing all containers..."
(cd "$COMPOSE_DIR" && docker-compose down --rmi all -v --remove-orphans)
echo "Done."
echo ""
sleep 2

# 2. Remove all unused images (including cache)
echo "[2/5] Removing all unused images and cache..."
docker system prune -a --volumes --force
echo "Done."
echo ""
sleep 2

# 3. Remove all Docker volumes
echo "[3/5] Removing all Docker volumes..."
docker volume prune --force
echo "Done."
echo ""
sleep 2

# 4. Remove all networks
echo "[4/5] Removing all unused networks..."
docker network prune --force
echo "Done."
echo ""
sleep 2

# 5. Full rebuild
echo "[5/5] Starting full rebuild with no cache..."
(cd "$COMPOSE_DIR" && docker-compose build --no-cache --pull)
echo ""

echo "=== Full Clean & Rebuild Complete ==="
echo "You can now start your containers with:"
echo "cd \"$COMPOSE_DIR\" && docker-compose up"
#!/bin/bash
# Start all system services for AI-SYSTEMS
DIR="$(cd "$(dirname "$0")" && pwd)"

# Make the script executable and run it
chmod +x "$DIR/ai-systems/docker_clean_rebuild.sh"
bash "$DIR/ai-systems/docker_clean_rebuild.sh"
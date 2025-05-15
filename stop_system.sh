#!/bin/bash
# Stop all system services for AI-SYSTEMS
DIR="$(cd "$(dirname "$0")" && pwd)"

bash "$DIR/stop_services.sh"

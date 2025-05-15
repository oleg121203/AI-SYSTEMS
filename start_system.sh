#!/bin/bash
# Start all system services for AI-SYSTEMS
DIR="$(cd "$(dirname "$0")" && pwd)"

bash "$DIR/ai-systems/run_services.sh"

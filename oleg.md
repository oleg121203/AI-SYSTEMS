# Kill all Python processes related to the system
pkill -f "python.*ai-systems"

# Restart services in the correct order
cd /Users/olegkizima/workspace/AI-SYSTEMS/ai-systems/project-manager && python3 main.py &
sleep 5
cd /Users/olegkizima/workspace/AI-SYSTEMS/ai-systems/cmp && python3 main.py &
sleep 5
cd /Users/olegkizima/workspace/AI-SYSTEMS/ai-systems/development-agents && python3 main.py &
sleep 5
cd /Users/olegkizima/workspace/AI-SYSTEMS/ai-systems/web/backend && python3 main.py &
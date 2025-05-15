#!/bin/bash

# Run script for AI-SYSTEMS using Python virtual environment
# This script starts all the services using Python directly

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting AI-SYSTEMS services from ai-systems directory...${NC}"

# Determine the root directory
ROOT_DIR="$(pwd)"
echo -e "${YELLOW}Using root directory: ${ROOT_DIR}${NC}"

# Check if virtual environment exists
if [ ! -d "${ROOT_DIR}/venv" ]; then
  echo -e "${RED}Error: Virtual environment not found. Please run setup_venv.sh from the root directory first.${NC}"
  exit 1
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source "${ROOT_DIR}/venv/bin/activate"

# Check if .env file exists, create it if not
if [ ! -f "${ROOT_DIR}/.env" ]; then
  echo -e "${YELLOW}Creating .env file...${NC}"
  echo "GITHUB_TOKEN=" >"${ROOT_DIR}/.env"
  echo -e "${YELLOW}Please edit the .env file and add your GitHub token.${NC}"
fi

# Load environment variables from .env
if [ -f "${ROOT_DIR}/.env" ]; then
  echo -e "${YELLOW}Loading environment variables from .env...${NC}"
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

# Change to the ai-systems directory
echo -e "${YELLOW}Changing to ai-systems directory...${NC}"
cd "${ROOT_DIR}/ai-systems" || {
  echo -e "${RED}ai-systems directory not found.${NC}"
  exit 1
}

# Check for port availability and adjust if needed
check_port() {
  local port=$1
  local service=$2
  local default_port=$3

  if lsof -i:$port >/dev/null 2>&1; then
    echo -e "${YELLOW}Warning: Port $port is already in use.${NC}"
    # Find an available port by incrementing
    local new_port=$((port + 1))
    while lsof -i:$new_port >/dev/null 2>&1; do
      new_port=$((new_port + 1))
    done
    echo -e "${YELLOW}Using port $new_port for $service instead.${NC}"
    eval "${service}_PORT=$new_port"
  else
    eval "${service}_PORT=$default_port"
  fi
}

# Define default ports
AI_CORE_DEFAULT_PORT=7871
DEV_AGENTS_DEFAULT_PORT=7872
PROJECT_MANAGER_DEFAULT_PORT=7873
CMP_DEFAULT_PORT=7874
GIT_SERVICE_DEFAULT_PORT=7875
WEB_BACKEND_DEFAULT_PORT=8000
WEB_FRONTEND_DEFAULT_PORT=3000

# Check port availability
check_port $AI_CORE_DEFAULT_PORT "AI_CORE" $AI_CORE_DEFAULT_PORT
check_port $DEV_AGENTS_DEFAULT_PORT "DEV_AGENTS" $DEV_AGENTS_DEFAULT_PORT
check_port $PROJECT_MANAGER_DEFAULT_PORT "PROJECT_MANAGER" $PROJECT_MANAGER_DEFAULT_PORT
check_port $CMP_DEFAULT_PORT "CMP" $CMP_DEFAULT_PORT
check_port $GIT_SERVICE_DEFAULT_PORT "GIT_SERVICE" $GIT_SERVICE_DEFAULT_PORT
check_port $WEB_BACKEND_DEFAULT_PORT "WEB_BACKEND" $WEB_BACKEND_DEFAULT_PORT
check_port $WEB_FRONTEND_DEFAULT_PORT "WEB_FRONTEND" $WEB_FRONTEND_DEFAULT_PORT

# Export environment variables with potentially adjusted ports
export AI_CORE_URL="http://localhost:${AI_CORE_PORT}"
export DEVELOPMENT_AGENTS_URL="http://localhost:${DEV_AGENTS_PORT}"
export PROJECT_MANAGER_URL="http://localhost:${PROJECT_MANAGER_PORT}"
export CMP_URL="http://localhost:${CMP_PORT}"
export GIT_SERVICE_URL="http://localhost:${GIT_SERVICE_PORT}"
export CONFIG_PATH="$(pwd)/config.json"

# Create a global config.json if it doesn't exist
if [ ! -f "config.json" ]; then
  echo -e "${YELLOW}Creating global config.json...${NC}"
  cat >config.json <<EOF
{
  "services": {
    "ai_core": {
      "url": "http://localhost:7861",
      "name": "AI Core",
      "description": "AI1 Coordinator service responsible for project planning and coordination"
    },
    "development_agents": {
      "url": "http://localhost:7862",
      "name": "Development Agents",
      "description": "AI2 Development Agents service responsible for code generation, testing, and documentation"
    },
    "project_manager": {
      "url": "http://localhost:7863",
      "name": "Project Manager",
      "description": "AI3 Project Manager service responsible for task management and progress tracking"
    },
    "cmp": {
      "url": "http://localhost:7864",
      "name": "Continuous Monitoring Platform",
      "description": "Monitoring service responsible for system metrics and health checks"
    }
  },
  "websocket": {
    "ping_interval": 30,
    "reconnect_interval": 5,
    "max_reconnect_attempts": 5
  },
  "api": {
    "timeout": 30,
    "retry_attempts": 3,
    "retry_delay": 1
  },
  "cors": {
    "allowed_origins": ["*"],
    "allowed_methods": ["*"],
    "allowed_headers": ["*"]
  },
  "logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": "${ROOT_DIR}/logs/ai-systems.log"
  }
}
EOF
fi

# Update config.json with dynamic ports
echo -e "${YELLOW}Updating config.json with dynamic ports...${NC}"
cat >config.json <<EOF
{
  "services": {
    "ai_core": {
      "url": "http://localhost:$AI_CORE_PORT",
      "name": "AI Core",
      "description": "AI1 Coordinator service responsible for project planning and coordination"
    },
    "development_agents": {
      "url": "http://localhost:$DEV_AGENTS_PORT",
      "name": "Development Agents",
      "description": "AI2 Development Agents service responsible for code generation, testing, and documentation"
    },
    "project_manager": {
      "url": "http://localhost:$PROJECT_MANAGER_PORT",
      "name": "Project Manager",
      "description": "AI3 Project Manager service responsible for task management and progress tracking"
    },
    "cmp": {
      "url": "http://localhost:$CMP_PORT",
      "name": "Continuous Monitoring Platform",
      "description": "Monitoring service responsible for system metrics and health checks"
    },
    "git_service": {
      "url": "http://localhost:$GIT_SERVICE_PORT",
      "name": "Git Service",
      "description": "Service responsible for Git operations and GitHub integration"
    }
  },
  "websocket": {
    "ping_interval": 30,
    "reconnect_interval": 5,
    "max_reconnect_attempts": 5
  },
  "api": {
    "timeout": 30,
    "retry_attempts": 3,
    "retry_delay": 1
  },
  "cors": {
    "allowed_origins": ["*"],
    "allowed_methods": ["*"],
    "allowed_headers": ["*"]
  },
  "logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": "${ROOT_DIR}/logs/ai-systems.log"
  }
}
EOF

# Ensure logs directory exists
mkdir -p "${ROOT_DIR}/logs"

# Copy config to each service directory
echo -e "${YELLOW}Copying config to service directories...${NC}"
cp config.json ai-core/
cp config.json development-agents/
cp config.json project-manager/
cp config.json cmp/
cp config.json web/backend/
cp config.json git-service/

# Start services in the background
echo -e "${YELLOW}Starting AI Core service...${NC}"
cd ai-core || {
  echo -e "${RED}AI Core directory not found.${NC}"
  exit 1
}
python main.py --port ${AI_CORE_PORT} >"${ROOT_DIR}/logs/ai-core.log" 2>&1 &
AI_CORE_PID=$!
cd .. || exit 1

echo -e "${YELLOW}Starting Development Agents service...${NC}"
cd development-agents || {
  echo -e "${RED}Development Agents directory not found.${NC}"
  exit 1
}
python main.py --port ${DEV_AGENTS_PORT} >"${ROOT_DIR}/logs/development-agents.log" 2>&1 &
DEV_AGENTS_PID=$!
cd .. || exit 1

echo -e "${YELLOW}Starting Project Manager service...${NC}"
cd project-manager || {
  echo -e "${RED}Project Manager directory not found.${NC}"
  exit 1
}
python main.py --port ${PROJECT_MANAGER_PORT} >"${ROOT_DIR}/logs/project-manager.log" 2>&1 &
PROJECT_MANAGER_PID=$!
cd .. || exit 1

echo -e "${YELLOW}Starting CMP service...${NC}"
cd cmp || {
  echo -e "${RED}CMP directory not found.${NC}"
  exit 1
}
python main.py --port ${CMP_PORT} >"${ROOT_DIR}/logs/cmp.log" 2>&1 &
CMP_PID=$!
cd .. || exit 1

echo -e "${YELLOW}Starting Git Service...${NC}"
cd git-service || {
  echo -e "${RED}Git Service directory not found.${NC}"
  exit 1
}
python git_service.py --port ${GIT_SERVICE_PORT} >"${ROOT_DIR}/logs/git-service.log" 2>&1 &
GIT_SERVICE_PID=$!
cd .. || exit 1

echo -e "${YELLOW}Starting Web Backend service...${NC}"
cd web/backend || {
  echo -e "${RED}Web Backend directory not found.${NC}"
  exit 1
}
uvicorn main:app --host 0.0.0.0 --port ${WEB_BACKEND_PORT} >"${ROOT_DIR}/logs/web-backend.log" 2>&1 &
WEB_BACKEND_PID=$!
cd ../.. || exit 1

# Create or update .env file for React frontend
echo -e "${YELLOW}Creating .env file for React frontend...${NC}"
cat >web/frontend/.env <<EOF
REACT_APP_API_URL=http://localhost:${WEB_BACKEND_PORT}
REACT_APP_WS_URL=ws://localhost:${WEB_BACKEND_PORT}/ws
PORT=${WEB_FRONTEND_PORT}
EOF

# Create or update config.js file for React frontend
echo -e "${YELLOW}Updating frontend config.js with dynamic ports...${NC}"
cat >web/frontend/src/config.js <<EOF
// This file is auto-generated by the run_services.sh script
// It contains the configuration for the frontend application

const config = {
  // API endpoints
  apiBaseUrl: 'http://localhost:${WEB_BACKEND_PORT}',
  wsBaseUrl: 'ws://localhost:${WEB_BACKEND_PORT}',
  
  // Service endpoints
  services: {
    aiCore: 'http://localhost:${AI_CORE_PORT}',
    developmentAgents: 'http://localhost:${DEV_AGENTS_PORT}',
    projectManager: 'http://localhost:${PROJECT_MANAGER_PORT}',
    cmp: 'http://localhost:${CMP_PORT}',
    gitService: 'http://localhost:${GIT_SERVICE_PORT}'
  }
};

export default config;
EOF

echo -e "${YELLOW}Starting Web Frontend service...${NC}"
cd web/frontend || {
  echo -e "${RED}Web Frontend directory not found.${NC}"
  exit 1
}
npm install
npm start >"${ROOT_DIR}/logs/web-frontend.log" 2>&1 &
WEB_FRONTEND_PID=$!
cd ../.. || exit 1

# Save PIDs to file for stopping later
echo ${AI_CORE_PID} >"${ROOT_DIR}/.ai_core.pid"
echo ${DEV_AGENTS_PID} >"${ROOT_DIR}/.dev_agents.pid"
echo ${PROJECT_MANAGER_PID} >"${ROOT_DIR}/.project_manager.pid"
echo ${CMP_PID} >"${ROOT_DIR}/.cmp.pid"
echo ${GIT_SERVICE_PID} >"${ROOT_DIR}/.git_service.pid"
echo ${WEB_BACKEND_PID} >"${ROOT_DIR}/.web_backend.pid"
echo ${WEB_FRONTEND_PID} >"${ROOT_DIR}/.web_frontend.pid"

echo -e "${GREEN}All services started successfully!${NC}"
echo -e "${GREEN}You can access the services at:${NC}"
echo -e "${YELLOW}Web Frontend:${NC} http://localhost:${WEB_FRONTEND_PORT}"
echo -e "${YELLOW}Web Backend API:${NC} http://localhost:${WEB_BACKEND_PORT}"
echo -e "${YELLOW}AI Core:${NC} http://localhost:${AI_CORE_PORT}"
echo -e "${YELLOW}Development Agents:${NC} http://localhost:${DEV_AGENTS_PORT}"
echo -e "${YELLOW}Project Manager:${NC} http://localhost:${PROJECT_MANAGER_PORT}"
echo -e "${YELLOW}CMP:${NC} http://localhost:${CMP_PORT}"
echo -e "${YELLOW}Git Service:${NC} http://localhost:${GIT_SERVICE_PORT}"
echo -e "${YELLOW}To stop all services, run:${NC}"
echo -e "  ./stop_services.sh"
echo -e "${YELLOW}To view logs, check the logs directory:${NC}"
echo -e "  tail -f ${ROOT_DIR}/logs/web-backend.log"

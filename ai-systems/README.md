# AI-SYSTEMS: Dockerized Microservices Architecture

## Overview

This directory contains the modernized implementation of the AI-SYSTEMS platform, restructured as a set of Docker-based microservices. The architecture maintains the core functionality described in the parent directory's README while providing enhanced integration, scalability, and deployment capabilities.

## Architecture

The system is organized into the following microservices:

### 1. AI Core (AI1)
- **Purpose**: Intelligent task orchestration and planning
- **Location**: `/ai-systems/ai-core`
- **Key Features**:
  - Dynamic resource allocation
  - Task dependency management
  - Real-time decision making
  - Performance optimization

### 2. Development Agents (AI2)
- **Purpose**: Code generation, testing, and documentation
- **Location**: `/ai-systems/development-agents`
- **Key Features**:
  - Code Generation Engine
  - Test Automation Framework
  - Documentation Generator
  - Quality Assurance System

### 3. Project Manager (AI3)
- **Purpose**: Project structure generation and management
- **Location**: `/ai-systems/project-manager`
- **Key Features**:
  - Intelligent project structure generation
  - CI/CD pipeline management
  - Resource optimization
  - Performance monitoring

### 4. Continuous Monitoring Platform (CMP)
- **Purpose**: System monitoring and metrics collection
- **Location**: `/ai-systems/cmp`
- **Key Features**:
  - Real-time monitoring dashboard
  - Task queue management
  - Resource allocation
  - Performance analytics

### 5. Web Interface
- **Purpose**: User interface for interacting with the system
- **Location**: `/ai-systems/web`
- **Components**:
  - **Backend**: FastAPI-based API gateway (`/ai-systems/web/backend`)
  - **Frontend**: React-based UI (`/ai-systems/web/frontend`)
- **Key Features**:
  - Modern, responsive UI/UX
  - Real-time development visualization
  - Interactive development workflow
  - Performance analytics
  - Multiple AI provider integration with API key management
  - Model availability checking
  - GitHub repository integration with CI/CD

### 6. Git Service
- **Purpose**: Handle Git operations for code storage and versioning
- **Location**: `/ai-systems/git-service`
- **Key Features**:
  - GitHub repository management
  - Automated code commits and pushes
  - Branch management
  - GitHub Actions workflow setup

### Infrastructure Dependencies
- **PostgreSQL**: Persistent data storage for all services
- **Redis**: In-memory cache and pub/sub for real-time messaging
- **RabbitMQ**: Message broker for asynchronous task processing

## Integration Improvements

The microservices architecture provides several improvements over the original design:

1. **Enhanced Service Communication**
   - RESTful APIs for synchronous communication
   - WebSockets for real-time updates
   - Standardized request/response formats

2. **Centralized Configuration**
   - Each service has a `config.json` file
   - Environment variables for sensitive information
   - Shared configuration through mounted volumes

3. **Unified Logging**
   - Centralized log collection
   - Structured logging format
   - Real-time log streaming

4. **Improved Error Handling**
   - Graceful degradation when services are unavailable
   - Automatic retry mechanisms
   - Detailed error reporting

5. **Metrics and Monitoring**
   - Prometheus integration for metrics collection
   - Grafana dashboards for visualization
   - Health check endpoints for all services

6. **AI Provider Integration**
   - Support for multiple AI providers (OpenAI, Anthropic, Google, Mistral, Codestral)
   - Multiple API key management per provider
   - Real-time model availability checking
   - Seamless provider switching

7. **GitHub Integration**
   - Automatic code repository management
   - GitHub Actions for CI/CD workflows
   - Commit generated code directly to GitHub
   - Testing automation via GitHub Actions

## Running the System

### Prerequisites
- Docker and Docker Compose (optional)
- Python 3.10+
- Node.js 18+
- Git
- API keys for AI providers (OpenAI, Anthropic, etc.)
- GitHub personal access token (for GitHub integration)
- PostgreSQL 14+ (if not using Docker)
- Redis 6+ (if not using Docker)
- RabbitMQ 3+ (if not using Docker)

### Using Docker Compose (if available)
```bash
# Clone the repository if you haven't already
git clone https://github.com/oleg121203/AI-SYSTEMS.git
cd AI-SYSTEMS

# Start all services
docker-compose up -d
```

### Using Python Virtual Environment
```bash
# Clone the repository if you haven't already
git clone https://github.com/oleg121203/AI-SYSTEMS.git
cd AI-SYSTEMS

# Set up the virtual environment
./setup_venv.sh

# Configure environment variables
cp ai-systems/.env.example ai-systems/.env
# Edit the .env file with your API keys and GitHub credentials

# Initialize the workspace
cd ai-systems
./setup.sh
```

## Repository Setup

AI-SYSTEMS uses a dedicated Git repository for storing generated code. By default, this repository is located at:

```
~/workspace/AI-SYSTEMS-REPO
```

The `setup.sh` script initializes this repository with a basic structure and configures Git appropriately. The location can be customized by modifying the `REPOSITORY_PATH` variable in your `.env` file.

### Environment Configuration

All services use a centralized `.env` file for configuration. This ensures consistency across components and simplifies setup. Key environment variables include:

- `REPOSITORY_PATH`: Path to the repository where generated code is stored
- `GITHUB_TOKEN`: Your GitHub personal access token for integration
- `GITHUB_REPO`: The GitHub repository to push generated code to
- `LOG_FILE_PATH` and `LOGS_DIR`: Paths for application logs

## Starting the Services

### Service Endpoints

After starting the system, the following endpoints will be available:

- **Web Frontend**: http://localhost:3000
- **Web Backend API**: http://localhost:8000
- **AI Core**: http://localhost:7861
- **Development Agents**: http://localhost:7862
- **Project Manager**: http://localhost:7863
- **CMP**: http://localhost:7864
- **Git Service**: http://localhost:7865

Note: The actual ports may vary if there are port conflicts. The `run_services.sh` script will automatically find available ports.

## API Documentation

- **Web Backend API**: http://localhost:8000/docs
- **AI Core API**: http://localhost:7861/docs
- **Development Agents API**: http://localhost:7862/docs
- **Project Manager API**: http://localhost:7863/docs
- **CMP API**: http://localhost:7864/docs
- **Git Service API**: http://localhost:7865/docs

## Directory Structure

Complete structure of the AI-SYSTEMS workspace:

```bash
ai-systems/
├── setup.sh               # Environment setup script
├── run_services.sh        # Service startup script
├── stop_services.sh       # Service shutdown script
├── check_repo.sh          # Repository verification script
├── sync_repo.sh           # GitHub synchronization script
├── force_push.sh          # GitHub force push script
├── reset_repo.sh          # Repository reset script
├── docker-compose.yml     # Docker services configuration
├── config.json            # Main configuration file
├── config.yaml            # Alternative configuration format
├── Dockerfile.base        # Base Docker image definition
├── requirements.txt       # Root Python dependencies
├── .env                   # Environment variables
│
├── ai-core/               # AI1 Coordinator service
│   ├── main.py            # Core service entry point
│   ├── config.json        # Service configuration
│   ├── Dockerfile         # Container definition
│   ├── requirements.txt   # Python dependencies
│   └── __pycache__/       # Compiled Python bytecode
│
├── development-agents/    # AI2 Development Agents service
│   ├── main.py            # Agents service entry point
│   ├── config.json        # Service configuration
│   ├── Dockerfile         # Container definition
│   ├── requirements.txt   # Python dependencies 
│   ├── test_agent.py      # Agent unit tests
│   └── __pycache__/       # Compiled Python bytecode
│
├── project-manager/       # AI3 Project Manager service
│   ├── main.py            # Manager service entry point
│   ├── config.json        # Service configuration
│   ├── git_integration.py # Git integration for manager
│   ├── Dockerfile         # Container definition
│   ├── requirements.txt   # Python dependencies
│   └── __pycache__/       # Compiled Python bytecode
│
├── cmp/                   # Continuous Monitoring Platform
│   ├── main.py            # Monitoring service entry point
│   ├── config.json        # Service configuration
│   ├── Dockerfile         # Container definition
│   ├── requirements.txt   # Python dependencies
│   ├── test_cmp.py        # CMP unit tests
│   ├── __pycache__/       # Compiled Python bytecode
│   └── logs/              # Service-specific logs
│       ├── system_metrics_2025-05-13.json  # Daily metrics
│       └── system_metrics_2025-05-14.json  # Daily metrics
│
├── git-service/           # GitHub Integration Service
│   ├── git_service.py     # Git operations handler
│   ├── config.json        # Service configuration
│   ├── Dockerfile         # Container definition
│   ├── requirements.txt   # Python dependencies
│   ├── test_git_service.py # Git service tests
│   └── stop_git_service.sh # Service control script
│
├── web/                   # Web interface
│   ├── backend/           # FastAPI backend
│   │   ├── main.py        # API gateway entry point
│   │   ├── config.json    # Backend configuration
│   │   ├── github_integration.py # GitHub API integration
│   │   ├── middleware.py  # Request middleware handler
│   │   ├── Dockerfile     # Backend container definition
│   │   ├── requirements.txt # Python dependencies
│   │   ├── test_api.py    # API tests
│   │   ├── __pycache__/   # Compiled Python bytecode
│   │   └── middleware/    # Extended middleware components
│   │       ├── __init__.py # Package initialization
│   │       ├── error_handler.py # Error handling middleware
│   │       └── __pycache__/ # Compiled Python bytecode
│   │
│   └── frontend/          # React frontend
│       ├── src/           # Frontend source code
│       │   ├── App.js     # Main application component
│       │   ├── App.css    # Application styles
│       │   ├── index.js   # Application entry point
│       │   ├── index.css  # Global styles
│       │   ├── config.js  # Frontend configuration
│       │   └── components/ # UI components
│       │       ├── AIModelSelector.js    # AI provider selection UI
│       │       ├── GitHubIntegration.js  # Basic GitHub integration
│       │       ├── GitHubIntegrationEnhanced.js # Advanced GitHub UI
│       │       ├── LogViewer.js          # Log viewing interface
│       │       ├── MonitoringDashboard.js # System monitoring
│       │       ├── PerformanceDashboard.js # Performance metrics
│       │       ├── ProjectCard.js        # Project visualization
│       │       ├── SystemStatus.js       # System status display
│       │       ├── TaskList.js           # Task management UI
│       │       └── WorkflowVisualizer.js # Workflow visualization
│       ├── public/        # Static assets
│       │   ├── index.html # HTML entry point
│       │   ├── favicon.ico # Website icon
│       │   ├── logo192.png # Small app logo
│       │   ├── logo512.png # Large app logo
│       │   └── manifest.json # PWA manifest
│       ├── build/         # Production build
│       │   ├── index.html # Built HTML
│       │   ├── static/    # Optimized static assets
│       │   │   ├── css/   # Compiled CSS
│       │   │   └── js/    # Compiled JavaScript
│       │   └── asset-manifest.json # Asset map
│       ├── Dockerfile     # Frontend container definition
│       ├── nginx.conf     # Nginx web server config
│       └── package.json   # Node.js dependencies
│
├── logs/                  # Centralized logs directory
│
└── tests/                 # System-wide integration tests
    ├── __init__.py        # Package initialization
    ├── test_git_integration.py   # Git integration tests
    └── test_github_integration.py # GitHub integration tests
```

In addition to this workspace structure, the system utilizes an external repository for storing generated code:

```bash
~/workspace/AI-SYSTEMS-REPO/    # Repository for generated code
├── src/                        # Source code directory
└── tests/                      # Tests directory
```

The external repository is automatically configured by the setup scripts and is managed by the Git Service.

Each service directory contains at minimum:
- `main.py`: Service entry point
- `config.json`: Service configuration
- `requirements.txt`: Python dependencies
- Service-specific modules

## Development Workflow

1. **Project Creation**:
   - User creates a new project through the web interface
   - Project Manager (AI3) generates the initial project structure
   - The structure is stored in a GitHub repository via the Git Service

2. **Task Generation**:
   - AI Core (AI1) analyzes the project structure
   - Tasks are created and assigned to Development Agents (AI2)
   - Tasks are tracked in the Project Manager

3. **Code Generation**:
   - Development Agents execute their assigned tasks
   - Generated code is committed to the GitHub repository using the Git Service
   - Progress is reported back to the Project Manager

4. **Monitoring and Feedback**:
   - CMP collects metrics and monitors system health
   - Web interface displays real-time progress
   - Users can provide feedback through the web interface

### Code Storage and Project Repository

Generated code is stored in an external GitHub repository, configured with the following environment variables:
- `GITHUB_TOKEN`: Authentication token for GitHub API access
- `GITHUB_REPO`: Repository name in format `username/repo`
- `GIT_USER_NAME` and `GIT_USER_EMAIL`: Git commit author information

The Project Manager service coordinates with the Git Service to ensure all generated code is properly versioned and accessible through GitHub. When a new project is created, a dedicated branch is created in the repository, and all subsequent code generated for that project is committed to that branch.

## Extending the System

### Adding a New Service
1. Create a new directory in the `ai-systems` folder
2. Implement the service using the existing services as templates
3. Add the service to the Docker Compose file
4. Update the Web Backend to integrate with the new service

### Customizing Existing Services
1. Modify the service's `config.json` file
2. Update the service's code as needed
3. Rebuild the Docker image or restart the service

## Testing

The system includes test files for each service to ensure proper functionality. These tests can be run individually or as part of a CI/CD pipeline.

### Running Tests
```bash
# Run tests for a specific service
cd ai-systems/development-agents
pytest test_agent.py

# Run all tests
cd ai-systems
pytest tests/
```

### Integration Tests
The `tests` directory contains integration tests that verify the communication between services and proper functioning of the system as a whole. These tests include:

- GitHub Integration Tests: Verify the system can properly interact with GitHub repositories
- Web API Tests: Verify the Web Backend API endpoints are functioning correctly
- End-to-End Tests: Verify the entire workflow from project creation to code generation

### Test Coverage
Ensure tests cover at least the following aspects for each service:
- API endpoints functionality
- Error handling and graceful degradation
- Integration with other services
- Performance under expected load

## Troubleshooting

### Common Issues

1. **Port Conflicts**:
   - The `run_services.sh` script automatically detects port conflicts and uses alternative ports
   - Check the console output for the actual ports being used

2. **Service Dependencies**:
   - Services may fail to start if their dependencies are not available
   - Check the logs for connection errors
   - Ensure all required services are running

3. **Configuration Issues**:
   - Verify that the `config.json` files are correctly formatted
   - Check that environment variables are properly set
   - Ensure the shared volume is accessible to all services

4. **GitHub Integration Issues**:
   - Verify that the GitHub token has proper permissions (repo, workflow)
   - Check that the repository exists and is accessible
   - Verify that the Git user name and email are properly configured

### Viewing Logs

```bash
# View logs for a specific service
tail -f logs/web-backend.log
tail -f logs/ai-core.log
# etc.
```

## Generated Projects

### Project Storage Location

Code generated by AI-SYSTEMS is stored in the following location:

1. **GitHub Repository**: All code is pushed to a GitHub repository specified by the `GITHUB_REPO` environment variable (default: `oleg121203/AI-SYSTEMS-REPO`). The repository URL is configured in the following files:
   - `/git-service/git_service.py`
   - `/web/backend/github_integration.py`

2. **Local Working Directory**: During development, code is also stored in a local working directory on the server:
   - Default location: `~/workspace/AI-SYSTEMS-REPO`
   - This path can be configured through the `GITHUB_REPO_PATH` environment variable

### Accessing Generated Code

Generated code can be accessed through:
1. The GitHub web interface by visiting the repository URL
2. Git commands to clone the repository locally
3. The Web Interface, which provides a code viewer for browsing generated files

Each project is organized in its own branch within the repository, making it easy to manage multiple projects simultaneously.

## Management Scripts

AI-SYSTEMS includes several utility scripts to help manage the repository and services:

- **setup.sh**: Initializes the environment, creates necessary directories, and sets up the Git repository
- **check_repo.sh**: Performs diagnostics to verify the repository setup and configuration
- **sync_repo.sh**: Synchronizes the local repository with GitHub, providing options to fetch, pull, or overwrite remote changes
- **force_push.sh**: Forces the remote GitHub repository to match the local repository state (use with caution)
- **reset_repo.sh**: Resets the repository to a clean state, useful for troubleshooting or starting over
- **run_services.sh**: Starts all services with proper environment configuration
- **stop_services.sh**: Gracefully stops all running services

These scripts simplify common operations and ensure consistent configuration across the system.

## Contributing

Contributions to the AI-SYSTEMS project are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Write tests for your changes
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file in the parent directory for details.

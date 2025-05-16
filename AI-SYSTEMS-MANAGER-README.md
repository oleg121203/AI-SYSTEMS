# AI-SYSTEMS Management Tools

This management system provides a unified interface for managing all aspects of your AI-SYSTEMS project. It includes both a command-line interface (CLI) and a web-based interface for easy management of services, Docker containers, Git operations, and more.

## Management Interfaces

### 1. Command Line Interface (CLI)

The CLI provides an interactive menu-based interface for managing your AI-SYSTEMS.

To start the CLI:

```bash
./ai-systems-manager.sh
```

The CLI menu provides the following options:

- **Start Services** - Start services directly or using Docker with specific profiles
- **Stop Services** - Stop all running services
- **Test Docker Profiles** - Test different Docker Compose profiles
- **Monitor System Performance** - Monitor Docker container performance
- **Backup Volume Management** - Manage Docker volume backups
- **Git Repository Management** - Manage Git repository operations
- **Clean and Rebuild Docker** - Clean and rebuild Docker containers
- **Web Management Interface** - Launch the web management interface

### 2. Web Interface

The web interface provides a modern, user-friendly way to manage your AI-SYSTEMS through a browser.

To start the web interface:

```bash
cd ai-systems-web-manager
npm start
```

Then open your browser and navigate to: http://localhost:3030

The web interface provides:

- Real-time system status monitoring
- One-click execution of management scripts
- Live command output display
- Docker container status

## Script Categories

The management system organizes scripts into the following categories:

### Service Management
- Start Services (Direct)
- Start Services (Docker)
- Stop All Services

### Docker Management
- Start Infrastructure Services
- Start AI Services
- Start Web Services
- Start Management Services
- Start Monitoring Services
- Start All Services
- Clean and Rebuild Docker

### Testing and Monitoring
- Test Docker Profiles
- Monitor Performance

### Backup Management
- Backup Volumes

### Git Management
- Check Repository Status
- Sync Repository
- Force Push Changes
- Reset Repository

## Docker Profiles

The system supports the following Docker Compose profiles:

- **infrastructure** - Core infrastructure services
- **ai** - AI services
- **web** - Web frontend and backend
- **management** - Management services
- **monitoring** - Monitoring services
- **full** - All services

## GitHub Integration

The system integrates with your GitHub repository at https://github.com/oleg121203/AI-SYSTEMS-REPO.git. The Git credentials are stored in the `.env` file with:

```
GIT_USER_NAME="Oleg Kizyma"
GIT_USER_EMAIL="oleg1203@gmail.com"
```

## Requirements

- Bash shell
- Docker and Docker Compose (for Docker-based operations)
- Node.js and npm (for the web interface)
- Git (for repository management)

## Troubleshooting

If you encounter any issues:

1. Check that Docker is running
2. Ensure all required dependencies are installed
3. Check the logs in the output window
4. Verify that the `.env` file contains the necessary credentials

## Additional Information

For more detailed information about specific scripts, refer to their individual documentation or examine the script source code.

# AI-SYSTEMS

## Purpose of AI-SYSTEMS

AI-SYSTEMS is a comprehensive system designed to automate the software development process through the interaction of multiple specialized AI agents. The main goal is to take a project description (target) as input and automatically generate any level of software or game, resulting in a complete, tested, and production-ready program without human intervention. This includes creating the appropriate project structure, source code, tests, documentation, and performing iterative improvements based on test results.

## System Architecture

The system consists of the following main components:

- **AI1 (Coordinator)**: Plans and coordinates tasks, managing dependencies between them and dynamically adjusting the plan to ensure efficient execution and avoid redundant work. Makes decisions based on test results. Uses LLM for flexible decision-making, task prioritization, and report analysis.
- **AI2 (Executors)**: Generates high-quality code, comprehensive tests, and detailed documentation using language-specific patterns and validation. Features multiple provider fallback and quality assurance checks.
- **AI3 (Monitor/Structure Manager)**: Creates the project structure, proactively monitors the system, provides consultations, identifies problems, initiates their resolution, and independently fixes testing errors.
- **MCP API**: Central API for interaction between components, manages task queues and provides status monitoring with robust error handling.
- **Web Interface**: Visualization of the development process and system management with real-time updates.

## Web Interface

The system includes a modern, responsive web interface that provides visualization and management of the development process. Key features include:

- **Dashboard Overview**: Provides a summary of the project status, including total files, completion percentage, and recent activity.
- **Control Center**: Allows starting/stopping individual AI agents or the entire system, with visual status indicators.
- **Prompt Management**: Edit and configure AI agent prompts directly from the interface.
- **Real-time Monitoring**: Charts and visualizations showing task distribution, completion status, and progress over time.
- **File Explorer & Editor**: Browse and edit project files directly in the browser with syntax highlighting.
- **Task Queues**: Monitor and track tasks in the executor, tester, and documenter queues.
- **System Logs**: View real-time logs with configurable display settings.
- **Theme Selection**: Multiple theme options including dark and light modes, and seasonal themes.

The interface is built with modern web technologies:

- Pure JavaScript for frontend logic
- Chart.js for data visualization
- Monaco Editor for code editing
- WebSockets for real-time updates
- Responsive design for desktop and mobile use

### Web Interface Setup

The web interface is automatically launched when starting the system with the `run_async_services.sh` script. By default, it's accessible at:

```http
http://localhost:7860
```

You can interact with the interface to:

1.  View real-time progress of your project development
2.  Manually adjust AI agent configurations if needed
3.  Browse and edit generated files
4.  Monitor system performance and task distribution

## Repository Structure

The system currently uses the following structure:

1.  **Main Repository (AI-SYSTEMS)**:
    - Contains the code of the system itself (AI agents, API)
    - Main scripts: ai1.py, ai2.py, ai3.py, mcp_api.py
    - Configuration: config.json, config.py
    - Utilities: utils.py, providers.py

2.  **Project Repository (repo/)**:
    - Located under the AI-SYSTEMS directory
    - Contains the generated project files
    - Managed by AI3, which creates the structure and files

## System Prompt Configuration

The system uses a hybrid approach to prompt management:

1.  **Base prompts in config.json**:
    - `ai1_prompt`: Basic instruction for the AI1 coordinator.
    - `ai2_prompts`: Array of basic instructions for AI2 (executor, tester, documenter).
    - `ai3_prompt`: Basic instruction for AI3 regarding project structure generation.

2.  **System instructions in code**:
    - Each AI agent supplements the basic prompt with system instructions (e.g., use of Latin characters, JSON format).
    - This provides flexibility (the main prompt can be changed through configuration) and reliability (critical instructions are protected in the code).

## Project Structure Generation

The AI3 system uses a two-stage approach to project structure generation:

1.  **First Cycle**: Initial structure generation
    - Uses a provider from the `structure_providers` list in the configuration
    - Generates a basic directory and file structure in JSON format

2.  **Second Cycle**: Structure refinement
    - Uses the same provider as for the first cycle
    - Analyzes the initial structure for completeness and logic
    - Makes improvements, adds missing files/directories
    - Optimizes according to best practices for the target project type

## System Operation Algorithm

1.  **Initialization (AI3):**
    - AI3 receives the project goal (`target`) from the configuration.
    - Generates initial JSON structure of files and directories for the project using LLM.
    - Creates these files and directories in the local repository (repo).
    - Generates the initial idea.md file with a project description using a robust provider fallback mechanism.
    - Reports progress to MCP API through dedicated endpoints (`/ai3/repo_cleared`, `/ai3/structure_creation_completed`, `/ai3/structure_setup_completed`).
    - Ensures idea.md always exists with safety mechanisms even if LLM generation fails.
    - Sends the generated structure to the MCP API.
    - Launches background monitoring processes for logs, tests, and task queues.

2.  **Planning and Coordination (AI1):**
    - AI1 receives the project structure and idea.md content from the MCP API.
    - Uses idea.md as the primary context for understanding the project's objectives and scope.
    - Analyzes file dependencies and the overall project graph to create an optimized task execution plan.
    - Decomposes the overall project goal (derived from the `target` configuration and `idea.md`) into specific, actionable tasks for AI2. Each task for AI2 will be focused on a particular file or component and will include the necessary context from `idea.md` and details about its dependencies.
    - Prioritizes tasks to ensure that foundational files are processed before dependent files, minimizing rework and obsolete tasks.
    - Dynamically adjusts the plan based on the results of completed tasks and test feedback.
    - Determines priorities of different task types using LLM.
    - Makes decisions regarding test results based on AI3 recommendations and its own analysis.

3.  **Task Execution (AI2):**
    - Generates high-quality code with language-specific patterns and best practices
    - Creates comprehensive tests with coverage validation and framework-specific patterns
    - Produces detailed documentation following language standards
    - Features intelligent provider fallback mechanism
    - Validates generated content quality with extensive checks

4.  **Automatic Test Execution and Fixing (AI3):**
    - Runs tests without user intervention.
    - Analyzes results and determines the exact causes of errors.
    - Independently fixes simple testing and linting errors.
    - Sends complex issues to AI1 for deeper analysis.

5.  **Result Processing and Refinement (AI1):**
    - Receives and analyzes the status of all tasks.
    - Makes decisions about task reassignment in case of errors.
    - Tracks the number of refinement attempts and determines when manual intervention is needed.

## Communication Protocol

The system uses a robust API-based communication protocol with these key components:

1.  **MCP API Endpoints**:
    - Task management: `/subtask`, `/task/{role}`, `/report`
    - Structure management: `/structure`, `/file_content`
    - Status reporting: `/ai3/repo_cleared`, `/ai3/structure_creation_completed`, `/ai3/structure_setup_completed`
    - Test recommendations: `/test_recommendation`
    - System management: `/start_ai1`, `/stop_ai1`, etc.
    - Monitoring endpoints: `/monitor/status`, `/monitor/performance`, `/monitor/resources`

2.  **WebSocket Updates**:
    - Real-time status updates to connected clients
    - Task status changes
    - Structure updates
    - Chart data for visualization
    - System performance metrics
    - Resource utilization statistics
    - AI agent status and activity feeds

3.  **File Operation Safety**:
    - Path sanitization to prevent directory traversal
    - Automatic handling of directory path edge cases
    - Proper file creation and error recovery

## Error Handling and Recovery

The system implements robust error handling mechanisms:

1.  **Provider Fallback System**:
    - Multiple LLM providers are tried in sequence for critical operations
    - If a primary provider fails, secondary providers are used
    - Default templates are provided as final fallback options

2.  **File Operation Safety**:
    - Intelligent handling of file paths with trailing slashes
    - Creation of appropriate index files for directories
    - Path validation and sanitization

3.  **API Communication Resilience**:
    - Retry logic for API requests
    - Error tracking and reporting
    - Graceful degradation when services are unavailable

4.  **Resource Management**:
    - Proper cleanup of resources (e.g., closing aiohttp sessions)
    - Memory usage monitoring
    - Rate limiting to prevent API overload

## System Monitoring

AI-SYSTEMS includes a comprehensive monitoring system that tracks performance, resource usage, and system health in real-time:

1. **Performance Monitoring**:
   - Task processing times and throughput 
   - AI model response times
   - Queue wait times and backlogs
   - Success/failure rates for each component

2. **Resource Monitoring**:
   - CPU and memory usage for each AI agent
   - Network traffic and API call volume
   - Disk space utilization
   - Provider quota and rate limit tracking

3. **Health Checks**:
   - Automatic detection of stalled or crashed components
   - Service availability monitoring
   - Process restart capabilities
   - Early warning system for potential issues

Monitoring data is accessible through:
- API endpoints at `/monitor/status`, `/monitor/performance`, `/monitor/resources`
- Real-time WebSocket feeds for live dashboards
- Log files in the `logs/` directory
- Status JSON files for integration with external monitoring tools

### Monitoring Configuration

Monitoring behavior can be configured in `config.json`:

```json
{
  "monitoring": {
    "enabled": true,
    "interval": 5,
    "alert_thresholds": {
      "cpu_percent": 85,
      "memory_percent": 80,
      "disk_space_percent": 90
    },
    "log_level": "info"
  }
}
```

## Provider Plugin System

AI-SYSTEMS features a flexible provider plugin system that allows you to add custom LLM providers withou
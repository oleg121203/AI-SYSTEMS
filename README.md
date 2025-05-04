# AI-SYSTEMS

## Purpose of AI-SYSTEMS

AI-SYSTEMS is a comprehensive system designed to automate the software development process through the interaction of multiple specialized AI agents. The main goal is to take a project description (target) as input and automatically generate a complete production-ready program without human intervention, including appropriate project structure, source code, tests, documentation, and iterative improvements based on test results.

## System Architecture

The system consists of the following main components:

- **AI1 (Coordinator)**: Plans and coordinates tasks, makes decisions based on test results. Uses LLM for flexible decision-making, task prioritization, and report analysis.
- **AI2 (Executors)**: Generates high-quality code, comprehensive tests, and detailed documentation using language-specific patterns and validation. Features multiple provider fallback and quality assurance checks.
- **AI3 (Monitor/Structure Manager)**: Creates the project structure, proactively monitors the system, provides consultations, identifies problems, initiates their resolution, and independently fixes testing errors.
- **MCP API**: Central API for interaction between components, manages task queues and provides status monitoring.
- **Web Interface**: Visualization of the development process and system management (work in progress).

## Repository Structure

The system currently uses the following structure:

1. **Main Repository (AI-SYSTEMS)**:
   - Contains the code of the system itself (AI agents, API)
   - Main scripts: ai1.py, ai2.py, ai3.py, mcp_api.py
   - Configuration: config.json, config.py
   - Utilities: utils.py, providers.py

2. **Project Repository (repo/)**:
   - Located under the AI-SYSTEMS directory
   - Contains the generated project files
   - Managed by AI3, which creates the structure and files

## System Prompt Configuration

The system uses a hybrid approach to prompt management:

1. **Base prompts in config.json**:
   - `ai1_prompt`: Basic instruction for the AI1 coordinator.
   - `ai2_prompts`: Array of basic instructions for AI2 (executor, tester, documenter).
   - `ai3_prompt`: Basic instruction for AI3 regarding project structure generation.

2. **System instructions in code**:
   - Each AI agent supplements the basic prompt with system instructions (e.g., use of Latin characters, JSON format).
   - This provides flexibility (the main prompt can be changed through configuration) and reliability (critical instructions are protected in the code).

## Project Structure Generation

The AI3 system uses a two-stage approach to project structure generation:

1. **First Cycle**: Initial structure generation
   - Uses a provider from the `structure_providers` list in the configuration
   - Generates a basic directory and file structure in JSON format

2. **Second Cycle**: Structure refinement
   - Uses the same provider as for the first cycle
   - Analyzes the initial structure for completeness and logic
   - Makes improvements, adds missing files/directories
   - Optimizes according to best practices for the target project type

## System Operation Algorithm

1. **Initialization (AI3):**
   * AI3 receives the project goal (`target`) from the configuration.
   * Generates initial JSON structure of files and directories for the project using LLM.
   * Creates these files and directories in the local repository (repo).
   * Generates the initial idea.md file with a project description.
   * Sends the generated structure to the MCP API.
   * Launches background monitoring processes for logs, tests, and task queues.

2. **Planning and Coordination (AI1):**
   * AI1 receives the project structure and idea.md content from the MCP API.
   * Uses idea.md as context for all tasks.
   * Determines priorities of different task types using LLM.
   * Makes decisions regarding test results based on AI3 recommendations and its own analysis.

3. **Task Execution (AI2):**
   * Generates high-quality code with language-specific patterns and best practices
   * Creates comprehensive tests with coverage validation and framework-specific patterns
   * Produces detailed documentation following language standards
   * Features intelligent provider fallback mechanism
   * Validates generated content quality with extensive checks

4. **Automatic Test Execution and Fixing (AI3):**
   * Runs tests without user intervention.
   * Analyzes results and determines the exact causes of errors.
   * Independently fixes simple testing and linting errors.
   * Sends complex issues to AI1 for deeper analysis.

5. **Result Processing and Refinement (AI1):**
   * Receives and analyzes the status of all tasks.
   * Makes decisions about task reassignment in case of errors.
   * Tracks the number of refinement attempts and determines when manual intervention is needed.

## Areas for Improvement

The current implementation has several areas that need improvement:

### Web Interface
* The visualization interface for the development process needs to be completed
* Dashboard for monitoring task queues, test results, and system status needs enhancement
* Real-time updates via WebSockets need to be fully implemented

### GitHub Integration
* GitHub Actions for automated code testing needs to be fully implemented
* Repository dispatch events need to be properly triggered and handled

### Error Handling
* More robust error handling and recovery mechanisms need to be implemented
* Automatic recovery from process failures needs enhancement

### Monitoring and Logging
* Comprehensive logging system needs improvement
* Better visualization of system state and progress

### Multi-Repository Structure
* Better separation between the main system repository and the generated project repository
* Improved Git integration for both repositories

## Setup and Launch

### System Requirements
* Docker
* Git
* Python 3.10+
* Node.js 18+
* Environment variable `GITHUB_TOKEN` (with `repo` and `workflow` permissions) for running GitHub Actions.

### Quick Start
```bash
# Clone the repository
git clone https://github.com/oleg121203/AI-SYSTEMS.git
cd AI-SYSTEMS

# Create a .env file and add your GITHUB_TOKEN
echo "GITHUB_TOKEN=ghp_YourGitHubPersonalAccessToken" > .env

# Start the system
./run_async_services.sh --target "Description of your project"
```

## Contributing to the Project

We welcome any contribution to the project! You can send suggestions or report issues through the GitHub Issue system.

## License

The project is distributed under the MIT License. Detailed information can be found in the LICENSE file.
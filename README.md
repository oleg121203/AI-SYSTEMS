# AI-SYSTEMS

## Purpose of AI-SYSTEMS

AI-SYSTEMS is a comprehensive system designed to automate the software development process through the interaction of multiple specialized AI agents. The main goal is to take a project description (target) as input and generate an appropriate project structure, write code, create tests, write documentation, and ensure iterative code improvement based on test results.

## System Architecture

The system consists of the following main components:

- **AI1 (Coordinator)**: Plans and coordinates tasks, makes decisions based on test results. Uses LLM for flexible decision-making, task prioritization, and report analysis.
- **AI2 (Executors)**: Generate code (executor), tests (tester), and documentation (documenter).
- **AI3 (Monitor/Structure Manager)**: Creates the project structure, proactively monitors the system, provides consultations, identifies problems, initiates their resolution, and independently fixes testing errors.
- **MCP API**: Central API for interaction between components, manages task queues.
- **Web Interface**: Visualization of the development process and system management.
- **GitHub Actions**: Automated code testing.

## Repository Structure

The system uses two repositories:

1. **Main Repository (AI-SYSTEMS)**:
   - Contains the code of the system itself (AI agents, API, web interface)
   - URL: `https://github.com/oleg121203/AI-SYSTEMS.git`

2. **Project Repository (repo/)**:
   - Nested repository where the generated project is stored
   - AI3 automatically creates files and makes commits
   - URL: `https://github.com/oleg121203/AI-SYSTEMS-REPO.git`

## System Prompt Configuration

The system uses a hybrid approach to prompt management:

1. **Base prompts in config.json**:
   - `ai1_prompt`: Basic instruction for the AI1 coordinator. Describes the goals and capabilities of AI1.
   - `ai2_prompts`: Array of basic instructions for AI2 (executor, tester, documenter).
   - `ai3_prompt`: Basic instruction for AI3 regarding project structure generation.

2. **System instructions in code**:
   - Each AI agent supplements the basic prompt with system instructions (e.g., use of Latin characters, JSON format).
   - This provides flexibility (the main prompt can be changed through configuration) and reliability (critical instructions are protected in the code).

## Project Structure Generation with Two Cycles

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
   * Launches background monitoring processes:
     * **Worker Monitoring**: Checks the status of AI2 workers and requests new tasks when idle.
     * **Log and Test Monitoring**: Scans logs for errors and automatically runs and analyzes tests.
     * **GitHub Actions Monitoring**: Analyzes the results of CI/CD test runs.
     * **Queue Monitoring**: Tracks the sizes of task queues and notifies AI1 for redistribution.

2. **Planning and Coordination (AI1):**
   * AI1 receives the project structure and idea.md content from the MCP API.
   * Uses idea.md as context for all tasks.
   * Determines priorities of different task types using LLM.
   * Makes decisions regarding test results based on AI3 recommendations and its own analysis.

3. **Task Execution (AI2):**
   * Generates code, tests, and documentation using various LLM providers.
   * Has a mechanism for automatic code block formatting and logic for specialized tasks.
   * Processes idea.md separately from regular code files.

4. **Automatic Test Execution and Fixing (AI3):**
   * Runs tests without user intervention.
   * Analyzes results and determines the exact causes of errors.
   * Independently fixes simple testing and linting errors.
   * Sends complex issues to AI1 for deeper analysis.

5. **Result Processing and Refinement (AI1):**
   * Receives and analyzes the status of all tasks.
   * Makes decisions about task reassignment in case of errors.
   * Tracks the number of refinement attempts and determines when manual intervention is needed.

## New Autonomous System Features

### Self-Correction of Code and Tests (AI3)
* **Automatic Detection and Correction of Errors**: AI3 now has a TestRunner component that runs all tests and can automatically fix errors.
* **Source Code and Test Analysis**: AI3 analyzes code and tests to determine the exact source of errors.
* **Autonomous Linting Error Correction**: AI3 automatically fixes formatting and style errors without user intervention.
* **Self-Verification of Fixes**: After making fixes, AI3 reruns tests to ensure the changes were successful.

### Enhanced Testing Capabilities
* **Comprehensive Test Result Analysis**: TestRunner collects detailed information about results and generates reports.
* **Code Test Coverage**: The system tracks and reports on code test coverage.
* **Error Prediction**: The system analyzes error patterns to predict potential problems.

### Improved Decision Making (AI1)
* **LLM-Based Evaluation of Test Results**: AI1 uses LLM models to make decisions regarding test results.
* **Fix History Tracking**: AI1 tracks previous fix attempts to make better decisions.
* **Critical Error Prioritization**: The system identifies and prioritizes the most important errors.

### Enhanced Interaction Between AI Agents
* **Extended Context Exchange**: AI agents share extended context for more coordinated work.
* **Collaborative Problem Solving**: AI3 and AI1 jointly analyze and solve complex problems.
* **Structured Error Reports**: Standardized detailed error reports for effective decision making.

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

## System Evaluation

### Strengths
* **Full Autonomy**: The system is capable of creating software from idea to working product without human intervention.
* **Self-Correction**: Automatic detection and correction of testing and linting errors.
* **Deep Problem Analysis**: Use of LLM to understand complex errors and fix them.
* **Flexible Architecture**: Modular structure allows easy extension of system functionality.
* **Multi-Level Collaboration**: Effective interaction between AI agents to solve complex tasks.

### Areas for Further Improvement
* **Handling Super Complex Errors**: Further improving the system's ability to fix complex logical errors.
* **Resource Usage Optimization**: Balancing computational resources between different system components.
* **Expanding Supported Technologies**: Adding more programming languages and frameworks.

## Contributing to the Project

We welcome any contribution to the project! You can send suggestions or report issues through the GitHub Issue system.

## License

The project is distributed under the MIT License. Detailed information can be found in the LICENSE file.
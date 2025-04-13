# AI-SYSTEMS

## The Essence of AI-SYSTEMS

AI-SYSTEMS is a comprehensive system designed to automate the software development process through the interaction of several specialized AI agents. The main goal is to take a project target description as input and generate an appropriate project structure, write code, create tests, write documentation, and provide iterative code improvements based on test results.

## System Architecture

The system consists of the following main components:

- **AI1 (Coordinator)**: Plans and coordinates tasks, makes decisions based on test results.
- **AI2 (Executors)**: Generate code (executor), tests (tester), and documentation (documenter).
- **AI3 (Overseer/Structure Manager)**: Creates project structure, monitors the system, provides consultations.
- **MCP API**: Central API for component interaction, manages task queues.
- **Web Interface**: Visualization of the development process and system management.
- **GitHub Actions**: Automated code testing.

## Repository Structure

The system uses two repositories:

1. **Main Repository (AI-SYSTEMS)**: 
   - Contains the system code (AI agents, API, web interface)
   - URL: `https://github.com/oleg121203/AI-SYSTEMS.git`

2. **Project Repository (repo/)**: 
   - Nested repository where the generated project is stored
   - AI3 automatically creates files and commits changes
   - URL: `https://github.com/oleg121203/AI-SYSTEMS-REPO.git`

## System Operation Algorithm

1. **Initialization (AI3):**
   * AI3 receives the project goal (`target`) from the configuration.
   * Generates the initial JSON structure of project files and directories using LLM.
   * Creates these files and directories in the local repository (repo).
   * Sends the generated structure to the MCP API.
   * Launches background monitoring processes:
     * Idle AI2 workers (executor, tester, documenter).
     * Errors in system log files.
     * Test results from GitHub Actions.

2. **Planning and Coordination (AI1):**
   * AI1 receives the project structure from the MCP API.
   * Builds a high-level structure of main tasks (e.g., by components: Backend, Frontend, etc.).
   * **Consults with AI3:** Sends the main task structure to AI3 for analysis and recommendations for improvement.
   * Breaks down each main task into microtasks (usually file by file: implementation, testing, documentation).
   * **Consults with AI3:** Sends the generated microtasks to AI3 for analysis and recommendations.
   * Initializes statuses for all microtasks.

3. **Task Distribution and Execution (AI1 -> MCP API -> AI2):**
   * AI1 starts managing tasks (`manage_tasks`):
     * Determines which tasks are ready for execution (e.g., "executor" for a new file, "tester" after "executor" completion).
     * Creates specific subtasks (with prompts, ID, role, filename, sometimes with code) and sends them to the MCP API.
   * MCP API places subtasks in the appropriate queues (executor, tester, documenter).
   * AI2 workers (launched separately for each role) periodically request tasks from their queue in the MCP API (`/task/{role}`).
   * Upon receiving a task, the AI2 worker uses the appropriate LLM provider to generate content (code, tests, documentation).
   * AI2 sends a report (`/report`) with the result (generated content or error status) back to the MCP API.

4. **Report Processing and Status Updates (MCP API):**
   * MCP API receives reports from AI2.
   * If the report contains code (`type: code`), it is written to the corresponding file in the repository (repo) and committed using Git.
   * The status of the corresponding subtask is updated (e.g., `code_received`, `tested`).
   * **Automatic Creation of Next Tasks:** MCP API automatically creates tasks for the tester and documenter after receiving code from the executor. This sequence allows all AI2 workers to work in parallel, increasing the overall efficiency of the system.
   * Status updates are broadcast via WebSocket to the web panel.

5. **Testing (GitHub Actions -> AI3 -> MCP API -> AI1):**
   * Commits made by MCP API (after receiving code from AI2-executor or tests from AI2-tester) trigger GitHub Actions workflow (`.github/workflows/ci.yml`).
   * GitHub Actions runs `pytest` for modified test files (or all tests).
   * AI3 monitors completed GitHub Actions runs (`monitor_github_actions`).
   * AI3 analyzes the result (success/failure), identifies related files, and forms a recommendation (`accept`/`rework`).
   * AI3 sends the recommendation to the MCP API (`/test_recommendation`).
   * MCP API updates the status of test tasks and forwards the recommendation to AI1.

6. **Decision Making and Refinement (AI1):**
   * AI1 receives test results and AI3's recommendation (`handle_test_result`).
   * AI1 makes the final decision (`decide_on_test_results`): accept the code (`accept`) or send it for refinement (`rework`).
   * If `accept`, the status of the corresponding tasks is updated to `accepted`.
   * If `rework`, the status is updated to `needs_rework`, and AI1 creates a new subtask for AI2-executor with a description of the required fixes (based on AI3's comments or error logs). This new task again goes through the execution and testing cycle.
   * AI1 periodically checks if all tasks have reached a final status (`accepted` or `skipped`).

7. **Monitoring by the "Overseer" (AI3):**
   * In parallel with the entire process, AI3:
     * Checks the status of all workers through the `/worker_status` endpoint in the MCP API. If a worker is idle (corresponding queue is empty), it requests a new task for it from the MCP API (`/request_task_for_idle_worker`).
     * If the API for status checking is unavailable, it uses a backup method of analyzing log files, looking for messages about an empty queue.
     * Collects and analyzes monitoring statistics (number of detected idle periods, requests for new tasks, successful requests).
     * If it finds errors in the logs, it requests a task to fix them from the MCP API (`/request_error_fix`).
     * Monitors test results (as described in point 5).

8. **Visualization (Dashboard):**
   * The web interface (`templates/index.html`, script.js, style.css) connects to the MCP API via WebSocket.
   * Displays AI agent statuses, task queue states, file structure, logs, statistics, and progress charts in real-time.
   * Allows the user to control the system (start/stop agents, reset, edit prompts).

## Advanced System Features

### Development Environment Management
* **Dev Container**: The system runs in a containerized environment with all the necessary tools (Git, Docker, Python, Node.js, Go, Rust)
* **Automatic Setup**: Scripts for automatic setup of the development environment

### Working with LLM Providers
* **Support for Multiple LLMs**: Ability to configure different LLMs for different types of tasks (code, tests, documentation)
* **API Key Rotation**: Automatic switching between multiple API keys to avoid limits
* **Request Caching**: Reducing the number of requests to LLM by storing previous results

### Multilingual Support
* **Multilingual Projects**: Support for generating projects in different programming languages
* **Web Interface Localization**: Ability to choose the interface language

### Advanced Testing Capabilities
* **Code Coverage Analysis**: Integration with code coverage analysis tools
* **Static Analysis**: Use of linters and other static analysis tools
* **Integration Tests**: Generation and execution of integration tests

### Developer Tools
* **CLI Interface**: System management via command line
* **Project Export/Import**: Ability to export and import projects
* **Advanced Analytics**: Detailed statistics and metrics of the development process
* **Code Block Formatting**: The `format_code_blocks` function automatically fixes the formatting of code blocks, adding a space between the language name and triple backticks. This avoids code parsing issues in the AI system.

#### Usage Example:
```python
example_text = """python```print('Hello')```"""
formatted = format_code_blocks(example_text)
print(formatted)
```

## Setup and Launch

### System Requirements
* Docker
* Git
* Python 3.10+
* Node.js 18+

### Quick Start
```bash
# Clone the repository
git clone https://github.com/oleg121203/AI-SYSTEMS.git
cd AI-SYSTEMS

# Setup environment
./setup.sh

# Launch the system
./start.sh --target "Your project description"
```

## System Evaluation

### Strengths
* **Modularity:** Clear division of responsibilities between AI agents (AI1 - coordination, AI2 - execution, AI3 - structure and monitoring).
* **Automation:** Complete automation of the development cycle from structure to testing and refinement.
* **Feedback:** Closed testing loop through GitHub Actions and AI3 result analysis allows the system to improve code on its own.
* **Monitoring:** The "overseer" role (AI3) adds resilience to the system by detecting problems (idle periods, errors) and initiating their resolution.
* **Consultations:** The consultation mechanism between AI1 and AI3 allows for improved task planning.
* **Centralized API:** MCP API serves as a single point of interaction, simplifying communication.
* **Visualization:** The dashboard provides a good overview of the system state.
* **Automatic Creation of Next Tasks:** The system automatically creates tasks for the tester and documenter immediately after receiving code, ensuring a continuous development process.
* **Improved Worker Status Monitoring:** AI3 uses a special `/worker_status` endpoint for effective detection of idle workers.

### Areas for Improvement
* **Complexity:** The system is quite complex due to the large number of interacting components. Debugging and maintenance can be challenging.
* **LLM Reliability:** The quality of the final product heavily depends on the quality of code/test/documentation generation by the underlying LLMs. Careful prompt tuning is required.
* **Error Handling:** The system must be resilient to errors at each stage (API errors, LLM errors, Git errors, GitHub Actions errors). Current handling may need expansion.
* **Refinement Efficiency:** The refinement mechanism (when AI1 creates a new task for fixing) must be efficient to avoid cycling on the same errors. More complex fixing strategies may be needed.
* **State Management:** Synchronizing state across all components (especially task statuses) is critically important and can be complex.
* **Scalability:** As the project size increases, the load on the API and LLM providers may increase.
* **GitHub Actions:** The current workflow may not be optimal (e.g., running tests only for files related to the changed code, not just the changed tests).

## Development Plans

### Short-term
* Improvement of the error handling system
* Expansion of the set of supported programming languages
* Optimization of the testing process

### Medium-term
* Integration with other CI/CD systems (besides GitHub Actions)
* Implementation of machine learning mechanisms to improve generation quality
* Adding support for mobile development

### Long-term
* Development of plugins for popular IDEs
* Creation of a marketplace for project templates
* Support for distributed development by multiple teams

## Contributing to the Project

We welcome any contribution to the project! Additional information can be found in the CONTRIBUTING.md file.

## License

The project is distributed under the MIT license. Detailed information can be found in the LICENSE file.

## Conclusion

The AI-SYSTEMS system has a well-thought-out architecture with a clear distribution of roles and an automated development cycle with testing and refinement. The inclusion of AI3 as an "overseer" and the consultation mechanism are strengths. The main challenges lie in the reliability of LLMs, comprehensive error handling, and effective state management in such a complex system. Overall, it is an ambitious and well-structured approach to automating software creation using AI.
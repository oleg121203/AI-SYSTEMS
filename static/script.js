// filepath: /workspaces/vscode-remote-try-python/static/script.js
let taskChart, progressChart, gitChart, editor, statusPieChart;
let ws;
const reconnectInterval = 5000; // Reconnect interval 5 seconds
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;

// --- Global DOM Elements (cache them) ---
let logContent; // Will be assigned in DOMContentLoaded
let aiButtons = {};
let queueLists = {};
let queueCounts = {};
let statElements = {};
let subtask_status = {}; // Add global status object

// --- Monaco Editor Setup ---
require.config({
  paths: { vs: "https://unpkg.com/monaco-editor@0.34.0/min/vs" },
});
require(["vs/editor/editor.main"], function () {
  const theme = localStorage.getItem("theme") || "dark"; // Default to dark
  setTheme(theme); // Apply theme immediately
  const editorTheme = getEditorTheme(theme);

  editor = monaco.editor.create(document.getElementById("editor"), {
    value: "// Select a file from the structure view",
    language: "plaintext",
    theme: editorTheme,
    automaticLayout: true, // Ensure editor resizes
  });
});

// --- WebSocket Connection ---
function connectWebSocket() {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
  console.log(`Attempting to connect to WebSocket: ${wsUrl}`);
  if (logContent)
    logContent.innerHTML += `<p><em>Attempting to connect to WebSocket: ${wsUrl}</em></p>`;

  ws = new WebSocket(wsUrl);

  ws.onopen = function (event) {
    console.log("WebSocket connection opened");
    if (logContent)
      logContent.innerHTML +=
        "<p><em>WebSocket connection established</em></p>";
    showNotification("Connected to server", "success");
    reconnectAttempts = 0; // Reset attempts on successful connection
    // Request initial full status upon connection
    ws.send(JSON.stringify({ action: "get_full_status" }));
    showNotification("Connected to server, requesting full status...", "info");
  };

  ws.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      console.log("Received data:", data); // Debugging

      // --- Route message based on type ---
      switch (data.type) {
        case "initial_status": // Initial full status
          ws.send(JSON.stringify({ action: "get_full_status" }));
          showNotification(
            "Connected to server, requesting full status...",
            "info"
          );
          break;
        case "full_status_update": // Periodic full status
          updateFullUI(data);
          break;
        case "status_update": // Just AI on/off status
          if (data.ai_status) {
            updateAllButtonStates(data.ai_status);
          }
          break;
        case "log_update": // Append log line
          if (data.log_line && logContent) {
            const logEntry = document.createElement("p");
            logEntry.textContent = data.log_line;
            // Clear "Connecting..." message on first real log
            if (logContent.innerHTML.includes("Connecting to server...")) {
              logContent.innerHTML = "";
            }
            logContent.appendChild(logEntry);
            logContent.scrollTop = logContent.scrollHeight; // Auto-scroll
          }
          break;
        case "structure_update": // Specific structure update
          if (data.structure) {
            updateFileStructure(data.structure);
          }
          break;
        case "queue_update": // Specific queue update
          if (data.queues) {
            updateQueues(data.queues);
          }
          break;
        case "specific_update": // Handle targeted updates
          console.log("Handling specific update:", data);
          if (data.queues) {
            updateQueues(data.queues);
          }
          if (data.subtasks) {
            // Update only specific subtask statuses
            Object.assign(subtask_status, data.subtasks); // Merge updates
            updateStatsFromSubtasks(subtask_status); // Recalculate stats
          }
          if (data.structure) {
            updateFileStructure(data.structure);
          }
          if (data.processed_over_time) {
            updateCharts({ processed_over_time: data.processed_over_time }); // Update specific chart data
          }
          if (data.task_status_distribution) {
            updateCharts({
              task_status_distribution: data.task_status_distribution,
            });
          }
          if (data.log_line && logContent) {
            const logEntry = document.createElement("p");
            logEntry.textContent = data.log_line;
            if (logContent.innerHTML.includes("Connecting to server...")) {
              logContent.innerHTML = "";
            }
            logContent.appendChild(logEntry);
            logContent.scrollTop = logContent.scrollHeight;
          }
          break;
        case "ping": // Ignore ping messages
          console.log("Ping received");
          break;
        default:
          console.warn("Received unhandled message type:", data.type, data);
          // Attempt generic update if structure looks right
          if (
            data.ai_status ||
            data.queues ||
            data.subtasks ||
            data.structure
          ) {
            console.log("Attempting generic update based on available data...");
            updateFullUI(data); // Try a full update
          }
      }
    } catch (e) {
      console.error(
        "Error parsing WebSocket message or updating UI:",
        e,
        "Raw data:",
        event.data
      );
      if (logContent)
        logContent.innerHTML += `<p><em><strong style="color:red;">Error parsing WebSocket message:</strong> ${e}</em></p>`;
    }
  };

  ws.onerror = function (event) {
    console.error("WebSocket error observed:", event);
    if (logContent)
      logContent.innerHTML +=
        '<p><em><strong style="color:red;">WebSocket error.</strong></em></p>';
    showNotification("WebSocket error", "error");
  };

  ws.onclose = function (event) {
    console.log(
      "WebSocket connection closed. Code:",
      event.code,
      "Reason:",
      event.reason
    );
    if (logContent)
      logContent.innerHTML += `<p><em>WebSocket connection closed. Attempting to reconnect... (${
        reconnectAttempts + 1
      }/${maxReconnectAttempts})</em></p>`;
    showNotification("Disconnected. Reconnecting...", "warning");
    reconnectAttempts++;
    if (reconnectAttempts < maxReconnectAttempts) {
      setTimeout(connectWebSocket, reconnectInterval);
    } else {
      console.error("Max WebSocket reconnection attempts reached.");
      if (logContent)
        logContent.innerHTML += `<p><em><strong style="color:red;">Failed to reconnect after ${maxReconnectAttempts} attempts.</strong> Please refresh the page.</em></p>`;
      showNotification("Failed to reconnect to server", "error");
    }
  };
}

// --- UI Update Functions ---

function updateFullUI(data) {
  console.log("Updating full UI with data:", data);
  if (data.ai_status) {
    updateAllButtonStates(data.ai_status);
  }
  if (data.queues) {
    updateQueues(data.queues);
  }
  // Update stats based on subtask statuses if available
  if (data.subtasks) {
    Object.assign(subtask_status, data.subtasks); // Merge all statuses
    updateStatsFromSubtasks(subtask_status);
  } else if (data.processed !== undefined && data.efficiency !== undefined) {
    updateStatsLegacy(data);
  }

  updateCharts(data); // Pass the whole data object

  if (data.structure) {
    updateFileStructure(data.structure);
  }
}

function updateStatsFromSubtasks(subtasks) {
  const total = Object.keys(subtasks).length;
  const completed = Object.values(subtasks).filter(
    (status) =>
      status === "accepted" ||
      status === "completed" ||
      status === "code_received" // Consider these as completed for stats
  ).length;
  const efficiency = total > 0 ? ((completed / total) * 100).toFixed(1) : 0;

  if (statElements.total) statElements.total.textContent = total;
  if (statElements.completed) statElements.completed.textContent = completed;
  if (statElements.efficiency)
    statElements.efficiency.textContent = `${efficiency}%`;
}

// Fallback if 'subtasks' field isn't in the data
function updateStatsLegacy(data) {
  if (statElements.total && data.total_tasks !== undefined)
    statElements.total.textContent = data.total_tasks;
  if (statElements.completed && data.processed !== undefined)
    statElements.completed.textContent = data.processed;
  if (statElements.efficiency && data.efficiency !== undefined)
    statElements.efficiency.textContent = data.efficiency;
}

function updateQueues(queuesData) {
  ["executor", "tester", "documenter"].forEach((role) => {
    const ul = queueLists[role];
    const countSpan = queueCounts[role];
    if (!ul || !countSpan) return; // Skip if elements not found

    ul.innerHTML = ""; // Clear existing list
    const tasks = queuesData[role] || [];
    countSpan.textContent = tasks.length; // Update count

    tasks.forEach((task) => {
      if (!task || !task.id || !task.text) {
        console.warn("Skipping invalid task object in queue:", task);
        return;
      }
      const li = document.createElement("li");
      const status = task.status || subtask_status[task.id] || "unknown"; // Get status from task or global state
      li.setAttribute("data-status", status);

      // --- Summary Row ---
      const summaryDiv = document.createElement("div");
      summaryDiv.className = "task-summary";

      const statusIcon = document.createElement("span");
      statusIcon.className = "status-icon";
      statusIcon.innerHTML = getStatusIcon(status);

      const taskFilename = document.createElement("span");
      taskFilename.className = "task-filename";
      taskFilename.textContent =
        task.filename || `Task ${task.id.substring(0, 8)}`; // Show filename or short ID

      const taskIdSpan = document.createElement("span");
      taskIdSpan.className = "task-id";
      taskIdSpan.textContent = `(ID: ${task.id.substring(0, 8)})`;

      summaryDiv.appendChild(statusIcon);
      summaryDiv.appendChild(taskFilename);
      summaryDiv.appendChild(taskIdSpan);
      li.appendChild(summaryDiv);

      // --- Details Div (Hidden) ---
      const detailsDiv = document.createElement("div");
      detailsDiv.className = "task-details";
      detailsDiv.textContent = task.text; // Full text here
      li.appendChild(detailsDiv);

      // --- Click Listener for Expansion ---
      li.addEventListener("click", () => {
        li.classList.toggle("expanded");
      });

      ul.appendChild(li);
    });
  });
}

function getStatusIcon(status) {
  switch (status) {
    case "pending":
      return "⏳";
    case "processing":
      return '<i class="fas fa-spinner fa-spin"></i>'; // Font Awesome spinner
    case "accepted":
    case "completed":
    case "code_received":
      return "✅";
    case "failed":
      return "❌";
    default:
      return "?";
  }
}

function updateCharts(data) {
  // Task Distribution Chart (Bar)
  if (!taskChart) {
    const ctx = document.getElementById("taskChart")?.getContext("2d");
    if (ctx) {
      taskChart = new Chart(ctx, {
        type: "bar",
        data: {
          labels: ["Executor", "Tester", "Documenter"],
          datasets: [
            {
              label: "Tasks in Queue",
              data: [0, 0, 0], // Initial data
              backgroundColor: [
                "rgba(54, 162, 235, 0.6)", // Blue
                "rgba(75, 192, 192, 0.6)", // Green
                "rgba(255, 159, 64, 0.6)", // Orange
              ],
              borderColor: [
                "rgba(54, 162, 235, 1)",
                "rgba(75, 192, 192, 1)",
                "rgba(255, 159, 64, 1)",
              ],
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { beginAtZero: true, ticks: { color: getChartFontColor() } },
            x: { ticks: { color: getChartFontColor() } },
          },
          plugins: { legend: { labels: { color: getChartFontColor() } } },
        },
      });
      console.log("Task chart initialized");
    }
  }
  // Update task chart data if available (using queue sizes)
  if (taskChart && data.queues) {
    taskChart.data.datasets[0].data = [
      (data.queues.executor || []).length,
      (data.queues.tester || []).length,
      (data.queues.documenter || []).length,
    ];
    taskChart.options.scales.y.ticks.color = getChartFontColor();
    taskChart.options.scales.x.ticks.color = getChartFontColor();
    taskChart.options.plugins.legend.labels.color = getChartFontColor();
    taskChart.update();
  }

  // Progress Chart (Line) - Assuming data.progress = { stages: [], values: [] }
  if (!progressChart) {
    const ctx = document.getElementById("progressChart")?.getContext("2d");
    if (ctx) {
      progressChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            {
              label: "Project Progress (%)",
              data: [],
              backgroundColor: "rgba(75, 192, 192, 0.2)",
              borderColor: "rgba(75, 192, 192, 1)",
              borderWidth: 1,
              tension: 0.1,
              fill: true,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              max: 100,
              ticks: { color: getChartFontColor() },
            },
            x: { ticks: { color: getChartFontColor() } },
          },
          plugins: { legend: { labels: { color: getChartFontColor() } } },
        },
      });
      console.log("Progress chart initialized");
    }
  }
  if (
    progressChart &&
    data.progress &&
    data.progress.stages &&
    data.progress.values
  ) {
    progressChart.data.labels = data.progress.stages;
    progressChart.data.datasets[0].data = data.progress.values;
    progressChart.options.scales.y.ticks.color = getChartFontColor();
    progressChart.options.scales.x.ticks.color = getChartFontColor();
    progressChart.options.plugins.legend.labels.color = getChartFontColor();
    progressChart.update();
  }

  // Git Commits Chart (Line) - Assuming data.processed_over_time = [...]
  if (!gitChart) {
    const ctx = document.getElementById("gitChart")?.getContext("2d");
    if (ctx) {
      gitChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: [],
          datasets: [
            {
              label: "Commits Over Time",
              data: [],
              backgroundColor: "rgba(255, 159, 64, 0.2)",
              borderColor: "rgba(255, 159, 64, 1)",
              borderWidth: 1,
              tension: 0.1,
              fill: true,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: { beginAtZero: true, ticks: { color: getChartFontColor() } },
            x: { ticks: { color: getChartFontColor() } },
          },
          plugins: { legend: { labels: { color: getChartFontColor() } } },
        },
      });
      console.log("Git chart initialized");
    }
  }
  if (gitChart && data.processed_over_time) {
    gitChart.data.labels = data.processed_over_time.map((_, i) => `T${i + 1}`);
    gitChart.data.datasets[0].data = data.processed_over_time;
    gitChart.options.scales.y.ticks.color = getChartFontColor();
    gitChart.options.scales.x.ticks.color = getChartFontColor();
    gitChart.options.plugins.legend.labels.color = getChartFontColor();
    gitChart.update();
  }

  // Status Distribution Chart (Pie)
  if (!statusPieChart) {
    const ctx = document.getElementById("statusPieChart")?.getContext("2d");
    if (ctx) {
      statusPieChart = new Chart(ctx, {
        type: "doughnut", // Or 'pie'
        data: {
          labels: ["Pending", "Processing", "Completed", "Failed", "Other"],
          datasets: [
            {
              label: "Task Status Distribution",
              data: [0, 0, 0, 0, 0], // Initial data
              backgroundColor: [
                "rgba(255, 159, 64, 0.7)", // Pending (Orange)
                "rgba(54, 162, 235, 0.7)", // Processing (Blue)
                "rgba(75, 192, 192, 0.7)", // Completed (Green)
                "rgba(255, 99, 132, 0.7)", // Failed (Red)
                "rgba(201, 203, 207, 0.7)", // Other (Grey)
              ],
              borderColor: [
                "rgba(255, 159, 64, 1)",
                "rgba(54, 162, 235, 1)",
                "rgba(75, 192, 192, 1)",
                "rgba(255, 99, 132, 1)",
                "rgba(201, 203, 207, 1)",
              ],
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "top",
              labels: { color: getChartFontColor() },
            },
            title: {
              display: true,
              text: "Task Statuses",
              color: getChartFontColor(),
            },
          },
        },
      });
      console.log("Status Pie chart initialized");
    }
  }
  // Update pie chart data if available
  if (statusPieChart && data.task_status_distribution) {
    const dist = data.task_status_distribution;
    statusPieChart.data.datasets[0].data = [
      dist.pending || 0,
      dist.processing || 0,
      dist.completed || 0,
      dist.failed || 0,
      dist.other || 0,
    ];
    statusPieChart.options.plugins.legend.labels.color = getChartFontColor();
    statusPieChart.options.plugins.title.color = getChartFontColor();
    statusPieChart.update();
  }
}

function getChartFontColor() {
  // Get the computed style of the body element
  const bodyStyle = window.getComputedStyle(document.body);
  // Return the value of the --text-color CSS variable
  return bodyStyle.getPropertyValue("--text-color").trim();
}

function updateFileStructure(structureData) {
  const fileStructureDiv = document.getElementById("file-structure");
  if (!fileStructureDiv) return;

  fileStructureDiv.innerHTML = ""; // Clear previous structure

  if (!structureData || Object.keys(structureData).length === 0) {
    fileStructureDiv.innerHTML =
      "<p><em>Project structure is empty or unavailable.</em></p>";
    return;
  }

  const rootUl = document.createElement("ul");
  fileStructureDiv.appendChild(rootUl);

  function renderNode(node, parentUl, currentPath = "") {
    // Sort entries: folders first, then files, alphabetically
    const entries = Object.entries(node).sort(
      ([keyA, valueA], [keyB, valueB]) => {
        const isDirA = typeof valueA === "object" && valueA !== null;
        const isDirB = typeof valueB === "object" && valueB !== null;
        if (isDirA !== isDirB) {
          return isDirA ? -1 : 1; // Folders first
        }
        return keyA.localeCompare(keyB); // Then alphabetical
      }
    );

    for (const [key, value] of entries) {
      const li = document.createElement("li");
      parentUl.appendChild(li);
      const isDirectory =
        typeof value === "object" &&
        value !== null &&
        Object.keys(value).length >= 0; // Treat empty objects as folders too
      const itemPath = currentPath ? `${currentPath}/${key}` : key; // Build path

      if (isDirectory) {
        li.innerHTML = `<span class="folder"><i class="fas fa-folder"></i> ${key}</span>`;
        li.classList.add("folder-item");
        const subUl = document.createElement("ul");
        li.appendChild(subUl);
        renderNode(value, subUl, itemPath); // Recurse

        // Toggle expansion on click
        li.querySelector(".folder").addEventListener("click", (e) => {
          li.classList.toggle("expanded");
          e.stopPropagation(); // Prevent event bubbling
        });
      } else {
        // It's a file (or should be treated as one)
        li.innerHTML = `<span class="file" data-path="${itemPath}"><i class="fas ${getFileIcon(
          key
        )}"></i> ${key}</span>`;
        // Add click listener to load file content
        li.querySelector(".file").addEventListener("click", (e) => {
          const path = e.currentTarget.getAttribute("data-path");
          loadFileContent(path);
          e.stopPropagation();
        });
      }
    }
  }

  renderNode(structureData, rootUl);
  console.log("File structure rendering completed");
}

function getFileIcon(filename) {
  const ext = filename.split(".").pop().toLowerCase();
  switch (ext) {
    case "py":
      return "fa-python fab"; // Use Font Awesome Brands for Python
    case "js":
      return "fa-js fab";
    case "html":
      return "fa-html5 fab";
    case "css":
      return "fa-css3-alt fab";
    case "json":
      return "fa-file-code"; // Generic code icon
    case "md":
      return "fa-markdown fab";
    case "txt":
      return "fa-file-alt";
    case "png":
    case "jpg":
    case "jpeg":
    case "gif":
    case "svg":
      return "fa-file-image";
    case "dockerfile":
      return "fa-docker fab";
    case "gitignore":
      return "fa-git-alt fab";
    default:
      return "fa-file"; // Default file icon
  }
}

async function loadFileContent(path) {
  if (!editor) {
    showNotification("Editor not initialized yet", "warning");
    return;
  }
  console.log("Attempting to load file content:", path);
  editor.setValue(`// Loading ${path}...`); // Placeholder content

  try {
    // Ensure path starts with '/' if necessary, or adjust based on backend expectation
    const safePath = path.startsWith("/") ? path.substring(1) : path; // Remove leading '/' if present, adjust as needed
    const response = await fetch(
      `/file_content?path=${encodeURIComponent(safePath)}`
    );

    if (response.ok) {
      const content = await response.text();
      const fileExt = path.split(".").pop().toLowerCase();
      const language = getMonacoLanguage(fileExt);

      // Get current model, update language and value
      const model = editor.getModel();
      if (model) {
        monaco.editor.setModelLanguage(model, language);
        model.setValue(content);
      } else {
        // Fallback if model doesn't exist (shouldn't normally happen)
        editor.setValue(content);
        monaco.editor.setModelLanguage(editor.getModel(), language); // Try setting on new implicit model
      }

      console.log(
        `File content loaded successfully for ${path}, language set to ${language}`
      );
      showNotification(`Loaded ${path}`, "info");
    } else {
      const errorText = await response.text();
      editor.setValue(
        `// Failed to load file: ${path}\n// Status: ${response.status}\n// ${errorText}`
      );
      showNotification(
        `Failed to load file: ${path} (${response.status})`,
        "error"
      );
      console.error(
        "Failed to load file content, status:",
        response.status,
        "Response:",
        errorText
      );
    }
  } catch (error) {
    console.error("Error loading file:", error);
    editor.setValue(`// Error loading file: ${path}\n// ${error.message}`);
    showNotification(`Error loading file: ${error.message}`, "error");
  }
}

function getMonacoLanguage(fileExt) {
  switch (fileExt) {
    case "py":
      return "python";
    case "js":
      return "javascript";
    case "html":
      return "html";
    case "css":
      return "css";
    case "json":
      return "json";
    case "md":
      return "markdown";
    case "ts":
      return "typescript";
    case "java":
      return "java";
    case "c":
      return "c";
    case "cpp":
      return "cpp";
    case "cs":
      return "csharp";
    case "go":
      return "go";
    case "php":
      return "php";
    case "rb":
      return "ruby";
    case "swift":
      return "swift";
    case "xml":
      return "xml";
    case "yaml":
    case "yml":
      return "yaml";
    case "sh":
      return "shell";
    case "dockerfile":
      return "dockerfile";
    default:
      return "plaintext";
  }
}

function updateAllButtonStates(aiStatusData) {
  console.log("Updating button states:", aiStatusData); // Debugging
  for (const [aiId, isRunning] of Object.entries(aiStatusData)) {
    updateButtonState(aiId, isRunning);
  }
}

function updateButtonState(aiId, isRunning) {
  const button = aiButtons[aiId]; // Use cached button
  const statusSpan = document.getElementById(`${aiId}-status`); // Get status span

  if (button && statusSpan) {
    statusSpan.textContent = isRunning ? "On" : "Off";
    if (isRunning) {
      button.classList.remove("off");
      button.classList.add("on");
      // Text could be dynamic too, e.g., `Stop ${aiId.toUpperCase()}`
    } else {
      button.classList.remove("on");
      button.classList.add("off");
      // Text could be dynamic too, e.g., `Start ${aiId.toUpperCase()}`
    }
    // Update text content if needed (optional)
    // button.innerHTML = `${aiId.toUpperCase()}: <span id="${aiId}-status">${isRunning ? 'On' : 'Off'}</span>`;
  } else {
    console.warn(`Button or status span not found for AI ID: ${aiId}`);
  }
}

// --- Theme Handling ---
function getEditorTheme(appTheme) {
  // Simple mapping: dark themes use 'vs-dark', light themes use 'vs-light'
  return appTheme === "dark" || appTheme === "winter" || appTheme === "autumn"
    ? "vs-dark"
    : "vs-light";
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme); // Set on <html> for CSS vars
  document.body.setAttribute("data-theme", theme); // Also set on body if needed by specific CSS rules
  localStorage.setItem("theme", theme);

  // Update Monaco Editor theme if editor exists
  if (editor) {
    const editorTheme = getEditorTheme(theme);
    monaco.editor.setTheme(editorTheme);
  }

  // Update chart colors if charts exist
  const chartColor = getChartFontColor();
  [taskChart, progressChart, gitChart, statusPieChart].forEach((chart) => {
    if (chart) {
      chart.options.scales.y.ticks.color = chartColor;
      chart.options.scales.x.ticks.color = chartColor;
      chart.options.plugins.legend.labels.color = chartColor;
      chart.update();
    }
  });

  console.log(`Theme set to: ${theme}`);
}

// --- Notifications ---
function showNotification(message, type = "info") {
  // success, error, warning, info
  const notification = document.createElement("div");
  notification.className = `notification ${type}`;
  notification.textContent = message;
  document.body.appendChild(notification);
  // Auto-remove after 5 seconds
  setTimeout(() => {
    notification.style.opacity = "0"; // Fade out
    setTimeout(() => notification.remove(), 500); // Remove after fade
  }, 5000);
}

// --- API Call Helpers ---
async function sendRequest(endpoint, method = "POST", body = null) {
  console.log(`Sending ${method} request to ${endpoint}`);
  try {
    const options = { method };
    if (body) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(endpoint, options);
    if (!response.ok) {
      const errorText = await response.text();
      console.error(`Error ${response.status} from ${endpoint}: ${errorText}`);
      throw new Error(`Network response was not ok (${response.status})`);
    }
    // Try parsing JSON, but return empty object if no content or not JSON
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
      return await response.json();
    } else {
      return {}; // Return empty object for non-JSON responses (like simple OK)
    }
  } catch (error) {
    console.error(`Fetch operation failed for ${endpoint}:`, error);
    showNotification(
      `Error communicating with server: ${error.message}`,
      "error"
    );
    throw error; // Re-throw for calling function to handle if needed
  }
}

// --- Control Actions ---
async function toggleAI(ai) {
  // Determine current state from the button's class or status span
  const statusSpan = document.getElementById(`${ai}-status`);
  const isOn = statusSpan ? statusSpan.textContent === "On" : false; // Safer check
  const action = isOn ? "stop" : "start";
  const endpoint = `/${action}_${ai}`;

  try {
    // Send request - state will be updated via WebSocket broadcast
    await sendRequest(endpoint);
    // Optimistic UI update (optional, WebSocket should confirm)
    // updateButtonState(ai, !isOn);
    showNotification(`${ai.toUpperCase()} ${action} request sent`, "info");
  } catch (error) {
    // Error already shown by sendRequest
  }
}

async function startAll() {
  try {
    await sendRequest("/start_all");
    showNotification("Start All request sent", "info");
  } catch (error) {}
}

async function stopAll() {
  try {
    await sendRequest("/stop_all");
    showNotification("Stop All request sent", "info");
  } catch (error) {}
}

async function resetSystem() {
  if (
    confirm(
      "Are you sure you want to reset the system? This will clear queues, logs, and restart AI processes."
    )
  ) {
    try {
      // Clear first, then restart (adjust endpoints if needed)
      await sendRequest("/clear", "POST");
      await sendRequest("/start_all", "POST"); // Or individual start endpoints
      showNotification("System reset and restart requested", "info");
      // Clear local UI elements immediately for responsiveness
      logContent.innerHTML = "<p><em>System reset requested...</em></p>";
      updateQueues({ executor: [], tester: [], documenter: [] }); // Clear queues visually
      updateStatsFromSubtasks({}); // Reset stats
      // Charts might need explicit clearing or will update on next WS message
    } catch (error) {
      // Error handled by sendRequest
    }
  }
}

async function clearLogs() {
  if (logContent) {
    logContent.innerHTML = ""; // Clear frontend log display
    showNotification("Frontend logs cleared", "info");
  }
  // Optionally, send request to backend to clear server-side log file if needed
  // try {
  //     await sendRequest('/clear_server_logs', 'POST'); // Example endpoint
  //     showNotification('Server logs cleared', 'info');
  // } catch (error) {}
}

async function saveConfig() {
  const configData = {
    target: document.getElementById("target")?.value,
    ai1_prompt: document.getElementById("ai1-prompt")?.value,
    // Ensure ai2_prompts is always an array of 3 strings
    ai2_prompts: [
      document.getElementById("ai2-0-prompt")?.value || "",
      document.getElementById("ai2-1-prompt")?.value || "",
      document.getElementById("ai2-2-prompt")?.value || "",
    ],
    ai3_prompt: document.getElementById("ai3-prompt")?.value,
  };

  console.log("Saving config:", configData);

  try {
    await sendRequest("/update_config", "POST", configData);
    showNotification("Configuration saved successfully", "success");
  } catch (error) {
    // Error handled by sendRequest
    showNotification("Failed to save configuration", "error"); // Specific message
  }
}

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM fully loaded and parsed");

  // Cache frequently accessed elements
  logContent = document.getElementById("log-content");
  aiButtons = {
    ai1: document.getElementById("ai1-button"),
    ai2: document.getElementById("ai2-button"),
    ai3: document.getElementById("ai3-button"),
  };
  queueLists = {
    executor: document.getElementById("executor-queue"),
    tester: document.getElementById("tester-queue"),
    documenter: document.getElementById("documenter-queue"),
  };
  queueCounts = {
    executor: document.getElementById("executor-queue-count"),
    tester: document.getElementById("tester-queue-count"),
    documenter: document.getElementById("documenter-queue-count"),
  };
  statElements = {
    total: document.getElementById("total-tasks"),
    completed: document.getElementById("completed-tasks"),
    efficiency: document.getElementById("efficiency"),
  };

  // Set initial theme from localStorage or default
  const savedTheme = localStorage.getItem("theme") || "dark"; // Default dark
  setTheme(savedTheme);

  // Connect WebSocket
  connectWebSocket();

  // Add theme button listeners (already handled by inline onclick, but could be done here)
  // document.querySelectorAll('.theme-button').forEach(button => {
  //     button.addEventListener('click', () => setTheme(button.dataset.theme));
  // });

  // Initial UI state (optional, WebSocket should provide data)
  updateQueues({ executor: [], tester: [], documenter: [] });
  updateStatsFromSubtasks({});

  console.log("Initialization complete.");
});

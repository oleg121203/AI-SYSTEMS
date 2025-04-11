let taskChart, progressChart, gitChart, editor, statusPieChart;
let ws;
const reconnectInterval = 5000;
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;

// Глобальні елементи DOM
let logContent;
let aiButtons = {};
let queueLists = {};
let queueCounts = {};
let statElements = {};
let subtask_status = {};

// Налаштування Monaco Editor
require.config({
  paths: { vs: "https://unpkg.com/monaco-editor@0.34.0/min/vs" },
});
require(["vs/editor/editor.main"], function () {
  const theme = localStorage.getItem("theme") || "dark";
  setTheme(theme);
  const editorTheme = getEditorTheme(theme);
  editor = monaco.editor.create(document.getElementById("editor"), {
    value: "// Select a file from the structure view",
    language: "plaintext",
    theme: editorTheme,
    automaticLayout: true,
  });
});

// Підключення до WebSocket
function connectWebSocket() {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
  console.log(`Attempting to connect to WebSocket: ${wsUrl}`);
  if (logContent)
    logContent.innerHTML += `<p><em>Attempting to connect to WebSocket: ${wsUrl}</em></p>`;

  ws = new WebSocket(wsUrl);

  ws.onopen = function () {
    console.log("WebSocket connection established");
    if (logContent)
      logContent.innerHTML +=
        "<p><em>WebSocket connection established</em></p>";
    showNotification("Connected to server", "success");
    reconnectAttempts = 0;
    // Запит повного статусу після підключення
    ws.send(JSON.stringify({ action: "get_full_status" }));
    console.log("Requested full status from server");
  };

  ws.onmessage = function (event) {
    try {
      // Start: Added raw message logging
      console.log("Raw WebSocket message received:", event.data);
      // End: Added raw message logging
      const data = JSON.parse(event.data);
      console.log("Parsed WebSocket data:", data); // Changed log message

      switch (data.type) {
        case "full_status_update":
          console.log("Processing full status update:", data);
          updateFullUI(data);
          break;
        case "status_update":
          console.log("Processing status update:", data.ai_status);
          if (data.ai_status) updateAllButtonStates(data.ai_status);
          break;
        case "specific_update":
          console.log("Processing specific update:", data);
          if (data.queues) updateQueues(data.queues);
          if (data.subtasks) {
            Object.assign(subtask_status, data.subtasks);
            updateStatsFromSubtasks(subtask_status);
          }
          if (data.structure) {
            console.log(
              "Received structure update, keys:",
              Object.keys(data.structure)
            );
            updateFileStructure(data.structure);
          }
          if (data.processed_over_time)
            updateCharts({ processed_over_time: data.processed_over_time });
          if (data.task_status_distribution)
            updateCharts({
              task_status_distribution: data.task_status_distribution,
            });
          if (data.log_line && logContent) {
            const logEntry = document.createElement("p");
            logEntry.textContent = data.log_line;
            if (logContent.innerHTML.includes("Connecting to server..."))
              logContent.innerHTML = "";
            logContent.appendChild(logEntry);
            logContent.scrollTop = logContent.scrollHeight;
            console.log("Added log entry:", data.log_line);
          }
          break;
        case "ping":
          console.log("Ping received");
          break;
        default:
          console.warn("Unhandled message type:", data.type);
      }
    } catch (e) {
      console.error(
        "Error parsing WebSocket message:",
        e,
        "Raw data:",
        event.data
      );
      if (logContent)
        logContent.innerHTML += `<p><em><strong style="color:red;">Error parsing message: ${e}</strong></em></p>`;
    }
  };

  ws.onerror = function (event) {
    console.error("WebSocket error occurred:", event);
    if (logContent)
      logContent.innerHTML += `<p><em><strong style="color:red;">WebSocket error</strong></em></p>`;
    showNotification("WebSocket error", "error");
  };

  ws.onclose = function (event) {
    console.log("WebSocket closed:", event.code, event.reason);
    if (logContent)
      logContent.innerHTML += `<p><em>WebSocket closed. Reconnecting... (${
        reconnectAttempts + 1
      }/${maxReconnectAttempts})</em></p>`;
    showNotification("Disconnected. Reconnecting...", "warning");
    reconnectAttempts++;
    if (reconnectAttempts < maxReconnectAttempts) {
      setTimeout(connectWebSocket, reconnectInterval);
    } else {
      console.error("Max reconnection attempts reached");
      if (logContent)
        logContent.innerHTML += `<p><em><strong style="color:red;">Failed to reconnect after ${maxReconnectAttempts} attempts</strong></em></p>`;
      showNotification("Failed to reconnect", "error");
    }
  };
}

// Оновлення повного UI
function updateFullUI(data) {
  console.log("Updating full UI with data:", data);
  if (data.ai_status) updateAllButtonStates(data.ai_status);
  if (data.queues) updateQueues(data.queues);
  if (data.subtasks) {
    Object.assign(subtask_status, data.subtasks);
    updateStatsFromSubtasks(subtask_status);
  }
  if (data.structure) updateFileStructure(data.structure);
  updateCharts(data);
}

// Оновлення статистики
function updateStatsFromSubtasks(subtasks) {
  const total = Object.keys(subtasks).length;
  const completed = Object.values(subtasks).filter((s) =>
    ["accepted", "completed", "code_received", "tested"].includes(s)
  ).length;
  const pending = Object.values(subtasks).filter((s) => s === "pending").length;
  const processing = Object.values(subtasks).filter(
    (s) => s === "processing"
  ).length;
  const failed = Object.values(subtasks).filter((s) => s === "failed").length;
  const efficiency = total > 0 ? ((completed / total) * 100).toFixed(1) : 0;

  console.log(
    `Stats - Total: ${total}, Completed: ${completed}, Pending: ${pending}, Processing: ${processing}, Failed: ${failed}, Efficiency: ${efficiency}%`
  );

  if (statElements.total) statElements.total.textContent = total;
  if (statElements.completed) statElements.completed.textContent = completed;
  if (statElements.efficiency)
    statElements.efficiency.textContent = `${efficiency}%`;
  // Start: Update new stat elements
  if (statElements.pending) statElements.pending.textContent = pending;
  if (statElements.processing) statElements.processing.textContent = processing;
  if (statElements.failed) statElements.failed.textContent = failed;
  // End: Update new stat elements
}

// Оновлення черг
function updateQueues(queuesData) {
  console.log("Updating queues:", queuesData);
  ["executor", "tester", "documenter"].forEach((role) => {
    const ul = queueLists[role];
    const countSpan = queueCounts[role];
    if (!ul || !countSpan) {
      console.error(`Queue element missing for role: ${role}`);
      return;
    }

    ul.innerHTML = "";
    const tasks = queuesData[role] || [];
    countSpan.textContent = tasks.length;
    console.log(`Queue ${role} updated with ${tasks.length} tasks`);

    tasks.forEach((task) => {
      if (!task || !task.id || !task.text) {
        console.warn("Invalid task object:", task);
        return;
      }
      const li = document.createElement("li");
      const status = task.status || subtask_status[task.id] || "unknown";
      li.setAttribute("data-status", status);

      const summaryDiv = document.createElement("div");
      summaryDiv.className = "task-summary";

      const statusIcon = document.createElement("span");
      statusIcon.className = "status-icon";
      statusIcon.innerHTML = getStatusIcon(status);

      const taskFilename = document.createElement("span");
      taskFilename.className = "task-filename";
      taskFilename.textContent =
        task.filename || `Task ${task.id.substring(0, 8)}`;

      const taskIdSpan = document.createElement("span");
      taskIdSpan.className = "task-id";
      taskIdSpan.textContent = `(ID: ${task.id.substring(0, 8)})`;

      summaryDiv.appendChild(statusIcon);
      summaryDiv.appendChild(taskFilename);
      summaryDiv.appendChild(taskIdSpan);
      li.appendChild(summaryDiv);

      const detailsDiv = document.createElement("div");
      detailsDiv.className = "task-details";
      detailsDiv.textContent = task.text;
      li.appendChild(detailsDiv);

      li.addEventListener("click", () => li.classList.toggle("expanded"));
      ul.appendChild(li);
    });
  });
}

function getStatusIcon(status) {
  switch (status) {
    case "pending":
      return "⏳";
    case "processing":
      return '<i class="fas fa-spinner fa-spin"></i>';
    case "accepted":
    case "completed":
    case "code_received":
    case "tested":
      return "✅";
    case "failed":
      return "❌";
    default:
      return "❓";
  }
}

// Оновлення графіків
function updateCharts(data) {
  console.log("Updating charts with data:", data);

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
              data: [0, 0, 0],
              backgroundColor: [
                "rgba(54, 162, 235, 0.6)",
                "rgba(75, 192, 192, 0.6)",
                "rgba(255, 159, 64, 0.6)",
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
  if (taskChart && data.queues) {
    taskChart.data.datasets[0].data = [
      (data.queues.executor || []).length,
      (data.queues.tester || []).length,
      (data.queues.documenter || []).length,
    ];
    taskChart.update();
    console.log("Task chart updated:", taskChart.data.datasets[0].data);
  }

  if (
    !progressChart &&
    data.progress &&
    data.progress.stages &&
    data.progress.values
  ) {
    const ctx = document.getElementById("progressChart")?.getContext("2d");
    if (ctx) {
      progressChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: data.progress.stages,
          datasets: [
            {
              label: "Project Progress (%)",
              data: data.progress.values,
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
    progressChart.update();
    console.log("Progress chart updated:", progressChart.data.datasets[0].data);
  }

  if (!gitChart && data.processed_over_time) {
    const ctx = document.getElementById("gitChart")?.getContext("2d");
    if (ctx) {
      gitChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: data.processed_over_time.map((_, i) => `T${i + 1}`),
          datasets: [
            {
              label: "Commits Over Time",
              data: data.processed_over_time,
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
    gitChart.update();
    console.log("Git chart updated:", gitChart.data.datasets[0].data);
  }

  if (!statusPieChart) {
    const ctx = document.getElementById("statusPieChart")?.getContext("2d");
    if (ctx) {
      statusPieChart = new Chart(ctx, {
        type: "doughnut",
        data: {
          labels: ["Pending", "Processing", "Completed", "Failed", "Other"],
          datasets: [
            {
              label: "Task Status Distribution",
              data: [0, 0, 0, 0, 0],
              backgroundColor: [
                "rgba(255, 159, 64, 0.7)",
                "rgba(54, 162, 235, 0.7)",
                "rgba(75, 192, 192, 0.7)",
                "rgba(255, 99, 132, 0.7)",
                "rgba(201, 203, 207, 0.7)",
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
          cutout: "60%",
          plugins: {
            legend: { position: "top", labels: { color: getChartFontColor() } },
            title: {
              display: true,
              text: "Task Status Distribution",
              color: getChartFontColor(),
            },
          },
        },
      });
      console.log("Status pie chart initialized");
    }
  }
  if (statusPieChart && data.task_status_distribution) {
    const dist = data.task_status_distribution;
    statusPieChart.data.datasets[0].data = [
      dist.pending || 0,
      dist.processing || 0,
      dist.completed || 0,
      dist.failed || 0,
      dist.other || 0,
    ];
    statusPieChart.update();
    console.log(
      "Status pie chart updated:",
      statusPieChart.data.datasets[0].data
    );
  }
}

function getChartFontColor() {
  return window
    .getComputedStyle(document.body)
    .getPropertyValue("--text-color")
    .trim();
}

// Оновлення структури файлів
function updateFileStructure(structureData) {
  // Start: Added detailed logging
  console.log(
    "Attempting to update file structure. Received data:",
    JSON.stringify(structureData, null, 2)
  );
  // End: Added detailed logging
  const fileStructureDiv = document.getElementById("file-structure");
  if (!fileStructureDiv) {
    console.error("File structure div (#file-structure) not found in DOM!");
    return;
  }
  // Start: Added check for visibility
  const styles = window.getComputedStyle(fileStructureDiv);
  if (styles.display === "none" || styles.visibility === "hidden") {
    console.warn(
      "File structure div (#file-structure) is currently hidden by CSS."
    );
  }
  // End: Added check for visibility

  fileStructureDiv.innerHTML = ""; // Очищення попереднього вмісту
  if (
    !structureData ||
    typeof structureData !== "object" ||
    Object.keys(structureData).length === 0
  ) {
    // Added type check
    fileStructureDiv.innerHTML =
      "<p><em>No project structure available or data is invalid</em></p>";
    console.warn("No valid structure data provided or data is empty/invalid."); // Changed log level
    return;
  }

  const rootUl = document.createElement("ul");
  fileStructureDiv.appendChild(rootUl);
  console.log("Created root UL element and appended to #file-structure."); // Added log

  function renderNode(node, parentUl, currentPath = "") {
    // Start: Added check for valid node
    if (!node || typeof node !== "object") {
      console.error(
        "Invalid node data encountered during rendering:",
        node,
        "at path:",
        currentPath
      );
      return;
    }
    // End: Added check for valid node

    const entries = Object.entries(node).sort(
      ([keyA, valueA], [keyB, valueB]) => {
        const isDirA = typeof valueA === "object" && valueA !== null;
        const isDirB = typeof valueB === "object" && valueB !== null;
        // Ensure consistent sorting: directories first, then files alphabetically
        if (isDirA !== isDirB) {
          return isDirA ? -1 : 1;
        }
        return keyA.localeCompare(keyB);
      }
    );
    // Start: Added logging for entries
    console.log(
      `Rendering path: '${currentPath}'. Found ${entries.length} entries.`
    );
    // End: Added logging for entries

    for (const [key, value] of entries) {
      const li = document.createElement("li");
      const isDirectory = typeof value === "object" && value !== null;
      const itemPath = currentPath ? `${currentPath}/${key}` : key;
      // Start: Added detailed logging inside loop
      console.log(
        `  Processing entry: '${key}', Type: ${
          isDirectory ? "Directory" : "File"
        }, Path: '${itemPath}'`
      );
      // End: Added detailed logging inside loop

      if (isDirectory) {
        li.innerHTML = `<span class="folder"><i class="fas fa-folder"></i> ${key}</span>`;
        li.classList.add("folder-item");
        const subUl = document.createElement("ul");
        li.appendChild(subUl);
        // Start: Added log before recursive call
        console.log(`    Recursively rendering directory: '${key}'`);
        // End: Added log before recursive call
        renderNode(value, subUl, itemPath); // Recursive call
        const folderSpan = li.querySelector(".folder");
        if (folderSpan) {
          folderSpan.addEventListener("click", (e) => {
            li.classList.toggle("expanded");
            e.stopPropagation();
          });
        } else {
          console.error(`Could not find .folder span for directory ${key}`);
        }
      } else {
        li.innerHTML = `<span class="file" data-path="${itemPath}"><i class="fas ${getFileIcon(
          key
        )}"></i> ${key}</span>`;
        const fileSpan = li.querySelector(".file");
        if (fileSpan) {
          fileSpan.addEventListener("click", (e) => {
            loadFileContent(e.currentTarget.getAttribute("data-path"));
            e.stopPropagation();
          });
        } else {
          console.error(`Could not find .file span for file ${key}`);
        }
      }
      parentUl.appendChild(li);
      // Start: Added log after appending
      console.log(`    Appended LI for '${key}' to parent UL.`);
      // End: Added log after appending
    }
  }

  try {
    // Added try...catch around the main render call
    renderNode(structureData, rootUl);
    console.log("File structure rendering function completed.");
  } catch (error) {
    console.error("Error during file structure rendering:", error);
    fileStructureDiv.innerHTML = `<p><em>Error rendering file structure: ${error.message}</em></p>`;
  }
}

function getFileIcon(filename) {
  const ext = filename.split(".").pop().toLowerCase();
  switch (ext) {
    case "py":
      return "fa-python fab";
    case "js":
      return "fa-js fab";
    case "html":
      return "fa-html5 fab";
    case "css":
      return "fa-css3-alt fab";
    case "json":
      return "fa-file-code";
    case "md":
      return "fa-markdown fab";
    case "txt":
      return "fa-file-alt";
    default:
      return "fa-file";
  }
}

async function loadFileContent(path) {
  if (!editor) {
    showNotification("Editor not initialized", "warning");
    return;
  }
  console.log("Loading file content for:", path);
  editor.setValue(`// Loading ${path}...`);

  try {
    const safePath = path.startsWith("/") ? path.substring(1) : path;
    const response = await fetch(
      `/file_content?path=${encodeURIComponent(safePath)}`
    );
    if (response.ok) {
      const content = await response.text();
      const fileExt = path.split(".").pop().toLowerCase();
      const language = getMonacoLanguage(fileExt);
      monaco.editor.setModelLanguage(editor.getModel(), language);
      editor.setValue(content);
      showNotification(`Loaded ${path}`, "info");
      console.log(`File ${path} loaded successfully`);
    } else {
      const errorText = await response.text();
      editor.setValue(
        `// Failed to load ${path}\n// Status: ${response.status}\n// ${errorText}`
      );
      showNotification(`Failed to load ${path} (${response.status})`, "error");
      console.error(
        `Failed to load ${path}: ${response.status} - ${errorText}`
      );
    }
  } catch (error) {
    console.error("Error loading file:", error);
    editor.setValue(`// Error loading ${path}\n// ${error.message}`);
    showNotification(`Error loading file: ${error.message}`, "error");
  }
}

function getMonacoLanguage(fileExt) {
  const map = {
    py: "python",
    js: "javascript",
    html: "html",
    css: "css",
    json: "json",
    md: "markdown",
    ts: "typescript",
    java: "java",
    c: "c",
    cpp: "cpp",
    cs: "csharp",
    go: "go",
  };
  return map[fileExt] || "plaintext";
}

function updateAllButtonStates(aiStatusData) {
  console.log("Updating button states:", aiStatusData);
  for (const [aiId, isRunning] of Object.entries(aiStatusData)) {
    const button = aiButtons[aiId];
    const statusSpan = document.getElementById(`${aiId}-status`);
    if (button && statusSpan) {
      statusSpan.textContent = isRunning ? "On" : "Off";
      button.classList.toggle("on", isRunning);
      button.classList.toggle("off", !isRunning);
    } else {
      console.warn(`Button or status span not found for AI: ${aiId}`);
    }
  }
}

function getEditorTheme(appTheme) {
  return ["dark", "winter", "autumn"].includes(appTheme)
    ? "vs-dark"
    : "vs-light";
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.body.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  if (editor) monaco.editor.setTheme(getEditorTheme(theme));
  const chartColor = getChartFontColor();
  [taskChart, progressChart, gitChart, statusPieChart].forEach((chart) => {
    if (chart) {
      chart.options.scales.y.ticks.color = chartColor;
      chart.options.scales.x.ticks.color = chartColor;
      chart.options.plugins.legend.labels.color = chartColor;
      chart.options.plugins.title &&
        (chart.options.plugins.title.color = chartColor);
      chart.update();
    }
  });
  console.log(`Theme set to: ${theme}`);
}

function showNotification(message, type = "info") {
  const notification = document.createElement("div");
  notification.className = `notification ${type}`;
  notification.textContent = message;
  document.body.appendChild(notification);
  setTimeout(() => {
    notification.style.opacity = "0";
    setTimeout(() => notification.remove(), 500);
  }, 5000);
}

async function sendRequest(endpoint, method = "POST", body = null) {
  try {
    const options = { method };
    if (body) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(endpoint, options);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Network error: ${response.status} - ${errorText}`);
    }
    const contentType = response.headers.get("content-type");
    return contentType && contentType.includes("application/json")
      ? await response.json()
      : {};
  } catch (error) {
    console.error(`Request failed for ${endpoint}:`, error);
    showNotification(`Error: ${error.message}`, "error");
    throw error;
  }
}

async function toggleAI(ai) {
  const statusSpan = document.getElementById(`${ai}-status`);
  const isOn = statusSpan.textContent === "On";
  const action = isOn ? "stop" : "start";
  await sendRequest(`/${action}_${ai}`);
  showNotification(`${ai.toUpperCase()} ${action} request sent`, "info");
}

async function startAll() {
  await sendRequest("/start_all");
  showNotification("Start All request sent", "info");
}

async function stopAll() {
  await sendRequest("/stop_all");
  showNotification("Stop All request sent", "info");
}

async function resetSystem() {
  if (
    confirm(
      "Reset system? This will clear queues, logs, and restart AI processes."
    )
  ) {
    await sendRequest("/clear", "POST");
    await sendRequest("/start_all", "POST");
    showNotification("System reset requested", "info");
    logContent.innerHTML = "<p><em>System reset requested...</em></p>";
    updateQueues({ executor: [], tester: [], documenter: [] });
    updateStatsFromSubtasks({});
    console.log("System reset completed");
  }
}

async function clearLogs() {
  if (logContent) {
    logContent.innerHTML = "";
    showNotification("Logs cleared", "info");
    console.log("Logs cleared locally");
  }
}

async function saveConfig() {
  const configData = {
    target: document.getElementById("target")?.value,
    ai1_prompt: document.getElementById("ai1-prompt")?.value,
    ai2_prompts: [
      document.getElementById("ai2-0-prompt")?.value || "",
      document.getElementById("ai2-1-prompt")?.value || "",
      document.getElementById("ai2-2-prompt")?.value || "",
    ],
    ai3_prompt: document.getElementById("ai3-prompt")?.value,
  };
  console.log("Saving configuration:", configData);
  await sendRequest("/update_config", "POST", configData);
  showNotification("Configuration saved", "success");
}

// Ініціалізація
document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM fully loaded");
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
    // Start: Add new stat elements
    pending: document.getElementById("pending-tasks"),
    processing: document.getElementById("processing-tasks"),
    failed: document.getElementById("failed-tasks"),
    // End: Add new stat elements
  };

  const savedTheme = localStorage.getItem("theme") || "dark";
  setTheme(savedTheme);
  connectWebSocket();
  updateQueues({ executor: [], tester: [], documenter: [] });
  updateStatsFromSubtasks({});
  console.log("Initialization complete");
});

// filepath: /workspaces/vscode-remote-try-python/static/script.js
let taskChart, progressChart, gitChart, editor, statusPieChart;
let ws;
const reconnectInterval = 5000;
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;

let logContent;
let aiButtons = {};
let queueLists = {};
let queueCounts = {};
let statElements = {};
let subtask_status = {};

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

function connectWebSocket() {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
  console.log(`Connecting to WebSocket: ${wsUrl}`);
  if (logContent)
    logContent.innerHTML += `<p><em>Connecting to WebSocket: ${wsUrl}</em></p>`;

  ws = new WebSocket(wsUrl);

  ws.onopen = function () {
    console.log("WebSocket connection established");
    if (logContent)
      logContent.innerHTML +=
        "<p><em>WebSocket connection established</em></p>";
    showNotification("Connected to server", "success");
    reconnectAttempts = 0;
    ws.send(JSON.stringify({ action: "get_full_status" }));
  };

  ws.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      console.log("Received WebSocket data:", data);

      switch (data.type) {
        case "full_status_update":
          updateFullUI(data);
          break;
        case "status_update":
          if (data.ai_status) updateAllButtonStates(data.ai_status);
          break;
        case "log_update":
          if (data.log_line && logContent) {
            const logEntry = document.createElement("p");
            logEntry.textContent = data.log_line;
            if (logContent.innerHTML.includes("Connecting to server..."))
              logContent.innerHTML = "";
            logContent.appendChild(logEntry);
            logContent.scrollTop = logContent.scrollHeight;
          }
          break;
        case "specific_update":
          console.log("Specific update:", data);
          if (data.queues) updateQueues(data.queues);
          if (data.subtasks) {
            Object.assign(subtask_status, data.subtasks);
            updateStatsFromSubtasks(subtask_status);
          }
          if (data.structure) updateFileStructure(data.structure);
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
        logContent.innerHTML += `<p><em><strong style="color:red;">Error: ${e}</strong></em></p>`;
    }
  };

  ws.onerror = function (event) {
    console.error("WebSocket error:", event);
    if (logContent)
      logContent.innerHTML +=
        '<p><em><strong style="color:red;">WebSocket error</strong></em></p>';
    showNotification("WebSocket error", "error");
  };

  ws.onclose = function (event) {
    console.log("WebSocket closed:", event.code, event.reason);
    if (logContent)
      logContent.innerHTML += `<p><em>Reconnecting... (${
        reconnectAttempts + 1
      }/${maxReconnectAttempts})</em></p>`;
    showNotification("Disconnected. Reconnecting...", "warning");
    reconnectAttempts++;
    if (reconnectAttempts < maxReconnectAttempts) {
      setTimeout(connectWebSocket, reconnectInterval);
    } else {
      console.error("Max reconnection attempts reached");
      if (logContent)
        logContent.innerHTML += `<p><em><strong style="color:red;">Failed to reconnect</strong></em></p>`;
      showNotification("Failed to reconnect", "error");
    }
  };
}

function updateFullUI(data) {
  console.log("Updating UI with full data:", data);
  if (data.ai_status) updateAllButtonStates(data.ai_status);
  if (data.queues) updateQueues(data.queues);
  if (data.subtasks) {
    Object.assign(subtask_status, data.subtasks);
    updateStatsFromSubtasks(subtask_status);
  }
  if (data.structure) updateFileStructure(data.structure);
  updateCharts(data);
}

function updateStatsFromSubtasks(subtasks) {
  const total = Object.keys(subtasks).length;
  const completed = Object.values(subtasks).filter((s) =>
    ["accepted", "completed", "code_received", "tested"].includes(s)
  ).length;
  const efficiency = total > 0 ? ((completed / total) * 100).toFixed(1) : 0;
  console.log(
    `Stats - Total: ${total}, Completed: ${completed}, Efficiency: ${efficiency}%`
  );

  if (statElements.total) statElements.total.textContent = total;
  if (statElements.completed) statElements.completed.textContent = completed;
  if (statElements.efficiency)
    statElements.efficiency.textContent = `${efficiency}%`;
}

function updateQueues(queuesData) {
  console.log("Updating queues:", queuesData);
  ["executor", "tester", "documenter"].forEach((role) => {
    const ul = queueLists[role];
    const countSpan = queueCounts[role];
    if (!ul || !countSpan) return;

    ul.innerHTML = "";
    const tasks = queuesData[role] || [];
    countSpan.textContent = tasks.length;

    tasks.forEach((task) => {
      if (!task || !task.id || !task.text) {
        console.warn("Invalid task:", task);
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
      return "?";
  }
}

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
              text: "Task Statuses",
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
  }
}

function getChartFontColor() {
  return window
    .getComputedStyle(document.body)
    .getPropertyValue("--text-color")
    .trim();
}

function updateFileStructure(structureData) {
  console.log("Updating file structure:", structureData);
  const fileStructureDiv = document.getElementById("file-structure");
  if (!fileStructureDiv) return;

  fileStructureDiv.innerHTML = "";
  if (!structureData || Object.keys(structureData).length === 0) {
    fileStructureDiv.innerHTML =
      "<p><em>No project structure available</em></p>";
    return;
  }

  const rootUl = document.createElement("ul");
  fileStructureDiv.appendChild(rootUl);

  function renderNode(node, parentUl, currentPath = "") {
    const entries = Object.entries(node).sort(
      ([keyA, valueA], [keyB, valueB]) => {
        const isDirA = typeof valueA === "object" && valueA !== null;
        const isDirB = typeof valueB === "object" && valueB !== null;
        return isDirA === isDirB ? keyA.localeCompare(keyB) : isDirA ? -1 : 1;
      }
    );

    for (const [key, value] of entries) {
      const li = document.createElement("li");
      parentUl.appendChild(li);
      const isDirectory = typeof value === "object" && value !== null;
      const itemPath = currentPath ? `${currentPath}/${key}` : key;

      if (isDirectory) {
        li.innerHTML = `<span class="folder"><i class="fas fa-folder"></i> ${key}</span>`;
        li.classList.add("folder-item");
        const subUl = document.createElement("ul");
        li.appendChild(subUl);
        renderNode(value, subUl, itemPath);
        li.querySelector(".folder").addEventListener("click", (e) => {
          li.classList.toggle("expanded");
          e.stopPropagation();
        });
      } else {
        li.innerHTML = `<span class="file" data-path="${itemPath}"><i class="fas ${getFileIcon(
          key
        )}"></i> ${key}</span>`;
        li.querySelector(".file").addEventListener("click", (e) => {
          loadFileContent(e.currentTarget.getAttribute("data-path"));
          e.stopPropagation();
        });
      }
    }
  }

  renderNode(structureData, rootUl);
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
  console.log("Loading file:", path);
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
    } else {
      const errorText = await response.text();
      editor.setValue(
        `// Failed to load ${path}\n// Status: ${response.status}\n// ${errorText}`
      );
      showNotification(`Failed to load ${path} (${response.status})`, "error");
    }
  } catch (error) {
    console.error("Error loading file:", error);
    editor.setValue(`// Error loading ${path}\n// ${error.message}`);
    showNotification(`Error: ${error.message}`, "error");
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
    if (!response.ok) throw new Error(`Network error: ${response.status}`);
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
  }
}

async function clearLogs() {
  if (logContent) {
    logContent.innerHTML = "";
    showNotification("Logs cleared", "info");
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
  await sendRequest("/update_config", "POST", configData);
  showNotification("Configuration saved", "success");
}

document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM loaded");
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

  const savedTheme = localStorage.getItem("theme") || "dark";
  setTheme(savedTheme);
  connectWebSocket();
  updateQueues({ executor: [], tester: [], documenter: [] });
  updateStatsFromSubtasks({});
});

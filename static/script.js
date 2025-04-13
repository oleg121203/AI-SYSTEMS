// Глобальні елементи DOM
let taskChart, progressChart, gitChart, statusPieChart;
let ws;
const reconnectInterval = 5000;
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;
let editor;
let logContent;
let aiButtons = {};
let queueLists = {};
let queueCounts = {};
let statElements = {};
let subtask_status = {};
let clearProjectBtn;
let allAIsOff = true;

// Базові функції для API і WebSocket
async function sendRequest(endpoint, method = "POST", data = null) {
  try {
    const options = {
      method: method,
      headers: {
        "Content-Type": "application/json",
      },
    };

    if (data) {
      options.body = JSON.stringify(data);
    }

    const response = await fetch(endpoint, options);
    if (!response.ok) {
      throw new Error(`Server responded with status: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error(`Error sending request to ${endpoint}:`, error);
    showNotification(`Error: ${error.message}`, "error");
    return null;
  }
}

function showNotification(message, type = "info") {
  console.log(`[${type.toUpperCase()}] ${message}`);

  // Создаем элемент уведомления
  const notification = document.createElement("div");
  notification.className = `notification ${type}`;
  notification.textContent = message;

  document.body.appendChild(notification);

  // Показываем уведомление с анимацией
  setTimeout(() => {
    notification.classList.add("show");

    setTimeout(() => {
      notification.classList.remove("show");
      setTimeout(() => notification.remove(), 300);
    }, 3000);
  }, 10);
}

function addLogLine(line) {
  if (!logContent) return;

  const logLine = document.createElement("p");
  logLine.textContent = line;

  // Ограничиваем количество строк лога
  while (logContent.childElementCount > 500) {
    logContent.removeChild(logContent.firstChild);
  }

  logContent.appendChild(logLine);
  logContent.scrollTop = logContent.scrollHeight;
}

// Функції для роботи з WebSocket
function connectWebSocket() {
  if (ws && ws.readyState !== WebSocket.CLOSED) {
    console.log("WebSocket already connected or connecting");
    return;
  }

  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/ws`;
  console.log(`Attempting to connect to WebSocket: ${wsUrl}`);

  if (logContent) {
    logContent.innerHTML = `<p><em>Attempting to connect to WebSocket: ${wsUrl}</em></p>`;
  }

  try {
    ws = new WebSocket(wsUrl);
    setupWebSocketHandlers();
  } catch (error) {
    console.error("Error creating WebSocket:", error);
    handleWebSocketError(error);
  }
}

function setupWebSocketHandlers() {
  ws.onopen = () => {
    console.log("WebSocket connection established");
    showNotification("Connected to server", "success");
    if (logContent) {
      logContent.innerHTML = "<p><em>WebSocket connection established</em></p>";
    }
    reconnectAttempts = 0;
    // Запрашиваем начальное состояние
    ws.send(JSON.stringify({ action: "get_full_status" }));
  };

  ws.onmessage = (event) => {
    try {
      console.log("Raw WebSocket message:", event.data);
      const data = JSON.parse(event.data);
      console.log("Parsed WebSocket data:", data);

      if (!data || typeof data !== "object") {
        throw new Error("Invalid message format");
      }

      switch (data.type) {
        case "full_status_update":
          handleFullStatusUpdate(data);
          break;
        case "status_update":
          if (data.ai_status) updateAllButtonStates(data.ai_status);
          break;
        case "specific_update":
          handleSpecificUpdate(data);
          break;
        case "error":
          console.error("Server error message:", data.message);
          showNotification(`Server error: ${data.message}`, "error");
          break;
        case "ping":
        case "pong":
          console.log(`${data.type} received`);
          break;
        default:
          console.warn("Unhandled message type:", data.type, data);
      }
    } catch (error) {
      console.error(
        "Error processing WebSocket message:",
        error,
        "Raw data:",
        event.data
      );
      if (logContent) {
        logContent.innerHTML += `<p><em><strong style="color:red;">Error processing message: ${error}</strong></em></p>`;
      }
    }
  };

  ws.onerror = (event) => {
    console.error("WebSocket error occurred:", event);
    if (logContent) {
      logContent.innerHTML += `<p><em><strong style="color:red;">WebSocket error</strong></em></p>`;
    }
    showNotification("WebSocket error", "error");
  };

  ws.onclose = (event) => {
    console.log("WebSocket closed:", event.code, event.reason);
    if (logContent) {
      logContent.innerHTML += `<p><em>WebSocket closed. Reconnecting... (${
        reconnectAttempts + 1
      }/${maxReconnectAttempts})</em></p>`;
    }
    showNotification("Disconnected. Reconnecting...", "warning");
    reconnectAttempts++;
    if (reconnectAttempts < maxReconnectAttempts) {
      setTimeout(connectWebSocket, reconnectInterval);
    } else {
      console.error("Max reconnection attempts reached");
      if (logContent) {
        logContent.innerHTML += `<p><em><strong style="color:red;">Failed to reconnect after ${maxReconnectAttempts} attempts</strong></em></p>`;
      }
      showNotification("Failed to reconnect", "error");
    }
  };
}

function handleFullStatusUpdate(data) {
  console.log("Processing full status update:", data);
  if (data.ai_status) {
    updateAllButtonStates(data.ai_status);
    checkAllAIsStatus(data.ai_status);
  }
  if (data.queues) updateQueues(data.queues);
  if (data.subtasks) {
    Object.assign(subtask_status, data.subtasks);
    updateStatsFromSubtasks(subtask_status);
  }

  // Додаткове логування для відстеження структури файлів
  if (data.structure) {
    console.log(
      "Full status update contains structure data:",
      Object.keys(data.structure).length ? "Yes" : "No (empty object)",
      "Keys:",
      Object.keys(data.structure)
    );
    updateFileStructure(data.structure);
  } else {
    console.warn("Full status update does not contain structure data");
  }

  updateCharts(data);
}

function handleSpecificUpdate(data) {
  console.log("Processing specific update:", data);

  if (data.ai_status) updateAllButtonStates(data.ai_status);

  if (data.queues) updateQueues(data.queues);

  if (data.subtasks) {
    Object.assign(subtask_status, data.subtasks);
    updateStatsFromSubtasks(subtask_status);
    updateQueueItemStatuses(subtask_status);
  }

  if (data.structure) updateFileStructure(data.structure);

  if (data.log_line && logContent) {
    addLogLine(data.log_line);
  }

  // Обновляем графики если есть данные
  const chartData = {};
  if (data.processed_over_time)
    chartData.processed_over_time = data.processed_over_time;
  if (data.task_status_distribution)
    chartData.task_status_distribution = data.task_status_distribution;
  if (data.queues) chartData.queues = data.queues;
  if (Object.keys(chartData).length > 0) updateCharts(chartData);
}

// Функції оновлення інтерфейсу
function updateAllButtonStates(aiStatusData) {
  console.log("Updating button states:", aiStatusData);

  let allOff = true;

  for (const [aiId, isRunning] of Object.entries(aiStatusData)) {
    const button = aiButtons[aiId];
    const statusSpan = document.getElementById(`${aiId}-status`);
    if (button && statusSpan) {
      statusSpan.textContent = isRunning ? "On" : "Off";
      button.classList.toggle("on", isRunning);
      button.classList.toggle("off", !isRunning);

      if (isRunning) {
        allOff = false;
      }
    } else {
      console.warn(`Button or status span not found for AI: ${aiId}`);
    }
  }

  allAIsOff = allOff;

  // Оновлюємо кнопку очистки проекту
  if (clearProjectBtn) {
    clearProjectBtn.disabled = !allOff;
    clearProjectBtn.title = allOff
      ? "Очистити всі дані проекту (репозиторій, логи, кеш)"
      : "Зупиніть всі процеси AI перед очищенням проекту";
  }
}

function checkAllAIsStatus(aiStatusData) {
  let allOff = true;
  for (const [_, isRunning] of Object.entries(aiStatusData)) {
    if (isRunning) {
      allOff = false;
      break;
    }
  }

  allAIsOff = allOff;

  if (clearProjectBtn) {
    clearProjectBtn.disabled = !allAIsOff;
  }
}

function updateStatsFromSubtasks(subtasks) {
  const total = Object.keys(subtasks).length;
  const completed = Object.values(subtasks).filter((s) =>
    ["accepted", "completed", "code_received", "tested"].includes(s)
  ).length;
  const pending = Object.values(subtasks).filter((s) => s === "pending").length;
  const processing = Object.values(subtasks).filter(
    (s) => s === "processing"
  ).length;
  const failed = Object.values(subtasks).filter(
    (s) => typeof s === "string" && s.includes("failed")
  ).length;
  const efficiency = total > 0 ? ((completed / total) * 100).toFixed(1) : 0;

  console.log(
    `Stats - Total: ${total}, Completed: ${completed}, Pending: ${pending}, Processing: ${processing}, Failed: ${failed}, Efficiency: ${efficiency}%`
  );

  // Оновлюємо елементи DOM з перевірками
  if (statElements.total) statElements.total.textContent = total;
  if (statElements.completed) statElements.completed.textContent = completed;
  if (statElements.efficiency)
    statElements.efficiency.textContent = `${efficiency}%`;
  if (statElements.pending) statElements.pending.textContent = pending;
  if (statElements.processing) statElements.processing.textContent = processing;
  if (statElements.failed) statElements.failed.textContent = failed;

  // Оновлюємо кругову діаграму
  updateCharts({
    task_status_distribution: {
      pending,
      processing,
      completed,
      failed,
      other: total - pending - processing - completed - failed,
    },
  });
}

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

    tasks.forEach((task) => {
      if (!task || !task.id || !task.text) {
        console.warn("Invalid task object:", task);
        return;
      }

      const li = document.createElement("li");
      const status = task.status || subtask_status[task.id] || "unknown";

      li.setAttribute("data-task-id", task.id);
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
      taskIdSpan.title = `Full ID: ${task.id}`;

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

  updateQueueItemStatuses(subtask_status);
}

function updateQueueItemStatuses(subtasks) {
  document.querySelectorAll(".queue-item li").forEach((item) => {
    const fullId = item.getAttribute("data-task-id");
    if (!fullId) return;

    if (subtasks[fullId]) {
      const newStatus = subtasks[fullId];
      const statusIcon = item.querySelector(".status-icon");

      if (statusIcon) statusIcon.innerHTML = getStatusIcon(newStatus);
      item.setAttribute("data-status", newStatus);
    }
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

// Функції для графіків
function updateCharts(data) {
  // Ініціалізація і оновлення графіка задач
  if (!taskChart) {
    initTaskChart();
  }
  if (taskChart && data.queues) {
    taskChart.data.datasets[0].data = [
      (data.queues.executor || []).length,
      (data.queues.tester || []).length,
      (data.queues.documenter || []).length,
    ];
    taskChart.update();
  }

  // Ініціалізація і оновлення графіка прогресу
  if (
    !progressChart &&
    data.progress &&
    data.progress.stages &&
    data.progress.values
  ) {
    initProgressChart(data.progress);
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

  // Ініціалізація і оновлення графіка Git-активності
  if (!gitChart && data.processed_over_time) {
    initGitChart(data.processed_over_time);
  }
  if (gitChart && data.processed_over_time) {
    gitChart.data.labels = data.processed_over_time.map((_, i) => `T${i + 1}`);
    gitChart.data.datasets[0].data = data.processed_over_time;
    gitChart.update();
  }

  // Ініціалізація і оновлення кругової діаграми статусів
  if (!statusPieChart) {
    initStatusPieChart();
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

function initTaskChart() {
  const ctx = document.getElementById("taskChart")?.getContext("2d");
  if (!ctx) return;

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
}

function initProgressChart(progress) {
  const ctx = document.getElementById("progressChart")?.getContext("2d");
  if (!ctx) return;

  progressChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: progress.stages,
      datasets: [
        {
          label: "Project Progress (%)",
          data: progress.values,
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
}

function initGitChart(processed_over_time) {
  const ctx = document.getElementById("gitChart")?.getContext("2d");
  if (!ctx) return;

  gitChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: processed_over_time.map((_, i) => `T${i + 1}`),
      datasets: [
        {
          label: "Commits Over Time",
          data: processed_over_time,
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
}

function initStatusPieChart() {
  const ctx = document.getElementById("statusPieChart")?.getContext("2d");
  if (!ctx) return;

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
}

function getChartFontColor() {
  return (
    window
      .getComputedStyle(document.body)
      .getPropertyValue("--text-color")
      .trim() || "#333"
  );
}

// Функції для структури файлів
function updateFileStructure(structureData) {
  console.log("Received structure data:", structureData);

  const fileStructureDiv = document.getElementById("file-structure");
  if (!fileStructureDiv) {
    console.error("File structure div (#file-structure) not found in DOM!");
    return;
  }

  fileStructureDiv.innerHTML = "";

  if (!structureData || typeof structureData !== "object") {
    console.error("Invalid structure data type:", typeof structureData);
    fileStructureDiv.innerHTML =
      "<p><em>No project structure available or data is invalid</em></p>";
    return;
  }

  // Перевірка, чи є структура вкладеною - можливо, дані приходять як { structure: { ... } }
  if (structureData.structure && typeof structureData.structure === "object") {
    console.log("Found nested structure property, using it instead");
    structureData = structureData.structure;
  }

  if (Object.keys(structureData).length === 0) {
    console.warn("Structure data is an empty object");
    fileStructureDiv.innerHTML =
      "<p><em>No project structure available (empty object)</em></p>";
    return;
  }

  console.log(
    "Creating root UL for file structure with",
    Object.keys(structureData).length,
    "top-level items"
  );
  const rootUl = document.createElement("ul");
  fileStructureDiv.appendChild(rootUl);

  try {
    renderNode(structureData, rootUl);
  } catch (error) {
    console.error("Error during file structure rendering:", error);
    fileStructureDiv.innerHTML = `<p><em>Error rendering file structure: ${error.message}</em></p>`;
  }
}

function renderNode(node, parentUl, currentPath = "") {
  console.log("Rendering node:", node, "Path:", currentPath);

  if (!node || typeof node !== "object") {
    console.warn("Invalid node to render:", node);
    return;
  }

  const entries = Object.entries(node).sort(
    ([keyA, valueA], [keyB, valueB]) => {
      const isDirA = typeof valueA === "object" && valueA !== null;
      const isDirB = typeof valueB === "object" && valueB !== null;
      // Directories first, then files alphabetically
      if (isDirA !== isDirB) return isDirA ? -1 : 1;
      return keyA.localeCompare(keyB);
    }
  );

  console.log("Sorted entries to render:", entries.length);

  for (const [key, value] of entries) {
    const li = document.createElement("li");
    const isDirectory = typeof value === "object" && value !== null;
    const itemPath = currentPath ? `${currentPath}/${key}` : key;

    if (isDirectory) {
      li.innerHTML = `<span class="folder"><i class="fas fa-folder"></i> ${key}</span>`;
      li.classList.add("folder-item");
      const subUl = document.createElement("ul");
      li.appendChild(subUl);
      renderNode(value, subUl, itemPath);

      const folderSpan = li.querySelector(".folder");
      if (folderSpan) {
        folderSpan.addEventListener("click", (e) => {
          li.classList.toggle("expanded");
          e.stopPropagation();
        });
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
      }
    }
    parentUl.appendChild(li);
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

// Функції для роботи з темами
function getEditorTheme(appTheme) {
  switch (appTheme) {
    case "dark":
    case "winter":
    case "autumn":
      return "vs-dark";
    case "spring":
    case "summer":
    default:
      return "vs";
  }
}

function setTheme(themeName) {
  console.log(`Setting theme to: ${themeName}`);
  document.documentElement.setAttribute("data-theme", themeName);
  document.body.setAttribute("data-theme", themeName);
  localStorage.setItem("theme", themeName);

  // Обновляем Monaco Editor
  if (editor) {
    const editorTheme = getEditorTheme(themeName);
    monaco.editor.setTheme(editorTheme);
  }

  // Обновляем цвета графиков
  updateChartsTheme();
}

function updateChartsTheme() {
  const theme = localStorage.getItem("theme") || "dark";
  const isDark = theme === "dark" || theme === "winter" || theme === "autumn";

  const chartOptions = {
    scales: {
      x: { ticks: { color: isDark ? "#fff" : "#666" } },
      y: { ticks: { color: isDark ? "#fff" : "#666" } },
    },
    plugins: {
      legend: { labels: { color: isDark ? "#fff" : "#666" } },
      title: { color: isDark ? "#fff" : "#666" },
    },
  };

  [taskChart, progressChart, gitChart, statusPieChart].forEach((chart) => {
    if (!chart) return;

    try {
      if (chart.options.scales?.x?.ticks) {
        chart.options.scales.x.ticks.color = chartOptions.scales.x.ticks.color;
      }

      if (chart.options.scales?.y?.ticks) {
        chart.options.scales.y.ticks.color = chartOptions.scales.y.ticks.color;
      }

      if (chart.options.plugins?.legend?.labels) {
        chart.options.plugins.legend.labels.color =
          chartOptions.plugins.legend.labels.color;
      }

      if (chart.options.plugins?.title) {
        chart.options.plugins.title.color = chartOptions.plugins.title.color;
      }

      chart.update();
    } catch (e) {
      console.error("Error updating chart colors:", e);
    }
  });
}

// Функції дій користувача
async function toggleAI(ai) {
  const statusSpan = document.getElementById(`${ai}-status`);
  const isOn = statusSpan.textContent === "On";
  const action = isOn ? "stop" : "start";

  try {
    await sendRequest(`/${action}_${ai}`);
    showNotification(`${ai.toUpperCase()} ${action} request sent`, "info");
  } catch (error) {
    showNotification(`Error toggling ${ai}: ${error.message}`, "error");
  }
}

async function startAll() {
  try {
    await sendRequest("/start_all");
    showNotification("Start All request sent", "info");
  } catch (error) {
    showNotification(`Error starting all AI: ${error.message}`, "error");
  }
}

async function stopAll() {
  try {
    await sendRequest("/stop_all");
    showNotification("Stop All request sent", "info");
  } catch (error) {
    showNotification(`Error stopping all AI: ${error.message}`, "error");
  }
}

async function resetSystem() {
  if (
    confirm(
      "Reset system? This will clear queues, logs, and restart AI processes."
    )
  ) {
    try {
      await sendRequest("/clear", "POST");
      await sendRequest("/start_all");

      showNotification("System reset requested", "info");
      if (logContent)
        logContent.innerHTML = "<p><em>System reset requested...</em></p>";

      // Очищаем локальный UI
      updateQueues({ executor: [], tester: [], documenter: [] });
      updateStatsFromSubtasks({});
    } catch (error) {
      showNotification(`Error resetting system: ${error.message}`, "error");
    }
  }
}

async function clearProject() {
  if (!allAIsOff) {
    showNotification("Спочатку зупиніть всі процеси AI", "warning");
    return;
  }

  if (
    confirm(
      "Це повністю видалить ВСІ дані проекту, включаючи репозиторій, комміти, логи та кеш. Продовжити?"
    )
  ) {
    try {
      clearProjectBtn.disabled = true;
      clearProjectBtn.textContent = "Очищення...";

      showNotification("Початок очищення проекту...", "info");
      const response = await fetch("/clear_project", { method: "POST" });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Помилка очищення проекту: ${response.status} - ${errorText}`
        );
      }

      const result = await response.json();
      showNotification(`Проект очищено: ${result.message}`, "success");

      // Очищаем локальный UI
      if (logContent)
        logContent.innerHTML =
          "<p><em>Проект очищено. Система готова до нового старту.</em></p>";
      updateQueues({ executor: [], tester: [], documenter: [] });
      updateStatsFromSubtasks({});
      updateFileStructure({});
    } catch (error) {
      showNotification(`Помилка: ${error.message}`, "error");
    } finally {
      clearProjectBtn.disabled = false;
      clearProjectBtn.textContent = "Очистити проект";
    }
  }
}

async function saveConfig() {
  try {
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
  } catch (error) {
    showNotification(`Error saving config: ${error.message}`, "error");
  }
}

// Налаштування Monaco Editor
require.config({
  paths: { vs: "https://unpkg.com/monaco-editor@0.34.0/min/vs" },
});

require(["vs/editor/editor.main"], function () {
  const theme = localStorage.getItem("theme") || "dark";
  const editorTheme = getEditorTheme(theme);

  editor = monaco.editor.create(document.getElementById("editor"), {
    value: "// Select a file from the structure view",
    language: "plaintext",
    theme: editorTheme,
    automaticLayout: true,
    minimap: { enabled: true },
    fontSize: 14,
    lineNumbers: "on",
    scrollBeyondLastLine: false,
    wordWrap: "on",
  });

  console.log("Monaco Editor initialized");
});

// Ініціалізація при завантаженні сторінки
document.addEventListener("DOMContentLoaded", () => {
  console.log("DOM fully loaded");

  // Ініціалізація DOM елементів
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
    pending: document.getElementById("pending-tasks"),
    processing: document.getElementById("processing-tasks"),
    failed: document.getElementById("failed-tasks"),
  };

  clearProjectBtn = document.getElementById("clear-project-button");

  // Налаштовуємо кнопки теми
  document.querySelectorAll(".theme-switcher button").forEach((button) => {
    button.addEventListener("click", () => {
      const theme = button.getAttribute("data-theme");
      if (theme) setTheme(theme);
    });
  });

  // Завантажуємо тему
  const savedTheme = localStorage.getItem("theme") || "dark";

  // Підключаємося до WebSocket
  connectWebSocket();

  // Ініціалізуємо UI з порожніми даними
  updateQueues({ executor: [], tester: [], documenter: [] });
  updateStatsFromSubtasks({});
  updateFileStructure({});

  // Встановлюємо тему
  setTheme(savedTheme);

  // Додати функцію для розгортання опису
  document.querySelectorAll(".queue-item li").forEach((item) => {
    item.addEventListener("click", () => {
      item.classList.toggle("expanded"); // Додає/знімає клас expanded
    });
  });

  console.log("Initialization complete");
});

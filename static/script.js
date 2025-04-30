let taskChart, progressChart, gitChart, editor, statusPieChart;
let ws;
const reconnectInterval = 10000; // Reconnect interval 5 seconds
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;
const MAX_LOG_LINES = 30; // Maximum number of log lines to keep
let actualTotalTasks = 0; // Add global variable for actual total tasks

// --- Global DOM Elements (cache them, assign in DOMContentLoaded) ---
let logContent;
let taskTableBody;
let aiButtons = {};
let queueLists = {};
let queueCounts = {};
let statElements = {};
let subtask_status = {}; // Add global status object

// Remove immediate assignment:
// const logsElement = document.getElementById('logs'); // Assign inside DOMContentLoaded
// const taskTableBody = document.getElementById('taskTable').querySelector('tbody'); // Assign inside DOMContentLoaded
// const wsUrl = `ws://${window.location.host}/ws`; // Define inside connectWebSocket
// let socket; // Not used globally, ws is used

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

// --- WebSocket Message Handling ---

function handleWebSocketMessage(event) {
  try {
    const data = JSON.parse(event.data);
    console.log("WebSocket received data:", data); // Log all received data

    // Prioritize specific types first
    if (data.type) {
      routeMessageByType(data);
    } else {
      // Handle messages without a 'type' field
      handleTypeLessMessage(data);
    }
  } catch (e) {
    console.error(
      "Error parsing WebSocket message or updating UI:",
      e,
      "Raw data:",
      event.data
    );
    logErrorToUI(`Error parsing WebSocket message: ${e}`);
  }
}

function routeMessageByType(data) {
  switch (data.type) {
    case "full_status_update":
      console.log("Processing full_status_update");
      updateFullUI(data);
      break;
    case "status_update":
      if (data.ai_status) {
        console.log("Processing status_update (AI status only)");
        updateAllButtonStates(data.ai_status);
      }
      break;
    case "log_update":
      handleLogUpdate(data.log_line);
      break;
    case "structure_update":
      if (data.structure) {
        updateFileStructure(data.structure);
      }
      break;
    case "queue_update":
      if (data.queues) {
        updateQueues(data.queues);
      }
      break;
    case "specific_update":
      handleSpecificUpdate(data);
      break;
    case "ping":
      console.log("Ping received");
      break;
    default:
      console.warn("Received unhandled message type:", data.type, data);
  }
}

function handleTypeLessMessage(data) {
  if (data.log_line && Object.keys(data).length === 1) {
    handleLogUpdate(data.log_line);
  } else if (data.subtasks && Object.keys(data).length === 1) {
    handleSubtaskUpdate(data.subtasks);
  } else if (data.queues && Object.keys(data).length === 1) {
    handleQueueOnlyUpdate(data.queues);
  } else if (
    data.progress_data ||
    data.git_activity ||
    data.task_status_distribution
  ) {
    handleChartUpdate(data);
  } else {
    // Only warn if it's an unknown structure without type
    if (
      !data.log_line &&
      !data.subtasks /* Add other known type-less fields */
    ) {
      console.warn("Received unhandled typeless message structure:", data);
    }
  }
}

function handleLogUpdate(logLine) {
  if (logLine && logContent) {
    const logEntry = document.createElement("p");
    logEntry.textContent = logLine;
    if (logContent.innerHTML.includes("Connecting to server...")) {
      logContent.innerHTML = "";
    }
    logContent.appendChild(logEntry);
    while (logContent.childElementCount > MAX_LOG_LINES) {
      if (logContent.firstChild) {
        logContent.removeChild(logContent.firstChild);
      }
    }
    logContent.scrollTop = logContent.scrollHeight;
  }
}

function handleSubtaskUpdate(subtasksData) {
  console.log("Processing subtasks-only update:", subtasksData);
  Object.assign(subtask_status, subtasksData); // Merge updates
  updateStats(subtask_status, null); // Pass null for queues
  updateCharts({
    task_status_distribution: calculateStatusDistribution(subtask_status),
  });
}

function handleQueueOnlyUpdate(queuesData) {
  console.log("Processing queues-only update:", queuesData);
  updateQueues(queuesData);
  updateCharts({ queues: queuesData }); // Update task distribution chart
}

function handleChartUpdate(chartData) {
  console.log("Processing chart updates (direct or typeless):", chartData);
  updateCharts(chartData);
}

function handleSpecificUpdate(data) {
  console.log("Processing specific_update:", data);
  // Wrap in block scope to allow lexical declarations
  {
    let needsChartUpdate = false;

    if (data.queues) {
      updateQueues(data.queues);
      needsChartUpdate = true;
    }
    if (data.subtasks) {
      Object.assign(subtask_status, data.subtasks);
      updateStats(subtask_status, data.queues);
      needsChartUpdate = true;
    }
    if (data.structure) {
      updateFileStructure(data.structure);
    }

    if (
      needsChartUpdate ||
      data.progress_data ||
      data.git_activity ||
      data.task_status_distribution
    ) {
      const chartUpdateData = {
        queues: data.queues,
        task_status_distribution:
          data.task_status_distribution ||
          (needsChartUpdate
            ? calculateStatusDistribution(subtask_status)
            : undefined),
        progress_data: data.progress_data,
        git_activity: data.git_activity,
      };
      updateCharts(chartUpdateData);
    }

    if (data.log_line) {
      handleLogUpdate(data.log_line);
    }
  }
}

function logErrorToUI(message) {
  if (logContent) {
    logContent.innerHTML += `<p><em><strong style="color:red;">${message}</strong></em></p>`;
  }
}

// --- WebSocket Connection ---
function connectWebSocket() {
  // Define wsUrl inside the function scope
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

    // Запит на оновлення графіків
    ws.send(JSON.stringify({ action: "get_chart_updates" }));
  };

  // Use the new handler function
  ws.onmessage = handleWebSocketMessage;

  ws.onerror = function (event) {
    console.error("WebSocket error observed:", event);
    logErrorToUI("WebSocket error.");
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
  // Update actual total tasks if provided
  if (data.actual_total_tasks !== undefined) {
    actualTotalTasks = data.actual_total_tasks;
    console.log(
      `[Stats Update] Actual total tasks updated to: ${actualTotalTasks}`
    );
  }

  // Ensure queues are updated *before* stats if both are present
  if (data.queues) {
    updateQueues(data.queues);
  }
  // Update stats based on subtask statuses if available
  if (data.subtasks) {
    const receivedSubtasksCount = Object.keys(data.subtasks).length;
    const globalStatusCountBefore = Object.keys(subtask_status).length;
    console.log(
      `[Stats Update] Received ${receivedSubtasksCount} task statuses. Global count before merge: ${globalStatusCountBefore}`
    );

    Object.assign(subtask_status, data.subtasks); // Merge all statuses

    const globalStatusCountAfter = Object.keys(subtask_status).length;
    console.log(
      `[Stats Update] Global count after merge: ${globalStatusCountAfter}`
    );

    // Pass both subtask status and queue data (if available) for the new calculation
    // Use the updated global actualTotalTasks
    updateStats(subtask_status, data.queues);
  } else if (data.processed !== undefined && data.efficiency !== undefined) {
    // Fallback to legacy update if subtasks/actual_total_tasks not present
    updateStatsLegacy(data);
  } else {
    // If only subtasks are present, still update stats
    updateStats(subtask_status, null); // Pass null for queues if not available
  }

  console.log("Calling updateCharts from updateFullUI"); // Log chart update trigger
  updateCharts(data); // Pass the whole data object

  if (data.structure) {
    console.log("Calling updateFileStructure from updateFullUI"); // Log structure update trigger
    updateFileStructure(data.structure);
  } else {
    // console.warn("updateFullUI: No structure data received."); // Less noisy warning
  }
}

// Renamed function to reflect its purpose better
// Modify updateStats to use the global actualTotalTasks
function updateStats(current_subtask_statuses, current_queues_data) {
  // Calculate completed tasks from the status object
  const completed = Object.values(current_subtask_statuses).filter(
    (status) =>
      status === "accepted" ||
      status === "completed" ||
      status === "code_received" // Consider 'code_received' as completed for this count
  ).length;

  // Calculate tasks currently in queues
  let tasksInQueues = 0;
  if (current_queues_data) {
    tasksInQueues =
      (current_queues_data.executor || []).length +
      (current_queues_data.tester || []).length +
      (current_queues_data.documenter || []).length;
  } else {
    // Fallback: read counts from DOM if queue data not passed
    tasksInQueues =
      parseInt(queueCounts.executor?.textContent || "0", 10) +
      parseInt(queueCounts.tester?.textContent || "0", 10) +
      parseInt(queueCounts.documenter?.textContent || "0", 10);
  }

  // Total Tasks now uses the global actualTotalTasks
  const total =
    actualTotalTasks > 0
      ? actualTotalTasks
      : Object.keys(current_subtask_statuses).length; // Fallback if actualTotalTasks is 0
  const knownTasksCount = Object.keys(current_subtask_statuses).length; // Keep track of known tasks

  // Calculate efficiency based on the ACTUAL total number of tasks
  const efficiency = total > 0 ? ((completed / total) * 100).toFixed(1) : 0;

  console.log(
    `[Stats Update] Calculated - Completed: ${completed}, In Queues: ${tasksInQueues}, Total (Actual): ${total}, Known Statuses: ${knownTasksCount}, Efficiency: ${efficiency}%`
  );

  if (statElements.total) statElements.total.textContent = total; // Update total tasks display
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
  let queuesChanged = false; // Flag to check if queue data actually changed

  ["executor", "tester", "documenter"].forEach((role) => {
    const ul = queueLists[role];
    const countSpan = queueCounts[role];
    if (!ul || !countSpan) return; // Skip if elements not found

    const tasks = queuesData?.[role] || []; // Optional chaining
    const currentCount = parseInt(countSpan.textContent || "0", 10);

    // Check if the count or task list structure might change
    if (tasks.length !== currentCount || ul.children.length !== tasks.length) {
      queuesChanged = true;
      ul.innerHTML = ""; // Clear existing list only if needed
      countSpan.textContent = tasks.length; // Update count

      tasks.forEach((task) => {
        // Optional chaining for task properties
        if (!task?.id || !task?.text) {
          console.warn("Skipping invalid task object in queue:", task);
          return;
        }
        const li = document.createElement("li");
        const status = task.status || subtask_status[task.id] || "pending";
        li.setAttribute("data-status", status);

        // ... (rest of li creation remains the same)
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
    } else {
      // Optimization: If count is the same, just update statuses if needed
      Array.from(ul.children).forEach((li, index) => {
        const task = tasks[index];
        // Optional chaining
        if (!task?.id) return;
        const newStatus = task.status || subtask_status[task.id] || "pending";
        const currentStatus = li.getAttribute("data-status");
        if (newStatus !== currentStatus) {
          li.setAttribute("data-status", newStatus);
          const iconSpan = li.querySelector(".status-icon");
          if (iconSpan) iconSpan.innerHTML = getStatusIcon(newStatus);
          queuesChanged = true; // Mark as changed if status updated
        }
      });
    }
  });

  // Update stats using the new function, passing current queue data and global subtask status
  // It will use the global actualTotalTasks internally
  updateStats(subtask_status, queuesData);

  // Update the task distribution chart if it exists and queues changed
  if (taskChart && queuesChanged) {
    console.log("Updating taskChart data due to queue changes:", queuesData);
    taskChart.data.datasets[0].data = [
      (queuesData.executor || []).length,
      (queuesData.tester || []).length,
      (queuesData.documenter || []).length,
    ];
    // Ensure colors are correct for the current theme
    taskChart.options.scales.y.ticks.color = getChartFontColor();
    taskChart.options.scales.x.ticks.color = getChartFontColor();
    taskChart.options.plugins.legend.labels.color = getChartFontColor();
    taskChart.update(); // Explicitly update the chart visualization
  }
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

// --- Chart Initialization and Update Functions ---

function initializeCharts() {
  initializeTaskChart();
  initializeProgressChart();
  initializeGitChart();
  initializeStatusPieChart();
}

function updateCharts(data) {
  console.log("updateCharts called with data:", JSON.stringify(data, null, 2));

  // Initialize charts if they don't exist
  if (!taskChart || !progressChart || !gitChart || !statusPieChart) {
    initializeCharts();
  }

  let chartsUpdated = false;

  if (updateTaskChartData(data.queues)) chartsUpdated = true;
  if (updateProgressChartData(data.progress_data, data.git_activity))
    chartsUpdated = true;
  if (updateGitChartData(data.git_activity)) chartsUpdated = true;
  if (updateStatusPieChartData(data.task_status_distribution))
    chartsUpdated = true;

  if (chartsUpdated) {
    updateAllChartThemes(); // Apply theme colors
    console.log("[Chart Update] One or more charts updated visually.");
  } else {
    console.log(
      "[Chart Update] No chart data changed, skipping visual update."
    );
  }
}

function getBaseChartOptions() {
  const chartColor = getChartFontColor();
  return {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      y: {
        beginAtZero: true,
        grid: { color: `${chartColor}20` },
        ticks: {
          color: chartColor,
          callback: function (value) {
            const label =
              this.chart.config._config.data.datasets[0]?.label || "";
            return value + (label.includes("%") ? "%" : "");
          },
        },
      },
      x: {
        grid: { color: `${chartColor}20` },
        ticks: { color: chartColor },
      },
    },
    plugins: {
      legend: {
        labels: { color: chartColor, font: { size: 12 } },
      },
      title: { display: true, color: chartColor },
    },
    animation: { duration: 750, easing: "easeInOutCubic" },
  };
}

// --- Task Chart ---
function initializeTaskChart() {
  if (taskChart) return;
  const ctx = document.getElementById("taskChart")?.getContext("2d");
  if (ctx) {
    const baseOptions = getBaseChartOptions();
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
        ...baseOptions,
        plugins: {
          ...baseOptions.plugins,
          title: { ...baseOptions.plugins.title, text: "Tasks Distribution" },
        },
      },
    });
  }
}

function updateTaskChartData(queuesData) {
  if (!taskChart || !queuesData) return false;
  console.log(
    "[Chart Update] Updating Task Distribution with queue data:",
    queuesData
  );
  const newData = [
    (queuesData.executor || []).length,
    (queuesData.tester || []).length,
    (queuesData.documenter || []).length,
  ];
  if (
    JSON.stringify(taskChart.data.datasets[0].data) !== JSON.stringify(newData)
  ) {
    taskChart.data.datasets[0].data = newData;
    console.log("[Chart Update] Task Distribution data changed.");
    return true;
  }
  return false;
}

// --- Progress Chart ---
const MAX_PROGRESS_POINTS = 20;

function initializeProgressChart() {
  if (progressChart) return;
  const ctx = document.getElementById("progressChart")?.getContext("2d");
  if (ctx) {
    const baseOptions = getBaseChartOptions();
    progressChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [], // Timestamps
        datasets: [
          {
            label: "Completed Tasks",
            data: [],
            borderColor: "rgb(54, 162, 235)",
            tension: 0.1,
            yAxisID: "yCount",
          },
          {
            label: "Successful Tests",
            data: [],
            borderColor: "rgb(255, 99, 132)",
            tension: 0.1,
            yAxisID: "yCount",
          },
          {
            label: "Git Actions",
            data: [],
            borderColor: "rgb(255, 205, 86)",
            tension: 0.1,
            yAxisID: "yCount",
          },
        ],
      },
      options: {
        ...baseOptions,
        scales: {
          x: {
            ...baseOptions.scales.x,
            ticks: {
              ...baseOptions.scales.x.ticks,
              display: false,
              maxRotation: 0,
              minRotation: 0,
              autoSkip: true,
              maxTicksLimit: 10,
            },
          },
          yCount: {
            type: "linear",
            position: "left",
            beginAtZero: true,
            title: {
              display: true,
              text: "Count",
              color: baseOptions.plugins.title.color,
            },
            ticks: { color: baseOptions.scales.y.ticks.color, stepSize: 1 },
            grid: {
              drawOnChartArea: false,
              color: baseOptions.scales.y.grid.color,
            },
          },
        },
        plugins: {
          ...baseOptions.plugins,
          title: {
            ...baseOptions.plugins.title,
            text: "Project Progress Over Time",
          },
          tooltip: {
            callbacks: {
              label: (context) =>
                `${context.dataset.label || ""}: ${context.parsed.y ?? "N/A"}`,
              title: (tooltipItems) => tooltipItems[0]?.label || "", // Use optional chaining
            },
          },
        },
      },
    });
  }
}

function updateProgressChartData(progressData, gitActivityData) {
  if (!progressChart || !progressData?.timestamp) return false; // Optional chaining

  console.log("Progress data received:", progressData);

  const labels = progressChart.data.labels;
  const datasets = progressChart.data.datasets;
  const completedTasksDataset = datasets.find(
    (ds) => ds.label === "Completed Tasks"
  );
  const successfulTestsDataset = datasets.find(
    (ds) => ds.label === "Successful Tests"
  );
  const gitActionsDataset = datasets.find((ds) => ds.label === "Git Actions");

  // Use latest Git Action count from git_activity if available, else from progress_data
  let latestGitActionCount = progressData.git_actions;
  if (gitActivityData?.values?.length > 0) {
    // Optional chaining
    latestGitActionCount =
      gitActivityData.values[gitActivityData.values.length - 1];
    console.log(
      `[Chart Update] Using latest git_actions value from git_activity: ${latestGitActionCount}`
    );
  } else {
    console.log(
      `[Chart Update] Using git_actions value from progress_data: ${latestGitActionCount}`
    );
  }

  // Add new data
  labels.push(progressData.timestamp); // Store full timestamp for tooltip
  completedTasksDataset?.data.push(progressData.completed_tasks); // Optional chaining
  successfulTestsDataset?.data.push(progressData.successful_tests); // Optional chaining
  console.log(
    `[Chart Update] Pushing git_actions value: ${latestGitActionCount}`
  );
  gitActionsDataset?.data.push(latestGitActionCount); // Optional chaining

  // Limit data points
  if (labels.length > MAX_PROGRESS_POINTS) {
    labels.shift();
    completedTasksDataset?.data.shift();
    successfulTestsDataset?.data.shift();
    gitActionsDataset?.data.shift();
  }

  // Update x-axis labels (displaying only HH:MM)
  progressChart.data.labels = labels.map((ts) =>
    new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );

  console.log("[Chart Update] Updating Progress Chart with new data point.");
  return true;
}

// --- Git Chart ---
function initializeGitChart() {
  if (gitChart) return;
  const ctx = document.getElementById("gitChart")?.getContext("2d");
  if (ctx) {
    const baseOptions = getBaseChartOptions();
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
            borderWidth: 2,
            tension: 0.4,
            fill: true,
          },
        ],
      },
      options: {
        ...baseOptions,
        plugins: {
          ...baseOptions.plugins,
          title: { ...baseOptions.plugins.title, text: "Git Activity" },
        },
      },
    });
  }
}

function updateGitChartData(gitActivityData) {
  if (!gitChart || !gitActivityData?.labels || !gitActivityData?.values)
    return false; // Optional chaining

  console.log(
    "[Chart Update] Updating Git Activity Chart with data:",
    gitActivityData
  );
  if (
    JSON.stringify(gitChart.data.labels) !==
      JSON.stringify(gitActivityData.labels) ||
    JSON.stringify(gitChart.data.datasets[0].data) !==
      JSON.stringify(gitActivityData.values)
  ) {
    gitChart.data.labels = gitActivityData.labels;
    gitChart.data.datasets[0].data = gitActivityData.values;
    console.log("[Chart Update] Git Activity data changed.");
    return true;
  }
  return false;
}

// --- Status Pie Chart ---
function initializeStatusPieChart() {
  if (statusPieChart) return;
  const ctx = document.getElementById("statusPieChart")?.getContext("2d");
  if (ctx) {
    const baseOptions = getBaseChartOptions(); // Get base options for colors
    statusPieChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["Pending", "Processing", "Completed", "Failed", "Other"],
        datasets: [
          {
            label: "Task Status Distribution",
            data: [0, 0, 0, 0, 0],
            backgroundColor: [
              "rgba(255, 205, 86, 0.7)", // Yellow
              "rgba(54, 162, 235, 0.7)", // Blue
              "rgba(75, 192, 192, 0.7)", // Green
              "rgba(255, 99, 132, 0.7)", // Red
              "rgba(201, 203, 207, 0.7)", // Grey
            ],
            borderColor: [
              "rgba(255, 205, 86, 1)",
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
            position: "right",
            labels: { color: baseOptions.plugins.legend.labels.color },
          },
          title: {
            display: true,
            text: "Task Statuses",
            color: baseOptions.plugins.title.color,
          },
        },
      },
    });
  }
}

function updateStatusPieChartData(statusDistributionData) {
  if (!statusPieChart || !statusDistributionData) return false;

  console.log(
    "[Chart Update] Updating Status Distribution with data:",
    statusDistributionData
  );
  const newData = [
    statusDistributionData.pending || 0,
    statusDistributionData.processing || 0,
    statusDistributionData.completed || 0,
    statusDistributionData.failed || 0,
    statusDistributionData.other || 0,
  ];
  if (
    JSON.stringify(statusPieChart.data.datasets[0].data) !==
    JSON.stringify(newData)
  ) {
    statusPieChart.data.datasets[0].data = newData;
    console.log("[Chart Update] Status Distribution data changed.");
    return true;
  }
  return false;
}

// --- Chart Theme Update ---
function updateAllChartThemes() {
  const newChartColor = getChartFontColor();
  [taskChart, progressChart, gitChart, statusPieChart].forEach((chart) => {
    updateChartTheme(chart, newChartColor);
  });
}

function updateChartTheme(chart, chartColor) {
  if (!chart?.options) return; // Optional chaining

  try {
    // Update common options like colors
    if (chart.options.scales) {
      if (chart.options.scales.y) {
        chart.options.scales.y.ticks.color = chartColor;
        chart.options.scales.y.grid.color = `${chartColor}20`;
        if (chart.options.scales.y.title)
          chart.options.scales.y.title.color = chartColor;
      }
      // Update yCount axis for progress chart
      if (chart.options.scales.yCount) {
        chart.options.scales.yCount.ticks.color = chartColor;
        chart.options.scales.yCount.grid.color = `${chartColor}20`;
        if (chart.options.scales.yCount.title)
          chart.options.scales.yCount.title.color = chartColor;
      }
      if (chart.options.scales.x) {
        chart.options.scales.x.ticks.color = chartColor;
        chart.options.scales.x.grid.color = `${chartColor}20`;
      }
    }
    // Optional chaining for plugins
    if (chart.options.plugins?.legend?.labels) {
      chart.options.plugins.legend.labels.color = chartColor;
    }
    if (chart.options.plugins?.title) {
      chart.options.plugins.title.color = chartColor;
    }
    chart.update();
  } catch (error) {
    console.error("Error updating chart theme:", error, "Chart:", chart);
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
  if (!fileStructureDiv) {
    console.error("File structure container not found!");
    return;
  }
  console.log(
    "updateFileStructure received data:",
    JSON.stringify(structureData, null, 2)
  );

  fileStructureDiv.innerHTML = ""; // Clear previous structure

  if (
    !structureData ||
    typeof structureData !== "object" ||
    Object.keys(structureData).length === 0
  ) {
    console.warn("File structure data is empty or invalid:", structureData);
    fileStructureDiv.innerHTML =
      "<p><em>Project structure is empty or unavailable.</em></p>";
    return;
  }

  const rootUl = document.createElement("ul");
  fileStructureDiv.appendChild(rootUl);

  function renderNode(node, parentUl, currentPath = "") {
    // --- Add logging here ---
    console.log(
      `Rendering node at path: '${currentPath}'. Node type: ${typeof node}`
      // node // Avoid logging potentially huge objects
    );
    if (typeof node !== "object" || node === null) {
      console.error(
        `Invalid node passed to renderNode at path '${currentPath}'. Expected object, got:`,
        node
      );
      const errorLi = document.createElement("li");
      errorLi.style.color = "red";
      errorLi.textContent = `Error: Invalid data for ${currentPath || "root"}`;
      parentUl.appendChild(errorLi);
      return; // Stop processing this invalid node
    }
    // --- End logging ---

    let entries;
    try {
      entries = Object.entries(node).sort(([keyA, valueA], [keyB, valueB]) => {
        const isDirA = typeof valueA === "object" && valueA !== null;
        const isDirB = typeof valueB === "object" && valueB !== null;
        if (isDirA !== isDirB) {
          return isDirA ? -1 : 1; // Folders first
        }
        return String(keyA).localeCompare(String(keyB)); // Then alphabetical
      });
      // console.log(
      //   `Sorted entries for path '${currentPath}':`,
      //   entries.map((e) => e[0])
      // ); // Log sorted keys - can be noisy
    } catch (sortError) {
      console.error(
        `Error sorting entries for node at path '${currentPath}':`,
        sortError,
        "Node:",
        node
      );
      const errorLi = document.createElement("li");
      errorLi.style.color = "red";
      errorLi.textContent = `Error sorting items in ${currentPath || "root"}`;
      parentUl.appendChild(errorLi);
      return; // Stop processing this node if sorting fails
    }

    for (const [key, value] of entries) {
      const li = document.createElement("li"); // Create li outside try block
      parentUl.appendChild(li); // Append li outside try block

      try {
        // --- Add logging inside try ---
        // console.log(
        //   `Processing entry: Key='${key}', Type='${typeof value}', Path='${currentPath}'`
        // ); // Can be noisy
        // ---

        const isDirectory = typeof value === "object" && value !== null;
        const itemPath = currentPath
          ? `${currentPath}/${String(key)}`
          : String(key);

        if (isDirectory) {
          // console.log(`Rendering folder: ${itemPath}`); // Noisy
          li.innerHTML = `<span class="folder"><i class="fas fa-folder"></i> ${String(
            key
          )}</span>`;
          li.classList.add("folder-item");
          const subUl = document.createElement("ul");
          li.appendChild(subUl);

          const folderSpan = li.querySelector(".folder");
          if (folderSpan) {
            folderSpan.addEventListener("click", (e) => {
              li.classList.toggle("expanded");
              e.stopPropagation();
            });
          } else {
            console.warn(
              "Could not find .folder span for event listener in:",
              li.innerHTML
            );
          }

          // Recurse only if the directory is not empty
          if (Object.keys(value).length > 0) {
            // console.log(`Recursing into folder: ${itemPath}`); // Noisy
            renderNode(value, subUl, itemPath); // Recurse
          } else {
            // console.log(`Folder is empty: ${itemPath}`); // Noisy
          }
        } else {
          // It's a file
          // console.log(`Rendering file: ${itemPath}`); // Noisy
          const iconClass = getFileIcon(String(key));
          // console.log(`Icon for ${key}: ${iconClass}`); // Log icon class
          li.innerHTML = `<span class="file" data-path="${itemPath}"><i class="fas ${iconClass}"></i> ${String(
            key
          )}</span>`;

          const fileSpan = li.querySelector(".file");
          if (fileSpan) {
            fileSpan.addEventListener("click", (e) => {
              const path = e.currentTarget.getAttribute("data-path");
              if (path) {
                loadFileContent(path);
              } else {
                console.error(
                  "File span clicked, but data-path attribute is missing:",
                  e.currentTarget
                );
              }
              e.stopPropagation();
            });
          } else {
            console.warn(
              "Could not find .file span for event listener in:",
              li.innerHTML
            );
          }
        }
      } catch (error) {
        console.error(
          `Error rendering node entry: Key='${key}', Path='${currentPath}', ValueType='${typeof value}':`,
          error,
          "Value:",
          value
        );
        li.style.color = "red";
        li.textContent = `Error rendering ${key}`;
      }
    }
  }

  try {
    console.log("Starting initial renderNode call for root.");
    renderNode(structureData, rootUl);
    console.log("File structure rendering completed.");
  } catch (error) {
    console.error("Error during initial call to renderNode:", error);
    fileStructureDiv.innerHTML =
      "<p><em>Error rendering file structure. Check browser console for details.</em></p>"; // Update message
  }
}

// Refactored getFileIcon using a map
const fileIconMap = {
  // Specific names
  ".gitignore": "fa-code-branch",
  ".gitattributes": "fa-code-branch",
  dockerfile: "fa-box-open",
  makefile: "fa-file-code",
  // Extensions
  py: "fa-file-code",
  js: "fa-file-code",
  html: "fa-file-code",
  css: "fa-file-code",
  json: "fa-file-code",
  md: "fa-file-lines",
  ts: "fa-file-code",
  java: "fa-file-code",
  c: "fa-file-code",
  h: "fa-file-code",
  cpp: "fa-file-code",
  hpp: "fa-file-code",
  cs: "fa-file-code",
  go: "fa-file-code",
  php: "fa-file-code",
  rb: "fa-file-code",
  swift: "fa-file-code",
  xml: "fa-file-code",
  yaml: "fa-file-alt",
  yml: "fa-file-alt",
  sh: "fa-terminal",
  bash: "fa-terminal",
  zsh: "fa-terminal",
  sql: "fa-database",
  txt: "fa-file-alt",
  log: "fa-file-alt",
  csv: "fa-file-csv",
  tsv: "fa-file-csv",
  png: "fa-file-image",
  jpg: "fa-file-image",
  jpeg: "fa-file-image",
  gif: "fa-file-image",
  bmp: "fa-file-image",
  ico: "fa-file-image",
  svg: "fa-file-image",
  mp3: "fa-file-audio",
  wav: "fa-file-audio",
  ogg: "fa-file-audio",
  flac: "fa-file-audio",
  aac: "fa-file-audio",
  mp4: "fa-file-video",
  avi: "fa-file-video",
  mov: "fa-file-video",
  wmv: "fa-file-video",
  mkv: "fa-file-video",
  pdf: "fa-file-pdf",
  doc: "fa-file-word",
  docx: "fa-file-word",
  xls: "fa-file-excel",
  xlsx: "fa-file-excel",
  ppt: "fa-file-powerpoint",
  pptx: "fa-file-powerpoint",
  zip: "fa-file-archive",
  rar: "fa-file-archive",
  "7z": "fa-file-archive",
  tar: "fa-file-archive",
  gz: "fa-file-archive",
  db: "fa-database",
  sqlite: "fa-database",
};

function getFileIcon(fileName) {
  const nameStr = String(fileName).toLowerCase();
  const ext = nameStr.includes(".") ? nameStr.split(".").pop() : "";

  // Check specific names first
  if (fileIconMap[nameStr]) {
    return fileIconMap[nameStr];
  }
  // Check extension
  if (ext && fileIconMap[ext]) {
    return fileIconMap[ext];
  }
  // Default icon
  return "fa-file";
}

async function loadFileContent(path) {
  if (!editor) {
    showNotification("Editor not initialized yet", "warning");
    return;
  }
  console.log("Attempting to load file content:", path);
  editor.setValue(`// Loading ${path}...`); // Placeholder content

  try {
    const response = await fetch(
      `/file_content?path=${encodeURIComponent(path)}`
    );

    if (response.ok) {
      const content = await response.text();

      // Перевірка, чи це повідомлення про бінарний файл
      if (content.startsWith("[Binary file:")) {
        // Встановлюємо спеціальне повідомлення для бінарних файлів
        editor.setValue(content);

        // Встановлюємо мову як plaintext для повідомлення про бінарний файл
        monaco.editor.setModelLanguage(editor.getModel(), "plaintext");

        console.log(`Binary file detected: ${path}`);
        showNotification(
          `Файл ${path} є бінарним і не може бути відображений`,
          "info"
        );
        return;
      }

      // Для текстових файлів - визначаємо мову та встановлюємо вміст
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

  // Update chart colors ONLY if charts have been initialized
  if (taskChart) {
    updateAllChartThemes(); // Use the refactored theme update function
  }

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
    // Error already shown by sendRequest, but log it for debugging
    console.error(`Failed to ${action} ${ai}:`, error);
    // Optionally show a more specific error notification if needed
    // showNotification(`Failed to ${action} ${ai}: ${error.message}`, "error");
  }
}

async function startAll() {
  try {
    await sendRequest("/start_all");
    showNotification("Start All request sent", "info");
  } catch (error) {
    console.error("Failed to start all AI:", error);
    // Error already shown by sendRequest
  }
}

async function stopAll() {
  try {
    await sendRequest("/stop_all");
    showNotification("Stop All request sent", "info");
  } catch (error) {
    console.error("Failed to stop all AI:", error);
    // Error already shown by sendRequest
  }
}

async function resetSystem() {
  if (
    confirm(
      "Are you sure you want to reset the system? This will clear queues, logs, and restart AI processes."
    )
  ) {
    try {
      await sendRequest("/clear", "POST");
      await sendRequest("/start_all", "POST");
      showNotification("System reset and restart requested", "info");
      logContent.innerHTML = "<p><em>System reset requested...</em></p>";
      updateQueues({ executor: [], tester: [], documenter: [] });
      updateStats({}, {});
    } catch (error) {
      console.error("Failed to reset system:", error);
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
    console.error("Failed to save configuration:", error);
    showNotification("Failed to save configuration", "error");
  }
}

// Функція для збереження окремого елемента конфігурації
async function saveConfigItem(key, elementId) {
  const element = document.getElementById(elementId);
  if (!element) {
    showNotification(
      `Error: Element with ID '${elementId}' not found.`,
      "error"
    );
    return;
  }

  let value;
  if (element.type === "number") {
    value = parseFloat(element.value);
    if (isNaN(value)) {
      showNotification(`Error: Invalid number format for ${key}.`, "error");
      return;
    }
  } else {
    value = element.value;
  }

  const data = { [key]: value };

  console.log(`Saving config item: ${key} = ${value}`);

  try {
    // Використовуємо новий ендпоінт
    await sendRequest("/update_config_item", "POST", data);
    showNotification(`${key} saved successfully`, "success");
  } catch (error) {
    console.error(`Failed to save config item ${key}:`, error);
    showNotification(`Failed to save ${key}`, "error");
  }
}

async function clearRepo() {
  if (
    confirm(
      "Are you sure you want to clear the entire repository? This will delete all files and commit history!"
    )
  ) {
    showNotification("Clearing repository...", "info");
    try {
      const response = await sendRequest("/clear_repo", "POST");
      showNotification(
        response?.status || "Repository cleared and re-initialized.", // Optional chaining
        "success"
      );
      // Refresh file structure after clearing
      // Assuming fetchAndUpdateStructure exists or implement it:
      // fetchAndUpdateStructure();
      // For now, just clear the displayed structure:
      const fileStructureDiv = document.getElementById("file-structure");
      if (fileStructureDiv)
        fileStructureDiv.innerHTML =
          "<p><em>Repository cleared. Refreshing...</em></p>";
      // Request full status update to get new structure
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: "get_full_status" }));
      }
    } catch (error) {
      console.error("Failed to clear repository:", error);
      showNotification("Failed to clear repository.", "error");
    }
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
  // Initial call to updateStats uses the default actualTotalTasks = 0
  updateStats({}, {});
  console.log("Initialization complete.");

  // Ініціалізація слайдера навантаження
  const loadSlider = document.getElementById("ai1-buffer-slider");
  if (loadSlider) {
    // Оновлюємо опис при завантаженні сторінки
    updateLoadDescription(loadSlider.value);

    // Додаємо обробник події зміни слайдера
    loadSlider.addEventListener("input", function () {
      updateLoadDescription(this.value);
    });
  }

  // Set up the log panel auto-retract behavior
  setupLogPanelBehavior();

  console.log("Initialization complete.");
});

// --- Helper function to calculate status distribution ---
function calculateStatusDistribution(statuses) {
  const statusCounts = Object.values(statuses).reduce(
    (acc, status) => {
      let category = "other";
      if (status === "pending") category = "pending";
      else if (status === "processing") category = "processing";
      else if (
        status === "accepted" ||
        status === "completed" ||
        status === "code_received"
      )
        category = "completed";
      else if (
        status === "failed" ||
        (typeof status === "string" && status.startsWith("Ошибка"))
      )
        category = "failed";

      acc[category] = (acc[category] || 0) + 1;
      return acc;
    },
    { pending: 0, processing: 0, completed: 0, failed: 0, other: 0 }
  );
  return statusCounts;
}

// --- Функції для слайдера навантаження системи ---
const loadLevelDescriptions = [
  {
    level: 1,
    title: "Мінімальне навантаження",
    description:
      "Найповільніша генерація, максимальна економія ресурсів, мінімальне навантаження на MCP.",
    bufferValue: 5,
  },
  {
    level: 2,
    title: "Низьке навантаження",
    description:
      "Повільна генерація, економне використання ресурсів, низьке навантаження на MCP.",
    bufferValue: 10,
  },
  {
    level: 3,
    title: "Середнє навантаження",
    description: "Збалансована швидкість генерації та використання ресурсів.",
    bufferValue: 15,
  },
  {
    level: 4,
    title: "Високе навантаження",
    description:
      "Швидка генерація, висока продуктивність, значне навантаження на MCP.",
    bufferValue: 20,
  },
  {
    level: 5,
    title: "Максимальне навантаження",
    description:
      "Найшвидша генерація, максимальна продуктивність, високе навантаження на MCP.",
    bufferValue: 25,
  },
];

function updateLoadDescription(levelValue) {
  const level = parseInt(levelValue);
  const descriptionData = loadLevelDescriptions[level - 1];
  const descriptionText = document.getElementById("load-description-text");
  const slider = document.getElementById("ai1-buffer-slider");

  if (descriptionText && descriptionData) {
    descriptionText.innerHTML = `<strong>Рівень ${level} (${descriptionData.title}):</strong> ${descriptionData.description}`;
  }

  // --- NEW: Update slider background gradient ---
  if (slider) {
    const percentage = ((level - 1) / (slider.max - slider.min)) * 100;
    // Define colors for the gradient stops (match CSS variables if possible)
    const colors = [
      "var(--success-color)", // Level 1
      "var(--tertiary-color)", // Level 2
      "var(--warning-color)", // Level 3
      "var(--primary-color)", // Level 4
      "var(--error-color)", // Level 5
    ];
    // Get the color corresponding to the current level
    const currentLevelColor = colors[level - 1];
    // Create a gradient that fills up to the current percentage with the level's color
    // and uses the default track background for the rest
    const trackBackground = getComputedStyle(document.documentElement)
      .getPropertyValue("--input-border")
      .trim();
    slider.style.background = `linear-gradient(to right, ${currentLevelColor} ${percentage}%, ${trackBackground} ${percentage}%)`;
  }
  // --- END NEW ---
}

function saveLoadLevel() {
  const slider = document.getElementById("ai1-buffer-slider");
  if (!slider) {
    showNotification("Помилка: елемент слайдера не знайдено", "error");
    return;
  }

  const level = parseInt(slider.value);
  const bufferValue = loadLevelDescriptions[level - 1].bufferValue;

  console.log(
    `Зберігаємо рівень навантаження: ${level} (buffer=${bufferValue})`
  );

  // Використаємо існуючу функцію saveConfigItem, але з обчисленим значенням буфера
  const data = { ai1_desired_active_buffer: bufferValue };

  // Запит на оновлення налаштування
  try {
    sendRequest("/update_config_item", "POST", data).then(() => {
      showNotification(`Рівень навантаження змінено на: ${level}`, "success");
    });
  } catch (error) {
    console.error(`Помилка збереження рівня навантаження:`, error);
    showNotification(`Помилка збереження рівня навантаження`, "error");
  }
}

// --- Log Panel Auto-Retract ---
let logPanelTimeoutId = null; // Variable to hold the timeout ID

function setupLogPanelBehavior() {
  const logPanelContainer = document.querySelector(".log-panel-container");

  if (logPanelContainer) {
    logPanelContainer.addEventListener("mouseenter", () => {
      // Clear any existing timeout when the mouse enters the area
      if (logPanelTimeoutId) {
        clearTimeout(logPanelTimeoutId);
        logPanelTimeoutId = null;
        console.log("Log panel retract timer cleared (mouse entered).");
      }
      // Add a class to ensure it's visible (CSS handles the transition)
      logPanelContainer.classList.add("log-panel-hover");
    });

    logPanelContainer.addEventListener("mouseleave", () => {
      // Start a timer to retract the panel when the mouse leaves
      logPanelTimeoutId = setTimeout(() => {
        logPanelContainer.classList.remove("log-panel-hover");
        console.log("Log panel retracted after 3s timeout.");
        logPanelTimeoutId = null;
      }, 3000); // 3000 milliseconds = 3 seconds
      console.log("Log panel retract timer started (3s).");
    });
  } else {
    console.error("Log panel container not found for setting up behavior.");
  }
}

let taskChart, progressChart, gitChart, editor, statusPieChart;
let ws;
const reconnectInterval = 10000; // Reconnect interval 5 seconds
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;
const MAX_LOG_LINES = 60; // Maximum number of log lines to keep
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
      // This message contains everything, update the entire UI
      updateFullUI(data);
      break; // Added break statement

    case "status_update":
      // Assume this might be a partial status, handle specifically
      // It might contain ai_status, subtasks, queues etc.
      console.log("Processing status_update via handleSpecificUpdate:", data);
      // Update AI button states if present
      if (data.ai_status) {
        updateAllButtonStates(data.ai_status);
      }
      // Delegate the rest to handleSpecificUpdate for consistency
      handleSpecificUpdate(data);
      break; // Added break statement

    case "log_update":
      // Handle single log line updates
      if (data.log_line) {
        handleLogUpdate(data.log_line);
      }
      break; // Added break statement

    case "structure_update":
      // Handle file structure updates
      if (data.structure) {
        updateFileStructure(data.structure);
      }
      break; // Added break statement

    case "queue_update":
      // Handle queue-only updates
      console.log("Processing queue_update:", data);
      if (data.queues) {
        updateQueues(data.queues);
        // Also update charts that depend on queue data (Task Distribution)
        // Pass only necessary data to updateCharts
        updateCharts({ queues: data.queues });
      }
      break; // Added break statement

    case "specific_update":
      // Handle messages with a mix of specific data points
      handleSpecificUpdate(data);
      break; // Added break statement

    case "ping":
      // Server ping, no UI update needed, maybe log?
      // console.log("Received ping from server");
      break; // Added break statement

    case "monitoring_update":
      // Handle updates specifically for monitoring charts/data
      console.log("Processing monitoring_update:", data);

      // Update actual total tasks count if provided
      if (data.total_tasks !== undefined) {
        actualTotalTasks = data.total_tasks;
        console.log(
          `[Monitoring] Updated actual total tasks to: ${actualTotalTasks}`
        );
      }

      // Update completed tasks if provided
      if (data.completed_tasks !== undefined && statElements.completed) {
        statElements.completed.textContent = data.completed_tasks;
        console.log(
          `[Monitoring] Updated completed tasks to: ${data.completed_tasks}`
        );
      }

      // Update efficiency if we have both total and completed
      if (data.total_tasks && data.completed_tasks && statElements.efficiency) {
        const efficiency =
          data.total_tasks > 0
            ? ((data.completed_tasks / data.total_tasks) * 100).toFixed(1)
            : "0.0";
        statElements.efficiency.textContent = `${efficiency}%`;
        console.log(`[Monitoring] Updated efficiency to: ${efficiency}%`);
      }

      // Update total tasks display
      if (data.total_tasks !== undefined && statElements.total) {
        statElements.total.textContent = data.total_tasks;
        console.log(
          `[Monitoring] Updated total tasks display to: ${data.total_tasks}`
        );
      }

      // Update queue data if present
      if (data.queues) {
        updateQueues(data.queues);
      }

      // Update subtask statuses if provided
      if (data.subtasks) {
        Object.assign(subtask_status, data.subtasks);
        updateQueueItemStatuses(data.subtasks);
      }

      // Update charts with available data
      updateCharts(data);
      updateProjectSummary(data); // Call to update project header
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

    // Use configurable maxLogLines
    while (logContent.childElementCount > maxLogLines) {
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

  // Update queue item statuses immediately with the new data
  updateQueueItemStatuses(subtasksData);

  updateStats(subtask_status, null); // Pass null for queues
  updateCharts({
    task_status_distribution: calculateStatusDistribution(subtask_status),
  });
  updateProjectSummary({ subtasks: subtasksData }); // Call to update project header
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
      // Update global status object
      Object.assign(subtask_status, data.subtasks);

      // Dynamically update queue items with new statuses
      updateQueueItemStatuses(data.subtasks);

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
    updateProjectSummary(data); // Call to update project header
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

  // Update project summary with the full data
  updateProjectSummary(data);

  // Update timeline chart
  updateTimelineChart(data);

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

    // Dynamically update queue items with new statuses
    updateQueueItemStatuses(data.subtasks);

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
      status === "code_received" ||
      status === "tested" ||
      status === "documented" ||
      status === "skipped"
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
  // if (statElements.completed) statElements.completed.textContent = completed; // DO NOT UPDATE COMPLETED
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

// --- Helper function to create a task list item ---
function createTaskListItem(task) {
  const status = task.status || subtask_status[task.id] || "pending";
  const li = document.createElement("li");
  li.setAttribute("data-task-id", task.id);
  li.setAttribute("data-status", status);
  li.classList.add("task-item");

  // Create the task summary section (always visible)
  const summaryDiv = document.createElement("div");
  summaryDiv.className = "task-summary";

  // Create status icon with appropriate styling
  const statusIcon = document.createElement("span");
  statusIcon.className = "status-icon";
  try {
    statusIcon.innerHTML = getStatusIcon(status);
  } catch (e) {
    console.error(`Error getting status icon for status '${status}':`, e);
    statusIcon.innerHTML = '<i class="fas fa-question-circle"></i>';
  }

  // Create filename display
  const taskFilename = document.createElement("span");
  taskFilename.className = "task-filename";
  taskFilename.textContent = task.filename || `Task ${task.id.substring(0, 8)}`;

  // Create task ID display (shortened)
  const taskIdSpan = document.createElement("span");
  taskIdSpan.className = "task-id";
  taskIdSpan.textContent = `ID: ${task.id.substring(0, 8)}`;

  // Assemble the summary section
  summaryDiv.appendChild(statusIcon);
  summaryDiv.appendChild(taskFilename);
  summaryDiv.appendChild(taskIdSpan);
  li.appendChild(summaryDiv);

  // Create details section (initially hidden)
  const detailsDiv = document.createElement("div");
  detailsDiv.className = "task-details";
  detailsDiv.textContent = task.text || "No details available";
  li.appendChild(detailsDiv);

  // Add click handler to toggle expanded state
  li.addEventListener("click", () => {
    li.classList.toggle("expanded");

    // If it was just expanded, scroll to ensure it's fully visible
    if (li.classList.contains("expanded")) {
      setTimeout(() => {
        li.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 100);
    }
  });

  return li;
}

function updateQueues(queuesData) {
  let anyQueueChanged = false; // Flag to check if any queue visually changed

  console.log(
    "[Queue Update] Received queue data:",
    JSON.stringify(queuesData)
  );

  ["executor", "tester", "documenter"].forEach((role) => {
    const ul = queueLists[role];
    const countSpan = queueCounts[role];
    if (!ul || !countSpan) {
      console.warn(`[Queue Update] UI elements for role '${role}' not found.`);
      return;
    }

    const incomingTasks = queuesData?.[role] || [];
    const incomingTaskIds = new Set(incomingTasks.map((task) => task.id));
    const currentListItems = ul.querySelectorAll("li[data-task-id]");
    const currentTaskIds = new Set();
    let listChanged = false;

    // --- Update existing items and identify current IDs ---
    currentListItems.forEach((li) => {
      const taskId = li.getAttribute("data-task-id");
      currentTaskIds.add(taskId);

      // Check if this task is still in the incoming data
      if (!incomingTaskIds.has(taskId)) {
        // Task removed
        li.remove();
        listChanged = true;
        console.log(
          `[Queue Update] Task ${taskId} removed from ${role} queue.`
        );
      } else {
        // Task still exists, check if status needs update
        const incomingTask = incomingTasks.find((t) => t.id === taskId);
        const newStatus =
          incomingTask?.status || subtask_status[taskId] || "pending";
        const currentStatus = li.getAttribute("data-status");

        if (newStatus !== currentStatus) {
          li.setAttribute("data-status", newStatus);
          const statusIcon = li.querySelector(".status-icon");
          if (statusIcon) {
            try {
              statusIcon.innerHTML = getStatusIcon(newStatus);
            } catch (e) {
              console.error(
                `Error getting status icon for status '${newStatus}':`,
                e
              );
              statusIcon.innerHTML = '<i class="fas fa-question-circle"></i>';
            }
          }
          listChanged = true;
          console.log(
            `[Queue Update] Task ${taskId} status updated to ${newStatus} in ${role} queue.`
          );
        }
        // Update filename/text if necessary (optional)
        const taskFilenameSpan = li.querySelector(".task-filename");
        const newFilename =
          incomingTask?.filename || `Task ${taskId.substring(0, 8)}`;
        if (taskFilenameSpan && taskFilenameSpan.textContent !== newFilename) {
          taskFilenameSpan.textContent = newFilename;
          listChanged = true; // Consider filename change as a visual change
        }
        const detailsDiv = li.querySelector(".task-details");
        const newText = incomingTask?.text || "";
        if (detailsDiv && detailsDiv.textContent !== newText) {
          detailsDiv.textContent = newText;
        }
      }
    });

    // --- Add new items ---
    incomingTasks.forEach((task) => {
      if (!currentTaskIds.has(task.id)) {
        const newLi = createTaskListItem(task);
        ul.appendChild(newLi);
        listChanged = true;
        console.log(`[Queue Update] Task ${task.id} added to ${role} queue.`);
      }
    });

    // Update count
    const newCount = incomingTasks.length;
    if (parseInt(countSpan.textContent || "0", 10) !== newCount) {
      countSpan.textContent = newCount;
      // Count change implies list changed visually
      listChanged = true;
    }
    console.log(`[Queue Update] Role '${role}': Count set to ${newCount}`);

    if (listChanged) {
      anyQueueChanged = true;
    }
  }); // End forEach role

  // Update stats using the new function, passing current queue data and global subtask status
  updateStats(subtask_status, queuesData);

  // Update the task distribution chart if it exists and any queue visually changed
  if (taskChart && anyQueueChanged) {
    console.log(
      "[Queue Update] Updating taskChart data due to queue changes:",
      queuesData
    );
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
  } else if (taskChart && !anyQueueChanged) {
    console.log("[Queue Update] No visual changes detected for taskChart.");
  }
}

// --- Helper function for status icons (ensure this exists) ---
function getStatusIcon(status) {
  // Example implementation (replace with your actual logic)
  switch (status) {
    case "pending":
      return '<i class="fas fa-clock text-warning"></i>';
    case "processing":
      return '<i class="fas fa-spinner fa-spin text-info"></i>';
    case "completed":
    case "accepted":
    case "code_received":
      return '<i class="fas fa-check-circle text-success"></i>';
    case "failed":
    case "needs_rework":
      return '<i class="fas fa-times-circle text-danger"></i>';
    default:
      return '<i class="fas fa-question-circle text-muted"></i>';
  }
}

// --- Chart Initialization and Update Functions ---

function initializeCharts() {
  initializeTaskChart();
  // --- REORDERED: Status Pie Chart is now second ---
  initializeStatusPieChart();
  // --- REORDERED: Progress Chart is now third ---
  initializeProgressChart();
  // --- REORDERED: Git Chart is now last ---
  initializeGitChart();
}

function updateCharts(data) {
  console.log("updateCharts called with data:", JSON.stringify(data, null, 2));

  // Initialize charts if they don't exist
  if (!taskChart || !progressChart || !gitChart || !statusPieChart) {
    initializeCharts();
  }

  let chartsUpdated = false;

  if (updateTaskChartData(data.queues)) chartsUpdated = true;
  // --- REORDERED: Update Status Pie Chart second ---
  if (updateStatusPieChartData(data.task_status_distribution))
    chartsUpdated = true;
  // --- REORDERED: Update Progress Chart third ---
  if (updateProgressChartData(data.progress_data, data.git_activity))
    chartsUpdated = true;
  // --- REORDERED: Update Git Chart last ---
  if (updateGitChartData(data.git_activity)) chartsUpdated = true;

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
    taskChart.update(); // Update chart after changing data
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
            borderColor: "rgb(54, 162, 235)", // Blue
            tension: 0.1,
            yAxisID: "yCount",
          },
          {
            label: "Successful Tests",
            data: [],
            borderColor: "rgb(75, 192, 192)", // Green
            tension: 0.1,
            yAxisID: "yCount",
          },
          {
            label: "Git Actions",
            data: [],
            borderColor: "rgb(255, 205, 86)", // Yellow
            tension: 0.1,
            yAxisID: "yCount",
          },
          {
            label: "Rejected Files",
            data: [],
            borderColor: "rgb(255, 99, 132)", // Red
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
              display: false, // Keep labels hidden for cleaner look
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
              drawOnChartArea: true, // Draw grid lines for this axis
              color: baseOptions.scales.y.grid.color,
            },
          },
        },
        plugins: {
          ...baseOptions.plugins,
          // --- MODIFIED: Legend position to top ---
          legend: {
            ...baseOptions.plugins.legend,
            position: "top",
          },
          // --- END MODIFIED ---
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
  // ... (existing logging and checks) ...
  console.log(
    "[Progress Chart] Received progressData:",
    JSON.stringify(progressData)
  );
  console.log(
    "[Progress Chart] Received gitActivityData:",
    JSON.stringify(gitActivityData)
  );

  if (!progressChart || !progressData?.timestamp) {
    console.log(
      "[Progress Chart] Skipping update: Chart not ready or no timestamp in progressData."
    );
    return false;
  }

  const labels = progressChart.data.labels;
  const datasets = progressChart.data.datasets;
  const completedTasksDataset = datasets.find(
    (ds) => ds.label === "Completed Tasks"
  );
  const successfulTestsDataset = datasets.find(
    (ds) => ds.label === "Successful Tests"
  );
  const gitActionsDataset = datasets.find((ds) => ds.label === "Git Actions");
  const rejectedFilesDataset = datasets.find(
    (ds) => ds.label === "Rejected Files"
  );

  if (!successfulTestsDataset || !rejectedFilesDataset) {
    // Check both datasets
    console.error("[Progress Chart] Required dataset(s) not found!");
    return false;
  }

  // ... (existing checks for successful_tests) ...
  if (
    progressData.successful_tests === undefined ||
    progressData.successful_tests === null
  ) {
    console.warn(
      "[Progress Chart] 'successful_tests' key missing or null in progressData. Using previous value or 0."
    );
  }
  // --- ADDED: Check for rejected_files ---
  if (
    progressData.rejected_files === undefined ||
    progressData.rejected_files === null
  ) {
    console.warn(
      "[Progress Chart] 'rejected_files' key missing or null in progressData. Using 0."
    );
  }
  // --- END ADDED ---

  // ... (existing git action count logic) ...
  let latestGitActionCount = progressData.git_actions;
  if (gitActivityData?.values?.length > 0) {
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
  completedTasksDataset?.data.push(progressData.completed_tasks ?? 0); // Use nullish coalescing for safety

  // Push successful_tests data
  const lastSuccessfulTestValue =
    successfulTestsDataset.data.length > 0
      ? successfulTestsDataset.data[successfulTestsDataset.data.length - 1]
      : 0;
  const currentSuccessfulTestValue =
    progressData.successful_tests ?? lastSuccessfulTestValue;
  successfulTestsDataset.data.push(currentSuccessfulTestValue);
  console.log(
    `[Progress Chart] Pushing successful_tests value: ${currentSuccessfulTestValue} (received: ${progressData.successful_tests})`
  );

  gitActionsDataset?.data.push(latestGitActionCount ?? 0); // Use nullish coalescing

  // --- ADDED: Push rejected_files data ---
  const currentRejectedFilesValue = progressData.rejected_files ?? 0; // Default to 0 if missing
  rejectedFilesDataset.data.push(currentRejectedFilesValue);
  console.log(
    `[Progress Chart] Pushing rejected_files value: ${currentRejectedFilesValue} (received: ${progressData.rejected_files})`
  );
  // --- END ADDED ---

  // Limit data points
  if (labels.length > MAX_PROGRESS_POINTS) {
    labels.shift();
    completedTasksDataset?.data.shift();
    successfulTestsDataset?.data.shift();
    gitActionsDataset?.data.shift();
    rejectedFilesDataset?.data.shift(); // Shift this dataset too
  }

  // Update x-axis labels (displaying only HH:MM)
  progressChart.data.labels = labels.map((ts) =>
    new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );

  console.log("[Chart Update] Updating Progress Chart with new data point.");
  progressChart.update(); // Explicitly update the chart
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
            // --- MODIFIED: Colors on one line ---
            backgroundColor: "rgba(255, 159, 64, 0.2)",
            borderColor: "rgba(255, 159, 64, 1)",
            // --- END MODIFIED ---
            borderWidth: 2,
            tension: 4,
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
  // --- REORDERED: Match new initialization order ---
  [taskChart, statusPieChart, progressChart, gitChart].forEach((chart) => {
    updateChartTheme(chart, newChartColor);
  });
  // --- END REORDERED ---
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
  // ADDED: midnight and forest to the dark theme list
  return appTheme === "dark" ||
    appTheme === "winter" ||
    appTheme === "autumn" ||
    appTheme === "midnight" ||
    appTheme === "forest"
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
      // --- CHANGE: Ensure resetSystem calls /clear ---
      await sendRequest("/clear");
      // --- END CHANGE ---
      showNotification(
        "System reset initiated. Services will restart.",
        "warning"
      );
    } catch (error) {
      console.error("Failed to reset system:", error);
      // Error already shown by sendRequest
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

  // Initialize enhanced file explorer
  setupEnhancedFileExplorer();

  // Initialize timeline chart
  initializeTimelineChart();

  // Set up editor change tracking
  setupEditorChangeTracking();

  // Initial UI state (optional, WebSocket should provide data)
  updateQueues({ executor: [], tester: [], documenter: [] });

  // Initial call to updateStats uses the default actualTotalTasks = 0
  updateStats({}, {});

  // Set initial project summary with placeholder data
  updateProjectSummary({
    target:
      "AI-SYSTEMS Project\nAn automated multi-agent software development system",
    structure: {},
  });

  // Initialize load slider
  const loadSlider = document.getElementById("ai1-buffer-slider");
  if (loadSlider) {
    // Update description on page load
    updateLoadDescription(loadSlider.value);

    // Add event listener for slider changes
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

// --- Log Panel Configuration and Behavior ---
let logDisplaySeconds = 3; // Default display duration in seconds
let maxLogLines = 60; // Default maximum lines to display
let logPanelMouseIsOver = false; // Track if mouse is over the panel

function setupLogPanelBehavior() {
  const logPanelContainer = document.querySelector(".log-panel-container");
  const logDisplaySecondsInput = document.getElementById("log-display-seconds");
  const logMaxLinesInput = document.getElementById("log-max-lines");

  // Load saved settings from localStorage if available
  if (localStorage.getItem("logDisplaySeconds")) {
    logDisplaySeconds = parseInt(localStorage.getItem("logDisplaySeconds"), 10);
    if (logDisplaySecondsInput)
      logDisplaySecondsInput.value = logDisplaySeconds;
  }

  if (localStorage.getItem("maxLogLines")) {
    maxLogLines = parseInt(localStorage.getItem("maxLogLines"), 10);
    if (logMaxLinesInput) logMaxLinesInput.value = maxLogLines;
  }

  if (logPanelContainer) {
    // Show log panel when mouse enters trigger area
    logPanelContainer.addEventListener("mouseenter", () => {
      logPanelMouseIsOver = true;
      logPanelContainer.classList.add("log-panel-hover");
    });

    // Handle mouse leave
    logPanelContainer.addEventListener("mouseleave", () => {
      logPanelMouseIsOver = false;
      retractLogPanel();
    });

    // Prevent panel from closing when interacting with input fields
    const inputFields = logPanelContainer.querySelectorAll(
      'input[type="number"]'
    );
    inputFields.forEach((input) => {
      input.addEventListener("focus", () => {
        // Keep panel open while input is focused
        logPanelMouseIsOver = true;
      });

      input.addEventListener("blur", () => {
        // Check if mouse is still over the panel
        setTimeout(() => {
          if (!logPanelContainer.matches(":hover")) {
            logPanelMouseIsOver = false;
            retractLogPanel();
          }
        }, 100); // Short delay to check hover state
      });

      // Prevent wheel events from scrolling the page when adjusting input value
      input.addEventListener("wheel", (e) => {
        if (document.activeElement === input) {
          e.preventDefault();
          // Optional: implement custom increment/decrement logic here if needed
        }
      });
    });

    // Handle click anywhere on the document to close log panel
    document.addEventListener("click", (e) => {
      // Only close if the panel is visible and the click is not on the panel
      if (
        logPanelContainer.classList.contains("log-panel-hover") &&
        !logPanelContainer.contains(e.target)
      ) {
        logPanelMouseIsOver = false;
        retractLogPanel();
      }
    });
  } else {
    console.error("Log panel container not found for setting up behavior.");
  }
}

function retractLogPanel() {
  const logPanelContainer = document.querySelector(".log-panel-container");
  if (!logPanelContainer || logPanelMouseIsOver) return;

  // Immediately remove hover class since we want it to close on click
  logPanelContainer.classList.remove("log-panel-hover");
  console.log("Log panel retracted immediately.");
}

// --- New function to update queue item statuses dynamically ---
function updateQueueItemStatuses(updatedStatuses) {
  // Skip if no statuses were provided or if queueLists is not initialized
  if (
    !updatedStatuses ||
    Object.keys(updatedStatuses).length === 0 ||
    !queueLists
  ) {
    return false;
  }

  let anyStatusChanged = false;

  // Check all queue lists for matching task IDs
  ["executor", "tester", "documenter"].forEach((role) => {
    const ul = queueLists[role];
    if (!ul) return;

    // Get all task items in this queue
    const taskItems = ul.querySelectorAll("li[data-task-id]");
    if (!taskItems.length) return;

    // Iterate through each task item
    taskItems.forEach((li) => {
      const taskId = li.getAttribute("data-task-id");
      // Check if this task has an updated status
      if (taskId && updatedStatuses[taskId] !== undefined) {
        const newStatus = updatedStatuses[taskId];
        const currentStatus = li.getAttribute("data-status");

        // Only update if status has changed
        if (newStatus !== currentStatus) {
          // Apply transition class for animation
          li.classList.add("status-changing");

          // Update the status after a short delay (for transition effect)
          setTimeout(() => {
            li.setAttribute("data-status", newStatus);

            // Update the status icon
            const statusIcon = li.querySelector(".status-icon");
            if (statusIcon) {
              try {
                statusIcon.innerHTML = getStatusIcon(newStatus);
                anyStatusChanged = true;

                // Add appropriate animation based on status
                if (newStatus === "processing") {
                  li.classList.add("pulse-animation");
                } else if (
                  newStatus === "completed" ||
                  newStatus === "accepted" ||
                  newStatus === "code_received"
                ) {
                  li.classList.add("success-animation");
                  setTimeout(
                    () => li.classList.remove("success-animation"),
                    2000
                  );
                } else if (
                  newStatus === "failed" ||
                  newStatus === "needs_rework"
                ) {
                  li.classList.add("error-animation");
                  setTimeout(
                    () => li.classList.remove("error-animation"),
                    2000
                  );
                }

                console.log(
                  `[Queue Dynamic Update] Task ${taskId} in ${role} queue updated to status: ${newStatus}`
                );
              } catch (e) {
                console.error(
                  `Error updating status icon for task ${taskId} to ${newStatus}:`,
                  e
                );
              }
            }

            // Remove transition class after update is complete
            setTimeout(() => {
              li.classList.remove("status-changing");
            }, 300);
          }, 150); // Short delay for transition effect
        }
      }
    });
  });

  return anyStatusChanged;
}

// Project Summary Functions
function updateProjectSummary(data) {
  console.log("[ProjectSummary] Updating project summary with data:", data);

  // Update project name and description
  const projectName = document.getElementById("project-name");
  const projectDescription = document.getElementById("project-description");
  // const filesCount = document.getElementById("project-files-count"); // For logging if needed, not for dynamic update
  // const projectProgress = document.getElementById("project-progress"); // This ID is removed from HTML structure
  // const projectStatusLabel = document.getElementById("project-status-label"); // This ID is removed from HTML structure
  // const lastActivity = document.getElementById("project-last-activity"); // For logging if needed, not for dynamic update

  // New elements for header stats
  const projectHeaderTotalTasksEl = document.getElementById(
    "project-header-total-tasks"
  );
  const projectHeaderCompletedTasksEl = document.getElementById(
    "project-header-completed-tasks"
  );
  const projectHeaderStatusEfficiencyEl = document.getElementById(
    "project-header-status-efficiency"
  );

  if (
    !projectName ||
    !projectDescription ||
    !projectHeaderTotalTasksEl || // Check new elements
    !projectHeaderCompletedTasksEl ||
    !projectHeaderStatusEfficiencyEl
    // !filesCount || // Not critical if only logged
    // !lastActivity // Not critical if only logged
  ) {
    console.error(
      "[ProjectSummary] One or more summary elements not found in DOM"
    );
    // return; // Allow partial update if some elements are missing but core ones are present
  }

  // Set default project name if we can't extract it
  let name = "AI-SYSTEMS Project";
  let description = "Multi-agent AI system for automated software development";

  // Extract from target if available
  if (data.target && typeof data.target === "string") {
    const targetLines = data.target.trim().split("\n");
    if (targetLines.length > 0) {
      const firstLine = targetLines[0].trim();
      // Look for project name patterns like "Project: Name" or just take first line
      const match = firstLine.match(/^(?:Project:)?\s*(.+)$/i);
      if (match && match[1]) {
        name = match[1];
      } else {
        name = firstLine;
      }

      // Get description from remaining lines if available
      if (targetLines.length > 1) {
        description = targetLines.slice(1).join(" ").trim();
      }
    }
  }

  // Extract project name from repo structure if target doesn't have it
  if (name === "AI-SYSTEMS Project" && data.structure && data.structure.repo) {
    const projectDirs = Object.keys(data.structure.repo);
    if (projectDirs.length > 0 && projectDirs[0] !== "project_name") {
      // Use the actual project directory name instead of placeholder
      name =
        projectDirs[0].charAt(0).toUpperCase() +
        projectDirs[0].slice(1) +
        " Project";
    }
  }

  // Update DOM elements for name and description
  if (projectName) projectName.textContent = name;
  if (projectDescription) projectDescription.textContent = description;

  // --- Logic for Total, Completed, Efficiency for Header ---
  let headerTotalTasks = actualTotalTasks; // Always use the global actualTotalTasks for total

  let headerCompletedTasksValue;

  if (data.type === "full_status_update") {
    // For full update, recalculate from all subtasks
    const relevantSubtasks = data.subtasks || subtask_status;
    headerCompletedTasksValue = Object.values(relevantSubtasks).filter(
      (status) =>
        status === "accepted" ||
        status === "completed" ||
        status === "code_received" ||
        status === "tested" ||
        status === "documented" ||
        status === "skipped"
    ).length;
    if (projectHeaderCompletedTasksEl)
      projectHeaderCompletedTasksEl.textContent = headerCompletedTasksValue;
  } else if (
    data.type === "monitoring_update" &&
    data.completed_tasks !== undefined
  ) {
    // For monitoring update, use its completed_tasks field directly for the header
    headerCompletedTasksValue = data.completed_tasks;
    if (projectHeaderCompletedTasksEl)
      projectHeaderCompletedTasksEl.textContent = headerCompletedTasksValue;
  } else {
    // For other partial updates (e.g., specific_update, subtask_only_update from non-monitoring sources),
    // DO NOT update the header's completed tasks count directly from subtasks.
    // It will retain its last value set by full_status or monitoring_update.
    // We still need a value for efficiency calculation, so read current text content.
    if (projectHeaderCompletedTasksEl) {
      headerCompletedTasksValue = parseInt(
        projectHeaderCompletedTasksEl.textContent,
        10
      );
      if (isNaN(headerCompletedTasksValue)) {
        // Fallback if textContent is not a number (e.g., initial '-')
        // For the very first load or if the value is not a number, calculate from global status as a baseline
        const relevantGlobalSubtasks = subtask_status;
        headerCompletedTasksValue = Object.values(
          relevantGlobalSubtasks
        ).filter(
          (status) =>
            status === "accepted" ||
            status === "completed" ||
            status === "code_received" ||
            status === "tested" ||
            status === "documented" ||
            status === "skipped"
        ).length;
        // Optionally set the text content here if it was '-' to avoid NaN in subsequent reads before a proper update
        if (projectHeaderCompletedTasksEl.textContent === "-") {
          projectHeaderCompletedTasksEl.textContent = headerCompletedTasksValue;
        }
      }
    } else {
      // Fallback if element doesn't exist yet (should not happen after DOMContentLoaded)
      const relevantGlobalSubtasks = subtask_status;
      headerCompletedTasksValue = Object.values(relevantGlobalSubtasks).filter(
        (status) =>
          status === "accepted" ||
          status === "completed" ||
          status === "code_received" ||
          status === "tested" ||
          status === "documented" ||
          status === "skipped"
      ).length;
    }
  }

  // Update Total Tasks in header (always reflects actualTotalTasks)
  if (projectHeaderTotalTasksEl)
    projectHeaderTotalTasksEl.textContent = headerTotalTasks;

  // Calculate and Update Efficiency in header
  let headerEfficiency = 0;
  // Ensure headerCompletedTasksValue is a number before division
  const numericCompletedTasks = Number(headerCompletedTasksValue);
  if (headerTotalTasks > 0 && !isNaN(numericCompletedTasks)) {
    headerEfficiency = (numericCompletedTasks / headerTotalTasks) * 100;
  }

  if (projectHeaderStatusEfficiencyEl) {
    if (
      headerEfficiency >= 100 &&
      headerTotalTasks > 0 &&
      numericCompletedTasks >= headerTotalTasks
    ) {
      // Ensure completed is also >= total for 100%
      projectHeaderStatusEfficiencyEl.textContent = "COMPLETE";
      projectHeaderStatusEfficiencyEl.classList.add("complete");
    } else {
      projectHeaderStatusEfficiencyEl.textContent = `${headerEfficiency.toFixed(
        1
      )}%`;
      projectHeaderStatusEfficiencyEl.classList.remove("complete");
    }
  }

  // Update files count (commented out as per previous request for no dynamic update)
  let fileCount = 0;
  if (data.structure) {
    fileCount = countFilesInStructure(data.structure);
    // filesCount.textContent = fileCount; // DO NOT UPDATE FILES COUNT
  }

  // Old progress percentage logic (now handled by headerEfficiency)
  // let progressPercent = 0; ...
  // if (projectProgress) { ... } // DO NOT UPDATE (element removed)
  // Old status label logic (now handled by projectHeaderStatusEfficiencyEl)
  // if (progressPercent >= 100) { ... } // DO NOT UPDATE (element removed)

  // Update last activity time (commented out as per previous request for no dynamic update)
  // if (data.last_activity_time) { ... }

  console.log(
    "[ProjectSummary] Updated with name:",
    name,
    "description:",
    description,
    "files (static):",
    document.getElementById("project-files-count")?.textContent || "-",
    "headerTotal:",
    headerTotalTasks,
    "headerCompleted:",
    projectHeaderCompletedTasksEl?.textContent || headerCompletedTasksValue, // Log what's displayed or calculated
    "headerStatus/Efficiency:",
    projectHeaderStatusEfficiencyEl?.textContent || "-",
    "lastActivity (static):",
    document.getElementById("project-last-activity")?.textContent || "-"
  );
}

function countFilesInStructure(structure) {
  let count = 0;

  function traverseStructure(node) {
    if (!node || typeof node !== "object") return;

    for (const key in node) {
      if (Object.hasOwn(node, key)) {
        const value = node[key];

        if (typeof value === "object" && value !== null) {
          // This is a directory, recursively count its files
          traverseStructure(value);
        } else {
          // This is a file
          count++;
        }
      }
    }
  }

  traverseStructure(structure);
  return count;
}

// Initialize and update Timeline chart
let timelineChart;

function initializeTimelineChart() {
  const canvasElement = document.getElementById("timelineChart");
  if (!canvasElement) {
    console.error("[Timeline] Canvas element 'timelineChart' not found.");
    return;
  }

  // Check if Chart.js knows about an instance on this canvas
  // and destroy it if it exists, to prevent "Canvas is already in use" error.
  const existingChartInstance = Chart.getChart(canvasElement);
  if (existingChartInstance) {
    console.log(
      "[Timeline] Destroying existing chart instance on canvas 'timelineChart'."
    );
    existingChartInstance.destroy();
  }

  // Now that the canvas is guaranteed to be free (or was already free),
  // we can create our new chart.
  // The global `timelineChart` variable will store this new instance.

  const ctx = canvasElement.getContext("2d");
  if (!ctx) {
    // Should not happen if canvasElement was found, but good practice
    console.error(
      "[Timeline] Failed to get 2D context from canvas 'timelineChart'."
    );
    return;
  }

  const baseOptions = getBaseChartOptions();

  timelineChart = new Chart(ctx, {
    type: "line",
    data: {
      // labels: [], // Labels array is not primarily used for x-axis in time series
      datasets: [
        {
          label: "Created Files",
          data: [],
          borderColor: "rgb(59, 130, 246)", // Bright blue
          backgroundColor: "rgba(59, 130, 246, 0.2)",
          borderWidth: 2,
          tension: 0.4,
          fill: true,
          pointBackgroundColor: "rgb(59, 130, 246)",
          pointBorderColor: "#fff",
          pointRadius: 4,
          pointHoverRadius: 6,
        },
        {
          label: "Tasks Completed",
          data: [],
          borderColor: "rgb(16, 185, 129)", // Green
          backgroundColor: "rgba(16, 185, 129, 0.2)",
          borderWidth: 2,
          tension: 0.4,
          fill: true,
          pointBackgroundColor: "rgb(16, 185, 129)",
          pointBorderColor: "#fff",
          pointRadius: 4,
          pointHoverRadius: 6,
        },
      ],
    },
    options: {
      ...baseOptions,
      plugins: {
        ...baseOptions.plugins,
        title: {
          ...baseOptions.plugins.title,
          text: "Task Timeline",
        },
      },
      scales: {
        ...baseOptions.scales, // Inherits y-axis settings from base
        x: {
          ...baseOptions.scales.x, // Inherits grid/tick color from base
          type: "time",
          time: {
            unit: "minute",
            displayFormats: {
              minute: "HH:mm", // e.g., 14:30
            },
            tooltipFormat: "MMM d, HH:mm", // e.g., May 7, 14:30
          },
          title: {
            display: true,
            text: "Time",
            color: baseOptions.plugins.title.color,
          },
        },
      },
    },
  });
  console.log("[Timeline] New timeline chart initialized successfully.");
}

function updateTimelineChart(data) {
  if (!timelineChart) {
    initializeTimelineChart();
    if (!timelineChart) {
      console.error("[Timeline] Failed to initialize timeline chart");
      return;
    }
  }

  console.log("[Timeline] Updating timeline chart with data:", data);

  const MAX_POINTS = 60; // Show up to 60 data points (e.g., 1 hour if 1 point/min)

  // Create a synthetic timeline if we don't have explicit timeline data
  if (!data.timeline_data && data.progress_data) {
    const timestamp = data.progress_data.timestamp || new Date().toISOString();
    const completedTasks = data.progress_data.completed_tasks || 0;
    let fileCount = 0;
    if (data.structure) {
      fileCount = countFilesInStructure(data.structure);
    } else if (data.git_activity?.values?.length > 0) {
      fileCount = data.git_activity.values.reduce((a, b) => a + b, 0); // Example: sum of git actions as a proxy
    }

    const pointDate = new Date(timestamp);

    // Add data point to chart datasets
    timelineChart.data.datasets[0].data.push({ x: pointDate, y: fileCount });
    timelineChart.data.datasets[1].data.push({
      x: pointDate,
      y: completedTasks,
    });

    console.log("[Timeline] Added data point:", {
      time: pointDate,
      files: fileCount,
      tasks: completedTasks,
    });
  } else if (data.timeline_data) {
    // Use explicit timeline data if available
    const labels = data.timeline_data.labels || [];

    if (data.timeline_data.files_created) {
      timelineChart.data.datasets[0].data = labels.map((label, index) => ({
        x: new Date(label), // Assuming label is a valid timestamp
        y: data.timeline_data.files_created[index],
      }));
    } else {
      timelineChart.data.datasets[0].data = []; // Clear if no data
    }

    if (data.timeline_data.tasks_completed) {
      timelineChart.data.datasets[1].data = labels.map((label, index) => ({
        x: new Date(label), // Assuming label is a valid timestamp
        y: data.timeline_data.tasks_completed[index],
      }));
    } else {
      timelineChart.data.datasets[1].data = []; // Clear if no data
    }
    console.log("[Timeline] Updated from explicit timeline data");
  }

  // Limit data points for all datasets
  timelineChart.data.datasets.forEach((dataset) => {
    // Sort data by time (x-value) to ensure shift removes the oldest
    dataset.data.sort((a, b) => a.x - b.x);
    while (dataset.data.length > MAX_POINTS) {
      dataset.data.shift(); // Remove the oldest data point
    }
  });

  // Apply current theme colors
  updateChartTheme(timelineChart, getChartFontColor());

  // Update the chart
  timelineChart.update();
}

// ADDED: Force immediate update even if there's only one data point
// This section was removed as time-axis handles single points by showing them,
// and the primary request is for 1-minute axis ticks.
// The "add second point" logic might conflict or be redundant.

// Enhanced File Explorer Functions
function setupEnhancedFileExplorer() {
  // File search functionality
  const searchInput = document.getElementById("file-search-input");
  const searchButton = document.getElementById("file-search-button");

  if (searchInput && searchButton) {
    searchButton.addEventListener("click", () =>
      performFileSearch(searchInput.value)
    );
    searchInput.addEventListener("keyup", (e) => {
      if (e.key === "Enter") {
        performFileSearch(searchInput.value);
      } else if (searchInput.value === "") {
        // Clear search highlighting if search field is emptied
        clearFileSearchHighlighting();
      }
    });
  }

  // Expand/collapse all functionality
  const expandAllButton = document.getElementById("expand-all-button");
  const collapseAllButton = document.getElementById("collapse-all-button");

  if (expandAllButton) {
    expandAllButton.addEventListener("click", expandAllFolders);
  }

  if (collapseAllButton) {
    collapseAllButton.addEventListener("click", collapseAllFolders);
  }

  // Refresh structure button
  const refreshButton = document.getElementById("refresh-structure-button");
  if (refreshButton) {
    refreshButton.addEventListener("click", refreshFileStructure);
  }

  // Editor actions
  const saveFileButton = document.getElementById("save-file-button");
  const copyContentButton = document.getElementById("copy-content-button");

  if (saveFileButton) {
    saveFileButton.addEventListener("click", saveCurrentFile);
  }

  if (copyContentButton) {
    copyContentButton.addEventListener("click", copyEditorContent);
  }
}

function performFileSearch(query) {
  if (!query) return;

  query = query.toLowerCase();
  console.log(`[FileSearch] Searching for: ${query}`);

  const fileStructure = document.getElementById("file-structure");
  if (!fileStructure) return;

  // Clear previous search highlights
  clearFileSearchHighlighting();

  // Search through all file elements
  const fileElements = fileStructure.querySelectorAll(".file");
  let matchFound = false;

  fileElements.forEach((fileElement) => {
    const fileName = fileElement.textContent.toLowerCase();

    if (fileName.includes(query)) {
      fileElement.classList.add("search-match");

      // Expand parent folders to show the match
      let parent = fileElement.closest("li");
      while (parent) {
        if (parent.classList.contains("folder-item")) {
          parent.classList.add("expanded");
        }
        parent = parent.parentElement.closest("li");
      }

      matchFound = true;
    }
  });

  if (!matchFound) {
    showNotification(`No files found containing "${query}"`, "warning");
  } else {
    // Scroll to first match
    const firstMatch = fileStructure.querySelector(".search-match");
    if (firstMatch) {
      firstMatch.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }
}

function clearFileSearchHighlighting() {
  const fileStructure = document.getElementById("file-structure");
  if (!fileStructure) return;

  const highlightedElements = fileStructure.querySelectorAll(".search-match");
  highlightedElements.forEach((element) => {
    element.classList.remove("search-match");
  });
}

function expandAllFolders() {
  const fileStructure = document.getElementById("file-structure");
  if (!fileStructure) return;

  const folderItems = fileStructure.querySelectorAll(".folder-item");
  folderItems.forEach((item) => {
    item.classList.add("expanded");
  });

  showNotification("All folders expanded", "info");
}

function collapseAllFolders() {
  const fileStructure = document.getElementById("file-structure");
  if (!fileStructure) return;

  const folderItems = fileStructure.querySelectorAll(".folder-item");
  folderItems.forEach((item) => {
    item.classList.remove("expanded");
  });

  showNotification("All folders collapsed", "info");
}

function refreshFileStructure() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: "get_file_structure" }));
    showNotification("Refreshing file structure...", "info");
  } else {
    showNotification("Cannot refresh: WebSocket connection is closed", "error");
  }
}

// Current file tracking
let currentFilePath = "";

function saveCurrentFile() {
  if (!currentFilePath || !editor) {
    showNotification("No file selected to save", "warning");
    return;
  }

  const content = editor.getValue();

  // Send save request to server
  fetchWithTimeout(
    "/save_file",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path: currentFilePath,
        content: content,
      }),
    },
    10000
  )
    .then((response) => {
      if (response.ok) {
        showNotification(`File saved: ${currentFilePath}`, "success");
        document.getElementById("save-file-button").disabled = true;
      } else {
        return response.text().then((text) => {
          throw new Error(`Failed to save file: ${text}`);
        });
      }
    })
    .catch((error) => {
      console.error("Error saving file:", error);
      showNotification(`Error saving file: ${error.message}`, "error");
    });
}

async function fetchWithTimeout(resource, options, timeout = 8000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(resource, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    throw error;
  }
}

function copyEditorContent() {
  if (!editor) {
    showNotification("Editor not available", "warning");
    return;
  }

  const content = editor.getValue();

  if (!content) {
    showNotification("No content to copy", "warning");
    return;
  }

  // Use modern clipboard API with fallback
  if (navigator.clipboard) {
    navigator.clipboard
      .writeText(content)
      .then(() => {
        showNotification("Content copied to clipboard", "success");
      })
      .catch((err) => {
        console.error("Could not copy text:", err);
        fallbackCopyTextToClipboard(content);
      });
  } else {
    fallbackCopyTextToClipboard(content);
  }
}

function fallbackCopyTextToClipboard(text) {
  // Fallback for browsers without clipboard API
  const textArea = document.createElement("textarea");
  textArea.value = text;

  // Make the textarea out of viewport
  textArea.style.position = "fixed";
  textArea.style.left = "-999999px";
  textArea.style.top = "-999999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    const successful = document.execCommand("copy");
    const msg = successful
      ? "Content copied to clipboard"
      : "Unable to copy content";
    showNotification(msg, successful ? "success" : "warning");
  } catch (err) {
    console.error("Fallback: Oops, unable to copy", err);
    showNotification("Failed to copy content", "error");
  }

  document.body.removeChild(textArea);
}

// Track editor changes
function setupEditorChangeTracking() {
  if (!editor) return;

  editor.onDidChangeModelContent((e) => {
    // Enable save button when content changes
    const saveButton = document.getElementById("save-file-button");
    if (saveButton) {
      saveButton.disabled = false;
    }
  });
}

// Enhanced file structure renderer
function updateFileStructure(structure) {
  const fileStructureDiv = document.getElementById("file-structure");
  if (!fileStructureDiv) {
    console.error("File structure container not found!");
    return;
  }

  console.log("Updating file structure with data:", structure);

  fileStructureDiv.innerHTML = "";

  if (
    !structure ||
    typeof structure !== "object" ||
    Object.keys(structure).length === 0
  ) {
    fileStructureDiv.innerHTML =
      "<p><em>Project structure is empty or unavailable.</em></p>";
    return;
  }

  const rootUl = document.createElement("ul");
  fileStructureDiv.appendChild(rootUl);

  renderNode(structure, rootUl);

  // Update project summary with file count
  const fileCount = countFilesInStructure(structure);
  const filesCountElement = document.getElementById("project-files-count");
  if (filesCountElement) {
    filesCountElement.textContent = fileCount;
  }
}

function renderNode(node, parentUl, currentPath = "") {
  if (typeof node !== "object" || node === null) {
    console.error(`Invalid node at path '${currentPath}'`);
    return;
  }

  const entries = Object.entries(node).sort(
    ([keyA, valueA], [keyB, valueB]) => {
      const isDirA = typeof valueA === "object" && valueA !== null;
      const isDirB = typeof valueB === "object" && valueB !== null;

      // Folders first, then files
      if (isDirA !== isDirB) {
        return isDirA ? -1 : 1;
      }

      // Alphabetical sorting
      return String(keyA).localeCompare(String(keyB));
    }
  );

  for (const [key, value] of entries) {
    const li = document.createElement("li");
    parentUl.appendChild(li);

    const isDirectory = typeof value === "object" && value !== null;
    const itemPath = currentPath ? `${currentPath}/${key}` : key;

    if (isDirectory) {
      // Directory
      li.classList.add("folder-item");
      li.innerHTML = `<span class="folder"><i class="fas fa-folder"></i> ${key}</span>`;

      const folderSpan = li.querySelector(".folder");
      folderSpan.addEventListener("click", (e) => {
        li.classList.toggle("expanded");

        // Change icon when expanded/collapsed
        const icon = folderSpan.querySelector("i");
        if (li.classList.contains("expanded")) {
          icon.classList.remove("fa-folder");
          icon.classList.add("fa-folder-open");
        } else {
          icon.classList.remove("fa-folder-open");
          icon.classList.add("fa-folder");
        }

        e.stopPropagation();
      });

      const subUl = document.createElement("ul");
      li.appendChild(subUl);

      if (Object.keys(value).length > 0) {
        renderNode(value, subUl, itemPath);
      } else {
        // Empty folder
        const emptyLi = document.createElement("li");
        emptyLi.innerHTML = "<em>Empty folder</em>";
        emptyLi.style.color = "var(--secondary-color)";
        emptyLi.style.fontStyle = "italic";
        subUl.appendChild(emptyLi);
      }
    } else {
      // File
      const iconClass = getFileIcon(key);
      li.innerHTML = `<span class="file" data-path="${itemPath}"><i class="fas ${iconClass}"></i> ${key}</span>`;

      const fileSpan = li.querySelector(".file");
      fileSpan.addEventListener("click", (e) => {
        // Remove previous selection
        const previouslySelected = document.querySelectorAll(".file.selected");
        previouslySelected.forEach((el) => el.classList.remove("selected"));

        // Mark as selected
        fileSpan.classList.add("selected");

        // Load file content
        loadFileContent(itemPath);

        // Update current file path display
        const currentFilePathElement =
          document.getElementById("current-file-path");
        if (currentFilePathElement) {
          currentFilePathElement.textContent = itemPath;
        }

        // Update global tracking variable
        currentFilePath = itemPath;

        e.stopPropagation();
      });
    }
  }
}

// --- New function to save log panel configuration ---
function saveLogPanelConfig(type) {
  if (type === "seconds") {
    const secondsInput = document.getElementById("log-display-seconds");
    if (secondsInput) {
      const newValue = parseInt(secondsInput.value, 10);
      if (!isNaN(newValue) && newValue > 0) {
        logDisplaySeconds = newValue;
        localStorage.setItem("logDisplaySeconds", logDisplaySeconds);
        showNotification(
          `Log display duration set to ${logDisplaySeconds} seconds`,
          "success"
        );
        console.log(`Log display duration saved: ${logDisplaySeconds} seconds`);
      } else {
        // Reset to previously valid value if input is invalid
        secondsInput.value = logDisplaySeconds;
        showNotification(
          "Please enter a valid positive number for seconds",
          "warning"
        );
      }
    }
  } else if (type === "lines") {
    const linesInput = document.getElementById("log-max-lines");
    if (linesInput) {
      const newValue = parseInt(linesInput.value, 10);
      if (!isNaN(newValue) && newValue > 0) {
        maxLogLines = newValue;
        localStorage.setItem("maxLogLines", maxLogLines);
        showNotification(`Maximum log lines set to ${maxLogLines}`, "success");
        console.log(`Maximum log lines saved: ${maxLogLines}`);

        // Trim existing logs if needed
        if (logContent) {
          while (logContent.childElementCount > maxLogLines) {
            if (logContent.firstChild) {
              logContent.removeChild(logContent.firstChild);
            }
          }
        }
      } else {
        // Reset to previously valid value if input is invalid
        linesInput.value = maxLogLines;
        showNotification(
          "Please enter a valid positive number for maximum lines",
          "warning"
        );
      }
    }
  }

  // Keep the panel open after saving configuration
  logPanelMouseIsOver = true;
  setTimeout(() => {
    // Check if mouse is still over the panel after a delay
    const logPanelContainer = document.querySelector(".log-panel-container");
    if (logPanelContainer && !logPanelContainer.matches(":hover")) {
      logPanelMouseIsOver = false;
      retractLogPanel();
    }
  }, 1000); // Longer delay to give user time to see the notification
}

// --- System Load Level Functions ---
function handleSystemLoadChange(value) {
  const loadDescriptionElement = document.getElementById("load-description");
  const loadValue = parseInt(value);

  // Define descriptions for each load level
  const descriptions = {
    1: "Minimal Load (5): Minimal system resources usage, slower but more reliable execution",
    2: "Low Load (10): Low resource usage with balanced reliability",
    3: "Medium Load (15): Balanced resource usage and performance",
    4: "High Load (20): High performance with increased resource usage",
    5: "Maximum Load (25): Maximum throughput with highest resource requirements",
  };

  // Update the description text
  if (loadValue >= 1 && loadValue <= 5) {
    loadDescriptionElement.textContent = descriptions[loadValue];
  }

  // Convert slider value (1-5) to actual buffer size (5, 10, 15, 20, 25)
  const bufferSize = loadValue * 5;

  // Send the update to the server
  fetch("/update_config_item", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ai1_desired_active_buffer: bufferSize }),
  })
    .then((response) => response.json())
    .then((data) => {
      // Show a toast or notification
      showToast(
        `System Load Level updated to ${loadValue}/5 (Buffer: ${bufferSize})`,
        "success"
      );

      // Update any UI elements that should reflect the new load level
      updateLoadLevelIndicators(loadValue, bufferSize);
    })
    .catch((error) => {
      console.error("Error updating system load:", error);
      showToast("Failed to update System Load Level", "error");
    });
}

function updateLoadLevelIndicators(levelValue, bufferSize) {
  // Update any additional UI elements that reflect the system load
  // For example, update a badge or status indicator
  const loadBadgeElement = document.getElementById("system-load-badge");
  if (loadBadgeElement) {
    loadBadgeElement.textContent = `${levelValue}/5`;

    // Update badge color based on load level
    loadBadgeElement.className = "badge"; // Reset classes
    if (levelValue <= 2) {
      loadBadgeElement.classList.add("bg-success"); // Green for low load
    } else if (levelValue <= 4) {
      loadBadgeElement.classList.add("bg-warning"); // Yellow for medium load
    } else {
      loadBadgeElement.classList.add("bg-danger"); // Red for high load
    }
  }

  // You could also update a gauge or progress visualization if you have one
  const loadIndicator = document.getElementById("load-indicator");
  if (loadIndicator) {
    loadIndicator.style.width = `${(levelValue / 5) * 100}%`;
  }
}

function showToast(message, type = "info") {
  // Use Bootstrap's toast if available
  if (window.bootstrap && window.bootstrap.Toast) {
    const toastEl = document.getElementById("systemToast");
    const toastBody = toastEl.querySelector(".toast-body");

    // Set message and class
    toastBody.textContent = message;
    toastEl.className = "toast"; // Reset classes
    toastEl.classList.add(`bg-${type === "error" ? "danger" : type}`);
    toastEl.classList.add("text-white");

    // Show the toast
    const toast = new bootstrap.Toast(toastEl);
    toast.show();
  } else {
    // Fallback to console if Bootstrap's toast is not available
    console.log(`Toast (${type}): ${message}`);

    // Simple custom toast implementation
    const toastContainer =
      document.getElementById("toastContainer") ||
      (() => {
        const container = document.createElement("div");
        container.id = "toastContainer";
        container.style.position = "fixed";
        container.style.bottom = "20px";
        container.style.right = "20px";
        container.style.zIndex = "9999";
        document.body.appendChild(container);
        return container;
      })();

    const toast = document.createElement("div");
    toast.className = `custom-toast ${type}`;
    toast.textContent = message;
    toast.style.padding = "10px 15px";
    toast.style.marginBottom = "10px";
    toast.style.borderRadius = "4px";
    toast.style.backgroundColor =
      type === "error"
        ? "#dc3545"
        : type === "success"
        ? "#28a745"
        : type === "warning"
        ? "#ffc107"
        : "#17a2b8";
    toast.style.color = "#fff";
    toast.style.boxShadow = "0 0.25rem 0.75rem rgba(0, 0, 0, 0.1)";

    toastContainer.appendChild(toast);

    // Remove toast after 3 seconds
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.5s";
      setTimeout(() => toastContainer.removeChild(toast), 500);
    }, 3000);
  }
}

// Initialize load level from current config on page load
function initializeSystemLoadLevel() {
  // Assuming we can extract the current value from the server-side rendered page
  // or fetch it from the server
  fetch("/providers")
    .then((response) => response.json())
    .then((data) => {
      const currentBuffer =
        data.current_config?.ai1_desired_active_buffer || 10; // Default to 10

      // Convert buffer size (5, 10, 15, 20, 25) to slider value (1-5)
      const sliderValue = currentBuffer / 5;

      // Set the slider value
      const slider = document.getElementById("system-load-level");
      if (slider) {
        slider.value = sliderValue;

        // Trigger the description update
        handleSystemLoadChange(sliderValue);
      }
    })
    .catch((error) => {
      console.error("Error initializing system load level:", error);
    });
}

// Register event listeners
document.addEventListener("DOMContentLoaded", function () {
  // Set up the system load level slider
  const systemLoadSlider = document.getElementById("ai1-buffer-slider");
  if (systemLoadSlider) {
    // Set initial value from server
    initializeSystemLoadLevel();

    // Add event listener for changes
    systemLoadSlider.addEventListener("change", function () {
      handleSystemLoadChange(this.value);
    });
  }
});

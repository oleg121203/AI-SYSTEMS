let taskChart, progressChart, gitChart, editor, statusPieChart;
let ws;
const reconnectInterval = 5000; // Reconnect interval 5 seconds
const maxReconnectAttempts = 10;
let reconnectAttempts = 0;

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

  ws.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      console.log("WebSocket received data:", data); // Log all received data

      // --- Handle messages potentially missing 'type' field ---
      if (!data.type) {
        if (data.log_line && Object.keys(data).length === 1) {
          // Handle log_line only message
          if (logContent) {
            const logEntry = document.createElement("p");
            logEntry.textContent = data.log_line;
            if (logContent.innerHTML.includes("Connecting to server...")) {
              logContent.innerHTML = "";
            }
            logContent.appendChild(logEntry);
            logContent.scrollTop = logContent.scrollHeight;
          }
          return; // Message handled
        } else if (data.subtasks && Object.keys(data).length === 1) {
          // Handle subtasks only message
          console.log("Processing subtasks-only update:", data.subtasks);
          Object.assign(subtask_status, data.subtasks); // Merge updates
          // Recalculate stats and update charts based on new subtask statuses
          updateStats(subtask_status, null); // Pass null for queues, updateStats will read from DOM if needed
          updateCharts({
            task_status_distribution:
              calculateStatusDistribution(subtask_status),
          }); // Pass calculated distribution
          return; // Message handled
        } else if (data.queues && Object.keys(data).length === 1) {
          // Додаємо обробку повідомлень, що містять лише поле queues
          console.log("Processing queues-only update:", data.queues);
          updateQueues(data.queues);
          // updateQueues calls updateStats. Explicitly call updateCharts for queue-related charts.
          updateCharts({ queues: data.queues }); // Pass queue data for task distribution chart
          return; // Повідомлення оброблено
        }
        // Обробка даних для графіків
        else if (
          data.progress_data ||
          data.git_activity ||
          data.task_status_distribution
        ) {
          console.log("Processing chart updates (no type):", data);
          // Centralize chart updating logic by calling updateCharts
          updateCharts(data);
          return; // Повідомлення оброблено
        }
        // Add more checks here for other potential type-less messages if needed
      }

      // --- Route message based on type (if present) ---
      switch (data.type) {
        case "full_status_update": // Periodic full status
          console.log("Processing full_status_update");
          updateFullUI(data); // This already calls updateCharts
          break;
        case "status_update": // Just AI on/off status
          if (data.ai_status) {
            console.log("Processing status_update (AI status only)");
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
          console.log("Processing specific_update:", data); // Log specific updates
          let needsChartUpdate = false;
          // Update queues first if present
          if (data.queues) {
            updateQueues(data.queues); // updateQueues calls updateStats
            needsChartUpdate = true; // Queue changes affect task chart
          }
          if (data.subtasks) {
            Object.assign(subtask_status, data.subtasks);
            // Recalculate stats using the updated subtask_status and potentially updated queues
            updateStats(subtask_status, data.queues);
            needsChartUpdate = true; // Subtask changes affect status chart and stats
          }
          if (data.structure) {
            updateFileStructure(data.structure);
          }
          // Explicitly call updateCharts if relevant data is present or implied
          // Also include chart-specific data if it arrived in this message
          if (
            needsChartUpdate ||
            data.progress_data ||
            data.git_activity ||
            data.task_status_distribution
          ) {
            // Combine potentially separate data pieces for updateCharts
            const chartUpdateData = {
              queues: data.queues, // For task chart
              task_status_distribution:
                data.task_status_distribution ||
                (needsChartUpdate
                  ? calculateStatusDistribution(subtask_status)
                  : undefined), // For status chart
              progress_data: data.progress_data, // For progress chart
              git_activity: data.git_activity, // For git chart
            };
            updateCharts(chartUpdateData);
          }

          // Handle log lines within specific updates too
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
          // Only warn if type is present but not handled, or if it's an unknown structure without type
          if (
            data.type ||
            (!data.log_line &&
              !data.subtasks) /* Add other known type-less fields */
          ) {
            console.warn(
              "Received unhandled message type or structure:",
              data.type,
              data
            );
          }
        // The generic update attempt is removed from here as specific handlers are preferred.
        // If necessary, a more robust generic handler could be added.
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
    updateStats(subtask_status, data.queues);
  } else if (data.processed !== undefined && data.efficiency !== undefined) {
    // Fallback if only legacy stats are available
    console.log("[Stats Update] Using legacy stats update.");
    updateStatsLegacy(data);
  } else if (data.queues) {
    // If only queues updated, still recalculate stats
    console.log("[Stats Update] Queues updated, recalculating stats.");
    updateStats(subtask_status, data.queues);
  } else {
    // If no relevant data, update stats with current known state
    console.log(
      "[Stats Update] No relevant data in message, updating stats from current global state."
    );
    // Need current queue counts for the new calculation. Get them from the DOM.
    const currentQueuesData = {
      executor: Array(parseInt(queueCounts.executor?.textContent || "0")).fill(
        {}
      ), // Dummy array of correct length
      tester: Array(parseInt(queueCounts.tester?.textContent || "0")).fill({}),
      documenter: Array(
        parseInt(queueCounts.documenter?.textContent || "0")
      ).fill({}),
    };
    updateStats(subtask_status, currentQueuesData);
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

  // Total Tasks should reflect all known subtasks
  const knownTasksCount = Object.keys(current_subtask_statuses).length;
  const total = knownTasksCount; // Use the count of all known statuses as the total

  // Calculate efficiency based on the number of tasks we have status for
  const efficiency =
    knownTasksCount > 0 ? ((completed / knownTasksCount) * 100).toFixed(1) : 0;

  console.log(
    `[Stats Update] Calculated - Completed: ${completed}, In Queues: ${tasksInQueues}, Total Known: ${total}, Efficiency: ${efficiency}%`
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

    const tasks = queuesData[role] || [];
    const currentCount = parseInt(countSpan.textContent || "0", 10);

    // Check if the count or task list structure might change
    // Optimization: Only redraw list if counts differ significantly or structure changes
    if (
      tasks.length !== currentCount ||
      ul.children.length !== tasks.length /* Add more checks if needed */
    ) {
      queuesChanged = true;
      ul.innerHTML = ""; // Clear existing list only if needed
      countSpan.textContent = tasks.length; // Update count

      tasks.forEach((task) => {
        if (!task || !task.id || !task.text) {
          console.warn("Skipping invalid task object in queue:", task);
          return;
        }
        const li = document.createElement("li");
        // Use 'pending' as a default if no status is known yet
        const status = task.status || subtask_status[task.id] || "pending";
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
    } else {
      // Optimization: If count is the same, just update statuses if needed
      Array.from(ul.children).forEach((li, index) => {
        const task = tasks[index];
        if (!task || !task.id) return;
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

function updateCharts(data) {
  console.log("updateCharts called with data:", JSON.stringify(data, null, 2)); // Log incoming data

  const chartColor = getChartFontColor();
  // ... (chartOptions definition remains the same)
  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      y: {
        beginAtZero: true,
        grid: {
          color: `${chartColor}20`, // Напівпрозорі лінії сітки
        },
        ticks: {
          color: chartColor,
          callback: function (value) {
            // Check if label exists and includes '%'
            const label =
              this.chart.config._config.data.datasets[0]?.label || "";
            return value + (label.includes("%") ? "%" : "");
          },
        },
      },
      x: {
        grid: {
          color: `${chartColor}20`,
        },
        ticks: { color: chartColor },
      },
    },
    plugins: {
      legend: {
        labels: {
          color: chartColor,
          font: {
            size: 12,
          },
        },
      },
      title: {
        display: true,
        color: chartColor,
      },
    },
    animation: {
      duration: 750,
      easing: "easeInOutCubic",
    },
  };

  // --- Initialize Charts (if they don't exist) ---

  // Task Distribution Chart (Bar)
  // ... (initialization code remains the same)
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
          ...chartOptions,
          plugins: {
            ...chartOptions.plugins,
            title: {
              ...chartOptions.plugins.title,
              text: "Tasks Distribution",
            },
          },
        },
      });
    }
  }

  // Progress Chart (Line)
  if (!progressChart) {
    const ctx = document.getElementById("progressChart")?.getContext("2d");
    if (ctx) {
      progressChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: [], // Часові мітки або етапи проекту
          datasets: [
            {
              label: "Виконані завдання",
              data: [],
              backgroundColor: "rgba(75, 192, 192, 0.2)",
              borderColor: "rgba(75, 192, 192, 1)",
              borderWidth: 2,
              tension: 0.4,
              fill: false,
              yAxisID: "y",
            },
            {
              label: "Успішні тести",
              data: [],
              backgroundColor: "rgba(54, 162, 235, 0.2)",
              borderColor: "rgba(54, 162, 235, 1)",
              borderWidth: 2,
              tension: 0.4,
              fill: false,
              yAxisID: "y",
            },
            {
              label: "Git дії",
              data: [],
              backgroundColor: "rgba(255, 159, 64, 0.2)",
              borderColor: "rgba(255, 159, 64, 1)",
              borderWidth: 2,
              tension: 0.4,
              fill: false,
              yAxisID: "y",
            },
            {
              label: "Загальний прогрес %",
              data: [],
              backgroundColor: "rgba(153, 102, 255, 0.2)",
              borderColor: "rgba(153, 102, 255, 1)",
              borderWidth: 3,
              tension: 0.4,
              fill: false,
              yAxisID: "y1",
            },
          ],
        },
        options: {
          ...chartOptions,
          scales: {
            ...chartOptions.scales,
            y: {
              ...chartOptions.scales.y,
              position: "left",
              title: {
                display: true,
                text: "Кількість",
                color: getChartFontColor(),
              },
            },
            y1: {
              type: "linear",
              position: "right",
              title: {
                display: true,
                text: "Відсоток завершення",
                color: getChartFontColor(),
              },
              max: 100,
              grid: {
                drawOnChartArea: false,
              },
              ticks: {
                color: getChartFontColor(),
                callback: function (value) {
                  return value + "%";
                },
              },
            },
          },
          plugins: {
            ...chartOptions.plugins,
            title: {
              ...chartOptions.plugins.title,
              text: "Деталі прогресу проєкту",
            },
          },
        },
      });
    }
  }

  // Git Commits Chart (Line)
  // ... (initialization code remains the same)
  if (!gitChart) {
    const ctx = document.getElementById("gitChart")?.getContext("2d");
    if (ctx) {
      gitChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: [], // Example: ['Day 1', 'Day 2', ...]
          datasets: [
            {
              label: "Commits Over Time",
              data: [], // Example: [5, 8, 12, ...]
              backgroundColor: "rgba(255, 159, 64, 0.2)",
              borderColor: "rgba(255, 159, 64, 1)",
              borderWidth: 2,
              tension: 0.4,
              fill: true,
            },
          ],
        },
        options: {
          ...chartOptions,
          plugins: {
            ...chartOptions.plugins,
            title: {
              ...chartOptions.plugins.title,
              text: "Git Activity",
            },
          },
        },
      });
    }
  }

  // Status Distribution Chart (Doughnut)
  // ... (initialization code remains the same)
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
                "rgba(255, 205, 86, 0.7)", // Yellow for Pending
                "rgba(54, 162, 235, 0.7)", // Blue for Processing
                "rgba(75, 192, 192, 0.7)", // Green for Completed
                "rgba(255, 99, 132, 0.7)", // Red for Failed
                "rgba(201, 203, 207, 0.7)", // Grey for Other
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
              labels: { color: chartColor },
            },
            title: {
              display: true,
              text: "Task Statuses",
              color: chartColor,
            },
          },
        },
      });
    }
  }

  // --- Update Chart Data ---

  let chartsUpdated = false;

  // Update Task Distribution (Bar Chart) - Based on QUEUE data
  if (taskChart && data.queues) {
    console.log(
      "[Chart Update] Updating Task Distribution with queue data:",
      data.queues
    );
    const newData = [
      (data.queues.executor || []).length,
      (data.queues.tester || []).length,
      (data.queues.documenter || []).length,
    ];
    // Check if data actually changed before updating
    if (
      JSON.stringify(taskChart.data.datasets[0].data) !==
      JSON.stringify(newData)
    ) {
      taskChart.data.datasets[0].data = newData;
      chartsUpdated = true;
      console.log("[Chart Update] Task Distribution data changed.");
    }
  }

  // Update Progress Chart (Line Chart) - Based on PROGRESS_DATA
  if (progressChart && data.progress_data) {
    console.log(
      "[Chart Update] Updating Progress Chart with data:",
      data.progress_data
    );
    if (data.progress_data.labels && data.progress_data.values) {
      let changed = false;

      // Check labels
      if (
        JSON.stringify(progressChart.data.labels) !==
        JSON.stringify(data.progress_data.labels)
      ) {
        progressChart.data.labels = data.progress_data.labels;
        changed = true;
      }

      // Update datasets if they exist in the data
      const datasetsToUpdate = [
        { index: 0, key: "completed_tasks" },
        { index: 1, key: "successful_tests" },
        { index: 2, key: "git_actions" },
        { index: 3, key: "values" }, // Overall progress percentage
      ];

      datasetsToUpdate.forEach((item) => {
        if (
          data.progress_data[item.key] &&
          JSON.stringify(progressChart.data.datasets[item.index].data) !==
            JSON.stringify(data.progress_data[item.key])
        ) {
          progressChart.data.datasets[item.index].data =
            data.progress_data[item.key];
          changed = true;
        }
      });

      if (changed) {
        console.log("[Chart Update] Progress Chart data changed.");
        chartsUpdated = true;
      }
    } else {
      console.warn(
        "[Chart Update] Progress data received but missing labels or values:",
        data.progress_data
      );
    }
  } else if (progressChart && data.progress) {
    // Legacy support
    // ... existing legacy handling ...
  } else if (progressChart) {
    // console.log("[Chart Update] No progress_data received for Progress Chart.");
  }

  // Update Git Activity Chart (Line Chart) - Based on GIT_ACTIVITY
  if (gitChart && data.git_activity) {
    console.log(
      "[Chart Update] Updating Git Activity Chart with data:",
      data.git_activity
    );
    if (data.git_activity.labels && data.git_activity.values) {
      if (
        JSON.stringify(gitChart.data.labels) !==
          JSON.stringify(data.git_activity.labels) ||
        JSON.stringify(gitChart.data.datasets[0].data) !==
          JSON.stringify(data.git_activity.values)
      ) {
        gitChart.data.labels = data.git_activity.labels;
        gitChart.data.datasets[0].data = data.git_activity.values;
        chartsUpdated = true;
        console.log("[Chart Update] Git Activity data changed.");
      }
    } else {
      console.warn(
        "[Chart Update] Git activity data missing labels or values:",
        data.git_activity
      );
    }
  } else if (gitChart) {
    // console.log("[Chart Update] No git_activity received for Git Chart.");
  }

  // Update Status Distribution Chart (Doughnut Chart) - Based on TASK_STATUS_DISTRIBUTION
  if (statusPieChart && data.task_status_distribution) {
    console.log(
      "[Chart Update] Updating Status Distribution with data:",
      data.task_status_distribution
    );
    const statusCounts = data.task_status_distribution;
    const newData = [
      statusCounts.pending || 0, // Use || 0 as fallback
      statusCounts.processing || 0,
      statusCounts.completed || 0,
      statusCounts.failed || 0,
      statusCounts.other || 0,
    ];
    if (
      JSON.stringify(statusPieChart.data.datasets[0].data) !==
      JSON.stringify(newData)
    ) {
      statusPieChart.data.datasets[0].data = newData;
      chartsUpdated = true;
      console.log("[Chart Update] Status Distribution data changed.");
    }
  } else if (statusPieChart) {
    // console.log("[Chart Update] No task_status_distribution received for Status Chart.");
  }

  // Update all charts if any data changed
  if (chartsUpdated) {
    // Ensure colors are correct for the current theme before updating
    const newChartColor = getChartFontColor(); // Recalculate color

    [taskChart, progressChart, gitChart, statusPieChart].forEach((chart) => {
      if (chart) {
        // Update common options like colors
        if (chart.options.scales) {
          if (chart.options.scales.y) {
            chart.options.scales.y.ticks.color = newChartColor;
            chart.options.scales.y.grid.color = `${newChartColor}20`;
            if (chart.options.scales.y.title)
              chart.options.scales.y.title.color = newChartColor;
          }
          if (chart.options.scales.y1) {
            // For progress chart second axis
            chart.options.scales.y1.ticks.color = newChartColor;
            if (chart.options.scales.y1.title)
              chart.options.scales.y1.title.color = newChartColor;
          }
          if (chart.options.scales.x) {
            chart.options.scales.x.ticks.color = newChartColor;
            chart.options.scales.x.grid.color = `${newChartColor}20`;
          }
        }
        if (chart.options.plugins && chart.options.plugins.legend) {
          chart.options.plugins.legend.labels.color = newChartColor;
        }
        if (chart.options.plugins && chart.options.plugins.title) {
          chart.options.plugins.title.color = newChartColor;
        }
        // Call update
        chart.update();
      }
    });
    console.log("[Chart Update] One or more charts updated visually.");
  } else {
    console.log(
      "[Chart Update] No chart data changed, skipping visual update."
    );
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
      `Rendering node at path: '${currentPath}'. Node type: ${typeof node}`,
      node
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
      console.log(
        `Sorted entries for path '${currentPath}':`,
        entries.map((e) => e[0])
      ); // Log sorted keys
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
        console.log(
          `Processing entry: Key='${key}', Type='${typeof value}', Path='${currentPath}'`
        );
        // ---

        const isDirectory = typeof value === "object" && value !== null;
        const itemPath = currentPath
          ? `${currentPath}/${String(key)}`
          : String(key);

        if (isDirectory) {
          console.log(`Rendering folder: ${itemPath}`);
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
            console.log(`Recursing into folder: ${itemPath}`);
            renderNode(value, subUl, itemPath); // Recurse
          } else {
            console.log(`Folder is empty: ${itemPath}`);
            // Optionally add a placeholder for empty folders
            // subUl.innerHTML = "<li><em>(empty)</em></li>";
          }
        } else {
          // It's a file
          console.log(`Rendering file: ${itemPath}`);
          const iconClass = getFileIcon(String(key));
          console.log(`Icon for ${key}: ${iconClass}`); // Log icon class
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
        // Log the specific error and the item being processed
        console.error(
          `Error rendering node entry: Key='${key}', Path='${currentPath}', ValueType='${typeof value}':`,
          error,
          "Value:",
          value
        );
        // Update the existing li with error message instead of adding a new one
        li.style.color = "red";
        li.textContent = `Error rendering ${key}`; // Keep the original error message format
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

// Need to also define getFileIcon if it's not already defined correctly
function getFileIcon(fileName) {
  // Ensure fileName is treated as a string
  const nameStr = String(fileName);
  // Handle files starting with '.' like .gitignore
  const ext = nameStr.includes(".")
    ? nameStr.split(".").pop().toLowerCase()
    : "";
  const baseName = nameStr.toLowerCase();

  // Prioritize specific names (FontAwesome 6 Free icons)
  // Note: Some brand icons (like fa-python, fa-js) might require FontAwesome Pro or specific setup.
  // Using generic icons for broader compatibility first.
  if (baseName === ".gitignore" || baseName === ".gitattributes")
    return "fa-code-branch"; // Git icon
  if (baseName === "dockerfile") return "fa-box-open"; // Generic box icon for Docker
  if (baseName === "makefile") return "fa-file-code";

  switch (ext) {
    // Code files
    case "py":
      return "fa-file-code"; // Generic code
    case "js":
      return "fa-file-code"; // Generic code
    case "html":
      return "fa-file-code";
    case "css":
      return "fa-file-code"; // fa-css3-alt exists but might need setup
    case "json":
      return "fa-file-code";
    case "md":
      return "fa-file-lines"; // Text file icon
    case "ts":
      return "fa-file-code";
    case "java":
      return "fa-file-code";
    case "c":
    case "h":
      return "fa-file-code";
    case "cpp":
    case "hpp":
      return "fa-file-code";
    case "cs":
      return "fa-file-code";
    case "go":
      return "fa-file-code";
    case "php":
      return "fa-file-code";
    case "rb":
      return "fa-file-code"; // fa-gem exists but might need setup
    case "swift":
      return "fa-file-code";
    case "xml":
      return "fa-file-code";
    case "yaml":
    case "yml":
      return "fa-file-alt"; // Use alt text file icon
    case "sh":
    case "bash":
    case "zsh":
      return "fa-terminal";
    case "sql":
      return "fa-database";

    // Text/Data files
    case "txt":
      return "fa-file-alt";
    case "log":
      return "fa-file-alt";
    case "csv":
      return "fa-file-csv";
    case "tsv":
      return "fa-file-csv"; // Use same icon as CSV

    // Image files
    case "png":
    case "jpg":
    case "jpeg":
    case "gif":
    case "bmp":
    case "ico":
    case "svg":
      return "fa-file-image";

    // Audio files
    case "mp3":
    case "wav":
    case "ogg":
    case "flac":
    case "aac":
      return "fa-file-audio";

    // Video files
    case "mp4":
    case "avi":
    case "mov":
    case "wmv":
    case "mkv":
      return "fa-file-video";

    // Document files
    case "pdf":
      return "fa-file-pdf";
    case "doc":
    case "docx":
      return "fa-file-word";
    case "xls":
    case "xlsx":
      return "fa-file-excel";
    case "ppt":
    case "pptx":
      return "fa-file-powerpoint";

    // Archive files
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return "fa-file-archive";

    // Other
    case "db":
    case "sqlite":
      return "fa-database";

    // Default
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
    // Check if the first chart exists as a proxy for all charts being initialized
    const chartColor = getChartFontColor();
    [taskChart, progressChart, gitChart, statusPieChart].forEach((chart) => {
      if (chart && chart.options) {
        // Check if chart and options exist
        try {
          // Update axis colors only if scales exist (for bar/line charts)
          if (chart.options.scales?.y?.ticks) {
            chart.options.scales.y.ticks.color = chartColor;
          }
          if (chart.options.scales?.x?.ticks) {
            chart.options.scales.x.ticks.color = chartColor;
          }

          // Update legend colors if legend exists
          if (chart.options.plugins?.legend?.labels) {
            chart.options.plugins.legend.labels.color = chartColor;
          }

          // Update title color if title exists
          if (chart.options.plugins?.title) {
            chart.options.plugins.title.color = chartColor;
          }

          chart.update(); // Update the chart to apply color changes
        } catch (error) {
          console.error("Error updating chart theme:", error, "Chart:", chart);
        }
      }
    });
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
      updateStats({}, {}); // Reset stats
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
        response.status || "Repository cleared and re-initialized.",
        "success"
      );
      // Optionally, refresh file structure or other UI elements
      fetchAndUpdateStructure(); // Assuming this function exists to refresh the file tree
    } catch (error) {
      // Error already shown by sendRequest
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
  updateStats({}, {}); // Виправлено виклик функції з updateStatsFromSubtasks на updateStats

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

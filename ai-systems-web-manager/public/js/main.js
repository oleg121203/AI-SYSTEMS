// Connect to Socket.IO server
const socket = io();

// DOM elements
const outputElement = document.getElementById('output');
const outputContainer = document.getElementById('output-container');
const clearOutputBtn = document.getElementById('clear-output');
const toggleExpandBtn = document.getElementById('toggle-expand');
const statusContainer = document.getElementById('status-container');
const volumesList = document.getElementById('volumes-list');
const networksList = document.getElementById('networks-list');
const volumeCountElement = document.getElementById('volume-count');
const backupCountElement = document.getElementById('backup-count');
const actionButtons = document.querySelectorAll('.action-btn');
const confirmModal = document.getElementById('confirm-modal');
const confirmMessage = document.getElementById('confirm-message');
const confirmYesBtn = document.getElementById('confirm-yes');
const confirmNoBtn = document.getElementById('confirm-no');
const testingDropdownToggle = document.getElementById('testing-dropdown-toggle');
const testingDropdown = document.getElementById('testing-dropdown');
const commandInputContainer = document.getElementById('command-input-container');
const commandInput = document.getElementById('command-input');
const runCommandBtn = document.getElementById('run-command');
const helpButton = document.getElementById('help-button');
const helpModal = document.getElementById('help-modal');
const helpCloseBtn = document.getElementById('help-close');

// Current script being executed
let currentScriptId = null;
let currentCustomCommand = null;

// Flag to track if the current script is confirmed and should display output
let scriptConfirmed = false;

// Initialize the page
document.addEventListener('DOMContentLoaded', function() {
  const socket = io();
  const output = document.getElementById('output');
  const clearBtn = document.getElementById('clear-output');
  const actionButtons = document.querySelectorAll('.action-btn');
  const statusContainer = document.getElementById('status-container');
  const toggleExpandBtn = document.getElementById('toggle-expand');
  const outputContainer = document.getElementById('output-container');
  const commandInputContainer = document.getElementById('command-input-container');
  const commandInput = document.getElementById('command-input');
  const runCommandBtn = document.getElementById('run-command');
  const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
  
  // Initialize typing effect for headers
  document.querySelectorAll('.typing').forEach(element => {
      const text = element.textContent;
      element.textContent = '';
      let i = 0;
      const typeInterval = setInterval(() => {
          if (i < text.length) {
              element.textContent += text.charAt(i);
              i++;
          } else {
              clearInterval(typeInterval);
          }
      }, 100);
  });
  
  // Toggle dropdown menus
  dropdownToggles.forEach(toggle => {
      toggle.addEventListener('click', function() {
          const dropdownContent = this.nextElementSibling;
          const isActive = dropdownContent.classList.contains('active');
          
          // Close all dropdowns
          document.querySelectorAll('.dropdown-content').forEach(dropdown => {
              dropdown.classList.remove('active');
          });
          document.querySelectorAll('.dropdown-toggle').forEach(btn => {
              btn.classList.remove('active');
          });
          
          // Toggle current dropdown
          if (!isActive) {
              dropdownContent.classList.add('active');
              this.classList.add('active');
          }
      });
  });
  
  // Toggle expand output
  toggleExpandBtn.addEventListener('click', toggleExpandOutput);
  
  // Clear output
  clearBtn.addEventListener('click', function() {
      output.innerHTML = '';
  });
  
  // Run script when action button is clicked
  actionButtons.forEach(button => {
      button.addEventListener('click', function() {
          const scriptId = this.getAttribute('data-script');
          socket.emit('run-script', scriptId);
          
          // Add command to output
          const scriptName = this.textContent.trim();
          output.innerHTML += `<div class="command">root@ai-systems:~# Running: ${scriptName}...</div>`;
          output.scrollTop = output.scrollHeight;
          
          // Auto-expand output when running a command
          if (!outputContainer.classList.contains('expanded')) {
              toggleExpandOutput();
          }
      });
  });
  
  // Run custom command
  function runCustomCommand() {
      const command = commandInput.value.trim();
      if (command) {
          socket.emit('run-custom-command', command);
          output.innerHTML += `<div class="command">root@ai-systems:~# ${command}</div>`;
          output.scrollTop = output.scrollHeight;
          commandInput.value = '';
      }
  }
  
  runCommandBtn.addEventListener('click', runCustomCommand);
  
  // Run command on Enter key
  commandInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
          runCustomCommand();
      }
  });
  
  // Listen for script output
  socket.on('script-output', function(data) {
      // Process ANSI color codes
      const processedData = processAnsiCodes(data);
      output.innerHTML += `<div>${processedData}</div>`;
      output.scrollTop = output.scrollHeight;
  });
  
  // Process ANSI color codes
  function processAnsiCodes(text) {
      // Replace ANSI color codes with CSS classes
      // This is a simplified version - a full implementation would handle more codes
      return text
          .replace(/\x1b\[31m([^\x1b]*)\x1b\[0m/g, '<span style="color: #ff3333;">$1</span>') // Red
          .replace(/\x1b\[32m([^\x1b]*)\x1b\[0m/g, '<span style="color: #00ff00;">$1</span>') // Green
          .replace(/\x1b\[33m([^\x1b]*)\x1b\[0m/g, '<span style="color: #ffff00;">$1</span>') // Yellow
          .replace(/\x1b\[34m([^\x1b]*)\x1b\[0m/g, '<span style="color: #3333ff;">$1</span>') // Blue
          .replace(/\x1b\[36m([^\x1b]*)\x1b\[0m/g, '<span style="color: #00ffff;">$1</span>') // Cyan
          .replace(/\x1b\[[0-9;]*[mK]/g, ''); // Remove any remaining ANSI codes
  }
  
  // Listen for script error
  socket.on('script-error', function(data) {
      output.innerHTML += `<div class="error">${data}</div>`;
      output.scrollTop = output.scrollHeight;
  });
  
  // Listen for script completion
  socket.on('script-complete', function(data) {
      output.innerHTML += `<div class="success">Command completed with exit code: ${data}</div>`;
      output.scrollTop = output.scrollHeight;
      
      // Refresh status after script completion
      socket.emit('get-status');
  });
  
  // Get initial status
  socket.emit('get-status');
  
  // Listen for status updates
  socket.on('status-update', function(data) {
      statusContainer.innerHTML = '';
      
      data.forEach(service => {
          const statusCard = document.createElement('div');
          statusCard.className = 'status-card';
          
          statusCard.innerHTML = `
              <div class="name">${service.name}</div>
              <div class="status ${service.running ? 'running' : 'stopped'}">
                  ${service.running ? 'RUNNING' : 'STOPPED'}
              </div>
          `;
          
          statusContainer.appendChild(statusCard);
      });
  });
  
  // Add keyboard shortcut for expanding/collapsing output (Ctrl+`)  
  document.addEventListener('keydown', function(e) {
      if (e.ctrlKey && e.key === '`') {
          toggleExpandOutput();
      }
  });
  
  // Focus command input when expanded
  outputContainer.addEventListener('transitionend', function() {
      if (outputContainer.classList.contains('expanded')) {
          commandInput.focus();
      }
  });
  
  // Load initial system status
  updateSystemStatus();
  
  // Set up event listeners
  setupEventListeners();
});

// Set up all event listeners
function setupEventListeners() {
  // Clear output button
  clearOutputBtn.addEventListener('click', () => {
      outputElement.innerHTML = '';
  });
  
  // Toggle expand button
  toggleExpandBtn.addEventListener('click', toggleExpandOutput);
  
  // Action buttons
  actionButtons.forEach(button => {
      button.addEventListener('click', () => {
          const scriptId = button.getAttribute('data-script');
          requestRunScript(scriptId);
      });
  });
  
  // Testing dropdown toggle
  if (testingDropdownToggle) {
      testingDropdownToggle.addEventListener('click', () => {
          testingDropdownToggle.classList.toggle('active');
          testingDropdown.classList.toggle('active');
      });
  }
  
  // Command input
  commandInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
          executeCustomCommand();
      }
  });
  
  runCommandBtn.addEventListener('click', executeCustomCommand);
  
  // Help button
  helpButton.addEventListener('click', () => {
      helpModal.style.display = 'flex';
  });
  
  helpCloseBtn.addEventListener('click', () => {
      helpModal.style.display = 'none';
  });
  
  // Confirmation modal buttons
  confirmYesBtn.addEventListener('click', () => {
      const scriptId = confirmYesBtn.getAttribute('data-script');
      const customCommand = confirmYesBtn.getAttribute('data-custom-command');
      hideConfirmation();
      
      if (customCommand) {
          // Execute custom command
          executeConfirmedCustomCommand(customCommand);
      } else {
          // Execute script
          runScript(scriptId);
      }
  });
  
  confirmNoBtn.addEventListener('click', hideConfirmation);
  
  // Socket.IO event listeners
  socket.on('output', handleScriptOutput);
  socket.on('scriptComplete', handleScriptComplete);
  
  // Set up refresh status timer
  setInterval(updateSystemStatus, 10000); // Update every 10 seconds
  
  // Close modals when clicking outside
  window.addEventListener('click', (e) => {
      if (e.target === confirmModal) {
          hideConfirmation();
      }
      if (e.target === helpModal) {
          helpModal.style.display = 'none';
      }
  });
}

// Show confirmation modal
function showConfirmation(scriptId, scriptName, customCommand, customMessage) {
  // If scriptName is not provided, try to get it from the button
  if (!scriptName) {
    const button = document.querySelector(`[data-script="${scriptId}"]`);
    scriptName = button ? button.textContent.trim() : scriptId;
  }
  
  // Use custom message if provided, otherwise use default
  if (customMessage) {
    confirmMessage.textContent = customMessage;
  } else {
    confirmMessage.textContent = `Are you sure you want to run "${scriptName}"?`;
  }
  
  // Store script ID for confirmation
  confirmYesBtn.setAttribute('data-script', scriptId);
  
  // Store custom command if provided
  if (customCommand) {
    confirmYesBtn.setAttribute('data-custom-command', customCommand);
  } else {
    confirmYesBtn.removeAttribute('data-custom-command');
  }
  
  // Show the modal
  confirmModal.style.display = 'flex';
}

// Hide confirmation modal
function hideConfirmation() {
  confirmModal.style.display = 'none';
}

// Request to run a script (first step - request confirmation)
function requestRunScript(scriptId) {
  // Reset the confirmation flag - no output should be displayed until confirmed
  scriptConfirmed = false;
  
  // Clear output if a different script is being run
  if (currentScriptId !== scriptId) {
    outputElement.innerHTML = '';
  }
  
  currentScriptId = scriptId;
  
  // Disable the button temporarily
  const button = document.querySelector(`[data-script="${scriptId}"]`);
  button.disabled = true;
  
  // Send request to get confirmation
  fetch('/api/request-run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ scriptId })
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`Server responded with status: ${response.status}`);
    }
    return response.text().then(text => {
      try {
        return JSON.parse(text);
      } catch (e) {
        appendToOutput(`Error parsing JSON response: ${text.substring(0, 100)}...\n`, 'error');
        throw new Error('Invalid JSON response from server');
      }
    });
  })
  .then(data => {
    // Re-enable the button
    button.disabled = false;
    
    if (!data.success) {
      appendToOutput(`Error: ${data.message}\n`, 'error');
      return;
    }
    
    // Handle different response statuses
    switch (data.status) {
      case 'no_action_needed':
        // No action needed, just show the message
        appendToOutput(`${data.message}\n`, 'info');
        // Update system status to reflect current state
        updateSystemStatus();
        return;
        
      case 'in_progress':
        // Operation already in progress
        appendToOutput(`${data.message}\n`, 'warning');
        // Update system status to reflect current state
        updateSystemStatus();
        return;
        
      case 'warning':
        // Warning but action still needed
        appendToOutput(`${data.message}\n`, 'warning');
        // Show confirmation with the specific warning message
        showConfirmation(scriptId, data.scriptName, null, data.confirmMessage);
        return;
        
      case 'needs_confirmation':
        // Standard confirmation needed
        showConfirmation(scriptId, data.scriptName);
        return;
        
      default:
        // Legacy handling for backward compatibility
        // Check if action is needed
        if (data.hasOwnProperty('actionNeeded') && !data.actionNeeded) {
          // No action needed, just show the message
          appendToOutput(`${data.message}\n`, 'info');
          // Update system status to reflect current state
          updateSystemStatus();
          return;
        }
        
        // Check if there's a warning message but action is still needed
        if (data.message && data.message.startsWith('Warning:')) {
          // Show warning message but still proceed with confirmation
          appendToOutput(`${data.message}\n`, 'warning');
        }
        
        // Show confirmation dialog if required
        if (data.requiresConfirmation) {
          showConfirmation(scriptId, data.scriptName);
        } else {
          // If no confirmation required but action needed, run directly
          runScript(scriptId);
        }
    }
  })
  .catch(error => {
    appendToOutput(`Error: ${error.message}\n`, 'error');
    button.disabled = false;
  });
}

// Actually run a script (second step - after confirmation)
function runScript(scriptId) {
  // Set the script as confirmed
  scriptConfirmed = true;
  
  // Disable the button
  const button = document.querySelector(`[data-script="${scriptId}"]`);
  button.disabled = true;
  
  // Show loading message
  appendToOutput(`Running script...\n`, 'normal');
  
  // Send request to actually run the script
  fetch('/api/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ scriptId })
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`Server responded with status: ${response.status}`);
    }
    return response.text().then(text => {
      try {
        return JSON.parse(text);
      } catch (e) {
        appendToOutput(`Error parsing JSON response: ${text.substring(0, 100)}...\n`, 'error');
        throw new Error('Invalid JSON response from server');
      }
    });
  })
  .then(data => {
    if (!data.success) {
      appendToOutput(`Error: ${data.message}\n`, 'error');
      button.disabled = false;
    }
  })
  .catch(error => {
    appendToOutput(`Error: ${error.message}\n`, 'error');
    button.disabled = false;
  });
}

// Handle script output from Socket.IO
function handleScriptOutput(data) {
  // Only display output if the script has been confirmed
  if (data.scriptId === currentScriptId && scriptConfirmed) {
    const outputClass = data.error ? 'error' : 'normal';
    appendToOutput(data.data, outputClass);
  }
}

// Handle script completion from Socket.IO
function handleScriptComplete(data) {
  if (data.scriptId === currentScriptId) {
    // Make sure the completed message is displayed even if script wasn't confirmed
    scriptConfirmed = true;
    
    const outputClass = data.success ? 'success' : 'error';
    appendToOutput(`\nScript completed with exit code: ${data.exitCode}\n`, outputClass);
    
    // Reset script confirmation flag
    scriptConfirmed = false;
    
    // Re-enable the button
    const button = document.querySelector(`[data-script="${data.scriptId}"]`);
    button.disabled = false;
    
    // Add success/error class for flashing effect
    button.classList.remove('success', 'error');
    button.classList.add(data.success ? 'success' : 'error');
    
    // Remove the class after 5 seconds
    setTimeout(() => {
      button.classList.remove('success', 'error');
    }, 5000);
    
    // Update system status after script completion
    updateSystemStatus();
  }
}

// Append text to the output element
function appendToOutput(text, className) {
  const span = document.createElement('span');
  span.className = className || 'normal';
  span.textContent = text;
  outputElement.appendChild(span);
  
  // Scroll to bottom
  outputElement.scrollTop = outputElement.scrollHeight;
  
  // If command output is expanded, focus the input field
  if (outputContainer.classList.contains('expanded')) {
    commandInput.focus();
  }
}

// Toggle expand output
function toggleExpandOutput() {
  // Force the display of output container before toggling class to ensure animations work
  outputContainer.style.display = 'block';
  
  // Toggle expanded class
  outputContainer.classList.toggle('expanded');
  
  if (outputContainer.classList.contains('expanded')) {
    // Expanded state
    toggleExpandBtn.innerHTML = '<i class="fas fa-compress"></i>';
    commandInputContainer.classList.remove('hidden');
    document.body.style.overflow = 'hidden'; // Prevent scrolling of background
    // Auto-focus the command input when expanded
    setTimeout(() => {
      commandInput.focus();
    }, 100);
    // Add keyboard shortcut for collapse (Escape key)
    document.addEventListener('keydown', collapseOnEscape);
  } else {
    // Collapsed state
    toggleExpandBtn.innerHTML = '<i class="fas fa-expand"></i>';
    commandInputContainer.classList.add('hidden');
    document.body.style.overflow = ''; // Restore scrolling
    // Remove keyboard event listener
    document.removeEventListener('keydown', collapseOnEscape);
  }
  
  // Ensure scrolling to bottom
  outputElement.scrollTop = outputElement.scrollHeight;
}

// Helper function to collapse terminal on Escape key
function collapseOnEscape(e) {
  if (e.key === 'Escape' && outputContainer.classList.contains('expanded')) {
    toggleExpandOutput();
  }
}

// Request to execute custom command (first step - request confirmation)
function executeCustomCommand() {
  const command = commandInput.value.trim();
  
  if (!command) return;
  
  // Reset the confirmation flag - no output should be displayed until confirmed
  scriptConfirmed = false;
  
  // Store the command for later execution
  currentCustomCommand = command;
  
  // Clear the input
  commandInput.value = '';
  
  // Request confirmation before executing
  fetch('/api/request-run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ customCommand: command })
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`Server responded with status: ${response.status}`);
    }
    return response.text().then(text => {
      try {
        return JSON.parse(text);
      } catch (e) {
        appendToOutput(`Error parsing JSON response: ${text.substring(0, 100)}...\n`, 'error');
        throw new Error('Invalid JSON response from server');
      }
    });
  })
  .then(data => {
    if (!data.success) {
      appendToOutput(`Error: ${data.message}\n`, 'error');
      return;
    }
    
    // Show confirmation dialog
    showConfirmation('custom', data.scriptName, data.customCommand);
  })
  .catch(error => {
    appendToOutput(`Error: ${error.message}\n`, 'error');
  });
}

// Execute custom command after confirmation
function executeConfirmedCustomCommand(command) {
  // Set the script as confirmed
  scriptConfirmed = true;
  
  // Show command in output
  appendToOutput(`$ ${command}\n`, 'command');
  
  // Send request to actually run the command
  fetch('/api/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ customCommand: command })
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`Server responded with status: ${response.status}`);
    }
    return response.text().then(text => {
      try {
        return JSON.parse(text);
      } catch (e) {
        appendToOutput(`Error parsing JSON response: ${text.substring(0, 100)}...\n`, 'error');
        throw new Error('Invalid JSON response from server');
      }
    });
  })
  .catch(error => {
    appendToOutput(`Error: ${error.message}\n`, 'error');
  });
}

// Update system status
function updateSystemStatus() {
  fetch('/api/status')
    .then(response => {
      if (!response.ok) {
        throw new Error(`Server responded with status: ${response.status}`);
      }
      return response.text().then(text => {
        try {
          return JSON.parse(text);
        } catch (e) {
          console.error(`Error parsing JSON response: ${text.substring(0, 100)}...`);
          throw new Error('Invalid JSON response from server');
        }
      });
    })
    .then(data => {
      // Update status container
      let statusHtml = '';
      
      if (data.containers && data.containers.length > 0) {
        data.containers.forEach(container => {
          statusHtml += `
            <div class="status-card">
              <div class="name">${container.name}</div>
              <div class="status running">${container.status}</div>
            </div>
          `;
        });
      } else {
        statusHtml = '<div class="status-card"><div class="name">No containers running</div></div>';
      }
      
      statusContainer.innerHTML = statusHtml;
      
      // Update volumes list
      let volumesHtml = '';
      if (data.volumes && data.volumes.length > 0) {
        data.volumes.forEach(volume => {
          volumesHtml += `<li>${volume}</li>`;
        });
      } else {
        volumesHtml = '<li>No volumes found</li>';
      }
      volumesList.innerHTML = volumesHtml;
      
      // Update networks list
      let networksHtml = '';
      if (data.networks && data.networks.length > 0) {
        data.networks.forEach(network => {
          networksHtml += `<li>${network}</li>`;
        });
      } else {
        networksHtml = '<li>No networks found</li>';
      }
      networksList.innerHTML = networksHtml;
      
      // Update volume count
      volumeCountElement.textContent = data.volumes ? data.volumes.length : 0;
      
      // Update backup count
      backupCountElement.textContent = data.backupCount || 0;
      
      // Update header status indicators
      const dockerStatusElement = document.querySelector('.status-indicators .status-item:first-child');
      const servicesStatusElement = document.querySelector('.status-indicators .status-item:nth-child(2)');
      
      dockerStatusElement.className = `status-item ${data.dockerRunning ? 'active' : 'inactive'}`;
      dockerStatusElement.innerHTML = `<i class="fas fa-server"></i> Docker: ${data.dockerRunning ? 'Running' : 'Stopped'}`;
      
      servicesStatusElement.className = `status-item ${data.servicesRunning ? 'active' : 'inactive'}`;
      servicesStatusElement.innerHTML = `<i class="fas fa-cogs"></i> Services: ${data.servicesRunning ? 'Running' : 'Stopped'}`;
    })
    .catch(error => {
      console.error('Error fetching status:', error);
      statusContainer.innerHTML = '<div class="error">Error fetching system status</div>';
    });
}

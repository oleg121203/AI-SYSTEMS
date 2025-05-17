const express = require('express');
const bodyParser = require('body-parser');
const { exec } = require('child_process');
const path = require('path');
const http = require('http');
const socketIo = require('socket.io');

// Initialize Express app
const app = express();
const server = http.createServer(app);
const io = socketIo(server);

// Helper functions for checking service status
function checkDockerRunning() {
  return new Promise((resolve) => {
    exec('docker info', (error) => {
      resolve(!error);
    });
  });
}

function checkServicesRunning() {
  return new Promise((resolve) => {
    exec('docker ps | grep ai-systems', (error, stdout) => {
      resolve(stdout.trim().length > 0);
    });
  });
}

function getServicesStatus() {
  return new Promise((resolve) => {
    exec('docker ps --format "{{.Names}},{{.Status}}" | grep ai-systems', (error, stdout) => {
      if (error) {
        resolve([]);
        return;
      }
      
      const services = [];
      stdout.split('\n').filter(Boolean).forEach(line => {
        const [name, status] = line.split(',');
        if (name && status) {
          services.push({
            name: name.replace('ai-systems_', ''),
            status: status,
            running: status.includes('Up')
          });
        }
      });
      
      resolve(services);
    });
  });
}

// Check if direct services are running by checking processes on specific ports
function checkDirectServicesRunning() {
  return new Promise((resolve) => {
    // Define the ports used by direct services
    const servicePorts = [
      7861, // AI Core
      7862, // Development Agents
      7863, // Project Manager
      7864, // CMP
      7865, // Git Service
      8001  // Web Backend
    ];
    
    // Alternative ports that might be used if primary ports are occupied
    const alternativePorts = [7876, 8002, 8003, 8004, 8005];
    
    // Combine all possible ports
    const allPorts = [...servicePorts, ...alternativePorts];
    
    // Check all ports in a single command
    const portCheckCommand = `lsof -i -P -n | grep LISTEN | grep -E '${allPorts.join('|')}'`;
    
    exec(portCheckCommand, (error, stdout) => {
      if (error) {
        // No processes found on these ports
        console.log('No direct services found running on expected ports');
        resolve({ running: false, services: [] });
        return;
      }
      
      // Parse the output to get running services
      const runningServices = [];
      const lines = stdout.split('\n').filter(Boolean);
      
      console.log('Found processes on service ports:', lines.length);
      
      lines.forEach(line => {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 9) {
          const port = parseInt(parts[8].split(':').pop());
          const pid = parts[1];
          const processName = parts[0];
          
          // Map port to service name
          let serviceName = 'unknown';
          if (port === 7861 || port === 7876) serviceName = 'AI Core';
          else if (port === 7862) serviceName = 'Development Agents';
          else if (port === 7863) serviceName = 'Project Manager';
          else if (port === 7864) serviceName = 'CMP';
          else if (port === 7865) serviceName = 'Git Service';
          else if (port === 8001 || port === 8002) serviceName = 'Web Backend';
          
          runningServices.push({
            port,
            pid,
            processName,
            serviceName,
            running: true
          });
        }
      });
      
      // Consider direct services running if we found at least 3 services
      const isRunning = runningServices.length >= 3;
      console.log('Direct services running check:', { 
        isRunning, 
        count: runningServices.length,
        services: runningServices.map(s => s.serviceName)
      });
      
      resolve({ 
        running: isRunning, 
        services: runningServices 
      });
    });
  });
}

// Set view engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Middleware
app.use(bodyParser.urlencoded({ extended: false }));
app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public')));

// Root directory
const ROOT_DIR = path.join(__dirname, '..');
const AI_SYSTEMS_DIR = path.join(ROOT_DIR, 'ai-systems');

// Available scripts
const scripts = {
  // Service management
  startServicesDirect: {
    name: 'Start Services (Direct)',
    command: `bash ${AI_SYSTEMS_DIR}/run_services.sh`,
    category: 'services'
  },
  stopServices: {
    name: 'Stop All Services',
    command: `bash ${AI_SYSTEMS_DIR}/stop_services.sh`,
    category: 'services'
  },
  
  // Docker profiles
  startInfrastructure: {
    name: 'Start Infrastructure Services',
    command: `cd ${AI_SYSTEMS_DIR} && docker-compose --profile infrastructure up -d`,
    category: 'docker'
  },
  startAI: {
    name: 'Start AI Services',
    command: `cd ${AI_SYSTEMS_DIR} && docker-compose --profile ai up -d`,
    category: 'docker'
  },
  startWeb: {
    name: 'Start Web Services',
    command: `cd ${AI_SYSTEMS_DIR} && docker-compose --profile web up -d`,
    category: 'docker'
  },
  startManagement: {
    name: 'Start Management Services',
    command: `cd ${AI_SYSTEMS_DIR} && docker-compose --profile management up -d`,
    category: 'docker'
  },
  startMonitoring: {
    name: 'Start Monitoring Services',
    command: `cd ${AI_SYSTEMS_DIR} && docker-compose --profile monitoring up -d`,
    category: 'docker'
  },
  startAll: {
    name: 'Start All Services (Docker)',
    command: `cd ${AI_SYSTEMS_DIR} && docker-compose --profile full up -d`,
    category: 'docker'
  },
  
  // Testing and monitoring
  testProfiles: {
    name: 'Test Docker Profiles',
    command: `bash ${AI_SYSTEMS_DIR}/test_profiles.sh`,
    category: 'testing'
  },
  monitorPerformance: {
    name: 'Monitor Performance',
    command: `bash ${AI_SYSTEMS_DIR}/monitor_performance.sh`,
    category: 'monitoring'
  },
  backupVolumes: {
    name: 'Backup Volumes',
    command: `bash ${AI_SYSTEMS_DIR}/backup_volumes.sh`,
    category: 'backup'
  },
  backupRabbitMQ: {
    name: 'Backup RabbitMQ Data',
    command: `bash ${AI_SYSTEMS_DIR}/backup_rabbitmq_data.sh`,
    category: 'backup'
  },
  backupPostgres: {
    name: 'Backup PostgreSQL Data',
    command: `bash ${AI_SYSTEMS_DIR}/backup_postgres_data.sh`,
    category: 'backup'
  },
  checkRepo: {
    name: 'Check Git Repository',
    command: `bash ${AI_SYSTEMS_DIR}/check_repo.sh`,
    category: 'git'
  },
  syncRepo: {
    name: 'Sync Git Repository',
    command: `bash ${AI_SYSTEMS_DIR}/sync_repo.sh`,
    category: 'git'
  },
  forcePush: {
    name: 'Force Push to Git',
    command: `bash ${AI_SYSTEMS_DIR}/force_push.sh`,
    category: 'git'
  },
  resetRepo: {
    name: 'Reset Git Repository',
    command: `bash ${AI_SYSTEMS_DIR}/reset_repo.sh`,
    category: 'git'
  },
  testHealthEndpoints: {
    name: 'Test Health Endpoints',
    command: `curl -s http://localhost:8000/health && echo "\n" && curl -s http://localhost:8001/health`,
    category: 'testing'
  },
  testLoadBalancing: {
    name: 'Test Load Balancing',
    command: `for i in {1..5}; do curl -s http://localhost:8080/api/status; echo "\n"; done`,
    category: 'testing'
  },
  runIntegrationTests: {
    name: 'Run Integration Tests',
    command: `cd ${AI_SYSTEMS_DIR}/.. && python -m pytest tests/integration -v`,
    category: 'testing'
  },
  checkSecurityConfig: {
    name: 'Check Security Config',
    command: `docker-compose -f ${AI_SYSTEMS_DIR}/docker-compose.yml config | grep -i secret || echo "No secrets found in docker-compose.yml"`,
    category: 'testing'
  }
};

// Routes
app.get('/', async (req, res) => {
  try {
    // Set up categories object
    const categories = {};
    Object.entries(scripts).forEach(([id, script]) => {
      if (!categories[script.category]) {
        categories[script.category] = [];
      }
      categories[script.category].push({ id, name: script.name });
    });

    console.log('Categories set up successfully');

    const categoryDisplayNames = {
      'services': 'System Services',
      'docker': 'Docker Management',
      'backup': 'Backup Operations',
      'git': 'Git Repository',
      'testing': 'Testing & Diagnostics',
      'monitoring': 'System Monitoring'
    };

    console.log('Category display names defined');

    const categoryOrder = ['services', 'docker', 'backup', 'testing', 'monitoring', 'git'];
    
    console.log('Category order defined');

    // Check Docker and services status
    let dockerRunning = false;
    let servicesRunning = false;
    
    try {
      dockerRunning = await checkDockerRunning();
      console.log('Docker status checked:', dockerRunning);
    } catch (err) {
      console.error('Error checking Docker status:', err);
    }
    
    try {
      servicesRunning = await checkServicesRunning();
      console.log('Services status checked:', servicesRunning);
    } catch (err) {
      console.error('Error checking services status:', err);
    }

    console.log('Ready to render template with:', {
      categoriesCount: Object.keys(categories).length,
      dockerRunning,
      servicesRunning
    });

    // Render the template
    res.render('index', { 
      categories, 
      categoryDisplayNames,
      categoryOrder,
      scripts,
      dockerRunning,
      servicesRunning
    });

    console.log('Template rendered successfully');
  } catch (error) {
    console.error('Error rendering index:', error);
    res.status(500).send(`Internal Server Error: ${error.message}\n${error.stack}`);
  }
});

// API endpoints for script execution with confirmation flow

// Step 1: Request confirmation before running a script
app.post('/api/request-run', async (req, res) => {
  console.log('Request to /api/request-run received:', req.body);
  const { scriptId, customCommand } = req.body;
  
  if (customCommand) {
    // For custom commands, send confirmation request
    console.log('Sending confirmation request for custom command');
    return res.json({
      success: true,
      requiresConfirmation: true,
      message: `Please confirm running custom command`,
      scriptName: `Custom: ${customCommand.substring(0, 30)}${customCommand.length > 30 ? '...' : ''}`,
      customCommand: customCommand // Pass back the custom command for execution after confirmation
    });
  }
  
  if (!scripts[scriptId]) {
    console.log('Invalid script ID:', scriptId);
    return res.status(400).json({ success: false, message: 'Invalid script ID' });
  }
  
  const script = scripts[scriptId];
  console.log('Checking status before confirming script:', script.name);
  
  // Check if the action is necessary based on current state
  let actionNeeded = true;
  let statusMessage = '';
  
  // Check if it's a start/stop service action and verify current state
  if (scriptId === 'startAll') {
    // Get detailed service status
    const services = await getServicesStatus();
    console.log('Current services status:', services);
    
    // Check if we have any running services
    const servicesRunning = services.length > 0 && services.some(service => service.running);
    console.log('Services running check:', servicesRunning, 'Service count:', services.length);
    
    if (servicesRunning) {
      actionNeeded = false;
      statusMessage = 'Services are already running. No action needed.';
      console.log('Action not needed:', statusMessage);
    }
  } else if (scriptId === 'startServicesDirect') {
    // Check if direct services are already running
    const directServicesStatus = await checkDirectServicesRunning();
    console.log('Direct services status:', directServicesStatus);
    
    if (directServicesStatus.running) {
      actionNeeded = false;
      statusMessage = 'Direct services are already running. No action needed.';
      console.log('Action not needed for direct services:', statusMessage);
    } else {
      // Check if Docker services are running, which might conflict with direct services
      const dockerServices = await getServicesStatus();
      const dockerServicesRunning = dockerServices.length > 0 && dockerServices.some(service => service.running);
      
      if (dockerServicesRunning) {
        // Add a warning that Docker services might conflict with direct services
        console.log('Warning: Docker services are running which might conflict with direct services');
        statusMessage = 'Warning: Docker services are running which might conflict with direct services on the same ports.';
      }
    }
  } else if (scriptId === 'stopServices') {
    // Get detailed service status
    const services = await getServicesStatus();
    console.log('Current services status for stop check:', services);
    
    // Check if we have any running services
    const servicesRunning = services.length > 0 && services.some(service => service.running);
    console.log('Services running check for stop:', servicesRunning, 'Service count:', services.length);
    
    // Also check direct services
    const directServicesStatus = await checkDirectServicesRunning();
    const anyServicesRunning = servicesRunning || directServicesStatus.running;
    
    if (!anyServicesRunning) {
      actionNeeded = false;
      statusMessage = 'Services are already stopped. No action needed.';
      console.log('Action not needed for stop:', statusMessage);
    }
  } else if (scriptId.startsWith('start') && scriptId !== 'startAll') {
    // For individual service profiles, check if that specific profile is running
    const services = await getServicesStatus();
    console.log('Current services for profile check:', services);
    
    const profileName = scriptId.replace('start', '').toLowerCase();
    console.log('Checking profile:', profileName);
    
    // Map profile names to expected service names
    const profileServiceMap = {
      'infrastructure': ['postgres', 'redis', 'rabbitmq'],
      'ai': ['ai-core', 'development-agents'],
      'web': ['web-backend'],
      'management': ['project-manager', 'git-service'],
      'monitoring': ['prometheus', 'grafana']
    };
    
    // Get the expected services for this profile
    const expectedServices = profileServiceMap[profileName] || [];
    console.log('Expected services for profile:', expectedServices);
    
    // Check if all expected services for this profile are running
    const runningServices = services.filter(service => service.running);
    console.log('Currently running services:', runningServices.map(s => s.name));
    
    // Extract just the service names without prefixes for easier matching
    const runningServiceNames = runningServices.map(s => {
      // Extract the base name from the full container name
      const name = s.name.replace('ai-systems_', '').replace('ai-systems-', '');
      return name.toLowerCase();
    });
    
    console.log('Simplified running service names:', runningServiceNames);
    
    // Check if all expected services are running
    const allExpectedRunning = expectedServices.length > 0 && 
      expectedServices.every(expected => 
        runningServiceNames.some(serviceName => serviceName.includes(expected))
      );
    
    console.log('All expected services running:', allExpectedRunning);
    
    if (allExpectedRunning) {
      actionNeeded = false;
      statusMessage = `${script.name.replace('Start ', '')} are already running. No action needed.`;
    }
  }
  
  if (!actionNeeded) {
    console.log(statusMessage);
    return res.json({
      success: true,
      requiresConfirmation: false,
      actionNeeded: false,
      message: statusMessage,
      scriptName: script.name
    });
  }
  
  console.log('Sending confirmation request for script:', script.name);
  
  // Send confirmation request
  return res.json({
    success: true,
    requiresConfirmation: true,
    actionNeeded: true,
    message: `Please confirm running: ${script.name}`,
    scriptName: script.name
  });
});

// Step 2: Actually run the script after confirmation
app.post('/api/run', (req, res) => {
  console.log('Request to /api/run received:', req.body);
  const { scriptId, customCommand } = req.body;
  
  if (customCommand) {
    // Custom command execution
    console.log('Executing custom command:', customCommand);
    res.json({ success: true, message: `Running custom command` });
    
    // Execute the custom command
    const process = exec(customCommand, { cwd: AI_SYSTEMS_DIR });
    
    // Generate a unique ID for this custom command
    const customId = `custom-${Date.now()}`;
    
    // Broadcast output to all connected clients
    process.stdout.on('data', (data) => {
      io.emit('output', { scriptId: customId, data });
    });
    
    process.stderr.on('data', (data) => {
      io.emit('output', { scriptId: customId, data, error: true });
    });
    
    process.on('close', (code) => {
      io.emit('scriptComplete', { 
        scriptId: customId, 
        exitCode: code,
        success: code === 0
      });
    });
    
    return;
  }
  
  if (!scripts[scriptId]) {
    console.log('Invalid script ID:', scriptId);
    return res.status(400).json({ success: false, message: 'Invalid script ID' });
  }
  
  const script = scripts[scriptId];
  console.log('Executing script:', script.name);
  
  // Send response that script is running
  res.json({ success: true, message: `Running: ${script.name}` });
  
  // Execute the script
  const process = exec(script.command);
  
  // Broadcast output to all connected clients
  process.stdout.on('data', (data) => {
    io.emit('output', { scriptId, data });
  });
  
  process.stderr.on('data', (data) => {
    io.emit('output', { scriptId, data, error: true });
  });
  
  process.on('close', (code) => {
    io.emit('scriptComplete', { 
      scriptId, 
      exitCode: code,
      success: code === 0
    });
  });
});

// Log all registered routes for debugging
console.log('Registered routes:');
app._router.stack.forEach(function(r){
  if (r.route && r.route.path){
    console.log(r.route.stack[0].method.toUpperCase() + ' ' + r.route.path);
  }
});

// API endpoint to get system status
app.get('/api/status', async (req, res) => {
  try {
    const dockerRunning = await checkDockerRunning();
    const servicesRunning = await checkServicesRunning();
    const services = await getServicesStatus();
    res.json({
      dockerRunning,
      servicesRunning,
      services
    });
  } catch (error) {
    console.error('Error getting status:', error);
    res.status(500).send('Internal Server Error');
  }
});

// Socket.IO connection
io.on('connection', (socket) => {
  console.log('Client connected');
  
  // Handle script execution
  socket.on('run-script', (scriptId) => {
    const script = scripts[scriptId];
    if (!script) {
      socket.emit('script-error', `Script ${scriptId} not found`);
      return;
    }
    
    console.log(`Running script: ${script.name}`);
    
    const child = exec(script.command);
    
    child.stdout.on('data', (data) => {
      socket.emit('script-output', data.toString());
    });
    
    child.stderr.on('data', (data) => {
      socket.emit('script-error', data.toString());
    });
    
    child.on('close', (code) => {
      socket.emit('script-complete', code);
    });
  });
  
  // Handle custom command execution
  socket.on('run-custom-command', (command) => {
    // Security check - prevent dangerous commands
    if (command.includes('rm -rf') || command.includes('sudo') || command.includes(':(){ :|:& };:')) {
      socket.emit('script-error', 'Command rejected for security reasons');
      return;
    }
    
    console.log(`Running custom command: ${command}`);
    
    // Execute in the AI-SYSTEMS directory for context
    const child = exec(command, { cwd: path.join(AI_SYSTEMS_DIR, '..') });
    
    child.stdout.on('data', (data) => {
      socket.emit('script-output', data.toString());
    });
    
    child.stderr.on('data', (data) => {
      socket.emit('script-error', data.toString());
    });
    
    child.on('close', (code) => {
      socket.emit('script-complete', code);
    });
  });
  
  // Handle status request
  socket.on('get-status', async () => {
    try {
      const services = await getServicesStatus();
      socket.emit('status-update', services);
    } catch (error) {
      console.error('Error getting status:', error);
    }
  });
  
  socket.on('disconnect', () => {
    console.log('Client disconnected');
  });
});

// Start server
const PORT = process.env.PORT || 3031;
server.listen(PORT, () => {
  console.log(`AI-SYSTEMS Web Manager running on http://localhost:${PORT}`);
});

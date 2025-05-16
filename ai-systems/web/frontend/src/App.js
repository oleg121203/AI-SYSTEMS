import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Alert,
  AlertTitle,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  CssBaseline,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Drawer,
  Grid,
  IconButton,
  LinearProgress,
  Link,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  Snackbar,
  Tab,
  Tabs,
  TextField,
  Toolbar,
  Typography
} from '@mui/material';

// Icons
import AddIcon from '@mui/icons-material/Add';
import DashboardIcon from '@mui/icons-material/Dashboard';
import DescriptionIcon from '@mui/icons-material/Description';
import FolderIcon from '@mui/icons-material/Folder';
import GitHubIcon from '@mui/icons-material/GitHub';
import MenuIcon from '@mui/icons-material/Menu';
import MonitorIcon from '@mui/icons-material/Monitor';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RefreshIcon from '@mui/icons-material/Refresh';
import SettingsIcon from '@mui/icons-material/Settings';
import TaskIcon from '@mui/icons-material/Task';
import ListAltIcon from '@mui/icons-material/ListAlt';

// Custom components
import ProjectCard from './components/ProjectCard';
import TaskList from './components/TaskList';
import SystemStatus from './components/SystemStatus';
import AIModelSelector from './components/AIModelSelector';
// Enhanced monitoring components
import EnhancedMonitoringDashboard from './components/EnhancedMonitoringDashboard';
import APIKeyMonitor from './components/APIKeyMonitor';
import AdvancedMetricsChart from './components/AdvancedMetricsChart';
import WorkflowVisualizer from './components/WorkflowVisualizer';
import PerformanceDashboard from './components/PerformanceDashboard';
import GitHubIntegration from './components/GitHubIntegration';
import LogViewer from './components/LogViewer';
import DebugAIConfig from './components/DebugAIConfig';
import AITaskManagementDashboard from './components/AITaskManagementDashboard';

// Configuration
import config from './config';

// Styles
import { ThemeProvider, createTheme } from '@mui/material/styles';
import './App.css';

// Create theme
const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#6366f1', // Indigo
      light: '#818cf8',
      dark: '#4f46e5',
    },
    secondary: {
      main: '#ec4899', // Pink
      light: '#f472b6',
      dark: '#db2777',
    },
    success: {
      main: '#10b981', // Emerald
      light: '#34d399',
      dark: '#059669',
    },
    error: {
      main: '#ef4444', // Red
      light: '#f87171',
      dark: '#dc2626',
    },
    warning: {
      main: '#f59e0b', // Amber
      light: '#fbbf24',
      dark: '#d97706',
    },
    info: {
      main: '#3b82f6', // Blue
      light: '#60a5fa',
      dark: '#2563eb',
    },
    background: {
      default: '#0a1929', // Deeper blue for better contrast
      paper: '#132f4c', // Richer blue for cards
      card: '#1e3a8a', // Special color for highlighted cards
      accent: '#1e40af', // Accent color for special elements
    },
    text: {
      primary: '#f8fafc', // Slate 50
      secondary: '#cbd5e1', // Slate 300
      accent: '#93c5fd', // Light blue accent text
    },
    action: {
      active: '#60a5fa',
      hover: 'rgba(96, 165, 250, 0.08)',
      selected: 'rgba(96, 165, 250, 0.16)',
      disabled: 'rgba(255, 255, 255, 0.3)',
      disabledBackground: 'rgba(255, 255, 255, 0.12)',
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h1: {
      fontWeight: 700,
    },
    h2: {
      fontWeight: 700,
    },
    h3: {
      fontWeight: 600,
    },
    h4: {
      fontWeight: 600,
    },
    h5: {
      fontWeight: 600,
    },
    h6: {
      fontWeight: 600,
    },
    button: {
      fontWeight: 600,
      textTransform: 'none',
    },
  },
  shape: {
    borderRadius: 10,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          padding: '10px 20px',
          boxShadow: '0 2px 4px rgba(0, 0, 0, 0.2)',
          transition: 'all 0.2s ease-in-out',
          fontWeight: 600,
          '&:hover': {
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
            transform: 'translateY(-2px)',
          },
        },
        contained: {
          background: 'linear-gradient(45deg, #6366f1 30%, #818cf8 90%)',
        },
        outlined: {
          borderWidth: 2,
          '&:hover': {
            borderWidth: 2,
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: 16,
          boxShadow: '0 8px 16px rgba(0, 0, 0, 0.2)',
          overflow: 'hidden',
          transition: 'transform 0.3s ease, box-shadow 0.3s ease',
          '&:hover': {
            boxShadow: '0 12px 24px rgba(0, 0, 0, 0.3)',
            transform: 'translateY(-5px)',
          },
          border: '1px solid rgba(255, 255, 255, 0.1)',
        },
      },
    },
    MuiCardHeader: {
      styleOverrides: {
        root: {
          background: 'linear-gradient(90deg, rgba(99, 102, 241, 0.2) 0%, rgba(129, 140, 248, 0.1) 100%)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 16,
          backgroundImage: 'linear-gradient(rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0))',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.3)',
          backgroundImage: 'linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%)',
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: {
          '& .MuiTabs-indicator': {
            height: 3,
            borderRadius: 3,
          },
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          transition: 'all 0.2s',
          '&.Mui-selected': {
            fontWeight: 700,
          },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          borderRadius: 8,
          boxShadow: '0 4px 8px rgba(0, 0, 0, 0.2)',
          padding: '8px 12px',
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          borderRadius: 4,
          height: 8,
        },
      },
    },
  },
});

function App() {
  // State for projects and tasks
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [projectTasks, setProjectTasks] = useState([]);
  
  // AI configuration state
  const [aiConfig, setAIConfig] = useState(null);
  // aiConfigLoading is used for future implementation of AI config loading states
  // eslint-disable-next-line no-unused-vars
  const [aiConfigLoading, setAIConfigLoading] = useState(false);
  
  // UI state
  const [loading, setLoading] = useState({
    projects: true,
    tasks: false,
    system: true,
    global: false,
    aiConfig: false,
    projectAction: false
  });
  const [error, setError] = useState(null);
  const [currentTab, setCurrentTab] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [systemStatus, setSystemStatus] = useState(null);
  const [notification, setNotification] = useState({
    open: false,
    message: '',
    severity: 'info',
    title: ''
  });
  
  // Project creation state
  const [newProjectDialog, setNewProjectDialog] = useState(false);
  const [newProject, setNewProject] = useState({
    name: '',
    description: '',
    repository_url: '',
    idea_md: ''
  });
  
  // WebSocket state
  const ws = useRef(null);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;
  
  // Initialize WebSocket connection
  const connectWebSocket = useCallback(() => {
    try {
      const wsUrl = `${config.wsBaseUrl}/ws`;
      
      // Close existing connection if it exists
      if (ws.current) {
        try {
          ws.current.close();
        } catch (err) {
          console.log('Error closing existing WebSocket:', err);
        }
      }
      
      ws.current = new WebSocket(wsUrl);
      
      ws.current.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts.current = 0;
        
        // Send ping to keep connection alive
        const pingInterval = setInterval(() => {
          if (ws.current && ws.current.readyState === WebSocket.OPEN) {
            try {
              ws.current.send(JSON.stringify({ type: 'ping' }));
            } catch (err) {
              console.log('Error sending ping:', err);
              clearInterval(pingInterval);
            }
          } else {
            clearInterval(pingInterval);
          }
        }, 30000);
      };
    
    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('WebSocket message:', data);
      
      switch (data.type) {
        case 'system_status':
          setSystemStatus(data.data);
          setLoading(prev => ({ ...prev, system: false }));
          break;
          
        case 'ai_config_update':
          console.log('Received AI config update from WebSocket:', data.data);
          // Make sure we have valid data before updating the state
          if (data.data && typeof data.data === 'object') {
            setAIConfig(data.data);
          }
          break;
          
        case 'project_update':
          // Refresh projects list when a project is updated
          fetchProjects();
          setNotification({
            open: true,
            message: `Project ${data.project_id}: ${data.message}`,
            severity: 'info'
          });
          break;
          
        case 'task_update':
          // Refresh tasks if the current project has a task update
          if (selectedProject && projectTasks.some(task => task.id === data.task_id)) {
            fetchProjectTasks(selectedProject.id);
          }
          break;
          
        case 'report':
          // Handle new report
          setNotification({
            open: true,
            message: `New report received: ${data.report.type} for ${data.report.file || 'project'}`,
            severity: 'info'
          });
          break;
          
        case 'pong':
          // Received pong from server
          console.log('Pong received from server');
          break;
          
        default:
          console.log('Unknown message type:', data.type);
      }
    };
    
    ws.current.onclose = (event) => {
      console.log('WebSocket disconnected', event.code, event.reason);
      
      // Don't attempt to reconnect if the close was clean (1000) or if we're refreshing the page
      if (event.code === 1000 || event.code === 1001) {
        console.log('Clean WebSocket close, not reconnecting');
        return;
      }
      
      // Attempt to reconnect
      if (reconnectAttempts.current < maxReconnectAttempts) {
        reconnectAttempts.current += 1;
        const timeout = Math.min(5000 * reconnectAttempts.current, 30000); // Exponential backoff with max of 30s
        setTimeout(() => {
          console.log(`Attempting to reconnect (${reconnectAttempts.current}/${maxReconnectAttempts})`);
          connectWebSocket();
        }, timeout);
      } else {
        setError('WebSocket connection lost. Please refresh the page.');
      }
    };
    
    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error);
      // Don't take action here, let the onclose handler deal with reconnection
    };
    } catch (err) {
      console.error('Error setting up WebSocket:', err);
      setTimeout(() => connectWebSocket(), 5000);
    }
  }, [selectedProject, projectTasks]); // config.wsBaseUrl is a constant and doesn't need to be in the dependency array
  
  // Initialize app
  useEffect(() => {
    fetchProjects();
    fetchSystemStatus();
    fetchAIConfigFromServer(); // Fetch AI configuration on initialization
    connectWebSocket();
    
    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [connectWebSocket]);
  
  // Handle tab changes
  const handleTabChange = (event, newValue) => {
    const previousTab = currentTab;
    setCurrentTab(newValue);
    
    // Always fetch AI configuration when switching to the AI Configuration tab
    if (newValue === 4) { // AI Configuration tab
      console.log('Switching to AI Configuration tab, fetching latest config');
      // Set loading state to show loading indicator
      setLoading(prev => ({ ...prev, aiConfig: true }));
      // Fetch the latest AI configuration from the server
      fetchAIConfigFromServer();
    }
    
    // If we're switching away from the AI Configuration tab and have unsaved changes, warn the user
    if (previousTab === 4 && newValue !== 4) {
      console.log('Switched away from AI Configuration tab');
    }
  };
  
  // Toggle drawer
  const handleDrawerToggle = () => {
    setDrawerOpen(!drawerOpen);
  };
  
  // Handle refresh
  const handleRefresh = () => {
    // Show a notification to indicate refresh is happening
    setNotification({
      open: true,
      message: "Refreshing data...",
      severity: "info"
    });
    
    setLoading(prev => ({ ...prev, global: true })); // Set global loading indicator
    
    switch (currentTab) {
      case 0:
        fetchProjects();
        break;
      case 1:
        if (selectedProject) {
          fetchProjectDetails(selectedProject.id);
        }
        break;
      case 2:
        fetchSystemStatus();
        break;
      case 4:
        fetchAIConfigFromServer();
        break;
      default:
        break;
    }
  };
  
  // Close notification
  const handleCloseNotification = () => {
    setNotification(prev => ({ ...prev, open: false }));
  };
  
  // Handle project selection
  const handleProjectSelect = (projectId) => {
    fetchProjectDetails(projectId);
    setCurrentTab(1);
  };
  
  // Handle input changes for new project form
  const handleInputChange = (event) => {
    const { name, value } = event.target;
    setNewProject(prev => ({ ...prev, [name]: value }));
  };
  
  // Handle create plan
  const handleCreatePlan = (projectId) => {
    // TODO: Implement plan creation
    console.log('Create plan for project:', projectId);
  };
  
  // Update AI configuration
  const handleUpdateAIConfig = async (configData) => {
    try {
      // Set loading state and show notification
      setLoading(prev => ({ ...prev, global: true, aiConfig: true }));
      setNotification({
        open: true,
        message: "Updating AI configuration...",
        severity: "info",
        title: "Processing"
      });
      
      console.log('Updating AI configuration with:', configData);
      
      // Process config to include API keys
      const processedConfig = {};
      
      // For each AI agent, include the provider, model, and API key if available
      Object.keys(configData).forEach(aiKey => {
        if (configData[aiKey]?.provider) {
          processedConfig[aiKey] = {
            provider: configData[aiKey].provider,
            model: configData[aiKey].model || ''
          };
          
          // Include API key if provided
          if (configData[aiKey].apiKey) {
            processedConfig[aiKey].apiKey = configData[aiKey].apiKey;
          }
        }
      });
      
      console.log('Sending processed config to backend:', processedConfig);
      console.log('API URL:', `${config.apiBaseUrl}/api/ai-config`);
      
      const response = await fetch(`${config.apiBaseUrl}/api/ai-config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(processedConfig),
        // Prevent caching
        cache: 'no-cache',
      });
      
      const responseData = await response.json();
      console.log('Response from backend:', responseData);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      // Update local state with the new configuration from the response
      // This ensures we have the exact state that was saved on the server
      if (responseData.config) {
        setAIConfig(responseData.config);
      } else {
        // Fallback to using our processed config if the response doesn't include the config
        setAIConfig(processedConfig);
      }
      
      setNotification({
        open: true,
        message: "AI configuration updated successfully",
        severity: "success",
        title: "Success"
      });
    } catch (e) {
      console.error("Error updating AI configuration:", e);
      
      // Get a more detailed error message if available
      let errorMessage = "Failed to update AI configuration";
      if (e.message) {
        if (e.message.includes('HTTP error!')) {
          errorMessage += ". Server returned an error.";
        } else {
          errorMessage += ". " + e.message;
        }
      }
      
      setNotification({
        open: true,
        message: errorMessage,
        severity: "error",
        title: "Error"
      });
      
      // Refresh from server to ensure UI is in sync with server state
      fetchAIConfigFromServer();
    } finally {
      // Clear loading states
      setLoading(prev => ({ ...prev, global: false, aiConfig: false }));
    }
  };
  
  // API Functions
  const fetchProjects = async () => {
    try {
      setLoading(prev => ({ ...prev, projects: true, global: true }));
      setNotification({
        open: true,
        message: "Loading projects...",
        severity: "info",
        title: "Loading"
      });
      
      const response = await fetch(`${config.apiBaseUrl}/api/projects`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setProjects(data);
      setError(null);
      
      setNotification({
        open: true,
        message: `Successfully loaded ${data.length} projects`,
        severity: "success",
        title: "Success"
      });
    } catch (e) {
      console.error("Error fetching projects:", e);
      setError("Failed to load projects. Please try again later.");
      setNotification({
        open: true,
        message: "Failed to load projects: " + e.message,
        severity: "error",
        title: "Error"
      });
    } finally {
      setLoading(prev => ({ ...prev, projects: false, global: false }));
    }
  };
  
  const fetchProjectDetails = async (projectId) => {
    try {
      setLoading(prev => ({ ...prev, global: true }));
      setNotification({
        open: true,
        message: "Loading project details...",
        severity: "info",
        title: "Loading"
      });
      
      const response = await fetch(`${config.apiBaseUrl}/api/projects/${projectId}`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setSelectedProject(data);
      // Fetch tasks for this project
      fetchProjectTasks(projectId);
      
      // Subscribe to project updates via WebSocket
      if (ws.current && ws.current.readyState === WebSocket.OPEN) {
        ws.current.send(JSON.stringify({ 
          type: 'subscribe', 
          project_id: projectId 
        }));
      }
      
      setNotification({
        open: true,
        message: `Project '${data.name}' loaded successfully`,
        severity: "success",
        title: "Success"
      });
    } catch (e) {
      console.error("Error fetching project details:", e);
      setNotification({
        open: true,
        message: "Failed to load project details: " + e.message,
        severity: "error",
        title: "Error"
      });
    } finally {
      setLoading(prev => ({ ...prev, global: false }));
    }
  };
  
  const fetchProjectTasks = async (projectId) => {
    try {
      setLoading(prev => ({ ...prev, tasks: true }));
      const response = await fetch(`${config.apiBaseUrl}/api/projects/${projectId}/tasks`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setProjectTasks(data);
    } catch (e) {
      console.error("Error fetching project tasks:", e);
      setNotification({
        open: true,
        message: "Failed to load project tasks",
        severity: "error"
      });
    } finally {
      setLoading(prev => ({ ...prev, tasks: false }));
    }
  };
  
  const fetchSystemStatus = async () => {
    try {
      setLoading(prev => ({ ...prev, system: true, global: true }));
      setNotification({
        open: true,
        message: "Loading system status...",
        severity: "info",
        title: "Loading"
      });
      
      const response = await fetch(`${config.apiBaseUrl}/api/status`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setSystemStatus(data);
      
      setNotification({
        open: true,
        message: "System status updated successfully",
        severity: "success",
        title: "Success"
      });
    } catch (e) {
      console.error("Error fetching system status:", e);
      setNotification({
        open: true,
        message: "Failed to load system status: " + e.message,
        severity: "error",
        title: "Error"
      });
    } finally {
      setLoading(prev => ({ ...prev, system: false, global: false }));
    }
  };

  // Fetch AI configuration from server
  const fetchAIConfigFromServer = async () => {
    try {
      setLoading(prev => ({ ...prev, aiConfig: true, global: true }));
      setNotification({
        open: true,
        message: "Loading AI configuration...",
        severity: "info",
        title: "Loading"
      });
      
      // Add a cache-busting parameter to prevent browser caching
      const timestamp = new Date().getTime();
      const response = await fetch(`${config.apiBaseUrl}/api/ai-config?t=${timestamp}`, {
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Pragma': 'no-cache',
          'Expires': '0'
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log('Fetched AI configuration from server:', data);
      
      // Ensure we have a valid configuration object
      if (data && typeof data === 'object') {
        // Update the state with the fetched configuration
        setAIConfig(data);
        
        setNotification({
          open: true,
          message: "AI configuration loaded successfully",
          severity: "success",
          title: "Success"
        });
      } else {
        throw new Error('Invalid configuration data received from server');
      }
    } catch (e) {
      console.error("Error fetching AI configuration:", e);
      setNotification({
        open: true,
        message: "Failed to load AI configuration: " + e.message,
        severity: "error",
        title: "Error"
      });
    } finally {
      setLoading(prev => ({ ...prev, aiConfig: false, global: false }));
    }
  };
  
  // Project Management Functions
  const handleCreateProject = async () => {
    try {
      // Show loading indicator and notification
      setLoading(prev => ({ ...prev, global: true }));
      setNotification({
        open: true,
        message: "Creating new project...",
        severity: "info",
        title: "Processing"
      });
      
      const response = await fetch(`${config.apiBaseUrl}/api/projects`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(newProject),
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      
      setNotification({
        open: true,
        message: result.message || `Project '${newProject.name}' created successfully`,
        severity: "success",
        title: "Success"
      });
      
      // Close dialog and refresh projects
      setNewProjectDialog(false);
      setNewProject({
        name: '',
        description: '',
        repository_url: '',
        idea_md: ''
      });
      fetchProjects();
    } catch (e) {
      console.error("Error creating project:", e);
      setNotification({
        open: true,
        message: "Failed to create project: " + e.message,
        severity: "error",
        title: "Error"
      });
    } finally {
      // Clear global loading state
      setLoading(prev => ({ ...prev, global: false }));
    }
  };
  
  const handleStartProject = async (projectId) => {
    try {
      // Show loading indicators
      setLoading(prev => ({ ...prev, projectAction: true, global: true }));
      setNotification({
        open: true,
        message: "Starting project...",
        severity: "info",
        title: "Processing"
      });
      
      const response = await fetch(`${config.apiBaseUrl}/api/projects/${projectId}/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      
      setNotification({
        open: true,
        message: result.message || "Project started successfully",
        severity: "success",
        title: "Success"
      });
      
      // Refresh project details
      fetchProjectDetails(projectId);
    } catch (e) {
      console.error("Error starting project:", e);
      setNotification({
        open: true,
        message: "Failed to start project: " + e.message,
        severity: "error",
        title: "Error"
      });
    } finally {
      setLoading(prev => ({ ...prev, projectAction: false, global: false }));
    }
  };
  
  // Function to render content based on selected tab
  const renderTabContent = () => {
    switch (currentTab) {
      case 0: // Projects
        return (
          <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Typography variant="h4" gutterBottom>
                Projects
              </Typography>
              <Button
                variant="contained"
                color="primary"
                startIcon={<AddIcon />}
                onClick={() => setNewProjectDialog(true)}
              >
                New Project
              </Button>
            </Box>
            
            {loading.projects ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
                <CircularProgress />
              </Box>
            ) : error ? (
              <Paper sx={{ p: 3, textAlign: 'center' }}>
                <Typography color="error">{error}</Typography>
              </Paper>
            ) : (
              <Grid container spacing={3}>
                {projects.map((project) => (
                  <Grid item xs={12} sm={6} md={4} key={project.id}>
                    <ProjectCard
                      project={project}
                      onSelect={() => handleProjectSelect(project.id)}
                      onStart={() => handleStartProject(project.id)}
                    />
                  </Grid>
                ))}
              </Grid>
            )}
          </Container>
        );
      
      case 1: // Project Details
      return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
          {selectedProject ? (
            <>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Typography variant="h4" gutterBottom>
                  {selectedProject.name}
                </Typography>
                
                <Box>
                  {selectedProject.status === 'planning' && (
                    <Button
                      variant="contained"
                      color="primary"
                      startIcon={<PlayArrowIcon />}
                      onClick={() => handleStartProject(selectedProject.id)}
                      sx={{ mr: 1 }}
                    >
                      Start Project
                    </Button>
                  )}
                  
                  <Button
                    variant="outlined"
                    startIcon={<DescriptionIcon />}
                    onClick={() => handleCreatePlan(selectedProject.id)}
                  >
                    Generate Plan
                  </Button>
                </Box>
              </Box>
              
              {/* Workflow Visualizer */}
              <WorkflowVisualizer 
                tasks={projectTasks} 
                loading={loading.tasks} 
              />
              
              <Paper sx={{ p: 3, mb: 3, boxShadow: 2 }}>
                <Typography variant="h6" gutterBottom>
                  Project Details
                </Typography>
                
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <Typography variant="subtitle1">
                      Description
                    </Typography>
                    <Typography variant="body1" paragraph>
                      {selectedProject.description}
                    </Typography>
                    
                    {selectedProject.repository_url && (
                      <>
                        <Typography variant="subtitle1">
                          Repository
                        </Typography>
                        <Link href={selectedProject.repository_url} target="_blank" rel="noopener">
                          {selectedProject.repository_url}
                        </Link>
                      </>
                    )}
                  </Grid>
                  
                  <Grid item xs={12} md={6}>
                    <Typography variant="subtitle1">
                      Status
                    </Typography>
                    <Chip 
                      label={selectedProject.status.toUpperCase()} 
                      color={
                        selectedProject.status === 'completed' ? 'success' :
                        selectedProject.status === 'active' ? 'primary' :
                        selectedProject.status === 'paused' ? 'warning' :
                        'default'
                      }
                      sx={{ mb: 2 }}
                    />
                    
                    <Typography variant="subtitle1">
                      Progress
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                      <Box sx={{ width: '100%', mr: 1 }}>
                        <LinearProgress 
                          variant="determinate" 
                          value={selectedProject.progress * 100} 
                          sx={{ height: 10, borderRadius: 5 }}
                        />
                      </Box>
                      <Box>
                        <Typography variant="body2" color="textSecondary">
                          {Math.round(selectedProject.progress * 100)}%
                        </Typography>
                      </Box>
                    </Box>
                    
                    <Typography variant="subtitle1" sx={{ mt: 2 }}>
                      Tasks
                    </Typography>
                    <Typography variant="body2">
                      {selectedProject.completed_tasks} / {selectedProject.task_count} completed
                    </Typography>
                  </Grid>
                </Grid>
              </Paper>
              
              <Typography variant="h5" gutterBottom>
                Tasks
              </Typography>
              
              {loading.tasks ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
                  <CircularProgress />
                </Box>
              ) : (
                <TaskList tasks={projectTasks} />
              )}
            </>
          ) : (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
              <Typography variant="h6" color="textSecondary">
                Select a project to view details
              </Typography>
            </Box>
          )}
        </Container>
      );
      
    case 2: // System Status
      return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
          <Typography variant="h4" gutterBottom>
            System Status
          </Typography>
          
          {loading.system ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <SystemStatus status={systemStatus} />
          )}
        </Container>
      );
      
    case 3: // Monitoring
      return (
        <Box>
          {/* Use the new EnhancedMonitoringDashboard component */}
          <EnhancedMonitoringDashboard />
        </Box>
      );
      
    case 4: // AI Settings
      return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
          <Typography variant="h4" gutterBottom>
            AI Configuration
          </Typography>
          
          {aiConfigLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <Paper sx={{ p: 3, mb: 4, boxShadow: 2 }}>
                <Typography variant="h6" gutterBottom>
                  AI Agents Configuration
                </Typography>
                <Typography variant="body2" color="textSecondary" paragraph>
                  Configure the AI providers and models used by each AI agent in the system. Changes will be applied to new projects.
                </Typography>
                <AIModelSelector 
                  initialConfig={aiConfig} 
                  onConfigUpdate={(newConfig) => {
                    // First update local state immediately for UI responsiveness
                    setAIConfig(newConfig);
                    // Then send to backend
                    handleUpdateAIConfig(newConfig);
                  }}
                  loading={loading.aiConfig}
                />
                {/* Add debugging tool for AI configuration */}
                <DebugAIConfig />
              </Paper>
            </>
          )}
        </Container>
      );
      
    case 5: // GitHub Integration
      return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
            <Typography variant="h4" gutterBottom>
              GitHub Integration
            </Typography>
          </Box>
          <Paper sx={{ p: 3, boxShadow: 2 }}>
            <GitHubIntegration />
          </Paper>
        </Container>
      );
      
    case 6: // AI Task Management
      return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
          <AITaskManagementDashboard />
        </Container>
      );
      
    case 7: // Logs
      return (
        <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
            <Typography variant="h4" gutterBottom>
              System Logs
            </Typography>
          </Box>
          <Paper sx={{ p: 3, boxShadow: 2 }}>
            <LogViewer />
          </Paper>
        </Container>
      );
        
      default:
        return null;
    }
  };
  
  // Render new project dialog
  const renderNewProjectDialog = () => {
    return (
      <Dialog open={newProjectDialog} onClose={() => setNewProjectDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>Create New Project</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Fill in the details below to create a new AI-powered project.
          </DialogContentText>
          
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <TextField
                autoFocus
                margin="dense"
                id="name"
                name="name"
                label="Project Name"
                type="text"
                fullWidth
                variant="outlined"
                value={newProject.name}
                onChange={handleInputChange}
                required
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                id="description"
                name="description"
                label="Project Description"
                type="text"
                fullWidth
                variant="outlined"
                multiline
                rows={3}
                value={newProject.description}
                onChange={handleInputChange}
                required
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                id="repository_url"
                name="repository_url"
                label="Repository URL (optional)"
                type="url"
                fullWidth
                variant="outlined"
                value={newProject.repository_url}
                onChange={handleInputChange}
                placeholder="https://github.com/username/repository"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                id="idea_md"
                name="idea_md"
                label="Project Idea (Markdown)"
                type="text"
                fullWidth
                variant="outlined"
                multiline
                rows={6}
                value={newProject.idea_md}
                onChange={handleInputChange}
                placeholder="# Project Idea\n\nDescribe your project idea in markdown format...\n\n## Features\n\n- Feature 1\n- Feature 2"
                required
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewProjectDialog(false)}>Cancel</Button>
          <Button onClick={handleCreateProject} variant="contained" color="primary">
            Create Project
          </Button>
        </DialogActions>
      </Dialog>
    );
  };

  return (
    <ThemeProvider theme={darkTheme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <AppBar position="static">
          <Toolbar>
            <IconButton
              color="inherit"
              aria-label="open drawer"
              edge="start"
              onClick={handleDrawerToggle}
              sx={{ mr: 2 }}
            >
              <MenuIcon />
            </IconButton>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
              AI-SYSTEMS Platform
            </Typography>
            <IconButton color="inherit" onClick={handleRefresh}>
              <RefreshIcon />
            </IconButton>
            <IconButton color="inherit" onClick={() => setNewProjectDialog(true)}>
              <AddIcon />
            </IconButton>
          </Toolbar>
          <Tabs 
            value={currentTab} 
            onChange={handleTabChange} 
            aria-label="navigation tabs"
            variant="scrollable"
            scrollButtons="auto"
            sx={{ bgcolor: 'background.paper' }}
          >
            <Tab icon={<FolderIcon />} label="Projects" />
            <Tab icon={<TaskIcon />} label="Project Details" disabled={!selectedProject} />
            <Tab icon={<DashboardIcon />} label="System Status" />
            <Tab icon={<MonitorIcon />} label="Monitoring" />
            <Tab icon={<SettingsIcon />} label="AI Settings" />
            <Tab label="GitHub" icon={<GitHubIcon />} />
            <Tab label="AI Tasks" icon={<TaskIcon />} />
            <Tab icon={<ListAltIcon />} label="Logs" />
          </Tabs>
        </AppBar>
        
        <Drawer
          variant="temporary"
          open={drawerOpen}
          onClose={handleDrawerToggle}
          sx={{
            '& .MuiDrawer-paper': { width: 240, boxSizing: 'border-box' },
          }}
        >
          <List>
            <ListItem button onClick={() => { setCurrentTab(0); setDrawerOpen(false); }}>
              <ListItemIcon><FolderIcon /></ListItemIcon>
              <ListItemText primary="Projects" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(1); setDrawerOpen(false); }} disabled={!selectedProject}>
              <ListItemIcon><TaskIcon /></ListItemIcon>
              <ListItemText primary="Project Details" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(2); setDrawerOpen(false); }}>
              <ListItemIcon><DashboardIcon /></ListItemIcon>
              <ListItemText primary="System Status" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(3); setDrawerOpen(false); }}>
              <ListItemIcon><MonitorIcon /></ListItemIcon>
              <ListItemText primary="Monitoring" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(4); setDrawerOpen(false); }}>
              <ListItemIcon><SettingsIcon /></ListItemIcon>
              <ListItemText primary="AI Settings" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(5); setDrawerOpen(false); }}>
              <ListItemIcon><GitHubIcon /></ListItemIcon>
              <ListItemText primary="GitHub Integration" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(6); setDrawerOpen(false); }}>
              <ListItemIcon><TaskIcon /></ListItemIcon>
              <ListItemText primary="AI Task Management" />
            </ListItem>
            <ListItem button onClick={() => { setCurrentTab(7); setDrawerOpen(false); }}>
              <ListItemIcon><ListAltIcon /></ListItemIcon>
              <ListItemText primary="Logs" />
            </ListItem>
            <Divider />
          </List>
        </Drawer>
        
        <Box component="main" sx={{ flexGrow: 1, position: 'relative' }}>
          {/* Global loading indicator */}
          {loading.global && (
            <Box sx={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              zIndex: 9999,
              width: '100%'
            }}>
              <LinearProgress color="secondary" />
            </Box>
          )}
          {renderTabContent()}
        </Box>
        
        {renderNewProjectDialog()}
        
        <Snackbar
          open={notification.open}
          autoHideDuration={6000}
          onClose={handleCloseNotification}
          anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
          sx={{ mt: 6 }} // Add margin top to avoid overlap with AppBar
        >
          <Alert 
            onClose={handleCloseNotification} 
            severity={notification.severity} 
            variant="filled"
            elevation={6}
            sx={{ width: '100%', boxShadow: 3 }}
          >
            {notification.title && (
              <AlertTitle>{notification.title}</AlertTitle>
            )}
            {notification.message}
          </Alert>
        </Snackbar>
      </Box>
    </ThemeProvider>
  );
}

export default App;

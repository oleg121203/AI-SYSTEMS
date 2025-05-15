import React, { useState, useEffect } from 'react';
import {
  Alert,
  Avatar,
  AvatarGroup,
  Box,
  Card,
  CardContent,
  CardHeader,
  Chip,
  CircularProgress,
  Divider,
  Grid,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemIcon,
  ListItemText,
  Paper,
  Snackbar,
  Tab,
  Tabs,
  Tooltip,
  Typography,
  useTheme
} from '@mui/material';
import {
  Timeline,
  TimelineConnector,
  TimelineContent,
  TimelineDot,
  TimelineItem,
  TimelineOppositeContent,
  TimelineSeparator
} from '@mui/lab';
import RefreshIcon from '@mui/icons-material/Refresh';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import AssignmentIcon from '@mui/icons-material/Assignment';
import BugReportIcon from '@mui/icons-material/BugReport';
import DescriptionIcon from '@mui/icons-material/Description';
import CodeIcon from '@mui/icons-material/Code';
import GitHubIcon from '@mui/icons-material/GitHub';
import CommitIcon from '@mui/icons-material/Commit';
import MergeIcon from '@mui/icons-material/Merge';
import PullRequestIcon from '@mui/icons-material/CallSplit';
import EventIcon from '@mui/icons-material/Event';
import NotificationsIcon from '@mui/icons-material/Notifications';
import WarningIcon from '@mui/icons-material/Warning';
import InfoIcon from '@mui/icons-material/Info';
import BuildIcon from '@mui/icons-material/Build';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import DashboardIcon from '@mui/icons-material/Dashboard';
import { format, formatDistanceToNow } from 'date-fns';
import TaskList from './TaskList';
import WorkflowVisualizer from './WorkflowVisualizer';
import config from '../config';

/**
 * AITaskManagementDashboard displays the task assignments, status, and workflow between different AI agents
 */
const AITaskManagementDashboard = () => {
  const theme = useTheme();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tasks, setTasks] = useState([]);
  const [aiAgents, setAIAgents] = useState([]);
  const [taskAssignments, setTaskAssignments] = useState({});
  const [errorReports, setErrorReports] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [selectedTab, setSelectedTab] = useState(0);
  const [notification, setNotification] = useState({
    open: false,
    message: '',
    severity: 'info'
  });

  // Handle notification close
  const handleCloseNotification = () => {
    setNotification(prev => ({ ...prev, open: false }));
  };

  // Mock data for project events when API is not available
  const mockEvents = [
    {
      id: 'event-1',
      type: 'commit',
      title: 'Initial commit',
      description: 'Added project structure and base files',
      timestamp: '2025-05-10T08:30:00Z',
      actor: 'ai2_executor',
      data: {
        commitId: 'a1b2c3d4',
        branch: 'main',
        filesChanged: 12
      }
    },
    {
      id: 'event-2',
      type: 'pull_request',
      title: 'Add user authentication',
      description: 'Implemented JWT authentication system',
      timestamp: '2025-05-12T14:45:00Z',
      actor: 'ai2_executor',
      data: {
        prNumber: '#42',
        status: 'open',
        branch: 'feature/auth'
      }
    },
    {
      id: 'event-3',
      type: 'issue',
      title: 'Fix login page responsiveness',
      description: 'Login page is not displaying correctly on mobile devices',
      timestamp: '2025-05-13T09:15:00Z',
      actor: 'ai3',
      data: {
        issueNumber: '#56',
        priority: 'medium',
        assignee: 'ai2_executor'
      }
    },
    {
      id: 'event-4',
      type: 'build',
      title: 'Build failed',
      description: 'CI pipeline failed due to failing tests',
      timestamp: '2025-05-14T16:20:00Z',
      actor: 'github_actions',
      data: {
        buildNumber: '#123',
        status: 'failed',
        failedTests: 3
      }
    },
    {
      id: 'event-5',
      type: 'deployment',
      title: 'Deployed to staging',
      description: 'Successfully deployed version 0.2.1 to staging environment',
      timestamp: '2025-05-15T11:30:00Z',
      actor: 'github_actions',
      data: {
        environment: 'staging',
        version: '0.2.1',
        status: 'success'
      }
    },
    {
      id: 'event-6',
      type: 'code_review',
      title: 'Code review completed',
      description: 'Reviewed PR #42 with minor suggestions',
      timestamp: '2025-05-15T13:45:00Z',
      actor: 'ai1',
      data: {
        prNumber: '#42',
        status: 'approved_with_comments',
        comments: 5
      }
    },
    {
      id: 'event-7',
      type: 'merge',
      title: 'Merged PR #42',
      description: 'Merged user authentication feature into main',
      timestamp: '2025-05-15T15:20:00Z',
      actor: 'ai3',
      data: {
        prNumber: '#42',
        branch: 'feature/auth',
        targetBranch: 'main'
      }
    }
  ];
  
  // Mock data for tasks when API is not available
  const mockTasks = [
    {
      id: 'task-1',
      title: 'Implement User Authentication',
      description: 'Create a secure authentication system with JWT',
      status: 'in_progress',
      type: 'implementation',
      priority: 'high',
      assignedTo: 'ai2_executor',
      createdAt: '2025-05-10T10:00:00Z',
      updatedAt: '2025-05-15T09:30:00Z'
    },
    {
      id: 'task-2',
      title: 'Write Tests for API Endpoints',
      description: 'Create comprehensive test suite for all API endpoints',
      status: 'planning',
      type: 'testing',
      priority: 'medium',
      assignedTo: 'ai2_tester',
      createdAt: '2025-05-12T14:00:00Z',
      updatedAt: '2025-05-15T11:20:00Z'
    },
    {
      id: 'task-3',
      title: 'Create API Documentation',
      description: 'Generate comprehensive documentation for all API endpoints',
      status: 'completed',
      type: 'documentation',
      priority: 'medium',
      assignedTo: 'ai2_documenter',
      createdAt: '2025-05-08T09:00:00Z',
      updatedAt: '2025-05-14T16:45:00Z'
    },
    {
      id: 'task-4',
      title: 'Fix GitHub Integration Issues',
      description: 'Resolve issues with GitHub webhook integration',
      status: 'blocked',
      type: 'implementation',
      priority: 'high',
      assignedTo: 'ai3',
      createdAt: '2025-05-13T11:30:00Z',
      updatedAt: '2025-05-15T10:15:00Z'
    },
    {
      id: 'task-5',
      title: 'Optimize Database Queries',
      description: 'Improve performance of database queries in the backend',
      status: 'in_progress',
      type: 'implementation',
      priority: 'high',
      assignedTo: 'ai2_executor',
      createdAt: '2025-05-14T13:20:00Z',
      updatedAt: '2025-05-15T14:10:00Z'
    }
  ];

  // Mock data for AI config when API is not available
  const mockAIConfig = {
    'ai1': { provider: 'OpenAI', model: 'gpt-4-turbo' },
    'ai2_executor': { provider: 'Anthropic', model: 'claude-3-opus' },
    'ai2_tester': { provider: 'Codestral', model: 'codestral-22b' },
    'ai2_documenter': { provider: 'OpenAI', model: 'gpt-4-turbo' },
    'ai3': { provider: 'Anthropic', model: 'claude-3-sonnet' }
  };

  // Fetch tasks, AI agents, task assignments, and error reports
  const fetchData = async () => {
    // Use loading for initial load, refreshing for subsequent refreshes
    const isInitialLoad = loading;
    if (!isInitialLoad) {
      setRefreshing(true);
      setNotification({
        open: true,
        message: 'Refreshing AI task data...',
        severity: 'info'
      });
    }
    
    let tasksData = [];
    let aiConfigData = {};
    let usedMockData = false;
    
    try {
      // Try to fetch active tasks from API
      try {
        const tasksResponse = await fetch(`${config.apiBaseUrl}/api/tasks`);
        if (!tasksResponse.ok) {
          throw new Error(`HTTP error! status: ${tasksResponse.status}`);
        }
        tasksData = await tasksResponse.json();
      } catch (error) {
        console.warn('Failed to fetch tasks from API, using mock data:', error);
        tasksData = mockTasks;
        usedMockData = true;
      }
      
      setTasks(tasksData);

      // Try to fetch AI agents configuration
      try {
        const aiConfigResponse = await fetch(`${config.apiBaseUrl}/api/ai-config`);
        if (!aiConfigResponse.ok) {
          throw new Error(`HTTP error! status: ${aiConfigResponse.status}`);
        }
        aiConfigData = await aiConfigResponse.json();
      } catch (error) {
        console.warn('Failed to fetch AI config from API, using mock data:', error);
        aiConfigData = mockAIConfig;
        usedMockData = true;
      }
      
      // Transform AI config into agents array
      const agents = Object.entries(aiConfigData || {}).map(([id, config]) => ({
        id,
        name: getAgentName(id),
        role: getAgentRole(id),
        provider: config.provider,
        model: config.model
      }));
      setAIAgents(agents);

      // Fetch task assignments (simulated for now)
      // In a real implementation, this would come from the backend
      const mockAssignments = {
        'ai1': tasksData.filter(t => t.status === 'planning' || t.status === 'reviewing'),
        'ai2_executor': tasksData.filter(t => t.status === 'in_progress' && t.type === 'implementation'),
        'ai2_tester': tasksData.filter(t => t.status === 'in_progress' && t.type === 'testing'),
        'ai2_documenter': tasksData.filter(t => t.status === 'in_progress' && t.type === 'documentation'),
        'ai3': tasksData.filter(t => t.status === 'blocked' || t.status === 'failed')
      };
      setTaskAssignments(mockAssignments);

      // Fetch error reports (simulated for now)
      const mockErrorReports = [
        {
          id: 'err-1',
          title: 'Test Failure in UserAuthentication',
          description: 'GitHub Action test failed: User login validation is not handling special characters correctly',
          file: 'auth/user_auth.py',
          lineNumber: 78,
          severity: 'high',
          status: 'pending',
          reportedBy: 'ai3',
          assignedTo: 'ai1'
        },
        {
          id: 'err-2',
          title: 'Performance Issue in Data Processing',
          description: 'The data processing function is taking too long to execute with large datasets',
          file: 'data/processor.py',
          lineNumber: 124,
          severity: 'medium',
          status: 'assigned',
          reportedBy: 'ai3',
          assignedTo: 'ai2_executor'
        }
      ];
      setErrorReports(mockErrorReports);
      
      // Show appropriate notification based on whether we used mock data
      if (!isInitialLoad) {
        if (usedMockData) {
          setNotification({
            open: true,
            message: `Using demo data: API endpoints not available. Loaded ${tasksData.length} mock tasks and ${agents.length} AI agents.`,
            severity: 'warning'
          });
        } else {
          setNotification({
            open: true,
            message: `Successfully loaded ${tasksData.length} tasks and ${agents.length} AI agents`,
            severity: 'success'
          });
        }
      }
    } catch (error) {
      console.error('Error fetching data:', error);
      
      // Fall back to mock data in case of complete failure
      setTasks(mockTasks);
      
      // Transform AI config into agents array using mock data
      const agents = Object.entries(mockAIConfig).map(([id, config]) => ({
        id,
        name: getAgentName(id),
        role: getAgentRole(id),
        provider: config.provider,
        model: config.model
      }));
      setAIAgents(agents);
      
      // Create mock assignments
      const mockAssignments = {
        'ai1': mockTasks.filter(t => t.status === 'planning' || t.status === 'reviewing'),
        'ai2_executor': mockTasks.filter(t => t.status === 'in_progress' && t.type === 'implementation'),
        'ai2_tester': mockTasks.filter(t => t.status === 'in_progress' && t.type === 'testing'),
        'ai2_documenter': mockTasks.filter(t => t.status === 'in_progress' && t.type === 'documentation'),
        'ai3': mockTasks.filter(t => t.status === 'blocked' || t.status === 'failed')
      };
      setTaskAssignments(mockAssignments);
      
      setNotification({
        open: true,
        message: `Using demo data: ${error.message}`,
        severity: 'warning'
      });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Helper function to get agent name
  const getAgentName = (id) => {
    switch (id) {
      case 'ai1':
        return 'AI1 Coordinator';
      case 'ai2_executor':
        return 'AI2 Executor';
      case 'ai2_tester':
        return 'AI2 Tester';
      case 'ai2_documenter':
        return 'AI2 Documenter';
      case 'ai3':
        return 'AI3 Project Manager';
      default:
        return id;
    }
  };

  // Helper function to get agent role
  const getAgentRole = (id) => {
    switch (id) {
      case 'ai1':
        return 'coordinator';
      case 'ai2_executor':
        return 'executor';
      case 'ai2_tester':
        return 'tester';
      case 'ai2_documenter':
        return 'documenter';
      case 'ai3':
        return 'manager';
      default:
        return 'unknown';
    }
  };

  // Get status icon based on task status
  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed':
        return <CheckCircleIcon color="success" />;
      case 'in_progress':
        return <HourglassEmptyIcon color="primary" />;
      case 'failed':
        return <ErrorOutlineIcon color="error" />;
      case 'blocked':
        return <ErrorOutlineIcon color="warning" />;
      default:
        return <AssignmentIcon color="disabled" />;
    }
  };

  // Get status color based on task status
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'in_progress':
        return 'primary';
      case 'failed':
        return 'error';
      case 'blocked':
        return 'warning';
      default:
        return 'default';
    }
  };

  // Get task type icon
  const getTaskTypeIcon = (type) => {
    switch (type) {
      case 'implementation':
        return <CodeIcon />;
      case 'testing':
        return <BugReportIcon />;
      case 'documentation':
        return <DescriptionIcon />;
      default:
        return <AssignmentIcon />;
    }
  };

  // Load data on component mount
  useEffect(() => {
    fetchData();
    // Set up polling for real-time updates - using a longer interval for mock data
    const intervalId = setInterval(fetchData, 60000); // Poll every 60 seconds
    
    return () => clearInterval(intervalId); // Clean up on unmount
  }, []);

  // Handle refresh button click
  const handleRefresh = () => {
    fetchData();
  };

  // Handle agent selection
  const handleAgentSelect = (agentId) => {
    setSelectedAgent(agentId === selectedAgent ? null : agentId);
    // Switch to Tasks tab when an agent is selected
    if (agentId !== selectedAgent) {
      setSelectedTab(2);
    }
  };
  
  // Handle tab change
  const handleTabChange = (event, newValue) => {
    setSelectedTab(newValue);
  };

  // Render AI agent cards
  const renderAgentCards = () => {
    return (
      <Grid container spacing={3}>
        {aiAgents.map((agent) => (
          <Grid item xs={12} sm={6} md={4} key={agent.id}>
            <Card 
              sx={{ 
                cursor: 'pointer',
                transition: 'transform 0.2s',
                '&:hover': { transform: 'translateY(-5px)' },
                bgcolor: selectedAgent === agent.id ? theme.palette.background.card : theme.palette.background.paper,
                borderLeft: `4px solid ${
                  agent.role === 'coordinator' ? theme.palette.primary.main :
                  agent.role === 'executor' ? theme.palette.secondary.main :
                  agent.role === 'tester' ? theme.palette.info.main :
                  agent.role === 'documenter' ? theme.palette.warning.main :
                  theme.palette.success.main
                }`
              }}
              onClick={() => handleAgentSelect(agent.id)}
            >
              <CardHeader
                title={agent.name}
                subheader={`${agent.provider} / ${agent.model}`}
                action={
                  <Chip 
                    label={`${taskAssignments[agent.id]?.length || 0} Tasks`} 
                    color={taskAssignments[agent.id]?.length > 0 ? 'primary' : 'default'}
                    size="small"
                  />
                }
              />
              <CardContent>
                <Typography variant="body2" color="textSecondary" gutterBottom>
                  {agent.role === 'coordinator' ? 'Coordinates all AI activities and assigns tasks' :
                   agent.role === 'executor' ? 'Implements code based on specifications' :
                   agent.role === 'tester' ? 'Tests code and reports issues' :
                   agent.role === 'documenter' ? 'Creates documentation for code' :
                   'Manages project and reports errors from GitHub Actions'}
                </Typography>
                
                {taskAssignments[agent.id]?.length > 0 && (
                  <Box sx={{ mt: 2 }}>
                    <Typography variant="caption" color="textSecondary">
                      Current Tasks:
                    </Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                      {taskAssignments[agent.id].slice(0, 3).map((task) => (
                        <Tooltip key={task.id} title={task.title || task.name}>
                          <Chip
                            icon={getTaskTypeIcon(task.type)}
                            label={task.title?.substring(0, 15) || task.name?.substring(0, 15) || task.id}
                            size="small"
                            color={getStatusColor(task.status)}
                            sx={{ mb: 0.5 }}
                          />
                        </Tooltip>
                      ))}
                      {taskAssignments[agent.id].length > 3 && (
                        <Chip
                          label={`+${taskAssignments[agent.id].length - 3} more`}
                          size="small"
                          variant="outlined"
                        />
                      )}
                    </Box>
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    );
  };

  // Get event icon based on event type
  const getEventIcon = (type) => {
    switch (type) {
      case 'commit':
        return <CommitIcon />;
      case 'pull_request':
        return <PullRequestIcon />;
      case 'merge':
        return <MergeIcon />;
      case 'issue':
        return <AssignmentIcon />;
      case 'build':
        return <BuildIcon />;
      case 'deployment':
        return <AutoFixHighIcon />;
      case 'code_review':
        return <DescriptionIcon />;
      case 'error':
        return <ErrorOutlineIcon color="error" />;
      case 'warning':
        return <WarningIcon color="warning" />;
      default:
        return <EventIcon />;
    }
  };
  
  // Get event color based on event type
  const getEventColor = (type, data) => {
    switch (type) {
      case 'commit':
        return 'info';
      case 'pull_request':
        return 'primary';
      case 'merge':
        return 'success';
      case 'issue':
        return 'warning';
      case 'build':
        return data?.status === 'failed' ? 'error' : 'success';
      case 'deployment':
        return data?.status === 'success' ? 'success' : 'error';
      case 'code_review':
        return 'info';
      case 'error':
        return 'error';
      case 'warning':
        return 'warning';
      default:
        return 'default';
    }
  };
  
  // Format timestamp
  const formatTimestamp = (timestamp) => {
    try {
      const date = new Date(timestamp);
      return {
        formatted: format(date, 'MMM dd, yyyy HH:mm'),
        relative: formatDistanceToNow(date, { addSuffix: true })
      };
    } catch (error) {
      return {
        formatted: 'Invalid date',
        relative: 'Unknown time'
      };
    }
  };

  // Render project timeline with all events
  const renderProjectTimeline = () => {
    // Combine tasks and events into a single timeline
    const allEvents = [
      ...mockEvents,
      ...errorReports.map(report => ({
        id: report.id,
        type: 'error',
        title: report.title,
        description: report.description,
        timestamp: new Date().toISOString(), // Use current time as fallback
        actor: report.reportedBy,
        data: {
          file: report.file,
          lineNumber: report.lineNumber,
          severity: report.severity
        }
      }))
    ];
    
    // Sort by timestamp, newest first
    const sortedEvents = [...allEvents].sort((a, b) => 
      new Date(b.timestamp) - new Date(a.timestamp)
    );
    
    return (
      <Paper sx={{ p: 3, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">
            Project Activity Timeline
          </Typography>
          <Chip 
            icon={<NotificationsIcon />}
            label={`${sortedEvents.length} Events`} 
            color="primary"
          />
        </Box>
        
        <Timeline position="alternate" sx={{ mb: 0 }}>
          {sortedEvents.map((event) => {
            const time = formatTimestamp(event.timestamp);
            const eventColor = getEventColor(event.type, event.data);
            
            return (
              <TimelineItem key={event.id}>
                <TimelineOppositeContent color="text.secondary">
                  <Typography variant="body2">{time.formatted}</Typography>
                  <Typography variant="caption">{time.relative}</Typography>
                </TimelineOppositeContent>
                
                <TimelineSeparator>
                  <TimelineDot color={eventColor}>
                    {getEventIcon(event.type)}
                  </TimelineDot>
                  <TimelineConnector />
                </TimelineSeparator>
                
                <TimelineContent>
                  <Paper elevation={2} sx={{ p: 2, bgcolor: `${eventColor}.light`, color: `${eventColor}.contrastText` }}>
                    <Typography variant="subtitle1" component="div" fontWeight="bold">
                      {event.title}
                    </Typography>
                    
                    <Typography variant="body2">{event.description}</Typography>
                    
                    <Box sx={{ display: 'flex', alignItems: 'center', mt: 1, flexWrap: 'wrap', gap: 1 }}>
                      {event.type === 'commit' && (
                        <>
                          <Chip size="small" label={`Commit: ${event.data.commitId.substring(0, 7)}`} />
                          <Chip size="small" label={`Branch: ${event.data.branch}`} />
                          <Chip size="small" label={`${event.data.filesChanged} files changed`} />
                        </>
                      )}
                      
                      {event.type === 'pull_request' && (
                        <>
                          <Chip size="small" label={`PR ${event.data.prNumber}`} />
                          <Chip 
                            size="small" 
                            color={event.data.status === 'open' ? 'primary' : 'success'}
                            label={event.data.status.toUpperCase()} 
                          />
                          <Chip size="small" label={`Branch: ${event.data.branch}`} />
                        </>
                      )}
                      
                      {event.type === 'issue' && (
                        <>
                          <Chip size="small" label={`Issue ${event.data.issueNumber}`} />
                          <Chip 
                            size="small" 
                            color={event.data.priority === 'high' ? 'error' : 'warning'}
                            label={`Priority: ${event.data.priority.toUpperCase()}`} 
                          />
                          <Chip size="small" label={`Assigned to: ${getAgentName(event.data.assignee)}`} />
                        </>
                      )}
                      
                      {event.type === 'build' && (
                        <>
                          <Chip size="small" label={`Build ${event.data.buildNumber}`} />
                          <Chip 
                            size="small" 
                            color={event.data.status === 'success' ? 'success' : 'error'}
                            label={event.data.status.toUpperCase()} 
                          />
                          {event.data.failedTests && (
                            <Chip size="small" color="error" label={`${event.data.failedTests} tests failed`} />
                          )}
                        </>
                      )}
                      
                      {event.type === 'deployment' && (
                        <>
                          <Chip size="small" label={`Environment: ${event.data.environment}`} />
                          <Chip size="small" label={`Version: ${event.data.version}`} />
                          <Chip 
                            size="small" 
                            color={event.data.status === 'success' ? 'success' : 'error'}
                            label={event.data.status.toUpperCase()} 
                          />
                        </>
                      )}
                      
                      {event.type === 'code_review' && (
                        <>
                          <Chip size="small" label={`PR ${event.data.prNumber}`} />
                          <Chip 
                            size="small" 
                            color={event.data.status.includes('approved') ? 'success' : 'warning'}
                            label={event.data.status.replace(/_/g, ' ').toUpperCase()} 
                          />
                          <Chip size="small" label={`${event.data.comments} comments`} />
                        </>
                      )}
                      
                      {event.type === 'merge' && (
                        <>
                          <Chip size="small" label={`PR ${event.data.prNumber}`} />
                          <Chip size="small" label={`From: ${event.data.branch}`} />
                          <Chip size="small" label={`To: ${event.data.targetBranch}`} />
                        </>
                      )}
                      
                      {event.type === 'error' && (
                        <>
                          <Chip size="small" color="error" label={`Severity: ${event.data.severity.toUpperCase()}`} />
                          <Chip size="small" label={`File: ${event.data.file}`} />
                          <Chip size="small" label={`Line: ${event.data.lineNumber}`} />
                        </>
                      )}
                      
                      <Chip 
                        size="small" 
                        avatar={<Avatar sx={{ bgcolor: theme.palette.background.paper }}>{getAgentName(event.actor).charAt(0)}</Avatar>}
                        label={getAgentName(event.actor)}
                        variant="outlined"
                      />
                    </Box>
                  </Paper>
                </TimelineContent>
              </TimelineItem>
            );
          })}
        </Timeline>
      </Paper>
    );
  };
  
  // Render error reports
  const renderErrorReports = () => {
    return (
      <Paper sx={{ p: 2, mt: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">
            Error Reports from GitHub Actions
          </Typography>
          <Chip 
            label={`${errorReports.length} Reports`} 
            color={errorReports.length > 0 ? 'error' : 'default'}
          />
        </Box>
        
        {errorReports.length === 0 ? (
          <Typography variant="body2" color="textSecondary" sx={{ textAlign: 'center', py: 2 }}>
            No error reports available
          </Typography>
        ) : (
          <Grid container spacing={2}>
            {errorReports.map((report) => (
              <Grid item xs={12} key={report.id}>
                <Paper 
                  elevation={1} 
                  sx={{ 
                    p: 2,
                    borderLeft: `4px solid ${
                      report.severity === 'high' ? theme.palette.error.main :
                      report.severity === 'medium' ? theme.palette.warning.main :
                      theme.palette.info.main
                    }`
                  }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <Box>
                      <Typography variant="subtitle1" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <ErrorOutlineIcon color="error" />
                        {report.title}
                      </Typography>
                      <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>
                        {report.description}
                      </Typography>
                      <Box sx={{ display: 'flex', alignItems: 'center', mt: 1 }}>
                        <Chip 
                          label={report.file} 
                          size="small" 
                          icon={<CodeIcon />} 
                          sx={{ mr: 1 }} 
                        />
                        <Typography variant="caption" color="textSecondary">
                          Line: {report.lineNumber}
                        </Typography>
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                      <Chip 
                        label={report.severity.toUpperCase()} 
                        color={
                          report.severity === 'high' ? 'error' :
                          report.severity === 'medium' ? 'warning' :
                          'info'
                        }
                        size="small"
                        sx={{ mb: 1 }}
                      />
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="caption" color="textSecondary">
                          {getAgentName(report.reportedBy)}
                        </Typography>
                        <ArrowForwardIcon fontSize="small" color="disabled" />
                        <Typography variant="caption" color="textSecondary">
                          {getAgentName(report.assignedTo)}
                        </Typography>
                      </Box>
                    </Box>
                  </Box>
                </Paper>
              </Grid>
            ))}
          </Grid>
        )}
      </Paper>
    );
  };

  return (
    <>
      <Box sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4">
            AI Task Management
          </Typography>
          <Tooltip title="Refresh data">
            <span>
              <IconButton onClick={handleRefresh} disabled={loading || refreshing}>
                {refreshing ? <CircularProgress size={24} /> : <RefreshIcon />}
              </IconButton>
            </span>
          </Tooltip>
        </Box>
        
        {/* Loading progress indicator */}
        {refreshing && !loading && (
          <Box sx={{ width: '100%', mb: 2 }}>
            <LinearProgress color="secondary" />
          </Box>
        )}

        {loading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', p: 5 }}>
            <CircularProgress size={40} thickness={4} />
            <Typography variant="h6" sx={{ mt: 2, color: 'text.secondary' }}>
              Loading AI Task Management Dashboard...
            </Typography>
          </Box>
        ) : (
          <>
            {/* Project Dashboard with Tabs */}
            <Paper sx={{ p: 2, mb: 3 }}>
              <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
                <Tabs value={selectedTab} onChange={handleTabChange} aria-label="project tabs" variant="scrollable" scrollButtons="auto">
                  <Tab icon={<DashboardIcon />} label="Overview" id="tab-0" />
                  <Tab icon={<EventIcon />} label="Timeline" id="tab-1" />
                  <Tab icon={<AssignmentIcon />} label="Tasks" id="tab-2" />
                  <Tab icon={<GitHubIcon />} label="GitHub" id="tab-3" />
                  <Tab icon={<ErrorOutlineIcon />} label="Issues" id="tab-4" />
                </Tabs>
              </Box>
              
              {/* Tab Content */}
              <Box role="tabpanel" hidden={selectedTab !== 0} id="tabpanel-0" aria-labelledby="tab-0">
                {selectedTab === 0 && (
                  <>
                    <Typography variant="h6" gutterBottom>
                      Project Overview
                    </Typography>
                    
                    {/* Project Stats */}
                    <Grid container spacing={2} sx={{ mb: 3 }}>
                      <Grid item xs={12} sm={6} md={3}>
                        <Card sx={{ height: '100%', bgcolor: 'primary.dark', color: 'primary.contrastText' }}>
                          <CardContent>
                            <Typography variant="h3" component="div">
                              {tasks.length}
                            </Typography>
                            <Typography variant="body2">
                              Active Tasks
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                      <Grid item xs={12} sm={6} md={3}>
                        <Card sx={{ height: '100%', bgcolor: 'success.dark', color: 'success.contrastText' }}>
                          <CardContent>
                            <Typography variant="h3" component="div">
                              {tasks.filter(t => t.status === 'completed').length}
                            </Typography>
                            <Typography variant="body2">
                              Completed Tasks
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                      <Grid item xs={12} sm={6} md={3}>
                        <Card sx={{ height: '100%', bgcolor: 'warning.dark', color: 'warning.contrastText' }}>
                          <CardContent>
                            <Typography variant="h3" component="div">
                              {mockEvents.filter(e => e.type === 'commit').length}
                            </Typography>
                            <Typography variant="body2">
                              Commits
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                      <Grid item xs={12} sm={6} md={3}>
                        <Card sx={{ height: '100%', bgcolor: 'error.dark', color: 'error.contrastText' }}>
                          <CardContent>
                            <Typography variant="h3" component="div">
                              {errorReports.length}
                            </Typography>
                            <Typography variant="body2">
                              Issues
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                    </Grid>
                    
                    {/* Workflow Visualization */}
                    <Typography variant="h6" gutterBottom>
                      AI Workflow Visualization
                    </Typography>
                    <WorkflowVisualizer tasks={tasks} loading={false} />
                    
                    {/* AI Agents */}
                    <Typography variant="h6" gutterBottom sx={{ mt: 3 }}>
                      AI Agents & Task Assignments
                    </Typography>
                    {renderAgentCards()}
                    
                    {/* Recent Activity */}
                    <Typography variant="h6" gutterBottom sx={{ mt: 3 }}>
                      Recent Activity
                    </Typography>
                    <List>
                      {mockEvents.slice(0, 5).map((event) => {
                        const time = formatTimestamp(event.timestamp);
                        return (
                          <ListItem key={event.id} divider>
                            <ListItemIcon>
                              {getEventIcon(event.type)}
                            </ListItemIcon>
                            <ListItemText 
                              primary={event.title}
                              secondary={
                                <>
                                  {event.description}
                                  <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                                    {time.relative} by {getAgentName(event.actor)}
                                  </Typography>
                                </>
                              }
                            />
                            <Chip 
                              size="small" 
                              label={event.type.replace('_', ' ')}
                              color={getEventColor(event.type, event.data)}
                            />
                          </ListItem>
                        );
                      })}
                    </List>
                  </>
                )}
              </Box>
              
              <Box role="tabpanel" hidden={selectedTab !== 1} id="tabpanel-1" aria-labelledby="tab-1">
                {selectedTab === 1 && renderProjectTimeline()}
              </Box>
              
              <Box role="tabpanel" hidden={selectedTab !== 2} id="tabpanel-2" aria-labelledby="tab-2">
                {selectedTab === 2 && (
                  <>
                    <Typography variant="h6" gutterBottom>
                      All Tasks
                    </Typography>
                    <TaskList tasks={tasks} />
                    
                    {selectedAgent && taskAssignments[selectedAgent]?.length > 0 && (
                      <Box sx={{ mt: 3 }}>
                        <Typography variant="h6" gutterBottom>
                          Tasks for {getAgentName(selectedAgent)}
                        </Typography>
                        <TaskList tasks={taskAssignments[selectedAgent]} />
                      </Box>
                    )}
                  </>
                )}
              </Box>
              
              <Box role="tabpanel" hidden={selectedTab !== 3} id="tabpanel-3" aria-labelledby="tab-3">
                {selectedTab === 3 && (
                  <>
                    <Typography variant="h6" gutterBottom>
                      GitHub Activity
                    </Typography>
                    <List>
                      {mockEvents
                        .filter(e => ['commit', 'pull_request', 'merge', 'issue'].includes(e.type))
                        .map((event) => {
                          const time = formatTimestamp(event.timestamp);
                          return (
                            <ListItem key={event.id} divider>
                              <ListItemIcon>
                                {getEventIcon(event.type)}
                              </ListItemIcon>
                              <ListItemText 
                                primary={event.title}
                                secondary={
                                  <>
                                    {event.description}
                                    <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                                      {time.relative} by {getAgentName(event.actor)}
                                    </Typography>
                                  </>
                                }
                              />
                              <Chip 
                                size="small" 
                                label={event.type.replace('_', ' ')}
                                color={getEventColor(event.type, event.data)}
                              />
                            </ListItem>
                          );
                        })}
                    </List>
                  </>
                )}
              </Box>
              
              <Box role="tabpanel" hidden={selectedTab !== 4} id="tabpanel-4" aria-labelledby="tab-4">
                {selectedTab === 4 && renderErrorReports()}
              </Box>
            </Paper>  
          </>
        )}
      </Box>
      
      {/* Notification Snackbar */}
      <Snackbar
        open={notification.open}
        autoHideDuration={6000}
        onClose={handleCloseNotification}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert 
          onClose={handleCloseNotification} 
          severity={notification.severity} 
          variant="filled"
          elevation={6}
          sx={{ width: '100%' }}
        >
          {notification.message}
        </Alert>
      </Snackbar>
    </>
  );
};

export default AITaskManagementDashboard;

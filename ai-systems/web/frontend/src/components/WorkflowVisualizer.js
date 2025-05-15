import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Tooltip,
  Paper,
  useTheme,
  IconButton,
  Chip,
  Badge,
  Collapse,
  Zoom,
  Fade,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Divider,
  LinearProgress,
  Stack,
  Grid
} from '@mui/material';
import { motion, AnimatePresence } from 'framer-motion';
import InfoIcon from '@mui/icons-material/Info';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import PendingIcon from '@mui/icons-material/Pending';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import ZoomInIcon from '@mui/icons-material/ZoomIn';
import ZoomOutIcon from '@mui/icons-material/ZoomOut';
import RefreshIcon from '@mui/icons-material/Refresh';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import MemoryIcon from '@mui/icons-material/Memory';
import SettingsIcon from '@mui/icons-material/Settings';

/**
 * WorkflowVisualizer component displays a real-time visualization of the AI workflow
 * @param {Object} props - Component props
 * @param {Array} props.tasks - Array of tasks to visualize
 * @param {Boolean} props.loading - Whether the component is loading data
 * @param {Object} props.aiConfig - Configuration of AI models being used
 */
const WorkflowVisualizer = ({ tasks = [], loading = false, aiConfig = {} }) => {
  const theme = useTheme();
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [zoom, setZoom] = useState(1);
  const [selectedNode, setSelectedNode] = useState(null);
  const [dataFlows, setDataFlows] = useState([]);
  const [showDetails, setShowDetails] = useState(false);
  const [animationPaused, setAnimationPaused] = useState(false);
  const [showModelInfo, setShowModelInfo] = useState(false);
  const [taskStats, setTaskStats] = useState({
    completed: 0,
    inProgress: 0,
    pending: 0,
    failed: 0
  });
  
  // Track task execution times for performance metrics
  const [executionTimes, setExecutionTimes] = useState({});
  const [nodeDetailsOpen, setNodeDetailsOpen] = useState(false);
  const [selectedNodeDetails, setSelectedNodeDetails] = useState(null);

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: 600 // Increased height for better visualization
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    
    return () => {
      window.removeEventListener('resize', updateDimensions);
    };
  }, []);
  
  // Handle zoom in/out
  const handleZoomIn = () => {
    setZoom(prevZoom => Math.min(prevZoom + 0.2, 2));
  };
  
  const handleZoomOut = () => {
    setZoom(prevZoom => Math.max(prevZoom - 0.2, 0.5));
  };
  
  const handleResetZoom = () => {
    setZoom(1);
  };
  
  // Toggle animation pause
  const toggleAnimationPause = () => {
    setAnimationPaused(prev => !prev);
  };
  
  // Handle node selection for details view
  const handleNodeClick = (node) => {
    setSelectedNodeDetails(node);
    setNodeDetailsOpen(true);
  };
  
  // Close node details dialog
  const handleCloseDetails = () => {
    setNodeDetailsOpen(false);
  };

  // Process tasks into nodes and edges for visualization
  useEffect(() => {
    if (!tasks.length) return;
    
    const newNodes = [];
    const newEdges = [];
    const newDataFlows = [];
    
    // Calculate task statistics
    const stats = {
      completed: 0,
      inProgress: 0,
      pending: 0,
      failed: 0
    };
    
    tasks.forEach(task => {
      if (task.status === 'completed') stats.completed++;
      else if (task.status === 'in_progress') stats.inProgress++;
      else if (task.status === 'failed') stats.failed++;
      else stats.pending++;
      
      // Track execution times for performance metrics
      if (task.startTime && task.endTime && task.status === 'completed') {
        setExecutionTimes(prev => ({
          ...prev,
          [task.id]: (new Date(task.endTime) - new Date(task.startTime)) / 1000 // in seconds
        }));
      }
    });
    
    setTaskStats(stats);
    
    // Define AI agent nodes with model info from aiConfig
    const agentNodes = [
      { 
        id: 'ai1', 
        label: 'AI1 Coordinator', 
        x: dimensions.width * 0.5, 
        y: 80, 
        type: 'coordinator',
        model: aiConfig.ai1?.model || 'Unknown',
        provider: aiConfig.ai1?.provider || 'Unknown',
        tasks: tasks.filter(t => t.agent === 'ai1').length
      },
      { 
        id: 'ai2_executor', 
        label: 'AI2 Executor', 
        x: dimensions.width * 0.25, 
        y: 200, 
        type: 'executor',
        model: aiConfig.ai2_executor?.model || 'Unknown',
        provider: aiConfig.ai2_executor?.provider || 'Unknown',
        tasks: tasks.filter(t => t.agent === 'ai2_executor' || t.role === 'executor').length
      },
      { 
        id: 'ai2_tester', 
        label: 'AI2 Tester', 
        x: dimensions.width * 0.5, 
        y: 200, 
        type: 'tester',
        model: aiConfig.ai2_tester?.model || 'Unknown',
        provider: aiConfig.ai2_tester?.provider || 'Unknown',
        tasks: tasks.filter(t => t.agent === 'ai2_tester' || t.role === 'tester').length
      },
      { 
        id: 'ai2_documenter', 
        label: 'AI2 Documenter', 
        x: dimensions.width * 0.75, 
        y: 200, 
        type: 'documenter',
        model: aiConfig.ai2_documenter?.model || 'Unknown',
        provider: aiConfig.ai2_documenter?.provider || 'Unknown',
        tasks: tasks.filter(t => t.agent === 'ai2_documenter' || t.role === 'documenter').length
      },
      { 
        id: 'ai3', 
        label: 'AI3 Project Manager', 
        x: dimensions.width * 0.5, 
        y: 320, 
        type: 'manager',
        model: aiConfig.ai3?.model || 'Unknown',
        provider: aiConfig.ai3?.provider || 'Unknown',
        tasks: tasks.filter(t => t.agent === 'ai3').length
      }
    ];
    
    // Add agent nodes
    newNodes.push(...agentNodes);
    
    // Add connections between agents with data flow indicators
    newEdges.push(
      { 
        id: 'edge-ai1-executor',
        source: 'ai1', 
        target: 'ai2_executor', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'command',
        strength: tasks.filter(t => t.role === 'executor').length
      },
      { 
        id: 'edge-ai1-tester',
        source: 'ai1', 
        target: 'ai2_tester', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'command',
        strength: tasks.filter(t => t.role === 'tester').length
      },
      { 
        id: 'edge-ai1-documenter',
        source: 'ai1', 
        target: 'ai2_documenter', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'command',
        strength: tasks.filter(t => t.role === 'documenter').length
      },
      { 
        id: 'edge-ai1-manager',
        source: 'ai1', 
        target: 'ai3', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'report',
        strength: tasks.filter(t => t.agent === 'ai3').length
      },
      { 
        id: 'edge-executor-manager',
        source: 'ai2_executor', 
        target: 'ai3', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'feedback',
        strength: Math.min(5, tasks.filter(t => t.role === 'executor' && t.status === 'completed').length)
      },
      { 
        id: 'edge-tester-manager',
        source: 'ai2_tester', 
        target: 'ai3', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'feedback',
        strength: Math.min(5, tasks.filter(t => t.role === 'tester' && t.status === 'completed').length)
      },
      { 
        id: 'edge-documenter-manager',
        source: 'ai2_documenter', 
        target: 'ai3', 
        animated: !animationPaused && stats.inProgress > 0,
        type: 'feedback',
        strength: Math.min(5, tasks.filter(t => t.role === 'documenter' && t.status === 'completed').length)
      }
    );
    
    // Create data flow visualizations
    newEdges.forEach(edge => {
      if (edge.strength > 0) {
        newDataFlows.push({
          id: `flow-${edge.id}`,
          sourceId: edge.source,
          targetId: edge.target,
          strength: edge.strength,
          type: edge.type
        });
      }
    });
    
    // Add task nodes with more information
    tasks.forEach((task, index) => {
      const taskId = `task-${task.id || index}`;
      const taskType = task.role || 'unknown';
      let targetAgent;
      
      switch (taskType) {
        case 'executor':
          targetAgent = 'ai2_executor';
          break;
        case 'tester':
          targetAgent = 'ai2_tester';
          break;
        case 'documenter':
          targetAgent = 'ai2_documenter';
          break;
        default:
          targetAgent = 'ai3';
      }
      
      // Calculate position with some randomness but avoid overlaps
      const baseX = getAgentNodeById(targetAgent, agentNodes).x;
      const baseY = getAgentNodeById(targetAgent, agentNodes).y + 100;
      const offset = index % 3 - 1; // -1, 0, or 1
      
      // Add task node with enhanced information
      newNodes.push({
        id: taskId,
        label: task.filename || `Task ${index + 1}`,
        x: baseX + (offset * 80),
        y: baseY + (Math.floor(index / 3) * 70),
        type: 'task',
        status: task.status,
        progress: task.progress || 0,
        startTime: task.startTime,
        endTime: task.endTime,
        priority: task.priority || 'medium',
        data: task
      });
      
      // Add edge from agent to task with more information
      newEdges.push({
        id: `edge-${targetAgent}-${taskId}`,
        source: targetAgent,
        target: taskId,
        animated: !animationPaused && task.status === 'in_progress',
        status: task.status,
        type: 'assignment'
      });
      
      // Add dependencies between tasks if they exist
      if (task.dependencies && task.dependencies.length > 0) {
        task.dependencies.forEach(depId => {
          const depTaskId = `task-${depId}`;
          if (newNodes.some(n => n.id === depTaskId)) {
            newEdges.push({
              id: `dep-${depTaskId}-${taskId}`,
              source: depTaskId,
              target: taskId,
              animated: false,
              status: 'dependency',
              type: 'dependency',
              style: { strokeDasharray: '3,3' }
            });
          }
        });
      }
    });
    
    setNodes(newNodes);
    setEdges(newEdges);
    setDataFlows(newDataFlows);
  }, [tasks, dimensions.width, animationPaused, aiConfig]);
  
  // Helper function to get agent node by ID
  const getAgentNodeById = (id, agentNodes) => {
    return agentNodes.find(node => node.id === id) || { x: 0, y: 0 };
  };
  
  // Get node style based on type and status
  const getNodeStyle = (node) => {
    let color, borderColor, opacity = 1, glow = false;
    
    // Base color by node type
    if (node.type === 'coordinator') color = theme.palette.primary.main;
    else if (node.type === 'executor') color = theme.palette.secondary.main;
    else if (node.type === 'tester') color = theme.palette.info.main;
    else if (node.type === 'documenter') color = theme.palette.warning.main;
    else if (node.type === 'manager') color = theme.palette.success.main;
    else color = theme.palette.grey[500];
    
    // Task nodes get special styling based on status
    if (node.type === 'task') {
      switch (node.status) {
        case 'completed':
          color = theme.palette.success.main;
          borderColor = theme.palette.success.dark;
          break;
        case 'in_progress':
          color = theme.palette.info.main;
          borderColor = theme.palette.info.dark;
          glow = true;
          break;
        case 'failed':
          color = theme.palette.error.main;
          borderColor = theme.palette.error.dark;
          break;
        case 'pending':
          color = theme.palette.grey[400];
          borderColor = theme.palette.grey[600];
          opacity = 0.8;
          break;
        default:
          color = theme.palette.grey[500];
          borderColor = theme.palette.grey[700];
      }
      
      // Adjust by priority if available
      if (node.priority === 'high') {
        opacity = 1;
        glow = true;
      } else if (node.priority === 'low') {
        opacity = 0.7;
      }
    } else {
      // For agent nodes
      borderColor = color;
      
      // Highlight active agents
      if (node.tasks > 0) {
        glow = true;
      }
    }
    
    return {
      backgroundColor: color,
      borderColor: borderColor || color,
      opacity,
      boxShadow: glow ? `0 0 8px 2px ${color}80` : '0 4px 8px rgba(0, 0, 0, 0.2)',
      border: `2px solid ${borderColor || color}`
    };
  };
  
  // Get node color (for backward compatibility)
  const getNodeColor = (node) => {
    return getNodeStyle(node).backgroundColor;
  };
  
  // Get edge style based on status and type
  const getEdgeStyle = (edge) => {
    let color, width = 2, dashArray = 'none';
    
    // Color based on edge type
    if (edge.type === 'command') color = theme.palette.primary.main;
    else if (edge.type === 'feedback') color = theme.palette.info.main;
    else if (edge.type === 'report') color = theme.palette.warning.main;
    else if (edge.type === 'dependency') {
      color = theme.palette.grey[600];
      dashArray = '5,5';
    }
    else if (edge.type === 'assignment') {
      // Assignment edges get colored by status
      if (edge.status === 'completed') color = theme.palette.success.main;
      else if (edge.status === 'in_progress') color = theme.palette.info.main;
      else if (edge.status === 'failed') color = theme.palette.error.main;
      else color = theme.palette.grey[400];
    }
    else color = theme.palette.grey[400];
    
    // Adjust width based on strength if available
    if (edge.strength) {
      width = Math.min(5, 1 + edge.strength * 0.5);
    }
    
    return {
      stroke: color,
      strokeWidth: width,
      strokeDasharray: edge.style?.strokeDasharray || dashArray
    };
  };
  
  // Get edge color (for backward compatibility)
  const getEdgeColor = (edge) => {
    return getEdgeStyle(edge).stroke;
  };

  return (
    <Paper 
      ref={containerRef}
      sx={{ 
        height: 600, 
        position: 'relative', 
        overflow: 'hidden',
        bgcolor: 'background.paper',
        borderRadius: 2,
        boxShadow: 3,
        mb: 3
      }}
    >
      <Typography variant="h6" sx={{ p: 2, borderBottom: `1px solid ${theme.palette.divider}` }}>
        AI Workflow Visualization
      </Typography>
      
      {/* Control Panel */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', p: 1, borderBottom: `1px solid ${theme.palette.divider}` }}>
        <Tooltip title="Zoom In">
          <IconButton onClick={handleZoomIn} size="small">
            <ZoomInIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Zoom Out">
          <IconButton onClick={handleZoomOut} size="small">
            <ZoomOutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title={animationPaused ? "Resume Animation" : "Pause Animation"}>
          <IconButton onClick={toggleAnimationPause} size="small">
            {animationPaused ? <PlayArrowIcon fontSize="small" /> : <PauseIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
        <Tooltip title="Show Model Info">
          <IconButton onClick={() => setShowModelInfo(!showModelInfo)} size="small">
            <MemoryIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      
      <Box sx={{ position: 'relative', height: 'calc(100% - 60px)' }}>
        {/* Render edges */}
        <svg 
          width="100%" 
          height="100%" 
          style={{ 
            position: 'absolute', 
            top: 0, 
            left: 0,
            pointerEvents: 'none'
          }}
        >
          {edges.map((edge, index) => {
            const sourceNode = nodes.find(node => node.id === edge.source);
            const targetNode = nodes.find(node => node.id === edge.target);
            
            if (!sourceNode || !targetNode) return null;
            
            return (
              <g key={`edge-${index}`}>
                <defs>
                  <marker
                    id={`arrowhead-${index}`}
                    markerWidth="10"
                    markerHeight="7"
                    refX="9"
                    refY="3.5"
                    orient="auto"
                  >
                    <polygon 
                      points="0 0, 10 3.5, 0 7" 
                      fill={getEdgeColor(edge)} 
                    />
                  </marker>
                </defs>
                <path
                  d={`M${sourceNode.x},${sourceNode.y} L${targetNode.x},${targetNode.y}`}
                  stroke={getEdgeStyle(edge).stroke}
                  strokeWidth={getEdgeStyle(edge).strokeWidth}
                  fill="none"
                  markerEnd={`url(#arrowhead-${index})`}
                  strokeDasharray={getEdgeStyle(edge).strokeDasharray}
                >
                  {edge.animated && !animationPaused && (
                    <animate 
                      attributeName="stroke-dashoffset" 
                      from="0" 
                      to="10" 
                      dur="1s" 
                      repeatCount="indefinite" 
                    />
                  )}
                </path>
              </g>
            );
          })}
        </svg>
        
        {/* Render nodes */}
        <AnimatePresence>
          {nodes.map((node) => (
            <Tooltip 
              key={node.id} 
              title={
                <Box sx={{ p: 1 }}>
                  <Typography variant="subtitle2">{node.label}</Typography>
                  {node.type === 'task' ? (
                    <>
                      <Typography variant="caption" display="block">
                        Status: {node.status}
                      </Typography>
                      {node.progress > 0 && (
                        <Typography variant="caption" display="block">
                          Progress: {node.progress}%
                        </Typography>
                      )}
                      {node.startTime && (
                        <Typography variant="caption" display="block">
                          Started: {new Date(node.startTime).toLocaleTimeString()}
                        </Typography>
                      )}
                    </>
                  ) : (
                    <>
                      <Typography variant="caption" display="block">
                        Model: {node.model || 'Not specified'}
                      </Typography>
                      <Typography variant="caption" display="block">
                        Provider: {node.provider || 'Not specified'}
                      </Typography>
                      <Typography variant="caption" display="block">
                        Tasks: {node.tasks || 0}
                      </Typography>
                    </>
                  )}
                </Box>
              }
              arrow
            >
              <motion.div
                initial={{ opacity: 0, scale: 0 }}
                animate={{ 
                  opacity: 1, 
                  scale: 1,
                  x: node.x - 30, // Center the node
                  y: node.y - 30  // Center the node
                }}
                exit={{ opacity: 0, scale: 0 }}
                transition={{ duration: 0.3 }}
                style={{
                  position: 'absolute',
                  width: node.type === 'task' ? 60 : 80,
                  height: node.type === 'task' ? 60 : 60,
                  borderRadius: node.type === 'task' ? '8px' : '50%',
                  ...getNodeStyle(node),
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  color: '#fff',
                  fontWeight: 'bold',
                  fontSize: node.type === 'task' ? '0.75rem' : '0.875rem',
                  textAlign: 'center',
                  padding: '8px',
                  cursor: 'pointer',
                  zIndex: 10,
                  transform: `scale(${zoom})`
                }}
                onClick={() => handleNodeClick(node)}
              >
                {node.type === 'task' ? (
                  <Box sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', width: '100%' }}>
                    {node.label}
                  </Box>
                ) : (
                  node.label
                )}
                
                {/* Show progress indicator for in-progress tasks */}
                {node.type === 'task' && node.status === 'in_progress' && (
                  <Box sx={{ position: 'absolute', bottom: -5, left: 0, width: '100%', display: 'flex', justifyContent: 'center' }}>
                    <CircularProgress size={16} color="inherit" />
                  </Box>
                )}
              </motion.div>
            </Tooltip>
          ))}
        </AnimatePresence>
        
        {/* Statistics Panel */}
        <Box sx={{ mt: 2, p: 2, borderTop: `1px solid ${theme.palette.divider}` }}>
          <Typography variant="subtitle2" gutterBottom>Task Statistics</Typography>
          <Grid container spacing={2}>
            <Grid item xs={3}>
              <Chip 
                icon={<CheckCircleIcon fontSize="small" />} 
                label={`Completed: ${taskStats.completed}`}
                size="small"
                color="success"
                variant="outlined"
              />
            </Grid>
            <Grid item xs={3}>
              <Chip 
                icon={<PendingIcon fontSize="small" />} 
                label={`In Progress: ${taskStats.inProgress}`}
                size="small"
                color="info"
                variant="outlined"
              />
            </Grid>
            <Grid item xs={3}>
              <Chip 
                icon={<ErrorIcon fontSize="small" />} 
                label={`Failed: ${taskStats.failed}`}
                size="small"
                color="error"
                variant="outlined"
              />
            </Grid>
            <Grid item xs={3}>
              <Chip 
                icon={<PendingIcon fontSize="small" />} 
                label={`Pending: ${taskStats.pending}`}
                size="small"
                color="default"
                variant="outlined"
              />
            </Grid>
          </Grid>
          
          {Object.keys(executionTimes).length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="caption">
                Avg. Execution Time: {
                  (Object.values(executionTimes).reduce((a, b) => a + b, 0) / Object.values(executionTimes).length).toFixed(2)
                } seconds
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
      
      {/* Node details dialog */}
      <Dialog open={nodeDetailsOpen} onClose={handleCloseDetails} maxWidth="sm" fullWidth>
        {selectedNodeDetails && (
          <>
            <DialogTitle>
              {selectedNodeDetails.type === 'task' ? 'Task Details' : 'AI Agent Details'}
            </DialogTitle>
            <DialogContent dividers>
              <Typography variant="h6">{selectedNodeDetails.label}</Typography>
              
              {selectedNodeDetails.type === 'task' ? (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="body2" gutterBottom>
                    <strong>Status:</strong> {selectedNodeDetails.status}
                  </Typography>
                  {selectedNodeDetails.progress > 0 && (
                    <Box sx={{ mt: 1 }}>
                      <Typography variant="body2" gutterBottom>
                        <strong>Progress:</strong> {selectedNodeDetails.progress}%
                      </Typography>
                      <LinearProgress 
                        variant="determinate" 
                        value={selectedNodeDetails.progress} 
                        sx={{ mt: 1, mb: 2 }}
                      />
                    </Box>
                  )}
                  {selectedNodeDetails.startTime && (
                    <Typography variant="body2" gutterBottom>
                      <strong>Started:</strong> {new Date(selectedNodeDetails.startTime).toLocaleString()}
                    </Typography>
                  )}
                  {selectedNodeDetails.endTime && (
                    <Typography variant="body2" gutterBottom>
                      <strong>Completed:</strong> {new Date(selectedNodeDetails.endTime).toLocaleString()}
                    </Typography>
                  )}
                  {selectedNodeDetails.priority && (
                    <Typography variant="body2" gutterBottom>
                      <strong>Priority:</strong> {selectedNodeDetails.priority}
                    </Typography>
                  )}
                </Box>
              ) : (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="body2" gutterBottom>
                    <strong>Model:</strong> {selectedNodeDetails.model || 'Not specified'}
                  </Typography>
                  <Typography variant="body2" gutterBottom>
                    <strong>Provider:</strong> {selectedNodeDetails.provider || 'Not specified'}
                  </Typography>
                  <Typography variant="body2" gutterBottom>
                    <strong>Active Tasks:</strong> {selectedNodeDetails.tasks || 0}
                  </Typography>
                </Box>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={handleCloseDetails}>Close</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Paper>
  );
};

export default WorkflowVisualizer;

import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Tooltip,
  Paper,
  useTheme
} from '@mui/material';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * WorkflowVisualizer component displays a real-time visualization of the AI workflow
 * @param {Object} props - Component props
 * @param {Array} props.tasks - Array of tasks to visualize
 * @param {Boolean} props.loading - Whether the component is loading data
 */
const WorkflowVisualizer = ({ tasks = [], loading = false }) => {
  const theme = useTheme();
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: 500 // Fixed height for visualization
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    
    return () => {
      window.removeEventListener('resize', updateDimensions);
    };
  }, []);

  // Process tasks into nodes and edges for visualization
  useEffect(() => {
    if (!tasks.length) return;
    
    const newNodes = [];
    const newEdges = [];
    
    // Define AI agent nodes
    const agentNodes = [
      { id: 'ai1', label: 'AI1 Coordinator', x: dimensions.width * 0.5, y: 80, type: 'coordinator' },
      { id: 'ai2_executor', label: 'AI2 Executor', x: dimensions.width * 0.25, y: 200, type: 'executor' },
      { id: 'ai2_tester', label: 'AI2 Tester', x: dimensions.width * 0.5, y: 200, type: 'tester' },
      { id: 'ai2_documenter', label: 'AI2 Documenter', x: dimensions.width * 0.75, y: 200, type: 'documenter' },
      { id: 'ai3', label: 'AI3 Project Manager', x: dimensions.width * 0.5, y: 320, type: 'manager' }
    ];
    
    // Add agent nodes
    newNodes.push(...agentNodes);
    
    // Add connections between agents
    newEdges.push(
      { source: 'ai1', target: 'ai2_executor', animated: true },
      { source: 'ai1', target: 'ai2_tester', animated: true },
      { source: 'ai1', target: 'ai2_documenter', animated: true },
      { source: 'ai1', target: 'ai3', animated: true }
    );
    
    // Add task nodes
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
      
      // Add task node
      newNodes.push({
        id: taskId,
        label: task.filename || `Task ${index + 1}`,
        x: getAgentNodeById(targetAgent, agentNodes).x + (Math.random() * 60 - 30),
        y: getAgentNodeById(targetAgent, agentNodes).y + 80,
        type: 'task',
        status: task.status,
        data: task
      });
      
      // Add edge from agent to task
      newEdges.push({
        source: targetAgent,
        target: taskId,
        animated: task.status === 'in_progress',
        status: task.status
      });
    });
    
    setNodes(newNodes);
    setEdges(newEdges);
  }, [tasks, dimensions.width]);
  
  // Helper function to get agent node by ID
  const getAgentNodeById = (id, agentNodes) => {
    return agentNodes.find(node => node.id === id) || { x: 0, y: 0 };
  };
  
  // Get node color based on type and status
  const getNodeColor = (node) => {
    if (node.type === 'coordinator') return theme.palette.primary.main;
    if (node.type === 'executor') return theme.palette.secondary.main;
    if (node.type === 'tester') return theme.palette.info.main;
    if (node.type === 'documenter') return theme.palette.warning.main;
    if (node.type === 'manager') return theme.palette.success.main;
    
    // Task nodes
    if (node.type === 'task') {
      switch (node.status) {
        case 'completed':
          return theme.palette.success.main;
        case 'in_progress':
          return theme.palette.primary.main;
        case 'failed':
          return theme.palette.error.main;
        default:
          return theme.palette.grey[500];
      }
    }
    
    return theme.palette.grey[500];
  };
  
  // Get edge color based on status
  const getEdgeColor = (edge) => {
    switch (edge.status) {
      case 'completed':
        return theme.palette.success.main;
      case 'in_progress':
        return theme.palette.primary.main;
      case 'failed':
        return theme.palette.error.main;
      default:
        return theme.palette.grey[500];
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Paper 
      ref={containerRef}
      sx={{ 
        height: 500, 
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
                  stroke={getEdgeColor(edge)}
                  strokeWidth="2"
                  fill="none"
                  markerEnd={`url(#arrowhead-${index})`}
                  strokeDasharray={edge.animated ? "5,5" : "none"}
                >
                  {edge.animated && (
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
                node.type === 'task' 
                  ? `${node.label} - ${node.status}`
                  : node.label
              }
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
                  backgroundColor: getNodeColor(node),
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  color: '#fff',
                  fontWeight: 'bold',
                  fontSize: node.type === 'task' ? '0.75rem' : '0.875rem',
                  textAlign: 'center',
                  padding: '8px',
                  boxShadow: '0 4px 8px rgba(0, 0, 0, 0.2)',
                  cursor: 'pointer',
                  zIndex: 10
                }}
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
      </Box>
    </Paper>
  );
};

export default WorkflowVisualizer;

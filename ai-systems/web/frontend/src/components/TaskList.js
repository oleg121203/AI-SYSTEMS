import React, { useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Divider,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  Typography
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import TaskIcon from '@mui/icons-material/Task';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import ErrorIcon from '@mui/icons-material/Error';
import CodeIcon from '@mui/icons-material/Code';

/**
 * TaskList component displays a list of tasks for a project
 * @param {Array} tasks - The array of tasks to display
 */
const TaskList = ({ tasks }) => {
  const [expanded, setExpanded] = useState(false);

  const handleChange = (panel) => (event, isExpanded) => {
    setExpanded(isExpanded ? panel : false);
  };

  // Get status icon based on task status
  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed':
        return <CheckCircleIcon color="success" />;
      case 'in_progress':
        return <HourglassEmptyIcon color="primary" />;
      case 'failed':
        return <ErrorIcon color="error" />;
      default:
        return <TaskIcon color="disabled" />;
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
      default:
        return 'default';
    }
  };

  // Calculate overall progress percentage
  const calculateProgress = () => {
    if (!tasks || tasks.length === 0) return 0;
    
    const completedTasks = tasks.filter(task => task.status === 'completed').length;
    return (completedTasks / tasks.length) * 100;
  };

  if (!tasks || tasks.length === 0) {
    return (
      <Paper sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body1">
          No tasks available for this project yet.
        </Typography>
      </Paper>
    );
  }

  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Overall Progress: {Math.round(calculateProgress())}%
        </Typography>
        <LinearProgress 
          variant="determinate" 
          value={calculateProgress()} 
          sx={{ height: 10, borderRadius: 5 }}
        />
      </Box>
      
      {tasks.map((task, index) => (
        <Accordion 
          key={task.id || index}
          expanded={expanded === `panel${index}`}
          onChange={handleChange(`panel${index}`)}
          sx={{ mb: 1 }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon />}
            aria-controls={`panel${index}-content`}
            id={`panel${index}-header`}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', width: '100%' }}>
              <Box sx={{ mr: 2 }}>
                {getStatusIcon(task.status)}
              </Box>
              <Box sx={{ flexGrow: 1 }}>
                <Typography variant="subtitle1">
                  {task.title || task.name || `Task ${index + 1}`}
                </Typography>
              </Box>
              <Chip 
                label={task.status} 
                color={getStatusColor(task.status)} 
                size="small" 
                sx={{ ml: 1 }}
              />
            </Box>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" paragraph>
              {task.description || 'No description available.'}
            </Typography>
            
            {task.subtasks && task.subtasks.length > 0 && (
              <>
                <Divider sx={{ my: 1 }} />
                <Typography variant="subtitle2" sx={{ mt: 1, mb: 1 }}>
                  Subtasks:
                </Typography>
                <List dense>
                  {task.subtasks.map((subtask, subtaskIndex) => (
                    <ListItem key={subtask.id || subtaskIndex}>
                      <ListItemIcon sx={{ minWidth: 36 }}>
                        {getStatusIcon(subtask.status)}
                      </ListItemIcon>
                      <ListItemText 
                        primary={subtask.title || subtask.name || `Subtask ${subtaskIndex + 1}`}
                        secondary={subtask.description || null}
                      />
                      <Chip 
                        label={subtask.status} 
                        color={getStatusColor(subtask.status)} 
                        size="small" 
                      />
                    </ListItem>
                  ))}
                </List>
              </>
            )}
            
            {task.files && task.files.length > 0 && (
              <>
                <Divider sx={{ my: 1 }} />
                <Typography variant="subtitle2" sx={{ mt: 1, mb: 1 }}>
                  Files:
                </Typography>
                <List dense>
                  {task.files.map((file, fileIndex) => (
                    <ListItem key={fileIndex}>
                      <ListItemIcon sx={{ minWidth: 36 }}>
                        <CodeIcon />
                      </ListItemIcon>
                      <ListItemText 
                        primary={file.name || file.path || `File ${fileIndex + 1}`}
                        secondary={file.description || null}
                      />
                    </ListItem>
                  ))}
                </List>
              </>
            )}
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
};

export default TaskList;

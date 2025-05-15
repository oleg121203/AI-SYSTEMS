import React from 'react';
import {
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  Typography,
  Box
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import DescriptionIcon from '@mui/icons-material/Description';
import VisibilityIcon from '@mui/icons-material/Visibility';

/**
 * ProjectCard component displays a project in a card format
 * @param {Object} project - The project object to display
 * @param {Function} onSelect - Function to call when the project is selected
 * @param {Function} onStart - Function to call when the project is started
 * @param {Function} onCreatePlan - Function to call when a plan is created
 */
const ProjectCard = ({ project, onSelect, onStart, onCreatePlan }) => {
  // Determine the status color
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'in_progress':
        return 'primary';
      case 'planning':
        return 'info';
      default:
        return 'default';
    }
  };

  return (
    <Card sx={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      transition: 'transform 0.2s, box-shadow 0.2s',
      '&:hover': {
        transform: 'translateY(-4px)',
        boxShadow: 6
      }
    }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Typography variant="h5" component="div" gutterBottom>
          {project.name}
        </Typography>
        <Box sx={{ mb: 2 }}>
          <Chip 
            label={project.status} 
            color={getStatusColor(project.status)} 
            size="small" 
          />
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {project.description}
        </Typography>
        {project.created_at && (
          <Typography variant="caption" color="text.secondary">
            Created: {new Date(project.created_at).toLocaleString()}
          </Typography>
        )}
      </CardContent>
      <CardActions>
        <Button 
          size="small" 
          startIcon={<VisibilityIcon />} 
          onClick={onSelect}
        >
          View
        </Button>
        <Button 
          size="small" 
          startIcon={<PlayArrowIcon />} 
          onClick={onStart}
          disabled={project.status === 'completed' || project.status === 'in_progress'}
        >
          Start
        </Button>
        <Button 
          size="small" 
          startIcon={<DescriptionIcon />} 
          onClick={onCreatePlan}
          disabled={project.status === 'completed'}
        >
          Plan
        </Button>
      </CardActions>
    </Card>
  );
};

export default ProjectCard;

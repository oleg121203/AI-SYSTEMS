import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Grid,
  Paper,
  Typography
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import WarningIcon from '@mui/icons-material/Warning';

/**
 * SystemStatus component displays the status of all system services
 * @param {Object} status - The system status object containing services and their statuses
 */
const SystemStatus = ({ status }) => {
  // Get status icon based on service status
  const getStatusIcon = (serviceStatus) => {
    switch (serviceStatus) {
      case 'healthy':
      case 'online':
      case 'running':
        return <CheckCircleIcon color="success" />;
      case 'degraded':
      case 'warning':
        return <WarningIcon color="warning" />;
      case 'error':
      case 'offline':
      case 'failed':
        return <ErrorIcon color="error" />;
      case 'starting':
      case 'initializing':
        return <HourglassEmptyIcon color="primary" />;
      default:
        return <HourglassEmptyIcon color="disabled" />;
    }
  };

  // Get status color based on service status
  const getStatusColor = (serviceStatus) => {
    switch (serviceStatus) {
      case 'healthy':
      case 'online':
      case 'running':
        return 'success';
      case 'degraded':
      case 'warning':
        return 'warning';
      case 'error':
      case 'offline':
      case 'failed':
        return 'error';
      case 'starting':
      case 'initializing':
        return 'primary';
      default:
        return 'default';
    }
  };

  // Get overall system status
  const getOverallStatus = () => {
    if (!status || !status.services || Object.keys(status.services).length === 0) {
      return 'unknown';
    }
    
    const serviceStatuses = Object.values(status.services).map(service => service.status);
    
    if (serviceStatuses.some(s => s === 'error' || s === 'offline' || s === 'failed')) {
      return 'error';
    }
    
    if (serviceStatuses.some(s => s === 'degraded' || s === 'warning')) {
      return 'warning';
    }
    
    if (serviceStatuses.every(s => s === 'healthy' || s === 'online' || s === 'running')) {
      return 'healthy';
    }
    
    return 'degraded';
  };

  if (!status || !status.services) {
    return (
      <Paper sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body1">
          System status information is not available.
        </Typography>
      </Paper>
    );
  }

  return (
    <Box>
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Box sx={{ mr: 2 }}>
              {getStatusIcon(getOverallStatus())}
            </Box>
            <Typography variant="h6">
              Overall System Status: 
            </Typography>
            <Chip 
              label={status.status || getOverallStatus()} 
              color={getStatusColor(status.status || getOverallStatus())} 
              sx={{ ml: 2 }}
            />
          </Box>
          {status.message && (
            <Typography variant="body2" sx={{ mt: 1 }}>
              {status.message}
            </Typography>
          )}
        </CardContent>
      </Card>
      
      <Typography variant="h6" gutterBottom>
        Service Status
      </Typography>
      
      <Grid container spacing={2}>
        {Object.entries(status.services).map(([serviceName, serviceData]) => (
          <Grid item xs={12} sm={6} md={4} key={serviceName}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                  <Box sx={{ mr: 1 }}>
                    {getStatusIcon(serviceData.status)}
                  </Box>
                  <Typography variant="subtitle1">
                    {serviceData.name || serviceName}
                  </Typography>
                </Box>
                <Chip 
                  label={serviceData.status} 
                  color={getStatusColor(serviceData.status)} 
                  size="small" 
                  sx={{ mb: 1 }}
                />
                {serviceData.description && (
                  <Typography variant="body2" color="text.secondary">
                    {serviceData.description}
                  </Typography>
                )}
                {serviceData.message && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {serviceData.message}
                  </Typography>
                )}
                {serviceData.url && (
                  <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                    URL: {serviceData.url}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

export default SystemStatus;

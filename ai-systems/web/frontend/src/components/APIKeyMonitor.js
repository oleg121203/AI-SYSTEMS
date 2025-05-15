import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  LinearProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  useTheme
} from '@mui/material';
import WarningIcon from '@mui/icons-material/Warning';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import AdvancedMetricsChart from './AdvancedMetricsChart';

/**
 * APIKeyMonitor component displays usage statistics for multiple API keys
 * @param {Object} props - Component props
 * @param {Object} props.apiKeyData - API key usage data
 * @param {Boolean} props.loading - Whether data is loading
 */
const APIKeyMonitor = ({ apiKeyData = {}, loading = false }) => {
  const theme = useTheme();
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [usageHistory, setUsageHistory] = useState({});
  
  // Initialize with the first provider when data loads
  useEffect(() => {
    if (apiKeyData && Object.keys(apiKeyData).length > 0 && !selectedProvider) {
      setSelectedProvider(Object.keys(apiKeyData)[0]);
    }
  }, [apiKeyData, selectedProvider]);
  
  // Generate mock usage history data for demonstration
  useEffect(() => {
    if (selectedProvider && apiKeyData[selectedProvider]) {
      const mockHistory = {};
      
      apiKeyData[selectedProvider].forEach((key, index) => {
        const now = new Date();
        const data = [];
        
        // Generate 24 hours of mock data
        for (let i = 24; i >= 0; i--) {
          const timestamp = new Date(now.getTime() - (i * 60 * 60 * 1000));
          // Random value with an upward trend
          const baseValue = key.usage_count ? (key.usage_count / 24) * (24 - i) : 0;
          const randomVariation = Math.random() * 10 - 5; // Random variation between -5 and 5
          const value = Math.max(0, Math.round(baseValue + randomVariation));
          
          data.push({
            timestamp: timestamp.toLocaleTimeString(),
            value
          });
        }
        
        mockHistory[`key${index}`] = data;
      });
      
      setUsageHistory(mockHistory);
    }
  }, [selectedProvider, apiKeyData]);
  
  // Calculate usage percentage
  const calculateUsagePercentage = (used, limit) => {
    if (!limit || limit === 0) return 0;
    return Math.min(100, Math.round((used / limit) * 100));
  };
  
  // Get status color based on usage percentage
  const getStatusColor = (percentage) => {
    if (percentage >= 90) return theme.palette.error.main;
    if (percentage >= 70) return theme.palette.warning.main;
    return theme.palette.success.main;
  };
  
  // Format time remaining until reset
  const formatTimeRemaining = (resetTime) => {
    if (!resetTime) return 'Unknown';
    
    try {
      const reset = new Date(resetTime);
      const now = new Date();
      const diff = reset - now;
      
      if (diff <= 0) return 'Reset now';
      
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      
      return `${hours}h ${minutes}m`;
    } catch (e) {
      return 'Invalid date';
    }
  };
  
  // Get status icon based on usage percentage
  const getStatusIcon = (percentage) => {
    if (percentage >= 90) return <WarningIcon color="error" />;
    if (percentage >= 70) return <AccessTimeIcon color="warning" />;
    return <CheckCircleIcon color="success" />;
  };
  
  // Render provider selection chips
  const renderProviderChips = () => {
    return (
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 3 }}>
        {Object.keys(apiKeyData).map((provider) => (
          <Chip
            key={provider}
            label={provider.toUpperCase()}
            color={provider === selectedProvider ? 'primary' : 'default'}
            onClick={() => setSelectedProvider(provider)}
            sx={{
              fontWeight: provider === selectedProvider ? 'bold' : 'normal',
              transition: 'all 0.2s',
              '&:hover': {
                transform: 'translateY(-2px)',
                boxShadow: 2
              }
            }}
          />
        ))}
      </Box>
    );
  };
  
  // Render API key usage table
  const renderApiKeyTable = () => {
    if (!selectedProvider || !apiKeyData[selectedProvider]) {
      return (
        <Typography variant="body2" color="text.secondary">
          No data available for selected provider
        </Typography>
      );
    }
    
    return (
      <TableContainer component={Paper} sx={{ mb: 3, boxShadow: 3 }}>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: theme.palette.background.accent }}>
              <TableCell>Key Index</TableCell>
              <TableCell>Usage</TableCell>
              <TableCell>Rate Limit</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Reset In</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {apiKeyData[selectedProvider].map((key, index) => {
              const usagePercentage = calculateUsagePercentage(
                key.usage_count || 0,
                key.limit || 1000
              );
              
              return (
                <TableRow key={index} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight="medium">
                      {selectedProvider.toUpperCase()}{index + 1}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2">
                        {key.usage_count || 0}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        / {key.limit || 'unlimited'}
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ width: '100%' }}>
                      <LinearProgress
                        variant="determinate"
                        value={usagePercentage}
                        sx={{
                          height: 8,
                          borderRadius: 4,
                          backgroundColor: theme.palette.background.paper,
                          '& .MuiLinearProgress-bar': {
                            backgroundColor: getStatusColor(usagePercentage)
                          }
                        }}
                      />
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      {getStatusIcon(usagePercentage)}
                      <Typography variant="body2">
                        {usagePercentage}%
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Tooltip title={key.reset_at || 'Unknown reset time'}>
                      <Typography variant="body2">
                        {formatTimeRemaining(key.reset_at)}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
    );
  };
  
  // Render usage history charts
  const renderUsageCharts = () => {
    if (!selectedProvider || !apiKeyData[selectedProvider] || !usageHistory) {
      return null;
    }
    
    return (
      <Grid container spacing={3}>
        {apiKeyData[selectedProvider].map((key, index) => (
          <Grid item xs={12} md={6} key={index}>
            <Card sx={{ height: '100%', boxShadow: 3 }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  {selectedProvider.toUpperCase()}{index + 1} Usage History
                </Typography>
                <Divider sx={{ mb: 2 }} />
                <AdvancedMetricsChart
                  data={usageHistory[`key${index}`] || []}
                  type="area"
                  dataKey="value"
                  xAxisKey="timestamp"
                  title=""
                  color={theme.palette.primary.main}
                  height={200}
                  tooltipFormatter={(value) => `${value} calls`}
                />
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    );
  };
  
  if (loading) {
    return (
      <Box sx={{ p: 3 }}>
        <LinearProgress />
        <Typography variant="body2" sx={{ mt: 2, textAlign: 'center' }}>
          Loading API key data...
        </Typography>
      </Box>
    );
  }
  
  if (!apiKeyData || Object.keys(apiKeyData).length === 0) {
    return (
      <Paper sx={{ p: 3, textAlign: 'center' }}>
        <Typography variant="body1">
          No API key data available.
        </Typography>
      </Paper>
    );
  }
  
  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        API Key Monitor
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Monitor usage and rate limits across multiple API keys for each provider.
      </Typography>
      
      {renderProviderChips()}
      {renderApiKeyTable()}
      {renderUsageCharts()}
    </Box>
  );
};

export default APIKeyMonitor;

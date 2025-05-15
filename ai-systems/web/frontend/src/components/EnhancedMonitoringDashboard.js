import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Container,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Tab,
  Tabs,
  Tooltip,
  Typography,
  useTheme,
  IconButton
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import MemoryIcon from '@mui/icons-material/Memory';
import StorageIcon from '@mui/icons-material/Storage';
import SpeedIcon from '@mui/icons-material/Speed';
import ApiIcon from '@mui/icons-material/Api';
import GitHubIcon from '@mui/icons-material/GitHub';
import AdvancedMetricsChart from './AdvancedMetricsChart';
import APIKeyMonitor from './APIKeyMonitor';
import { motion } from 'framer-motion';

/**
 * EnhancedMonitoringDashboard component displays system metrics and monitoring information
 * with advanced visualizations and real-time updates
 */
const EnhancedMonitoringDashboard = () => {
  const theme = useTheme();
  const [timeRange, setTimeRange] = useState('1h');
  const [refreshInterval, setRefreshInterval] = useState(60);
  const [activeTab, setActiveTab] = useState(0);
  const [metrics, setMetrics] = useState({
    apiRequests: [],
    cpuUsage: [],
    memoryUsage: [],
    diskUsage: [],
    taskDurations: [],
    githubOperations: []
  });
  const [apiKeyData, setApiKeyData] = useState({});
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Generate mock time series data for demonstration
  const generateMockTimeSeriesData = (points, min, max, trend = 'random') => {
    const now = new Date();
    const data = [];
    let lastValue = (min + max) / 2;

    for (let i = points; i >= 0; i--) {
      const timestamp = new Date(now.getTime() - (i * (60 * 60 * 1000) / points));
      
      // Generate value based on trend
      let value;
      switch (trend) {
        case 'up':
          // Upward trend with some randomness
          value = min + ((max - min) * (points - i) / points) + (Math.random() * 10 - 5);
          break;
        case 'down':
          // Downward trend with some randomness
          value = max - ((max - min) * (points - i) / points) + (Math.random() * 10 - 5);
          break;
        case 'wave':
          // Sine wave pattern
          value = ((max - min) / 2) * Math.sin((i / points) * Math.PI * 4) + ((max + min) / 2);
          break;
        case 'spike':
          // Occasional spikes
          value = (i % 5 === 0) ? max * 0.8 + (Math.random() * max * 0.2) : min + (Math.random() * (max - min) * 0.3);
          break;
        case 'continuous':
          // Continuous line with small variations from previous value
          const change = (Math.random() * 10 - 5);
          value = Math.max(min, Math.min(max, lastValue + change));
          lastValue = value;
          break;
        default:
          // Random values
          value = Math.floor(Math.random() * (max - min + 1)) + min;
      }

      // Ensure value is within bounds
      value = Math.max(min, Math.min(max, Math.round(value)));

      data.push({
        timestamp: timestamp.toLocaleTimeString(),
        value
      });
    }

    return data;
  };

  // Generate mock API key data
  const generateMockApiKeyData = () => {
    const providers = ['openai', 'anthropic', 'codestral', 'gemini', 'groq'];
    const data = {};

    providers.forEach(provider => {
      const keyCount = Math.floor(Math.random() * 3) + 1; // 1-3 keys per provider
      const keys = [];

      for (let i = 0; i < keyCount; i++) {
        const usageCount = Math.floor(Math.random() * 800) + 100;
        const limit = 1000;
        const now = new Date();
        const resetAt = new Date(now.getTime() + (Math.floor(Math.random() * 12) + 1) * 60 * 60 * 1000);

        keys.push({
          index: i,
          usage_count: usageCount,
          limit: limit,
          remaining: limit - usageCount,
          reset_at: resetAt.toISOString()
        });
      }

      data[provider] = keys;
    });

    return data;
  };

  // Fetch metrics data
  const fetchMetrics = useCallback(async () => {
    try {
      setLoading(true);
      
      // In a real implementation, this would fetch from the API
      // For now, we'll generate mock data
      setMetrics({
        apiRequests: generateMockTimeSeriesData(24, 10, 100, 'continuous'),
        cpuUsage: generateMockTimeSeriesData(24, 20, 80, 'wave'),
        memoryUsage: generateMockTimeSeriesData(24, 30, 90, 'up'),
        diskUsage: generateMockTimeSeriesData(24, 40, 70, 'continuous'),
        taskDurations: generateMockTimeSeriesData(24, 100, 5000, 'spike'),
        githubOperations: generateMockTimeSeriesData(24, 0, 50, 'continuous')
      });
      
      // Generate mock API key data
      setApiKeyData(generateMockApiKeyData());
      
      // Set last updated timestamp
      setLastUpdated(new Date());
    } catch (error) {
      console.error('Error fetching metrics:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  // Set up data fetching on component mount and when time range changes
  useEffect(() => {
    fetchMetrics();

    // Refresh metrics based on selected interval
    const intervalId = setInterval(fetchMetrics, refreshInterval * 1000);

    return () => clearInterval(intervalId);
  }, [timeRange, refreshInterval, fetchMetrics]);

  // Handle time range change
  const handleTimeRangeChange = (event) => {
    setTimeRange(event.target.value);
  };

  // Handle refresh interval change
  const handleRefreshIntervalChange = (event) => {
    setRefreshInterval(event.target.value);
  };

  // Handle tab change
  const handleTabChange = (event, newValue) => {
    setActiveTab(newValue);
  };

  // Format last updated time
  const formatLastUpdated = () => {
    if (!lastUpdated) return 'Never';
    return lastUpdated.toLocaleTimeString();
  };

  // Render the system metrics tab
  const renderSystemMetricsTab = () => {
    return (
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%', boxShadow: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <MemoryIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="h6">CPU Usage</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <AdvancedMetricsChart
                data={metrics.cpuUsage}
                type="area"
                dataKey="value"
                xAxisKey="timestamp"
                color={theme.palette.primary.main}
                height={250}
                tooltipFormatter={(value) => `${value}%`}
              />
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%', boxShadow: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <StorageIcon color="secondary" sx={{ mr: 1 }} />
                <Typography variant="h6">Memory Usage</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <AdvancedMetricsChart
                data={metrics.memoryUsage}
                type="area"
                dataKey="value"
                xAxisKey="timestamp"
                color={theme.palette.secondary.main}
                height={250}
                tooltipFormatter={(value) => `${value}%`}
              />
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%', boxShadow: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <SpeedIcon color="warning" sx={{ mr: 1 }} />
                <Typography variant="h6">Task Durations</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <AdvancedMetricsChart
                data={metrics.taskDurations}
                type="line"
                dataKey="value"
                xAxisKey="timestamp"
                color={theme.palette.warning.main}
                height={250}
                tooltipFormatter={(value) => `${value}ms`}
              />
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%', boxShadow: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <StorageIcon color="info" sx={{ mr: 1 }} />
                <Typography variant="h6">Disk Usage</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <AdvancedMetricsChart
                data={metrics.diskUsage}
                type="area"
                dataKey="value"
                xAxisKey="timestamp"
                color={theme.palette.info.main}
                height={250}
                tooltipFormatter={(value) => `${value}%`}
              />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    );
  };

  // Render the API metrics tab
  const renderApiMetricsTab = () => {
    return (
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Card sx={{ boxShadow: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <ApiIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="h6">API Requests</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <AdvancedMetricsChart
                data={metrics.apiRequests}
                type="bar"
                dataKey="value"
                xAxisKey="timestamp"
                color={theme.palette.primary.main}
                height={250}
                tooltipFormatter={(value) => `${value} requests`}
              />
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={12}>
          <Card sx={{ boxShadow: 3 }}>
            <CardContent>
              <APIKeyMonitor apiKeyData={apiKeyData} loading={loading} />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    );
  };

  // Render the GitHub metrics tab
  const renderGitHubMetricsTab = () => {
    return (
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Card sx={{ boxShadow: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                <GitHubIcon color="primary" sx={{ mr: 1 }} />
                <Typography variant="h6">GitHub Operations</Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <AdvancedMetricsChart
                data={metrics.githubOperations}
                type="line"
                dataKey="value"
                xAxisKey="timestamp"
                color={theme.palette.primary.main}
                height={250}
                tooltipFormatter={(value) => `${value} operations`}
              />
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={12}>
          <Card sx={{ boxShadow: 3 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                GitHub Integration Status
              </Typography>
              <Divider sx={{ mb: 2 }} />
              <Typography variant="body1" paragraph>
                Repository: <strong>oleg121203/AI-SYSTEMS-REPO</strong>
              </Typography>
              <Typography variant="body1" paragraph>
                Default Branch: <strong>master</strong>
              </Typography>
              <Typography variant="body1" paragraph>
                Last Commit: <strong>12 minutes ago</strong>
              </Typography>
              <Typography variant="body1" paragraph>
                Workflow Runs: <strong>5 successful</strong>, <strong>1 failed</strong>
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    );
  };

  // Render the active tab content
  const renderTabContent = () => {
    switch (activeTab) {
      case 0:
        return renderSystemMetricsTab();
      case 1:
        return renderApiMetricsTab();
      case 2:
        return renderGitHubMetricsTab();
      default:
        return renderSystemMetricsTab();
    }
  };

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      {loading && !lastUpdated ? (
        <Box display="flex" justifyContent="center" alignItems="center" minHeight="60vh">
          <CircularProgress />
          <Typography variant="h6" sx={{ ml: 2 }}>
            Loading metrics...
          </Typography>
        </Box>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Typography variant="h5">
                System Monitoring Dashboard
              </Typography>

              <Box sx={{ display: 'flex', gap: 2 }}>
                <FormControl size="small">
                  <InputLabel id="time-range-label">Time Range</InputLabel>
                  <Select
                    labelId="time-range-label"
                    id="time-range"
                    value={timeRange}
                    label="Time Range"
                    onChange={handleTimeRangeChange}
                  >
                    <MenuItem value="1h">Last Hour</MenuItem>
                    <MenuItem value="6h">Last 6 Hours</MenuItem>
                    <MenuItem value="24h">Last 24 Hours</MenuItem>
                    <MenuItem value="7d">Last 7 Days</MenuItem>
                  </Select>
                </FormControl>

                <FormControl size="small">
                  <InputLabel id="refresh-interval-label">Refresh</InputLabel>
                  <Select
                    labelId="refresh-interval-label"
                    id="refresh-interval"
                    value={refreshInterval}
                    label="Refresh"
                    onChange={handleRefreshIntervalChange}
                  >
                    <MenuItem value={10}>10 seconds</MenuItem>
                    <MenuItem value={30}>30 seconds</MenuItem>
                    <MenuItem value={60}>1 minute</MenuItem>
                    <MenuItem value={300}>5 minutes</MenuItem>
                  </Select>
                </FormControl>

                <Button
                  variant="outlined"
                  startIcon={<RefreshIcon />}
                  onClick={fetchMetrics}
                >
                  Refresh
                </Button>
              </Box>
            </Box>

            <Paper sx={{ mb: 3, p: 1 }}>
              <Tabs
                value={activeTab}
                onChange={handleTabChange}
                indicatorColor="primary"
                textColor="primary"
                variant="fullWidth"
              >
                <Tab label="System Metrics" icon={<MemoryIcon />} iconPosition="start" />
                <Tab label="API Usage" icon={<ApiIcon />} iconPosition="start" />
                <Tab label="GitHub Integration" icon={<GitHubIcon />} iconPosition="start" />
              </Tabs>
            </Paper>

            {loading && (
              <LinearProgress sx={{ mb: 2 }} />
            )}

            <Box sx={{ mb: 2, display: 'flex', justifyContent: 'flex-end' }}>
              <Typography variant="caption" color="text.secondary">
                Last updated: {formatLastUpdated()}
              </Typography>
            </Box>

            {renderTabContent()}
          </Box>
        </motion.div>
      )}
    </Container>
  );
};

export default EnhancedMonitoringDashboard;

import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  CircularProgress,
  Container,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Typography
} from '@mui/material';

/**
 * MonitoringDashboard component displays system metrics and monitoring information
 */
const MonitoringDashboard = () => {
  const [timeRange, setTimeRange] = useState('1h');
  const [metrics, setMetrics] = useState({
    apiRequests: [],
    cpuUsage: [],
    memoryUsage: [],
    taskDurations: []
  });
  const [loading, setLoading] = useState(true);

  // Generate mock time series data for demonstration
  const generateMockTimeSeriesData = (points, min, max) => {
    const now = new Date();
    const data = [];

    for (let i = points; i >= 0; i--) {
      const timestamp = new Date(now.getTime() - (i * (60 * 60 * 1000) / points));
      const value = Math.floor(Math.random() * (max - min + 1)) + min;

      data.push({
        timestamp,
        value
      });
    }

    return data;
  };

  // Calculate average value from time series data
  const calculateAverage = (data) => {
    if (!data || data.length === 0) return 0;
    const sum = data.reduce((acc, point) => acc + point.value, 0);
    return Math.round(sum / data.length);
  };

  // Calculate maximum value from time series data
  const calculateMax = (data) => {
    if (!data || data.length === 0) return 0;
    return Math.max(...data.map(point => point.value));
  };

  // Handle time range change
  const handleTimeRangeChange = (event) => {
    setTimeRange(event.target.value);
  };

  // Fetch metrics data
  const fetchMetrics = async () => {
    try {
      setLoading(true);
      // In a real implementation, this would fetch from the API
      // For now, we'll generate mock data
      setMetrics({
        apiRequests: generateMockTimeSeriesData(24, 10, 100),
        cpuUsage: generateMockTimeSeriesData(24, 0, 100),
        memoryUsage: generateMockTimeSeriesData(24, 0, 100),
        taskDurations: generateMockTimeSeriesData(24, 100, 5000)
      });
    } catch (error) {
      console.error('Error fetching metrics:', error);
    } finally {
      setLoading(false);
    }
  };

  // Set up data fetching on component mount and when time range changes
  useEffect(() => {
    fetchMetrics();

    // Refresh metrics every minute
    const intervalId = setInterval(fetchMetrics, 60000);

    return () => clearInterval(intervalId);
  }, [timeRange]); // eslint-disable-line react-hooks/exhaustive-deps

  // Render a metric card
  const renderMetricCard = (title, data, unit = '', description = '') => {
    const average = calculateAverage(data);
    const max = calculateMax(data);

    return (
      <Card sx={{ height: '100%' }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            {title}
          </Typography>

          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Average
              </Typography>
              <Typography variant="h4">
                {average}{unit}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Max
              </Typography>
              <Typography variant="h4">
                {max}{unit}
              </Typography>
            </Box>
          </Box>

          {description && (
            <Typography variant="body2" color="text.secondary">
              {description}
            </Typography>
          )}

          <Divider sx={{ my: 2 }} />

          <Box sx={{ height: 100, position: 'relative' }}>
            {/* This would be a chart in a real implementation */}
            <Box sx={{
              position: 'absolute',
              bottom: 0,
              left: 0,
              right: 0,
              display: 'flex',
              alignItems: 'flex-end',
              height: '100%'
            }}>
              {data.map((point, index) => (
                <Box
                  key={index}
                  sx={{
                    width: `${100 / data.length}%`,
                    height: `${(point.value / max) * 100}%`,
                    backgroundColor: 'primary.main',
                    opacity: 0.7,
                    mx: 0.5
                  }}
                />
              ))}
            </Box>
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1 }}>
            <Typography variant="caption" color="text.secondary">
              {data.length > 0 ? data[0].timestamp.toLocaleTimeString() : ''}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {data.length > 0 ? data[data.length - 1].timestamp.toLocaleTimeString() : ''}
            </Typography>
          </Box>
        </CardContent>
      </Card>
    );
  };

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      {loading ? (
        <Box display="flex" justifyContent="center" alignItems="center" minHeight="60vh">
          <CircularProgress />
          <Typography variant="h6" sx={{ ml: 2 }}>
            Loading metrics...
          </Typography>
        </Box>
      ) : (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
            <Typography variant="h5">
              System Metrics
            </Typography>

            <FormControl sx={{ minWidth: 120 }} size="small">
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
          </Box>

          <Grid container spacing={3}>
            <Grid item xs={12} md={6}>
              {renderMetricCard(
                'API Requests',
                metrics.apiRequests,
                '',
                'Total number of API requests per time interval'
              )}
            </Grid>
            <Grid item xs={12} md={6}>
              {renderMetricCard(
                'Task Durations',
                metrics.taskDurations,
                'ms',
                'Average duration of AI tasks in milliseconds'
              )}
            </Grid>
            <Grid item xs={12} md={6}>
              {renderMetricCard(
                'CPU Usage',
                metrics.cpuUsage,
                '%',
                'Average CPU usage across all services'
              )}
            </Grid>
            <Grid item xs={12} md={6}>
              {renderMetricCard(
                'Memory Usage',
                metrics.memoryUsage,
                '%',
                'Average memory usage across all services'
              )}
            </Grid>
          </Grid>

          <Typography variant="h5" sx={{ mt: 4, mb: 2 }}>
            Recent Events
          </Typography>

          <Paper sx={{ p: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
              No recent events to display.
            </Typography>
          </Paper>
        </Box>
      )}
    </Container>
  );
};

export default MonitoringDashboard;

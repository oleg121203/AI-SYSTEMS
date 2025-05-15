import React, { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Grid,
  Typography,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  CircularProgress,
  Divider,
  Paper,
  Chip,
  useTheme
} from '@mui/material';
import { 
  XAxis, YAxis, CartesianGrid, Tooltip, 
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  PieChart, Pie, Cell, Legend
} from 'recharts';

/**
 * PerformanceDashboard component for visualizing system performance metrics
 * @param {Object} props - Component props
 * @param {Object} props.metrics - System metrics data
 * @param {Boolean} props.loading - Whether the component is loading data
 */
const PerformanceDashboard = ({ metrics = {}, loading = false }) => {
  const theme = useTheme();
  const [timeRange, setTimeRange] = useState('1h');
  const [activeMetric, setActiveMetric] = useState('apiRequests');
  
  // Define colors for charts
  const colors = {
    primary: theme.palette.primary.main,
    secondary: theme.palette.secondary.main,
    success: theme.palette.success.main,
    error: theme.palette.error.main,
    warning: theme.palette.warning.main,
    info: theme.palette.info.main,
  };
  
  // Mock data for demonstration if no metrics provided
  const defaultMetrics = {
    apiRequests: generateMockTimeSeriesData(24, 10, 100),
    cpuUsage: generateMockTimeSeriesData(24, 0, 100),
    memoryUsage: generateMockTimeSeriesData(24, 0, 100),
    taskDurations: generateMockTimeSeriesData(24, 100, 5000),
    tasksByStatus: [
      { name: 'Pending', value: 8 },
      { name: 'In Progress', value: 5 },
      { name: 'Completed', value: 12 },
      { name: 'Failed', value: 2 }
    ],
    agentActivity: [
      { name: 'Coordinator', tasks: 25, success: 22, failure: 3 },
      { name: 'Executor', tasks: 18, success: 15, failure: 3 },
      { name: 'Tester', tasks: 12, success: 10, failure: 2 },
      { name: 'Documenter', tasks: 8, success: 8, failure: 0 }
    ]
  };
  
  // Use provided metrics or fallback to default mock data
  const data = Object.keys(metrics).length > 0 ? metrics : defaultMetrics;
  
  // Generate mock time series data for demonstration
  function generateMockTimeSeriesData(points, min, max) {
    const now = new Date();
    const data = [];
    
    for (let i = points; i >= 0; i--) {
      const timestamp = new Date(now.getTime() - (i * (60 * 60 * 1000) / points));
      const value = Math.floor(Math.random() * (max - min + 1)) + min;
      
      data.push({
        timestamp: timestamp.toLocaleTimeString(),
        value
      });
    }
    
    return data;
  }
  
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
  
  // Handle active metric change
  const handleMetricChange = (event) => {
    setActiveMetric(event.target.value);
  };
  
  // Custom tooltip for charts
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <Paper sx={{ p: 1.5, boxShadow: 2 }}>
          <Typography variant="body2" color="textSecondary">
            {label}
          </Typography>
          {payload.map((entry, index) => (
            <Typography 
              key={index} 
              variant="body2" 
              sx={{ color: entry.color, fontWeight: 'bold' }}
            >
              {entry.name}: {entry.value}
            </Typography>
          ))}
        </Paper>
      );
    }
    return null;
  };
  
  // Get metric unit based on metric type
  const getMetricUnit = (metricType) => {
    switch (metricType) {
      case 'cpuUsage':
      case 'memoryUsage':
        return '%';
      case 'taskDurations':
        return 'ms';
      default:
        return '';
    }
  };
  
  // Get metric description based on metric type
  const getMetricDescription = (metricType) => {
    switch (metricType) {
      case 'apiRequests':
        return 'Total number of API requests per time interval';
      case 'cpuUsage':
        return 'Average CPU usage across all services';
      case 'memoryUsage':
        return 'Average memory usage across all services';
      case 'taskDurations':
        return 'Average duration of AI tasks in milliseconds';
      default:
        return '';
    }
  };
  
  // Render the main metric chart
  const renderMainChart = () => {
    const metricData = data[activeMetric];
    
    if (!metricData || metricData.length === 0) {
      return (
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
          <Typography variant="body2" color="textSecondary">
            No data available
          </Typography>
        </Box>
      );
    }
    
    return (
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={metricData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={colors.primary} stopOpacity={0.8}/>
              <stop offset="95%" stopColor={colors.primary} stopOpacity={0.1}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
          <XAxis 
            dataKey="timestamp" 
            stroke={theme.palette.text.secondary}
            tick={{ fontSize: 12 }}
          />
          <YAxis 
            stroke={theme.palette.text.secondary}
            tick={{ fontSize: 12 }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area 
            type="monotone" 
            dataKey="value" 
            stroke={colors.primary} 
            fillOpacity={1} 
            fill="url(#colorValue)" 
            name={activeMetric}
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  };
  
  // Render task status distribution chart
  const renderTaskStatusChart = () => {
    const COLORS = [colors.warning, colors.primary, colors.success, colors.error];
    
    return (
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={data.tasksByStatus}
            cx="50%"
            cy="50%"
            labelLine={false}
            outerRadius={80}
            fill="#8884d8"
            dataKey="value"
            nameKey="name"
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
          >
            {data.tasksByStatus.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
        </PieChart>
      </ResponsiveContainer>
    );
  };
  
  // Render agent activity chart
  const renderAgentActivityChart = () => {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <BarChart
          data={data.agentActivity}
          margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
          <XAxis dataKey="name" stroke={theme.palette.text.secondary} />
          <YAxis stroke={theme.palette.text.secondary} />
          <Tooltip content={<CustomTooltip />} />
          <Legend />
          <Bar dataKey="success" name="Successful Tasks" fill={colors.success} />
          <Bar dataKey="failure" name="Failed Tasks" fill={colors.error} />
        </BarChart>
      </ResponsiveContainer>
    );
  };
  
  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5">
          System Performance
        </Typography>
        
        <Box sx={{ display: 'flex', gap: 2 }}>
          <FormControl sx={{ minWidth: 120 }} size="small">
            <InputLabel id="metric-select-label">Metric</InputLabel>
            <Select
              labelId="metric-select-label"
              id="metric-select"
              value={activeMetric}
              label="Metric"
              onChange={handleMetricChange}
            >
              <MenuItem value="apiRequests">API Requests</MenuItem>
              <MenuItem value="cpuUsage">CPU Usage</MenuItem>
              <MenuItem value="memoryUsage">Memory Usage</MenuItem>
              <MenuItem value="taskDurations">Task Durations</MenuItem>
            </Select>
          </FormControl>
          
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
      </Box>
      
      {/* Main metric chart */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
            <Box>
              <Typography variant="h6" gutterBottom>
                {activeMetric === 'apiRequests' ? 'API Requests' : 
                 activeMetric === 'cpuUsage' ? 'CPU Usage' :
                 activeMetric === 'memoryUsage' ? 'Memory Usage' : 'Task Durations'}
              </Typography>
              <Typography variant="body2" color="textSecondary" gutterBottom>
                {getMetricDescription(activeMetric)}
              </Typography>
            </Box>
            
            <Box sx={{ display: 'flex', gap: 2 }}>
              <Box sx={{ textAlign: 'center' }}>
                <Typography variant="caption" color="textSecondary">
                  Average
                </Typography>
                <Typography variant="h6">
                  {calculateAverage(data[activeMetric])}{getMetricUnit(activeMetric)}
                </Typography>
              </Box>
              
              <Box sx={{ textAlign: 'center' }}>
                <Typography variant="caption" color="textSecondary">
                  Max
                </Typography>
                <Typography variant="h6">
                  {calculateMax(data[activeMetric])}{getMetricUnit(activeMetric)}
                </Typography>
              </Box>
            </Box>
          </Box>
          
          {renderMainChart()}
        </CardContent>
      </Card>
      
      {/* Additional metrics */}
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Task Status Distribution
              </Typography>
              {renderTaskStatusChart()}
            </CardContent>
          </Card>
        </Grid>
        
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Agent Activity
              </Typography>
              {renderAgentActivityChart()}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      
      {/* System alerts */}
      <Typography variant="h6" sx={{ mt: 4, mb: 2 }}>
        System Alerts
      </Typography>
      
      <Paper sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
          <Chip 
            label="All Systems Operational" 
            color="success" 
            sx={{ mr: 2 }}
          />
          <Typography variant="body2" color="textSecondary">
            Last updated: {new Date().toLocaleTimeString()}
          </Typography>
        </Box>
        
        <Divider sx={{ my: 2 }} />
        
        <Typography variant="body2" color="textSecondary" sx={{ fontStyle: 'italic' }}>
          No active alerts at this time.
        </Typography>
      </Paper>
    </Box>
  );
};

export default PerformanceDashboard;

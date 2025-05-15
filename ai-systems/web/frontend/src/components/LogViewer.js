import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  Box, 
  Card, 
  CardContent, 
  CardHeader, 
  Typography, 
  TextField,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  IconButton,
  Tooltip,
  Paper,
  Switch,
  FormControlLabel,
  CircularProgress
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import DownloadIcon from '@mui/icons-material/Download';
import ClearIcon from '@mui/icons-material/Clear';
import FilterListIcon from '@mui/icons-material/FilterList';
import AutorenewIcon from '@mui/icons-material/Autorenew';
import config from '../config';

const LogViewer = () => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [logSource, setLogSource] = useState('web-backend');
  const [filterText, setFilterText] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [lineCount, setLineCount] = useState(100);
  const [error, setError] = useState(null);
  const logEndRef = useRef(null);
  const refreshTimerRef = useRef(null);

  // Available log sources
  const logSources = [
    { value: 'web-backend', label: 'Web Backend' },
    { value: 'ai-core', label: 'AI Core' },
    { value: 'development-agents', label: 'Development Agents' },
    { value: 'project-manager', label: 'Project Manager' },
    { value: 'cmp', label: 'CMP' }
  ];
  
  // Function to fetch logs wrapped in useCallback to prevent recreation on every render
  const fetchLogs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      console.log(`Fetching logs from: ${config.apiBaseUrl}/api/logs/${logSource}?lines=${lineCount}`);
      const response = await fetch(`${config.apiBaseUrl}/api/logs/${logSource}?lines=${lineCount}`);
      
      if (!response.ok) {
        throw new Error(`Error fetching logs: ${response.statusText}`);
      }
      
      const data = await response.json();
      console.log('Received log data:', data);
      
      if (data.success && Array.isArray(data.logs)) {
        console.log(`Received ${data.logs.length} log lines`);
        setLogs(data.logs);
      } else {
        console.warn('No logs found or invalid format:', data);
        setLogs([]);
        setError(data.message || 'Failed to fetch logs');
      }
    } catch (error) {
      console.error('Error fetching logs:', error);
      setError(error.message);
    } finally {
      setLoading(false);
    }
  }, [logSource, lineCount]);

  // Fetch logs on component mount and when log source changes
  useEffect(() => {
    fetchLogs();
    
    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [logSource, lineCount, fetchLogs]);

  // Set up auto-refresh
  useEffect(() => {
    if (refreshTimerRef.current) {
      clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    
    if (autoRefresh) {
      refreshTimerRef.current = setInterval(fetchLogs, 5000);
    }
    
    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [autoRefresh, fetchLogs]);

  // Scroll to bottom when logs update
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const handleLogSourceChange = (event) => {
    setLogSource(event.target.value);
  };

  const handleFilterChange = (event) => {
    setFilterText(event.target.value);
  };

  const handleAutoRefreshChange = (event) => {
    setAutoRefresh(event.target.checked);
  };

  const handleLineCountChange = (event) => {
    setLineCount(event.target.value);
  };

  const clearLogs = () => {
    setLogs([]);
  };

  const downloadLogs = () => {
    // Create a blob with the log content
    const logText = logs.join('\n');
    const blob = new Blob([logText], { type: 'text/plain' });
    
    // Create a download link and trigger the download
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${logSource}-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`;
    document.body.appendChild(a);
    a.click();
    
    // Clean up
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Filter logs based on filter text
  const filteredLogs = filterText
    ? logs.filter(log => log.toLowerCase().includes(filterText.toLowerCase()))
    : logs;

  // Color-code log levels
  const getLogColor = (logLine) => {
    if (logLine.includes('ERROR') || logLine.includes('CRITICAL')) {
      return '#f44336'; // Red for errors
    } else if (logLine.includes('WARNING')) {
      return '#ff9800'; // Orange for warnings
    } else if (logLine.includes('INFO')) {
      return '#2196f3'; // Blue for info
    } else if (logLine.includes('DEBUG')) {
      return '#4caf50'; // Green for debug
    }
    return 'inherit'; // Default text color
  };

  return (
    <Card>
      <CardHeader 
        title="Log Viewer" 
        action={
          <Box display="flex" alignItems="center">
            <FormControlLabel
              control={
                <Switch
                  checked={autoRefresh}
                  onChange={handleAutoRefreshChange}
                  color="primary"
                />
              }
              label="Auto-refresh"
            />
            <Tooltip title="Refresh logs">
              <IconButton onClick={fetchLogs} disabled={loading}>
                <RefreshIcon />
              </IconButton>
            </Tooltip>
            <Tooltip title="Clear logs">
              <IconButton onClick={clearLogs} disabled={loading}>
                <ClearIcon />
              </IconButton>
            </Tooltip>
            <Tooltip title="Download logs">
              <IconButton onClick={downloadLogs} disabled={loading || logs.length === 0}>
                <DownloadIcon />
              </IconButton>
            </Tooltip>
          </Box>
        }
      />
      <CardContent>
        <Box mb={3} display="flex" flexWrap="wrap" gap={2} alignItems="center">
          <FormControl variant="outlined" size="small" sx={{ minWidth: 200 }}>
            <InputLabel id="log-source-label">Log Source</InputLabel>
            <Select
              labelId="log-source-label"
              value={logSource}
              onChange={handleLogSourceChange}
              label="Log Source"
            >
              {logSources.map((source) => (
                <MenuItem key={source.value} value={source.value}>
                  {source.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          
          <FormControl variant="outlined" size="small" sx={{ width: 120 }}>
            <InputLabel id="line-count-label">Lines</InputLabel>
            <Select
              labelId="line-count-label"
              value={lineCount}
              onChange={handleLineCountChange}
              label="Lines"
            >
              <MenuItem value={50}>50</MenuItem>
              <MenuItem value={100}>100</MenuItem>
              <MenuItem value={200}>200</MenuItem>
              <MenuItem value={500}>500</MenuItem>
              <MenuItem value={1000}>1000</MenuItem>
            </Select>
          </FormControl>
          
          <TextField
            variant="outlined"
            size="small"
            label="Filter"
            value={filterText}
            onChange={handleFilterChange}
            placeholder="Filter logs..."
            InputProps={{
              startAdornment: <FilterListIcon color="action" sx={{ mr: 1 }} />,
            }}
            sx={{ flexGrow: 1 }}
          />
          
          {autoRefresh && (
            <Box display="flex" alignItems="center">
              <AutorenewIcon color="primary" sx={{ mr: 1, animation: 'spin 2s linear infinite' }} />
              <Typography variant="body2" color="textSecondary">
                Refreshing every 5s
              </Typography>
            </Box>
          )}
        </Box>
        
        {error && (
          <Typography color="error" variant="body2" gutterBottom>
            Error: {error}
          </Typography>
        )}
        
        <Paper 
          variant="outlined" 
          sx={{ 
            height: 500, 
            overflow: 'auto', 
            p: 2, 
            backgroundColor: '#1e1e1e',
            fontFamily: 'monospace',
            fontSize: '0.85rem',
            position: 'relative'
          }}
        >
          {loading && (
            <Box 
              position="absolute" 
              top={0} 
              right={0} 
              p={1} 
              bgcolor="rgba(0,0,0,0.5)" 
              borderRadius={1}
            >
              <CircularProgress size={24} color="primary" />
            </Box>
          )}
          
          {filteredLogs.length > 0 ? (
            <Box component="pre" sx={{ margin: 0 }}>
              {filteredLogs.map((log, index) => {
                // Skip empty lines or invalid entries
                if (!log || typeof log !== 'string') return null;
                
                return (
                  <Box 
                    key={index} 
                    component="div" 
                    sx={{ 
                      color: getLogColor(log),
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      mb: 0.5,
                      lineHeight: 1.4,
                      fontSize: '0.85rem'
                    }}
                  >
                    {log}
                  </Box>
                );
              })}
              <div ref={logEndRef} />
            </Box>
          ) : (
            <Box 
              display="flex" 
              justifyContent="center" 
              alignItems="center" 
              height="100%"
            >
              <Typography color="text.secondary">
                {loading ? 'Loading logs...' : 'No logs available'}
              </Typography>
            </Box>
          )}
        </Paper>
        
        <Box mt={2} display="flex" justifyContent="space-between">
          <Typography variant="body2" color="textSecondary">
            {filteredLogs.length} {filteredLogs.length === 1 ? 'entry' : 'entries'} 
            {filterText && logs.length !== filteredLogs.length && ` (filtered from ${logs.length})`}
          </Typography>
          
          <Button 
            variant="outlined" 
            size="small" 
            onClick={fetchLogs} 
            startIcon={<RefreshIcon />}
            disabled={loading}
          >
            Refresh
          </Button>
        </Box>
      </CardContent>
    </Card>
  );
};

export default LogViewer;

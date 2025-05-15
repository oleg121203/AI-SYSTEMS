import React, { useState } from 'react';
import { Box, Button, TextField, Typography, Paper, Alert } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import config from '../config';

/**
 * A simple debugging component for directly testing the AI configuration API
 */
const DebugAIConfig = () => {
  const [response, setResponse] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  
  const handleTestConfig = async () => {
    setLoading(true);
    setResponse('');
    setError('');
    
    try {
      // Use a simple test configuration
      const testConfig = {
        ai1: {
          provider: "gemini",
          model: "gemini-pro"
        }
      };
      
      console.log('Sending test config to:', `${config.apiBaseUrl}/api/ai-config`);
      console.log('Test config data:', JSON.stringify(testConfig));
      
      const response = await fetch(`${config.apiBaseUrl}/api/ai-config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(testConfig),
      });
      
      const data = await response.json();
      console.log('Response from API:', data);
      
      if (!response.ok) {
        throw new Error(`HTTP status ${response.status}: ${JSON.stringify(data)}`);
      }
      
      setResponse(JSON.stringify(data, null, 2));
    } catch (e) {
      console.error('Error testing AI config:', e);
      setError(`Error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <Box sx={{ mt: 4 }}>
      <Paper elevation={3} sx={{ p: 3 }}>
        <Typography variant="h6" gutterBottom>
          Debug AI Configuration
        </Typography>
        
        <Button
          variant="contained"
          color="primary"
          onClick={handleTestConfig}
          disabled={loading}
          startIcon={<SendIcon />}
          sx={{ mb: 2 }}
        >
          Test AI Configuration Update
        </Button>
        
        {loading && (
          <Typography variant="body2" sx={{ my: 1 }}>
            Testing configuration update...
          </Typography>
        )}
        
        {error && (
          <Alert severity="error" sx={{ my: 2 }}>
            {error}
          </Alert>
        )}
        
        {response && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle1" gutterBottom>
              API Response:
            </Typography>
            <TextField
              multiline
              fullWidth
              rows={4}
              variant="outlined"
              value={response}
              InputProps={{
                readOnly: true,
              }}
            />
          </Box>
        )}
        
        <Box sx={{ mt: 3 }}>
          <Typography variant="subtitle2" color="text.secondary">
            Check browser console for detailed logs
          </Typography>
        </Box>
      </Paper>
    </Box>
  );
};

export default DebugAIConfig;

import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  CardHeader,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Tooltip,
  Typography,
  Alert,
  Divider,
  Button
} from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import CloseIcon from '@mui/icons-material/Close';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import KeyIcon from '@mui/icons-material/Key';
import SaveIcon from '@mui/icons-material/Save';
import ProviderIcon from './ProviderIcon';
import config from '../config';

/**
 * AIModelSelector component allows selecting AI providers and models for each AI agent
 * @param {Object} props - Component props
 * @param {Function} props.onConfigUpdate - Function to call when configuration is updated
 * @param {Object} props.initialConfig - Initial AI configuration
 * @param {Boolean} props.loading - Whether the component is loading data
 */
const AIModelSelector = ({ onConfigUpdate, initialConfig, loading = false }) => {
  const [providers, setProviders] = useState({});
  const [selectedProviders, setSelectedProviders] = useState({
    ai1: '',
    ai2_executor: '',
    ai2_tester: '',
    ai2_documenter: '',
    ai3: ''
  });
  const [selectedModels, setSelectedModels] = useState({});
  const [selectedApiKeys, setSelectedApiKeys] = useState({});
  const [availableModels, setAvailableModels] = useState({});
  const [modelAvailability, setModelAvailability] = useState({});
  const [checkingAvailability, setCheckingAvailability] = useState({});
  
  // State for Ollama model pulling
  const [pullingModels, setPullingModels] = useState({});
  const [pullStatus, setPullStatus] = useState({});
  
  // New state to track whether we have unsaved changes
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const response = await fetch(`${config.apiBaseUrl}/api/providers`);
        if (!response.ok) {
          throw new Error(`Error fetching providers: ${response.statusText}`);
        }
        const data = await response.json();
        setProviders(data);
      } catch (err) {
        console.error('Failed to fetch providers:', err);
        setError('Failed to load AI providers. Please try again later.');
      }
    };
    
    fetchProviders();
  }, []); // Only fetch providers once
  
  // Separate useEffect to handle initialConfig changes
  useEffect(() => {
    // Initialize with initial config if available
    if (initialConfig) {
      console.log('Initializing with config:', initialConfig);
      const providerConfig = {};
      const modelConfig = {};
      const apiKeyConfig = {};
      
      Object.keys(initialConfig).forEach(aiKey => {
        if (initialConfig[aiKey]?.provider) {
          providerConfig[aiKey] = initialConfig[aiKey].provider;
          modelConfig[aiKey] = initialConfig[aiKey].model || '';
          
          // Initialize API key selection if available
          if (initialConfig[aiKey]?.apiKey) {
            apiKeyConfig[aiKey] = initialConfig[aiKey].apiKey;
          }
        }
      });
      
      setSelectedProviders(prevState => ({
        ...prevState,
        ...providerConfig
      }));
      
      setSelectedModels(prevState => ({
        ...prevState,
        ...modelConfig
      }));
      
      setSelectedApiKeys(prevState => ({
        ...prevState,
        ...apiKeyConfig
      }));
      
      // Fetch models for each selected provider
      Object.entries(providerConfig).forEach(([aiKey, provider]) => {
        if (provider) {
          fetchModelsForProvider(provider, aiKey, apiKeyConfig[aiKey]);
        }
      });
      
      // Reset unsaved changes flag since we just loaded from server
      setHasUnsavedChanges(false);
    }
  }, [initialConfig]); // Re-run when initialConfig changes

  // Fetch available models for a provider
  const fetchModelsForProvider = async (provider, aiKey, apiKey = '') => {
    if (!provider) return;
    
    try {
      // Build URL based on whether an API key is provided
      let url = `${config.apiBaseUrl}/api/providers/${provider}/models`;
      if (apiKey) {
        // Check model availability if API key is provided
        setCheckingAvailability({
          ...checkingAvailability,
          [aiKey]: true
        });
        
        url = `${config.apiBaseUrl}/api/providers/${provider}/models?check_availability=true&api_key=${encodeURIComponent(apiKey)}`;
      }
      
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Failed to fetch models for ${provider}`);
      }
      
      const data = await response.json();
      
      // Update available models
      setAvailableModels(prevState => ({
        ...prevState,
        [aiKey]: data.models
      }));
      
      // Update model availability if it was checked
      if (apiKey && data.availability) {
        setModelAvailability(prevState => ({
          ...prevState,
          [aiKey]: data.availability
        }));
      }
    } catch (err) {
      console.error(`Error fetching models for ${provider}:`, err);
      setError(`Failed to load models for ${provider}. Please try again later.`);
    } finally {
      if (apiKey) {
        setCheckingAvailability({
          ...checkingAvailability,
          [aiKey]: false
        });
      }
    }
  };

  // Handle provider selection change
  const handleProviderChange = async (event, aiKey) => {
    const provider = event.target.value;
    
    setSelectedProviders(prevState => ({
      ...prevState,
      [aiKey]: provider
    }));
    
    // Reset selected model when provider changes
    setSelectedModels(prevState => ({
      ...prevState,
      [aiKey]: ''
    }));
    
    // Reset selected API key when provider changes
    setSelectedApiKeys(prevState => ({
      ...prevState,
      [aiKey]: ''
    }));
    
    // Fetch models for the selected provider
    await fetchModelsForProvider(provider, aiKey);
    
    // Mark that we have unsaved changes
    setHasUnsavedChanges(true);
  };

  // Handle model selection change
  const handleModelChange = async (event, aiKey) => {
    const model = event.target.value;
    
    setSelectedModels(prevState => ({
      ...prevState,
      [aiKey]: model
    }));
    
    // Mark that we have unsaved changes
    setHasUnsavedChanges(true);
  };

  // Handle API key selection change
  const handleApiKeyChange = async (event, aiKey) => {
    const apiKey = event.target.value;
    
    setSelectedApiKeys(prevState => ({
      ...prevState,
      [aiKey]: apiKey
    }));
    
    // Fetch models with availability check when API key changes
    if (apiKey && selectedProviders[aiKey]) {
      await fetchModelsForProvider(selectedProviders[aiKey], aiKey, apiKey);
    }
    
    // Mark that we have unsaved changes
    setHasUnsavedChanges(true);
  };
  
  // Handle pulling an Ollama model
  const handlePullModel = async (aiKey, modelId) => {
    const provider = selectedProviders[aiKey];
    
    // Only Ollama providers support pulling models
    if (!provider || !provider.startsWith('ollama_')) {
      setError('Only Ollama providers support pulling models');
      return;
    }
    
    // Set pulling state
    setPullingModels(prev => ({
      ...prev,
      [aiKey]: {
        ...prev[aiKey],
        [modelId]: true
      }
    }));
    
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/providers/${provider}/pull-model`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ model: modelId })
      });
      
      const data = await response.json();
      
      // Update pull status
      setPullStatus(prev => ({
        ...prev,
        [aiKey]: {
          ...prev[aiKey],
          [modelId]: data
        }
      }));
      
      // If successful, show a message and check availability again after a delay
      if (data.status === 'success') {
        // Wait a moment and then check if the model is available
        setTimeout(async () => {
          if (selectedProviders[aiKey] && selectedApiKeys[aiKey]) {
            await fetchModelsForProvider(selectedProviders[aiKey], aiKey, selectedApiKeys[aiKey]);
          }
        }, 5000); // Check after 5 seconds, then the user can check again manually if needed
      }
    } catch (err) {
      console.error('Failed to pull model:', err);
      setPullStatus(prev => ({
        ...prev,
        [aiKey]: {
          ...prev[aiKey],
          [modelId]: {
            status: 'error',
            message: 'Failed to pull model',
            details: err.message
          }
        }
      }));
    } finally {
      // Clear pulling state after a delay to show the status message
      setTimeout(() => {
        setPullingModels(prev => ({
          ...prev,
          [aiKey]: {
            ...prev[aiKey],
            [modelId]: false
          }
        }));
      }, 2000);
    }
  };

  // Helper function to create updated config object
  const createUpdatedConfig = (aiKey, change) => {
    // Start with the current configuration
    const currentConfig = {};
    
    // Add current selections to the config
    Object.keys(selectedProviders).forEach(key => {
      if (selectedProviders[key]) {
        currentConfig[key] = {
          provider: selectedProviders[key],
          model: selectedModels[key] || '',
          apiKey: selectedApiKeys[key] || ''
        };
      }
    });
    
    // Update the specific AI agent's config
    currentConfig[aiKey] = change;
    
    return currentConfig;
  };
  
  // Handle save button click
  const handleSaveConfig = () => {
    // Create the complete configuration object
    const completeConfig = {};
    
    // Add current selections to the config
    Object.keys(selectedProviders).forEach(key => {
      if (selectedProviders[key]) {
        completeConfig[key] = {
          provider: selectedProviders[key],
          model: selectedModels[key] || '',
          apiKey: selectedApiKeys[key] || ''
        };
      }
    });
    
    // Notify parent component about the configuration update
    onConfigUpdate(completeConfig);
    
    // Reset the unsaved changes flag
    setHasUnsavedChanges(false);
  };
  
  // AI agent descriptions
  const aiDescriptions = {
    ai1: 'Project Coordinator - Formulates tasks and tracks progress',
    ai2_executor: 'Code Generator - Implements files according to requirements',
    ai2_tester: 'Test Writer - Creates tests for implemented code',
    ai2_documenter: 'Documentation Generator - Creates documentation for code',
    ai3: 'Project Manager - Generates project structure and monitors progress'
  };

  // Display names for AI agents
  const aiDisplayNames = {
    ai1: 'AI1 - Coordinator',
    ai2_executor: 'AI2 - Executor',
    ai2_tester: 'AI2 - Tester',
    ai2_documenter: 'AI2 - Documenter',
    ai3: 'AI3 - Project Manager'
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
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      
      {/* Save Configuration Button */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
        <Button
          variant="contained"
          color="primary"
          onClick={handleSaveConfig}
          disabled={!hasUnsavedChanges}
          startIcon={<SaveIcon />}
        >
          Save Configuration
        </Button>
      </Box>
      
      <Grid container spacing={2}>
        {Object.keys(aiDisplayNames).map((aiKey) => (
          <Grid item xs={12} md={6} key={aiKey}>
            <Card>
              <CardHeader
                avatar={
                  selectedProviders[aiKey] ? 
                  <ProviderIcon provider={selectedProviders[aiKey]} size="medium" /> : 
                  <SmartToyIcon />
                }
                title={aiDisplayNames[aiKey]}
                subheader={aiDescriptions[aiKey]}
              />
              <Divider />
              <CardContent>
                <Box sx={{ mb: 2 }}>
                  <FormControl fullWidth>
                    <InputLabel>Provider</InputLabel>
                    <Select
                      value={selectedProviders[aiKey] || ''}
                      onChange={(e) => handleProviderChange(e, aiKey)}
                      label="Provider"
                    >
                      <MenuItem value="">
                        <em>Select a provider</em>
                      </MenuItem>
                      {Object.keys(providers).map((provider) => (
                        <MenuItem key={provider} value={provider}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <ProviderIcon provider={provider} size="small" />
                            <Typography>
                              {providers[provider]?.name || provider}
                            </Typography>
                            {providers[provider]?.configured && (
                              <CheckCircleIcon fontSize="small" color="success" sx={{ ml: 1 }} />
                            )}
                          </Box>
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Box>
                
                {selectedProviders[aiKey] && providers[selectedProviders[aiKey]]?.api_keys?.length > 0 && (
                  <Box sx={{ mb: 2 }}>
                    <FormControl fullWidth>
                      <InputLabel>API Key</InputLabel>
                      <Select
                        value={selectedApiKeys[aiKey] || ''}
                        onChange={(e) => handleApiKeyChange(e, aiKey)}
                        label="API Key"
                        startAdornment={<KeyIcon color="action" sx={{ mr: 1 }} />}
                      >
                        <MenuItem value="">
                          <em>Select an API key</em>
                        </MenuItem>
                        {providers[selectedProviders[aiKey]]?.api_keys.map((keyInfo, index) => (
                          <MenuItem key={index} value={keyInfo.key}>
                            {keyInfo.name}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Box>
                )}
                
                <Box>
                  <FormControl fullWidth disabled={!selectedProviders[aiKey]}>
                    <InputLabel>Model</InputLabel>
                    <Select
                      value={selectedModels[aiKey] || ''}
                      onChange={(e) => handleModelChange(e, aiKey)}
                      label="Model"
                    >
                      <MenuItem value="">
                        <em>Select a model</em>
                      </MenuItem>
                      {availableModels[aiKey]?.map((model) => {
                        // If it's a string (old format), use it directly
                        const modelId = typeof model === 'string' ? model : model.id;
                        const isAvailable = modelAvailability[aiKey]?.[modelId] !== false; // Default to true if not checked
                        const isChecking = checkingAvailability[aiKey];
                        const modelObj = typeof model === 'object' ? model : { id: model };
                        const category = modelObj.category || '';
                        const capabilities = modelObj.capabilities || [];
                        const statusDetails = modelObj.statusDetails || null;
                        const latency = modelObj.latency || null;
                        const isPulling = pullingModels[aiKey]?.[modelId];
                        const pullStatusData = pullStatus[aiKey]?.[modelId];
                        const isOllamaProvider = selectedProviders[aiKey]?.startsWith('ollama_');
                        
                        return (
                          <MenuItem 
                            key={modelId} 
                            value={modelId}
                            disabled={modelAvailability[aiKey] && !isAvailable}
                            sx={{ 
                              flexDirection: 'column',
                              alignItems: 'flex-start', 
                              py: 1, 
                              borderLeft: category === 'advanced' ? '4px solid #6366f1' : 'none',
                              ...(modelAvailability[aiKey] && !isAvailable ? {
                                opacity: 0.5,
                                bgcolor: 'rgba(211, 47, 47, 0.04)'
                              } : {})
                            }}
                          >
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                                <Typography variant="body1" fontWeight={category === 'advanced' ? 'bold' : 'normal'}>
                                  {modelId}
                                </Typography>
                                {category === 'advanced' && (
                                  <Tooltip title="Advanced model">
                                    <Box 
                                      sx={{ 
                                        ml: 1, 
                                        px: 1, 
                                        py: 0.1, 
                                        bgcolor: 'primary.main', 
                                        color: 'white', 
                                        borderRadius: 1,
                                        fontSize: '0.7rem'
                                      }}
                                    >
                                      PRO
                                    </Box>
                                  </Tooltip>
                                )}
                              </Box>
                              
                              {/* Availability indicator */}
                              {selectedApiKeys[aiKey] && (
                                <Box sx={{ 
                                  display: 'flex', 
                                  alignItems: 'center',
                                  ml: 1,
                                  gap: 1
                                }}>
                                  {isChecking ? (
                                    <CircularProgress size={16} thickness={6} />
                                  ) : isAvailable ? (
                                    <Tooltip title={statusDetails || "Model is available"}>
                                      <Box 
                                        sx={{ 
                                          display: 'flex',
                                          alignItems: 'center',
                                          justifyContent: 'center',
                                          width: 24, 
                                          height: 24, 
                                          borderRadius: '50%', 
                                          bgcolor: 'success.main',
                                          color: 'white',
                                          boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                                        }}
                                      >
                                        <CheckIcon fontSize="small" />
                                      </Box>
                                    </Tooltip>
                                  ) : (
                                    <>
                                      <Tooltip title={statusDetails || "Model is not available"}>
                                        <Box 
                                          sx={{ 
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            width: 24, 
                                            height: 24, 
                                            borderRadius: '50%', 
                                            bgcolor: 'error.main',
                                            color: 'white',
                                            boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                                          }}
                                        >
                                          <CloseIcon fontSize="small" />
                                        </Box>
                                      </Tooltip>
                                      
                                      {/* Show pull button for Ollama providers */}
                                      {isOllamaProvider && (
                                        <Tooltip title={isPulling ? "Pulling model..." : 
                                                        (pullStatusData?.status === 'success' ? 
                                                          pullStatusData?.message : 
                                                          "Pull this model from Ollama")}>
                                          <span> {/* Wrapper to allow tooltip on disabled button */}
                                            <Button
                                              variant="outlined"
                                              color="primary"
                                              size="small"
                                              disabled={isPulling}
                                              onClick={(e) => {
                                                e.stopPropagation(); // Prevent selecting the model
                                                handlePullModel(aiKey, modelId);
                                              }}
                                              sx={{ minWidth: 'auto', p: '2px 8px' }}
                                            >
                                              {isPulling ? (
                                                <CircularProgress size={16} thickness={6} />
                                              ) : (
                                                'Pull'
                                              )}
                                            </Button>
                                          </span>
                                        </Tooltip>
                                      )}
                                    </>
                                  )}
                                </Box>
                              )}
                            </Box>
                            
                            {/* Capabilities and Latency section */}
                            <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                              {capabilities.map(capability => (
                                <Tooltip key={capability} title={`Supports ${capability}`}>
                                  <Box
                                    sx={{
                                      px: 1,
                                      py: 0.2,
                                      borderRadius: 4,
                                      fontSize: '0.65rem',
                                      backgroundColor: 'rgba(99, 102, 241, 0.1)',
                                      color: 'text.secondary',
                                      border: '1px solid rgba(99, 102, 241, 0.2)'
                                    }}
                                  >
                                    {capability}
                                  </Box>
                                </Tooltip>
                              ))}
                              
                              {latency && (
                                <Tooltip title="Response time in milliseconds">
                                  <Box
                                    sx={{
                                      px: 1,
                                      py: 0.2,
                                      borderRadius: 4,
                                      fontSize: '0.65rem',
                                      backgroundColor: 'rgba(16, 185, 129, 0.1)',
                                      color: 'text.secondary',
                                      border: '1px solid rgba(16, 185, 129, 0.2)',
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 0.5
                                    }}
                                  >
                                    <HourglassEmptyIcon sx={{ fontSize: '0.75rem' }} />
                                    {latency}ms
                                  </Box>
                                </Tooltip>
                              )}
                            </Box>
                          </MenuItem>
                        );
                      })}
                    </Select>
                  </FormControl>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
};

export default AIModelSelector;

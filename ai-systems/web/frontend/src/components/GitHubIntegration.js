import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  CircularProgress,
  Divider,
  Grid,
  IconButton,
  Paper,
  TextField,
  Typography,
  Tooltip,
  Snackbar,
  Alert,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Stack
} from '@mui/material';
import GitHubIcon from '@mui/icons-material/GitHub';
import CodeIcon from '@mui/icons-material/Code';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import RefreshIcon from '@mui/icons-material/Refresh';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import HistoryIcon from '@mui/icons-material/History';
import BranchIcon from '@mui/icons-material/AccountTree';
import BuildIcon from '@mui/icons-material/Build';
import config from '../config';

const GitHubIntegration = () => {
  const [repoStatus, setRepoStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [setupLoading, setSetupLoading] = useState(false);
  const [commitMessage, setCommitMessage] = useState('');
  const [files, setFiles] = useState([{ id: Date.now(), path: '', content: '' }]);
  const [notification, setNotification] = useState({ open: false, message: '', severity: 'info' });
  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [commitHistory, setCommitHistory] = useState([]);
  
  // Helper function to format dates
  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };
  
  // Function to open the commit dialog
  const openCommitDialog = () => {
    setCommitDialogOpen(true);
  };
  
  // Function to add a new file input
  const addFileInput = () => {
    setFiles([...files, { id: Date.now(), path: '', content: '' }]);
  };
  
  // Function to remove a file input
  const removeFileInput = (id) => {
    if (files.length > 1) {
      setFiles(files.filter(file => file.id !== id));
    }
  };
  
  // Function to update a file's properties
  const updateFile = (id, field, value) => {
    setFiles(files.map(file => 
      file.id === id ? { ...file, [field]: value } : file
    ));
  };
  
  // Define fetchRepoStatus function before using it in useEffect
  const fetchRepoStatus = async () => {
    setLoading(true);
    try {
      // Try to fetch directly from Git Service first
      try {
        const gitServiceResponse = await fetch(`${config.services.gitService}/info`);
        if (gitServiceResponse.ok) {
          const gitServiceData = await gitServiceResponse.json();
          setRepoStatus({
            configured: true,
            repository: gitServiceData.repo_url,
            remote_url: gitServiceData.repo_url,
            has_remote: true,
            current_branch: gitServiceData.branch,
            last_commit: gitServiceData.last_commit,
            file_count: gitServiceData.file_count
          });
          setLoading(false);
          return;
        }
      } catch (gitServiceError) {
        console.log('Direct Git Service not available, falling back to API Gateway');
      }

      // Fallback to API Gateway
      const response = await fetch(`${config.apiBaseUrl}/api/git/status`);
      const data = await response.json();
      
      if (response.ok && data.success) {
        setRepoStatus({
          configured: true,
          repository: data.repository,
          remote_url: data.remote_url,
          has_remote: data.has_remote,
          current_branch: data.current_branch,
          last_commit: data.last_commit
        });
      } else {
        setRepoStatus({
          configured: false,
          error: data.detail || 'Failed to get repository status'
        });
      }
    } catch (error) {
      console.error('Error fetching repository status:', error);
      setRepoStatus({
        configured: false,
        error: 'Failed to connect to Git service'
      });
    } finally {
      setLoading(false);
    }
  };

  // Fetch repository status on component mount
  useEffect(() => {
    fetchRepoStatus();
  }, []);
  
  // Set up interval for refreshing repo status
  useEffect(() => {
    if (repoStatus?.configured) {
      const intervalId = setInterval(() => {
        fetchRepoStatus();
      }, 60000); // Refresh every minute
      
      // Cleanup interval on component unmount
      return () => clearInterval(intervalId);
    }
  }, [repoStatus?.configured]);

  const handleSetupGitRepo = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/git/setup`, {
        method: 'POST',
      });
      const responseData = await response.json();
      
      if (response.ok) {
        setNotification({
          open: true,
          message: 'Git repository setup successful',
          severity: 'success'
        });
        fetchRepoStatus();
      } else {
        setNotification({
          open: true,
          message: `Error: ${responseData.detail || 'Failed to setup Git repository'}`,
          severity: 'error'
        });
      }
    } catch (error) {
      console.error('Error setting up Git repository:', error);
      setNotification({
        open: true,
        message: 'Error setting up Git repository',
        severity: 'error'
      });
    } finally {
      setLoading(false);
    }
  };
  
  const setupGitHubActions = async () => {
    setSetupLoading(true);
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/git/setup-actions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      
      if (!response.ok) {
        throw new Error(`Error setting up GitHub Actions: ${response.statusText}`);
      }
      
      const responseData = await response.json();
      setNotification({
        open: true,
        message: `GitHub Actions workflows set up successfully! ${responseData.details || ''}`,
        severity: 'success'
      });
    } catch (error) {
      console.error('Failed to set up GitHub Actions:', error);
      setNotification({
        open: true,
        message: `Failed to set up GitHub Actions: ${error.message}`,
        severity: 'error'
      });
    } finally {
      setSetupLoading(false);
    }
  };

  const commitToRepository = async () => {
    if (!commitMessage) {
      showNotification('Please enter a commit message', 'warning');
      return;
    }

    // Validate files
    const validFiles = files.filter(file => file.path && file.content);
    if (validFiles.length === 0) {
      showNotification('Please add at least one file with path and content', 'warning');
      return;
    }

    // Check for empty paths or content
    const hasEmptyFields = files.some(file => (file.path && !file.content) || (!file.path && file.content));
    if (hasEmptyFields) {
      showNotification('Some files have empty paths or content. Please fill all fields or remove the file.', 'warning');
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${config.apiBaseUrl}/api/git/commit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          files: validFiles.map(file => ({
            path: file.path,
            content: file.content,
          })),
          commit_message: commitMessage,
        }),
      });
      
      if (!response.ok) {
        throw new Error(`Error committing to repository: ${response.statusText}`);
      }
      
      const data = await response.json();
      showNotification(`Successfully committed ${validFiles.length} file(s) to repository!`, 'success');
      
      // Add the new commit to history
      const newCommit = {
        id: Date.now(),
        hash: data.files ? data.files[0].substring(0, 7) : 'latest',
        message: commitMessage,
        date: new Date().toISOString()
      };
      setCommitHistory([newCommit, ...commitHistory]);
      
      // Clear form after successful commit
      setCommitMessage('');
      setFiles([{ id: Date.now(), path: '', content: '' }]);
      setCommitDialogOpen(false);
      
      // Refresh repo status
      fetchRepoStatus();
    } catch (error) {
      console.error('Failed to commit to repository:', error);
      showNotification(`Failed to commit to repository: ${error.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const showNotification = (message, severity = 'info') => {
    setNotification({
      open: true,
      message,
      severity,
    });
  };

  const handleCloseNotification = () => {
    setNotification({ ...notification, open: false });
  };

  return (
    <Card 
      elevation={3} 
      sx={{ 
        mb: 4, 
        overflow: 'visible',
        transition: 'transform 0.3s ease-in-out',
        '&:hover': {
          transform: 'translateY(-5px)'
        }
      }}
    >
      <CardHeader
        title={
          <Box display="flex" alignItems="center">
            <GitHubIcon sx={{ mr: 1 }} />
            <Typography variant="h5" component="div">
              GitHub Integration
            </Typography>
          </Box>
        }
        action={
          <Tooltip title="Refresh repository status">
            <IconButton onClick={fetchRepoStatus} disabled={loading}>
              {loading ? <CircularProgress size={24} /> : <RefreshIcon />}
            </IconButton>
          </Tooltip>
        }
        sx={{ 
          pb: 1,
          background: 'linear-gradient(90deg, rgba(99, 102, 241, 0.15) 0%, rgba(59, 130, 246, 0.15) 100%)'
        }}
      />

      <CardContent>
        {repoStatus ? (
          <Box>
            <Box mb={3}>
              <Typography variant="subtitle1" gutterBottom>
                Repository Status
              </Typography>
              <Paper elevation={0} variant="outlined" sx={{ p: 2 }}>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <List dense>
                      <ListItem>
                        <ListItemIcon>
                          <GitHubIcon color="primary" />
                        </ListItemIcon>
                        <ListItemText 
                          primary="Repository" 
                          secondary={
                            <Typography component="span" variant="body2" sx={{ wordBreak: 'break-all' }}>
                              {repoStatus.repository}
                            </Typography>
                          } 
                        />
                      </ListItem>
                      <ListItem>
                        <ListItemIcon>
                          <CodeIcon color="info" />
                        </ListItemIcon>
                        <ListItemText 
                          primary="Remote URL" 
                          secondary={
                            <Typography component="span" variant="body2" sx={{ wordBreak: 'break-all' }}>
                              {repoStatus.remote_url}
                            </Typography>
                          } 
                        />
                      </ListItem>
                    </List>
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <List dense>
                      <ListItem>
                        <ListItemIcon>
                          <BranchIcon color="success" />
                        </ListItemIcon>
                        <ListItemText 
                          primary="Current Branch" 
                          secondary={
                            <Chip 
                              label={repoStatus.current_branch} 
                              size="small" 
                              color="primary" 
                              variant="outlined"
                            />
                          } 
                        />
                      </ListItem>
                      <ListItem>
                        <ListItemIcon>
                          <HistoryIcon color="secondary" />
                        </ListItemIcon>
                        <ListItemText 
                          primary="Last Commit" 
                          secondary={
                            <Typography component="span" variant="body2">
                              {repoStatus.last_commit || 'No commits yet'}
                            </Typography>
                          } 
                        />
                      </ListItem>
                    </List>
                  </Grid>
                </Grid>
              </Paper>
            </Box>

            <Divider sx={{ my: 3 }} />

            <Box mb={3}>
              <Typography variant="subtitle1" gutterBottom>
                Repository Management
              </Typography>
              <Stack direction="row" spacing={2} mb={2}>
                <Button
                  variant="outlined"
                  color="primary"
                  startIcon={<GitHubIcon />}
                  onClick={handleSetupGitRepo}
                  disabled={loading}
                >
                  Initialize Repository
                </Button>
              </Stack>
              
              <Typography variant="subtitle1" gutterBottom>
                GitHub Actions
              </Typography>
              <Button
                variant="contained"
                color="secondary"
                startIcon={<BuildIcon />}
                onClick={setupGitHubActions}
                disabled={setupLoading}
                sx={{ mt: 1 }}
              >
                {setupLoading ? (
                  <>
                    <CircularProgress size={24} color="inherit" sx={{ mr: 1 }} />
                    Setting up...
                  </>
                ) : (
                  'Setup GitHub Actions'
                )}
              </Button>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                This will set up CI/CD workflows for testing your code.
              </Typography>
            </Box>

            <Divider sx={{ my: 3 }} />

            <Box mb={3}>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="subtitle1">
                  Recent Commits
                </Typography>
              </Box>
              
              {commitHistory.length > 0 ? (
                <Paper elevation={0} variant="outlined" sx={{ p: 1 }}>
                  <List dense>
                    {commitHistory.slice(0, 3).map((commit) => (
                      <ListItem key={commit.id}>
                        <ListItemIcon>
                          <Chip 
                            label={commit.hash} 
                            size="small" 
                            color="primary" 
                            variant="outlined"
                          />
                        </ListItemIcon>
                        <ListItemText 
                          primary={commit.message}
                          secondary={formatDate(commit.date)}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No commit history available.
                </Typography>
              )}
            </Box>

            <Divider sx={{ my: 3 }} />

            <Box>
              <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="subtitle1">
                  Commit to Repository
                </Typography>
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={<CloudUploadIcon />}
                  onClick={openCommitDialog}
                >
                  New Commit
                </Button>
              </Box>
              <Typography variant="body2" color="text.secondary">
                Commit your changes to the GitHub repository. You can add multiple files in a single commit.
              </Typography>
            </Box>
          </Box>
        ) : loading ? (
          <Box display="flex" justifyContent="center" my={4}>
            <CircularProgress />
          </Box>
        ) : (
          <Typography color="error">
            Failed to load repository status. Please try again.
          </Typography>
        )}
      </CardContent>

      {/* Commit Dialog */}
      <Dialog 
        open={commitDialogOpen} 
        onClose={() => setCommitDialogOpen(false)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>Commit to Repository</DialogTitle>
        <DialogContent dividers>
          <TextField
            label="Commit Message"
            variant="outlined"
            fullWidth
            value={commitMessage}
            onChange={(e) => setCommitMessage(e.target.value)}
            margin="normal"
            required
          />
          
          <Box mt={3}>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="subtitle1">
                Files to Commit
              </Typography>
              <Button
                variant="outlined"
                color="primary"
                startIcon={<AddIcon />}
                onClick={addFileInput}
                size="small"
              >
                Add File
              </Button>
            </Box>
            
            {files.map((file, index) => (
              <Paper 
                key={file.id} 
                variant="outlined" 
                sx={{ p: 2, mb: 2, position: 'relative' }}
              >
                <Box position="absolute" top={8} right={8}>
                  <IconButton 
                    size="small" 
                    color="error" 
                    onClick={() => removeFileInput(file.id)}
                    disabled={files.length === 1}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Box>
                
                <Grid container spacing={2}>
                  <Grid item xs={12}>
                    <TextField
                      label="File Path"
                      variant="outlined"
                      fullWidth
                      value={file.path}
                      onChange={(e) => updateFile(file.id, 'path', e.target.value)}
                      placeholder="e.g., src/example.js"
                      required
                      helperText="Path relative to repository root"
                      size="small"
                    />
                  </Grid>
                  <Grid item xs={12}>
                    <TextField
                      label="File Content"
                      variant="outlined"
                      fullWidth
                      multiline
                      rows={6}
                      value={file.content}
                      onChange={(e) => updateFile(file.id, 'content', e.target.value)}
                      required
                      size="small"
                    />
                  </Grid>
                </Grid>
              </Paper>
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCommitDialogOpen(false)}>Cancel</Button>
          <Button 
            variant="contained" 
            color="primary"
            onClick={commitToRepository}
            disabled={loading}
            startIcon={loading ? <CircularProgress size={20} /> : <CloudUploadIcon />}
          >
            {loading ? 'Committing...' : 'Commit Changes'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={notification.open}
        autoHideDuration={6000}
        onClose={handleCloseNotification}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={handleCloseNotification} severity={notification.severity} sx={{ width: '100%' }}>
          {notification.message}
        </Alert>
      </Snackbar>
    </Card>
  );
};

export default GitHubIntegration;

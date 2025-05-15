// Enhanced GitHubIntegration component methods for direct Git Service integration

// Use this as a reference for updating the GitHubIntegration.js file to enhance 
// the Git Service integration with the frontend.

// Enhanced commitToRepository function to use Git Service directly
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
    // Try to use Git Service directly first
    try {
      const gitServiceResponse = await fetch(`${config.services.gitService}/commit`, {
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
      
      if (gitServiceResponse.ok) {
        const data = await gitServiceResponse.json();
        if (data.success) {
          showNotification(`Successfully committed ${validFiles.length} file(s) to repository!`, 'success');
          
          // Add the new commit to history
          const newCommit = {
            id: Date.now(),
            hash: data.commit_hash ? data.commit_hash.substring(0, 7) : 'latest',
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
          return;
        }
      }
    } catch (gitServiceError) {
      console.log('Direct Git Service commit failed, falling back to API Gateway', gitServiceError);
    }

    // Fallback to API Gateway
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

// Enhanced setupGitHubActions function to use Git Service directly
const setupGitHubActions = async () => {
  setSetupLoading(true);
  try {
    // Try to use Git Service directly first
    try {
      const gitServiceResponse = await fetch(`${config.services.gitService}/github-actions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          workflow_name: "ci.yml",
          workflow_content: null  // Use default CI workflow
        }),
      });
      
      if (gitServiceResponse.ok) {
        const data = await gitServiceResponse.json();
        if (data.success) {
          setNotification({
            open: true,
            message: `GitHub Actions workflows set up successfully with Git Service!`,
            severity: 'success'
          });
          fetchRepoStatus();
          setSetupLoading(false);
          return;
        }
      }
    } catch (gitServiceError) {
      console.log('Direct Git Service setup failed, falling back to API Gateway', gitServiceError);
    }

    // Fallback to API Gateway
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

// Enhanced handleSetupGitRepo function to use Git Service directly
const handleSetupGitRepo = async () => {
  setLoading(true);
  try {
    // Try to use Git Service directly first
    try {
      const gitServiceResponse = await fetch(`${config.services.gitService}/setup`, {
        method: 'POST',
      });
      
      if (gitServiceResponse.ok) {
        const data = await gitServiceResponse.json();
        if (data.success) {
          setNotification({
            open: true,
            message: 'Git repository setup successful with Git Service',
            severity: 'success'
          });
          fetchRepoStatus();
          setLoading(false);
          return;
        }
      }
    } catch (gitServiceError) {
      console.log('Direct Git Service setup failed, falling back to API Gateway', gitServiceError);
    }

    // Fallback to API Gateway
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

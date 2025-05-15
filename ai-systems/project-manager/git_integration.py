"""
Git Service Integration Module for Project Manager

This module provides integration between the Project Manager and the Git Service,
allowing for version control of generated code.
"""

import os
import logging
import json
import requests
from typing import Dict, List, Any, Optional

logger = logging.getLogger("project_manager.git_integration")

class GitServiceIntegration:
    """Class for integrating with the Git Service"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the Git Service integration
        
        Args:
            config: Project Manager configuration
        """
        self.git_service_url = config.get("services", {}).get("git_service", {}).get("url", "http://localhost:7865")
        self.timeout = config.get("api", {}).get("timeout", 30)
        self.initialized = False
        self.test_connection()
    
    def test_connection(self) -> bool:
        """Test the connection to the Git Service
        
        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            response = requests.get(f"{self.git_service_url}/health", timeout=self.timeout)
            self.initialized = response.status_code == 200
            if self.initialized:
                logger.info("Successfully connected to Git Service")
            else:
                logger.warning(f"Could not connect to Git Service: {response.status_code}")
            return self.initialized
        except Exception as e:
            logger.error(f"Error connecting to Git Service: {e}")
            self.initialized = False
            return False
    
    def get_repo_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the repository
        
        Returns:
            Dict: Repository information or None if there was an error
        """
        if not self.initialized:
            if not self.test_connection():
                logger.error("Cannot get repo info: Git Service not available")
                return None
        
        try:
            response = requests.get(f"{self.git_service_url}/info", timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error getting repo info: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting repo info: {e}")
            return None
    
    def commit_files(self, files: List[Dict[str, str]], commit_message: str, branch: str = "main") -> Optional[Dict[str, Any]]:
        """Commit files to the repository
        
        Args:
            files: List of file dictionaries with "path" and "content" keys
            commit_message: Message for the commit
            branch: Branch to commit to, defaults to "main"
        
        Returns:
            Dict: Response data or None if there was an error
        """
        if not self.initialized:
            if not self.test_connection():
                logger.error("Cannot commit files: Git Service not available")
                return None
        
        try:
            # Convert files to the format expected by the Git Service
            formatted_files = [{"path": f["path"], "content": f["content"]} for f in files]
            
            payload = {
                "files": formatted_files,
                "commit_message": commit_message,
                "branch": branch
            }
            
            response = requests.post(
                f"{self.git_service_url}/commit", 
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error committing files: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error committing files: {e}")
            return None
    
    def setup_github_actions(self, workflow_name: str = "ci.yml", custom_content: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Set up GitHub Actions workflows
        
        Args:
            workflow_name: Name of the workflow file, defaults to "ci.yml"
            custom_content: Custom workflow content, defaults to None for standard CI workflow
        
        Returns:
            Dict: Response data or None if there was an error
        """
        if not self.initialized:
            if not self.test_connection():
                logger.error("Cannot setup GitHub Actions: Git Service not available")
                return None
        
        try:
            payload = {
                "workflow_name": workflow_name,
                "workflow_content": custom_content
            }
            
            response = requests.post(
                f"{self.git_service_url}/github-actions", 
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Error setting up GitHub Actions: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error setting up GitHub Actions: {e}")
            return None
    
    def get_file_content(self, file_path: str, branch: str = "main") -> Optional[str]:
        """Get the content of a file from the repository
        
        Args:
            file_path: Path to the file
            branch: Branch to get the file from, defaults to "main"
        
        Returns:
            str: File content or None if the file doesn't exist or there was an error
        """
        # This functionality doesn't yet exist in the Git Service, so we'll implement it here
        # as a placeholder for future implementation
        logger.warning("Get file content not implemented in Git Service yet")
        return None

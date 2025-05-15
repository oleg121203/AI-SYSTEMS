import os
import sys
import unittest
import requests
import json
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from git_service.git_service import GitService

# Load environment variables
load_dotenv()

# Constants
API_BASE_URL = "http://localhost:8001"
GITHUB_REPO = os.getenv("GITHUB_REPO", "oleg121203/AI-SYSTEMS-REPO")
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "Oleg Kizyma")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "oleg1203@gmail.com")

class TestGitHubIntegration(unittest.TestCase):
    """Test the GitHub integration functionality"""
    
    def setUp(self):
        """Set up the test environment"""
        # Check if the backend is running
        try:
            response = requests.get(f"{API_BASE_URL}/api/status")
            if response.status_code != 200:
                self.skipTest("Backend server is not running")
        except requests.exceptions.ConnectionError:
            self.skipTest("Backend server is not running")
    
    def test_git_status_endpoint(self):
        """Test the Git status endpoint"""
        response = requests.get(f"{API_BASE_URL}/api/git/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["repository"], GITHUB_REPO)
    
    def test_git_commit_endpoint(self):
        """Test the Git commit endpoint"""
        test_file = {
            "path": "tests/test_file.txt",
            "content": f"This is a test file created by the test suite at {os.path.basename(__file__)}"
        }
        
        payload = {
            "files": [test_file],
            "commit_message": "Test commit from test suite"
        }
        
        response = requests.post(
            f"{API_BASE_URL}/api/git/commit",
            json=payload
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
    
    def test_git_service_direct(self):
        """Test the GitService class directly"""
        git_service = GitService()
        
        # Test repository exists
        self.assertTrue(os.path.exists(git_service.repo_path))
        
        # Test commit file
        test_file_path = "tests/direct_test_file.txt"
        test_content = f"This is a direct test file created by {os.path.basename(__file__)}"
        result = git_service.commit_file(
            test_file_path,
            test_content,
            "Direct test commit from test suite"
        )
        
        self.assertTrue(result)


class TestModelAvailability(unittest.TestCase):
    """Test the model availability functionality"""
    
    def setUp(self):
        """Set up the test environment"""
        # Check if the backend is running
        try:
            response = requests.get(f"{API_BASE_URL}/api/status")
            if response.status_code != 200:
                self.skipTest("Backend server is not running")
        except requests.exceptions.ConnectionError:
            self.skipTest("Backend server is not running")
        
        # Get API keys from environment
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self.mistral_api_key = os.getenv("MISTRAL_API_KEY")
        self.codestral_api_key = os.getenv("CODESTRAL_API_KEY")
    
    def test_model_availability_openai(self):
        """Test model availability for OpenAI"""
        if not self.openai_api_key:
            self.skipTest("OpenAI API key not available")
        
        response = requests.get(
            f"{API_BASE_URL}/api/providers/openai/models",
            params={
                "check_availability": "true",
                "api_key": self.openai_api_key
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("models", data)
        self.assertTrue(len(data["models"]) > 0)
        
        # Check that each model has an availability flag
        for model in data["models"]:
            self.assertIn("id", model)
            self.assertIn("available", model)
    
    def test_model_availability_anthropic(self):
        """Test model availability for Anthropic"""
        if not self.anthropic_api_key:
            self.skipTest("Anthropic API key not available")
        
        response = requests.get(
            f"{API_BASE_URL}/api/providers/anthropic/models",
            params={
                "check_availability": "true",
                "api_key": self.anthropic_api_key
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("models", data)
        self.assertTrue(len(data["models"]) > 0)


if __name__ == "__main__":
    unittest.main()

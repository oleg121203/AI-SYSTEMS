import os
import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import tempfile

# Add the parent directory to the path so we can import the required modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from git_service.git_service import GitService
from web.backend.github_integration import GitHubIntegration

class TestGitIntegration(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        
        # Mock the environment variables for both integration points
        self.env_patcher = patch.dict('os.environ', {
            'GIT_USER_NAME': 'Test User',
            'GIT_USER_EMAIL': 'test@example.com',
            'GITHUB_TOKEN': 'test_token',
            'GITHUB_REPO': 'test/repo',
            'GITHUB_REPO_URL': 'https://github.com/test/repo.git',
            'GITHUB_REPO_PATH': self.repo_path
        })
        self.env_patcher.start()
        
        # Mock subprocess.run to avoid actual git commands
        self.subprocess_patcher = patch('subprocess.run')
        self.mock_subprocess = self.subprocess_patcher.start()
        self.mock_subprocess.return_value.stdout = 'test_output'
        self.mock_subprocess.return_value.stderr = ''
        self.mock_subprocess.return_value.returncode = 0
        
    def tearDown(self):
        self.temp_dir.cleanup()
        self.env_patcher.stop()
        self.subprocess_patcher.stop()
    
    def test_git_service_integration(self):
        """Test integration between Git Service and GitHub Integration"""
        # Create instances of both classes
        git_service = GitService(repo_path=self.repo_path)
        github_integration = GitHubIntegration()
        
        # Test file info
        test_files = {
            "README.md": "# Test Project\n\nThis is a test project.",
            "src/main.py": "print('Hello, world!')"
        }
        
        # Use GitService to commit files
        from git_service.git_service import FileContent
        files = [
            FileContent(path=path, content=content)
            for path, content in test_files.items()
        ]
        
        result_git_service, _ = git_service.commit_files(files, "Test commit via Git Service")
        self.assertTrue(result_git_service)
        
        # Use GitHubIntegration to commit files
        result_github = github_integration.commit_code(test_files, "Test commit via GitHub Integration")
        self.assertEqual(result_github['status'], 'success')
        
        # Verify both systems interact with the same repository
        git_service_info = git_service.get_repo_info()
        github_info = github_integration.get_repo_status()
        
        # Both systems should be working with the same repository URL
        # (ignoring the token replacement in the Git Service)
        self.assertTrue(github_info['repository'] in git_service_info['repo_url'] or 
                        git_service_info['repo_url'] in github_info['repository'])
    
    def test_end_to_end_workflow(self):
        """Test the end-to-end workflow that would be used in the real system"""
        # Create an instance of the Git Service
        git_service = GitService(repo_path=self.repo_path)
        
        # 1. Initialize the repository (would normally be done by the Git Service)
        git_service.ensure_repo_exists()
        
        # 2. Setup GitHub Actions for CI/CD (would normally be done by the Git Service)
        git_service.setup_github_actions()
        
        # 3. Create an initial project structure (would normally be done by the Project Manager)
        project_files = [
            FileContent(
                path="README.md", 
                content="# Test Project\n\nThis is a test project created by AI-SYSTEMS."
            ),
            FileContent(
                path="src/__init__.py", 
                content="# Source code package"
            ),
            FileContent(
                path="tests/__init__.py", 
                content="# Test package"
            )
        ]
        
        result, _ = git_service.commit_files(project_files, "Initial project structure")
        self.assertTrue(result)
        
        # 4. Generate code for the project (would normally be done by the Development Agents)
        code_files = [
            FileContent(
                path="src/main.py",
                content="""
def hello_world():
    return "Hello, world!"

if __name__ == "__main__":
    print(hello_world())
"""
            ),
            FileContent(
                path="tests/test_main.py",
                content="""
import unittest
from src.main import hello_world

class TestMain(unittest.TestCase):
    def test_hello_world(self):
        self.assertEqual(hello_world(), "Hello, world!")

if __name__ == "__main__":
    unittest.main()
"""
            )
        ]
        
        result, _ = git_service.commit_files(code_files, "Add hello world implementation and tests")
        self.assertTrue(result)
        
        # 5. Get repository information (would normally be displayed in the UI)
        repo_info = git_service.get_repo_info()
        self.assertIsNotNone(repo_info['last_commit'])
        self.assertGreaterEqual(repo_info['file_count'], 5)  # At least 5 files (README, src/, tests/, etc.)

if __name__ == '__main__':
    unittest.main()

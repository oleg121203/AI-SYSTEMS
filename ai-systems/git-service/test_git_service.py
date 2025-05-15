import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock
import sys
import json

# Add the parent directory to the path so we can import the git_service module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from git_service.git_service import GitService

class TestGitService(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        
        # Mock the environment variables
        self.env_patcher = patch.dict('os.environ', {
            'GIT_USER_NAME': 'Test User',
            'GIT_USER_EMAIL': 'test@example.com',
            'GITHUB_TOKEN': 'test_token',
            'GITHUB_REPO': 'test/repo'
        })
        self.env_patcher.start()
        
        # Mock subprocess.run to avoid actual git commands
        self.subprocess_patcher = patch('subprocess.run')
        self.mock_subprocess = self.subprocess_patcher.start()
        self.mock_subprocess.return_value.stdout = 'test_output'
        self.mock_subprocess.return_value.returncode = 0
        
    def tearDown(self):
        self.temp_dir.cleanup()
        self.env_patcher.stop()
        self.subprocess_patcher.stop()
    
    def test_init(self):
        """Test GitService initialization"""
        git_service = GitService(repo_path=self.repo_path)
        self.assertEqual(git_service.repo_path, self.repo_path)
    
    def test_ensure_repo_exists(self):
        """Test ensure_repo_exists method"""
        git_service = GitService(repo_path=self.repo_path)
        git_service.ensure_repo_exists()
        
        # Check that git commands were called correctly
        calls = self.mock_subprocess.call_args_list
        self.assertGreaterEqual(len(calls), 2)  # At least clone and config calls
        
        # Check that the right user name and email were set
        for call in calls:
            args = call[0][0]
            if 'config' in args and 'user.name' in args:
                self.assertEqual(args[3], 'Test User')
            elif 'config' in args and 'user.email' in args:
                self.assertEqual(args[3], 'test@example.com')
    
    def test_commit_file(self):
        """Test commit_file method"""
        git_service = GitService(repo_path=self.repo_path)
        
        # Create a file to commit
        file_path = "test_file.txt"
        content = "Test content"
        
        # Commit the file
        result, commit_hash = git_service.commit_file(file_path, content, "Test commit")
        
        # Check that the result is True
        self.assertTrue(result)
        
        # Check that git commands were called correctly
        calls = self.mock_subprocess.call_args_list
        
        # Extract just the first argument of each call
        command_lists = [call[0][0] for call in calls]
        
        # Find the add command
        add_commands = [cmd for cmd in command_lists if 'add' in cmd]
        self.assertGreaterEqual(len(add_commands), 1)
        self.assertEqual(add_commands[0][1], 'add')
        self.assertEqual(add_commands[0][2], file_path)
        
        # Find the commit command
        commit_commands = [cmd for cmd in command_lists if 'commit' in cmd]
        self.assertGreaterEqual(len(commit_commands), 1)
        self.assertEqual(commit_commands[0][1], 'commit')
        self.assertEqual(commit_commands[0][2], '-m')
        self.assertEqual(commit_commands[0][3], 'Test commit')
        
        # Find the push command
        push_commands = [cmd for cmd in command_lists if 'push' in cmd]
        self.assertGreaterEqual(len(push_commands), 1)
        self.assertEqual(push_commands[0][1], 'push')
    
    def test_commit_files(self):
        """Test commit_files method"""
        from git_service.git_service import FileContent
        
        git_service = GitService(repo_path=self.repo_path)
        
        # Create files to commit
        files = [
            FileContent(path="test_file1.txt", content="Test content 1"),
            FileContent(path="test_file2.txt", content="Test content 2")
        ]
        
        # Commit the files
        result, commit_hash = git_service.commit_files(files, "Test commit")
        
        # Check that the result is True
        self.assertTrue(result)
        
        # Check that git commands were called correctly
        calls = self.mock_subprocess.call_args_list
        
        # Extract just the first argument of each call
        command_lists = [call[0][0] for call in calls]
        
        # Find the add commands
        add_commands = [cmd for cmd in command_lists if 'add' in cmd]
        self.assertGreaterEqual(len(add_commands), 2)  # One for each file
        
        # Find the commit command
        commit_commands = [cmd for cmd in command_lists if 'commit' in cmd]
        self.assertGreaterEqual(len(commit_commands), 1)
        self.assertEqual(commit_commands[0][1], 'commit')
        self.assertEqual(commit_commands[0][2], '-m')
        self.assertEqual(commit_commands[0][3], 'Test commit')
        
        # Find the push command
        push_commands = [cmd for cmd in command_lists if 'push' in cmd]
        self.assertGreaterEqual(len(push_commands), 1)
        self.assertEqual(push_commands[0][1], 'push')
    
    def test_setup_github_actions(self):
        """Test setup_github_actions method"""
        git_service = GitService(repo_path=self.repo_path)
        
        # Setup GitHub Actions
        git_service.setup_github_actions()
        
        # Check that the workflow file was created (mocked)
        calls = self.mock_subprocess.call_args_list
        
        # Extract just the first argument of each call
        command_lists = [call[0][0] for call in calls]
        
        # Find the commit command for the workflow
        commit_commands = [cmd for cmd in command_lists if 'commit' in cmd and '.github/workflows' in str(cmd)]
        self.assertGreaterEqual(len(commit_commands), 1)
    
    def test_get_repo_info(self):
        """Test get_repo_info method"""
        git_service = GitService(repo_path=self.repo_path)
        
        # The subprocess mock will return 'test_output' for any command
        # For the ls-files command, we want to simulate multiple files
        self.mock_subprocess.return_value.stdout = "\n".join(["file1", "file2", "file3"])
        
        # Get repo info
        repo_info = git_service.get_repo_info()
        
        # Check that the repo info has the expected keys
        self.assertIn('repo_url', repo_info)
        self.assertIn('branch', repo_info)
        self.assertIn('last_commit', repo_info)
        self.assertIn('file_count', repo_info)
        
        # Check that the file count is correct
        self.assertEqual(repo_info['file_count'], 3)
        
        # Check that the branch is correct
        self.assertEqual(repo_info['branch'], 'test_output')

if __name__ == '__main__':
    unittest.main()

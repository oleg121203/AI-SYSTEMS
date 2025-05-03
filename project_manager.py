import asyncio
import json
import logging
import os
import re
import shutil
import time
from typing import Dict, List, Optional, Set, Tuple, Any
from pathlib import Path

import aiofiles
from git import Repo, GitCommandError

from utils import log_message, SystemMonitor, TestValidator

logger = logging.getLogger("project_manager")

class ProjectStructure:
    """Represents and manages the project structure"""
    
    def __init__(self, repo_path: str = "repo"):
        self.repo_path = Path(repo_path)
        self.structure = {}
        self.file_map = {}  # Mapping of file paths to metadata
        self.dependencies = {}  # Dependencies between files
        self.history = []  # History of structure changes
        
    async def initialize(self):
        """Initialize project structure from disk or create new"""
        if not self.repo_path.exists():
            os.makedirs(self.repo_path, exist_ok=True)
            log_message(f"Created project directory at {self.repo_path}")
        
        try:
            # Try to initialize or open Git repo
            if not (self.repo_path / ".git").exists():
                Repo.init(self.repo_path)
                log_message(f"Initialized new Git repository at {self.repo_path}")
            else:
                Repo(self.repo_path)
                log_message(f"Opened existing Git repository at {self.repo_path}")
                
            # Scan existing directory structure
            self.structure = await self._scan_directory(self.repo_path)
            log_message(f"Scanned project structure with {len(self.file_map)} files")
        except Exception as e:
            log_message(f"Error initializing project structure: {e}")
            self.structure = {"type": "directory", "name": self.repo_path.name, "children": []}
    
    async def _scan_directory(self, dir_path: Path, rel_path: str = "") -> Dict[str, Any]:
        """Recursively scan directory and build structure"""
        if not dir_path.exists() or not dir_path.is_dir():
            return {}
        
        result = {
            "type": "directory",
            "name": dir_path.name,
            "children": []
        }
        
        try:
            for item in dir_path.iterdir():
                # Skip hidden files and directories
                if item.name.startswith("."):
                    continue
                
                item_rel_path = f"{rel_path}/{item.name}" if rel_path else item.name
                
                if item.is_dir():
                    child = await self._scan_directory(item, item_rel_path)
                    if child:
                        result["children"].append(child)
                else:
                    # Process file
                    file_info = {
                        "type": "file",
                        "name": item.name,
                        "size": item.stat().st_size,
                        "last_modified": item.stat().st_mtime
                    }
                    result["children"].append(file_info)
                    
                    # Add to file map with extension-based metadata
                    file_ext = item.suffix.lower()
                    file_type = self._determine_file_type(file_ext)
                    
                    self.file_map[item_rel_path] = {
                        "path": item_rel_path,
                        "type": file_type,
                        "extension": file_ext,
                        "size": item.stat().st_size,
                        "last_modified": item.stat().st_mtime
                    }
        except Exception as e:
            log_message(f"Error scanning directory {dir_path}: {e}")
        
        return result
    
    def _determine_file_type(self, extension: str) -> str:
        """Determine file type based on extension"""
        code_extensions = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "react",
            ".tsx": "react",
            ".html": "html",
            ".css": "css",
            ".scss": "css",
            ".less": "css",
            ".json": "json",
            ".md": "markdown",
            ".go": "go",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".rs": "rust",
            ".php": "php",
            ".rb": "ruby",
            ".sh": "shell"
        }
        
        return code_extensions.get(extension, "unknown")
    
    async def update_from_spec(self, spec: Dict[str, Any]):
        """Update structure based on specification from AI"""
        if not spec:
            log_message("Empty project specification received")
            return
        
        # Store history of changes
        self.history.append({
            "timestamp": time.time(),
            "spec": spec,
            "action": "update_from_spec"
        })
        
        # Extract top-level structure
        if "structure" in spec:
            top_structure = spec["structure"]
        else:
            # If no explicit structure, use the entire spec as structure
            top_structure = spec
            
        # First pass: create directories
        for item_name, item_data in top_structure.items():
            if isinstance(item_data, dict) and "type" in item_data and item_data["type"] == "directory":
                # It's a directory definition
                await self._ensure_directory(Path(self.repo_path, item_name))
                
                # Process children recursively
                if "children" in item_data and isinstance(item_data["children"], list):
                    await self._process_directory_children(
                        Path(self.repo_path, item_name),
                        item_name,
                        item_data["children"]
                    )
        
        # Second pass: create files (ensuring directories exist first helps with dependencies)
        for item_name, item_data in top_structure.items():
            if isinstance(item_data, dict) and "type" in item_data and item_data["type"] == "file":
                # It's a file definition
                file_path = Path(self.repo_path, item_name)
                await self._create_file(
                    file_path,
                    item_name,
                    item_data.get("content", ""),
                    item_data.get("description", "")
                )
        
        # Final pass: update structure
        self.structure = await self._scan_directory(self.repo_path)
        log_message(f"Updated project structure with {len(self.file_map)} files")
    
    async def _process_directory_children(self, parent_path: Path, parent_rel_path: str, children: List[Dict[str, Any]]):
        """Process children of a directory definition"""
        for child in children:
            if not isinstance(child, dict) or "name" not in child:
                continue
                
            child_name = child["name"]
            child_path = parent_path / child_name
            child_rel_path = f"{parent_rel_path}/{child_name}"
            
            if child.get("type") == "directory":
                await self._ensure_directory(child_path)
                
                # Process nested children
                if "children" in child and isinstance(child["children"], list):
                    await self._process_directory_children(
                        child_path,
                        child_rel_path,
                        child["children"]
                    )
            elif child.get("type") == "file":
                await self._create_file(
                    child_path,
                    child_rel_path,
                    child.get("content", ""),
                    child.get("description", "")
                )
    
    async def _ensure_directory(self, dir_path: Path):
        """Ensure directory exists, creating it if necessary"""
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            log_message(f"Error creating directory {dir_path}: {e}")
            return False
    
    async def _create_file(self, file_path: Path, rel_path: str, content: str, description: str = ""):
        """Create or update a file"""
        try:
            # Ensure parent directory exists
            await self._ensure_directory(file_path.parent)
            
            # Write content to file
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)
            
            # Update file map
            file_ext = file_path.suffix.lower()
            file_type = self._determine_file_type(file_ext)
            
            self.file_map[rel_path] = {
                "path": rel_path,
                "type": file_type,
                "extension": file_ext,
                "size": file_path.stat().st_size,
                "last_modified": file_path.stat().st_mtime,
                "description": description
            }
            
            log_message(f"Created/updated file: {rel_path}")
            return True
        except Exception as e:
            log_message(f"Error creating file {file_path}: {e}")
            return False
    
    async def analyze_dependencies(self):
        """Analyze dependencies between files"""
        self.dependencies = {}
        
        # Group files by type for efficient processing
        files_by_type = {}
        for file_path, file_info in self.file_map.items():
            file_type = file_info["type"]
            if file_type not in files_by_type:
                files_by_type[file_type] = []
            files_by_type[file_type].append(file_path)
        
        # Process files by type
        for file_type, files in files_by_type.items():
            if file_type == "python":
                await self._analyze_python_dependencies(files)
            elif file_type in ["javascript", "typescript", "react"]:
                await self._analyze_js_dependencies(files)
        
        log_message(f"Analyzed dependencies, found {sum(len(deps) for deps in self.dependencies.values())} relationships")
    
    async def _analyze_python_dependencies(self, file_paths: List[str]):
        """Analyze dependencies in Python files"""
        import_pattern = re.compile(r'^\s*(?:from|import)\s+([.\w]+)', re.MULTILINE)
        
        for file_path in file_paths:
            try:
                full_path = self.repo_path / file_path
                if not full_path.exists():
                    continue
                
                async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                    content = await f.read()
                
                # Find imports
                imports = import_pattern.findall(content)
                if not imports:
                    continue
                
                # Convert module imports to potential file dependencies
                dependencies = set()
                for imp in imports:
                    # Handle relative imports
                    if imp.startswith("."):
                        # Calculate potential file paths
                        parts = imp.lstrip(".").split(".")
                        dir_levels = imp.count(".")
                        current_dir = Path(file_path).parent
                        
                        # Go up directory levels for relative import
                        target_dir = current_dir
                        for _ in range(dir_levels):
                            if target_dir.name:  # Not at root
                                target_dir = target_dir.parent
                        
                        if parts[0]:  # Non-empty module name
                            # Try as a Python file
                            potential_file = target_dir / f"{parts[0]}.py"
                            potential_path = str(potential_file)
                            if potential_path in self.file_map:
                                dependencies.add(potential_path)
                            
                            # Try as a directory (package)
                            potential_dir = target_dir / parts[0]
                            potential_init = potential_dir / "__init__.py"
                            potential_init_path = str(potential_init.relative_to(self.repo_path))
                            if potential_init_path in self.file_map:
                                dependencies.add(potential_init_path)
                    else:
                        # Standard import - more complex to resolve accurately
                        # Just add potential local module matches
                        parts = imp.split(".")
                        if parts:
                            # Look for matching files in the whole project
                            for path in self.file_map:
                                if path.endswith(f"{parts[0]}.py") or path.endswith(f"{parts[0]}/__init__.py"):
                                    dependencies.add(path)
                
                # Store dependencies
                if dependencies:
                    self.dependencies[file_path] = list(dependencies)
            
            except Exception as e:
                log_message(f"Error analyzing Python dependencies for {file_path}: {e}")
    
    async def _analyze_js_dependencies(self, file_paths: List[str]):
        """Analyze dependencies in JavaScript/TypeScript files"""
        # Matches both ES6 imports and CommonJS requires
        import_pattern = re.compile(r'(?:import\s+.+\s+from\s+[\'"]([^\'"]*)[\'"]);?|(?:require\([\'"]([^\'"]*)[\'"]\))', re.MULTILINE)
        
        for file_path in file_paths:
            try:
                full_path = self.repo_path / file_path
                if not full_path.exists():
                    continue
                
                async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                    content = await f.read()
                
                # Find imports
                matches = import_pattern.findall(content)
                if not matches:
                    continue
                
                # Extract the non-empty group from each match
                imports = [match[0] if match[0] else match[1] for match in matches]
                
                # Convert module imports to potential file dependencies
                dependencies = set()
                for imp in imports:
                    # Skip external modules
                    if not imp.startswith(".") and not imp.startswith("/"):
                        continue
                    
                    # Handle relative imports
                    is_relative = imp.startswith(".")
                    
                    # Calculate base directory
                    base_dir = Path(file_path).parent if is_relative else Path()
                    
                    # Remove "./" prefix if present
                    clean_path = imp.lstrip("./")
                    
                    # Calculate potential paths to check
                    potential_paths = []
                    
                    # The imported path as is
                    if clean_path:
                        potential_paths.append(str(base_dir / clean_path))
                    
                    # With extensions
                    for ext in [".js", ".jsx", ".ts", ".tsx"]:
                        potential_paths.append(str(base_dir / f"{clean_path}{ext}"))
                    
                    # For directory imports
                    for file in ["index.js", "index.ts", "index.jsx", "index.tsx"]:
                        potential_paths.append(str(base_dir / clean_path / file))
                    
                    # Find matching file in project
                    for potential_path in potential_paths:
                        normalized_path = str(Path(potential_path))
                        if normalized_path in self.file_map:
                            dependencies.add(normalized_path)
                
                # Store dependencies
                if dependencies:
                    self.dependencies[file_path] = list(dependencies)
            
            except Exception as e:
                log_message(f"Error analyzing JS dependencies for {file_path}: {e}")
    
    async def commit_changes(self, message: str = "Update project structure"):
        """Commit all changes to the Git repository"""
        try:
            repo = Repo(self.repo_path)
            
            # Check if there are changes to commit
            if not repo.is_dirty(untracked_files=True):
                log_message("No changes to commit")
                return True
            
            # Add all files
            repo.git.add(A=True)
            
            # Commit changes
            repo.index.commit(message)
            log_message(f"Committed changes: {message}")
            return True
        except GitCommandError as e:
            log_message(f"Git error committing changes: {e}")
            return False
        except Exception as e:
            log_message(f"Error committing changes: {e}")
            return False
    
    def get_structure(self) -> Dict[str, Any]:
        """Get current project structure"""
        return self.structure
    
    def get_file_list(self) -> List[str]:
        """Get list of all files in the project"""
        return list(self.file_map.keys())
    
    def get_dependencies(self, file_path: str = None) -> Dict[str, List[str]]:
        """Get dependencies for a specific file or all files"""
        if file_path:
            return {file_path: self.dependencies.get(file_path, [])}
        return self.dependencies


class ProjectBuilder:
    """Manages the build process for the project"""
    
    def __init__(self, project_structure: ProjectStructure):
        self.project_structure = project_structure
        self.build_config = {}
        self.build_history = []
        self.current_build = None
    
    async def detect_project_type(self) -> Dict[str, Any]:
        """Detect project type based on files and structure"""
        file_map = self.project_structure.file_map
        file_extensions = {}
        
        # Count file extensions
        for file_path, info in file_map.items():
            ext = info.get("extension", "")
            if ext:
                file_extensions[ext] = file_extensions.get(ext, 0) + 1
        
        # Check for specific project files
        has_package_json = any(path.endswith("package.json") for path in file_map)
        has_requirements_txt = any(path.endswith("requirements.txt") for path in file_map)
        has_cargo_toml = any(path.endswith("Cargo.toml") for path in file_map)
        has_go_mod = any(path.endswith("go.mod") for path in file_map)
        has_pom_xml = any(path.endswith("pom.xml") for path in file_map)
        has_gemfile = any(path.endswith("Gemfile") for path in file_map)
        
        # Determine primary language
        top_extensions = sorted(file_extensions.items(), key=lambda x: x[1], reverse=True)
        primary_language = None
        secondary_language = None
        
        if top_extensions:
            # Map extensions to languages
            ext_to_lang = {
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".jsx": "react",
                ".tsx": "react-typescript",
                ".go": "go",
                ".java": "java",
                ".c": "c",
                ".cpp": "cpp",
                ".cs": "csharp",
                ".rb": "ruby",
                ".php": "php",
                ".rs": "rust",
                ".html": "html",
                ".css": "css",
                ".scss": "scss"
            }
            
            primary_ext = top_extensions[0][0]
            primary_language = ext_to_lang.get(primary_ext, "unknown")
            
            if len(top_extensions) > 1:
                secondary_ext = top_extensions[1][0]
                secondary_language = ext_to_lang.get(secondary_ext, "unknown")
        
        # Determine frameworks
        frameworks = []
        
        # JavaScript/TypeScript frameworks
        if has_package_json:
            try:
                package_json_path = next(path for path in file_map if path.endswith("package.json"))
                async with aiofiles.open(self.project_structure.repo_path / package_json_path, "r") as f:
                    package_data = json.loads(await f.read())
                
                dependencies = package_data.get("dependencies", {})
                dev_dependencies = package_data.get("devDependencies", {})
                all_deps = {**dependencies, **dev_dependencies}
                
                if "react" in all_deps:
                    frameworks.append("react")
                if "next" in all_deps:
                    frameworks.append("nextjs")
                if "vue" in all_deps:
                    frameworks.append("vue")
                if "angular" in all_deps or "@angular/core" in all_deps:
                    frameworks.append("angular")
                if "express" in all_deps:
                    frameworks.append("express")
                if "koa" in all_deps:
                    frameworks.append("koa")
            except Exception as e:
                log_message(f"Error parsing package.json: {e}")
        
        # Python frameworks
        if has_requirements_txt:
            try:
                req_path = next(path for path in file_map if path.endswith("requirements.txt"))
                async with aiofiles.open(self.project_structure.repo_path / req_path, "r") as f:
                    requirements = await f.read()
                
                if "django" in requirements.lower():
                    frameworks.append("django")
                if "flask" in requirements.lower():
                    frameworks.append("flask")
                if "fastapi" in requirements.lower():
                    frameworks.append("fastapi")
            except Exception as e:
                log_message(f"Error parsing requirements.txt: {e}")
        
        # Determine project type
        project_type = "unknown"
        
        if primary_language == "javascript" or primary_language == "typescript":
            if "react" in frameworks:
                project_type = "react-app"
            elif "angular" in frameworks:
                project_type = "angular-app"
            elif "vue" in frameworks:
                project_type = "vue-app"
            elif "nextjs" in frameworks:
                project_type = "nextjs-app"
            elif "express" in frameworks or "koa" in frameworks:
                project_type = "node-backend"
            else:
                project_type = "javascript-project"
        elif primary_language == "python":
            if "django" in frameworks:
                project_type = "django-app"
            elif "flask" in frameworks:
                project_type = "flask-app"
            elif "fastapi" in frameworks:
                project_type = "fastapi-app"
            else:
                project_type = "python-project"
        elif primary_language == "rust":
            project_type = "rust-project"
        elif primary_language == "go":
            project_type = "go-project"
        elif primary_language == "java":
            project_type = "java-project"
        
        return {
            "project_type": project_type,
            "primary_language": primary_language,
            "secondary_language": secondary_language,
            "frameworks": frameworks,
            "file_extensions": file_extensions
        }
    
    async def configure_build(self, project_type: str = None):
        """Configure the build process based on detected project type"""
        if not project_type:
            detection = await self.detect_project_type()
            project_type = detection["project_type"]
        
        build_config = {
            "project_type": project_type,
            "commands": [],
            "environment": {},
            "artifacts": []
        }
        
        # Configure based on project type
        if project_type == "react-app":
            build_config["commands"] = [
                "npm install",
                "npm run build"
            ]
            build_config["artifacts"] = ["build/"]
        
        elif project_type == "nextjs-app":
            build_config["commands"] = [
                "npm install",
                "npm run build"
            ]
            build_config["artifacts"] = [".next/"]
        
        elif project_type == "angular-app":
            build_config["commands"] = [
                "npm install",
                "ng build --prod"
            ]
            build_config["artifacts"] = ["dist/"]
        
        elif project_type == "vue-app":
            build_config["commands"] = [
                "npm install",
                "npm run build"
            ]
            build_config["artifacts"] = ["dist/"]
        
        elif project_type == "node-backend":
            build_config["commands"] = [
                "npm install",
                "npm run build"
            ]
            build_config["artifacts"] = ["dist/", "build/"]
        
        elif project_type == "python-project":
            build_config["commands"] = [
                "pip install -r requirements.txt"
            ]
            build_config["artifacts"] = ["__pycache__/"]
        
        elif project_type == "django-app" or project_type == "flask-app" or project_type == "fastapi-app":
            build_config["commands"] = [
                "pip install -r requirements.txt",
                "python manage.py collectstatic --noinput" if project_type == "django-app" else ""
            ]
            build_config["artifacts"] = ["static/", "__pycache__/"]
        
        elif project_type == "rust-project":
            build_config["commands"] = [
                "cargo build --release"
            ]
            build_config["artifacts"] = ["target/release/"]
        
        elif project_type == "go-project":
            build_config["commands"] = [
                "go build -o app"
            ]
            build_config["artifacts"] = ["app"]
        
        self.build_config = build_config
        log_message(f"Configured build for project type: {project_type}")
        return build_config
    
    async def execute_build(self) -> Dict[str, Any]:
        """Execute the build process"""
        if not self.build_config:
            await self.configure_build()
        
        build_id = str(int(time.time()))
        build_start = time.time()
        
        self.current_build = {
            "id": build_id,
            "start_time": build_start,
            "status": "running",
            "commands": [],
            "logs": []
        }
        
        log_message(f"Starting build {build_id}")
        
        # Execute commands
        for cmd in self.build_config["commands"]:
            if not cmd:  # Skip empty commands
                continue
                
            command_start = time.time()
            result = {
                "command": cmd,
                "start_time": command_start,
                "status": "unknown",
                "output": "",
                "error": ""
            }
            
            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.project_structure.repo_path)
                )
                
                stdout, stderr = await process.communicate()
                
                result["output"] = stdout.decode()
                result["error"] = stderr.decode()
                result["exit_code"] = process.returncode
                result["end_time"] = time.time()
                result["duration"] = result["end_time"] - command_start
                
                if process.returncode == 0:
                    result["status"] = "success"
                    log_message(f"Command succeeded: {cmd}")
                else:
                    result["status"] = "failed"
                    log_message(f"Command failed: {cmd} (exit code: {process.returncode})")
                    # Break the build if a command fails
                    self.current_build["status"] = "failed"
                    self.current_build["failure_reason"] = f"Command failed: {cmd}"
                    break
            
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                result["end_time"] = time.time()
                result["duration"] = result["end_time"] - command_start
                
                log_message(f"Error executing command: {cmd} - {e}")
                self.current_build["status"] = "error"
                self.current_build["failure_reason"] = f"Error: {e}"
                break
            
            self.current_build["commands"].append(result)
            self.current_build["logs"].append(f"[{result['status']}] {cmd}")
        
        # If we didn't set a failure status, it succeeded
        if self.current_build["status"] == "running":
            self.current_build["status"] = "success"
        
        self.current_build["end_time"] = time.time()
        self.current_build["duration"] = self.current_build["end_time"] - build_start
        
        self.build_history.append(self.current_build)
        
        log_message(f"Build {build_id} completed with status: {self.current_build['status']}")
        return self.current_build
    
    def get_latest_build(self) -> Dict[str, Any]:
        """Get the latest build information"""
        if self.current_build:
            return self.current_build
        elif self.build_history:
            return self.build_history[-1]
        else:
            return {"status": "no_builds", "message": "No builds have been executed"}
    
    def get_build_history(self) -> List[Dict[str, Any]]:
        """Get the build history"""
        return self.build_history


class ProjectTester:
    """Manages testing of the project"""
    
    def __init__(self, project_structure: ProjectStructure):
        self.project_structure = project_structure
        self.test_validator = TestValidator()
        self.test_results = {}
        self.test_history = []
    
    async def discover_tests(self) -> Dict[str, List[str]]:
        """Discover test files in the project"""
        file_map = self.project_structure.file_map
        tests_by_type = {}
        
        # Patterns for test files
        test_patterns = {
            "python": [r"test_.*\.py$", r".*_test\.py$"],
            "javascript": [r".*\.test\.(js|jsx)$", r".*\.spec\.(js|jsx)$"],
            "typescript": [r".*\.test\.(ts|tsx)$", r".*\.spec\.(ts|tsx)$"],
            "go": [r".*_test\.go$"],
            "rust": [r".*_test\.rs$"],
            "java": [r".*Test\.java$"]
        }
        
        # Find test files
        for file_path, info in file_map.items():
            file_type = info.get("type", "unknown")
            
            # Skip unknown file types
            if file_type == "unknown":
                continue
            
            # Get patterns for this file type
            patterns = test_patterns.get(file_type, [])
            
            # Check if file matches any test pattern
            is_test = any(re.search(pattern, file_path) for pattern in patterns)
            
            if is_test:
                if file_type not in tests_by_type:
                    tests_by_type[file_type] = []
                tests_by_type[file_type].append(file_path)
        
        log_message(f"Discovered {sum(len(tests) for tests in tests_by_type.values())} test files")
        return tests_by_type
    
    async def map_tests_to_code(self, test_files: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Map test files to their corresponding code files"""
        test_to_code = {}
        
        for file_type, tests in test_files.items():
            for test_file in tests:
                code_file = await self._find_corresponding_code_file(test_file, file_type)
                if code_file:
                    test_to_code[test_file] = code_file
        
        log_message(f"Mapped {len(test_to_code)} test files to code files")
        return test_to_code
    
    async def _find_corresponding_code_file(self, test_file: str, file_type: str) -> Optional[str]:
        """Find the code file that corresponds to a test file"""
        file_map = self.project_structure.file_map
        
        # Extract test file name and directory
        test_path = Path(test_file)
        test_dir = test_path.parent
        test_name = test_path.name
        
        # Apply language-specific logic
        if file_type == "python":
            if test_name.startswith("test_"):
                # test_module.py -> module.py
                code_name = test_name[5:]  # Remove "test_" prefix
                potential_paths = [
                    str(test_dir / code_name),
                    str((test_dir / "..").resolve().relative_to(self.project_structure.repo_path) / code_name)
                ]
            elif test_name.endswith("_test.py"):
                # module_test.py -> module.py
                code_name = test_name[:-8] + ".py"  # Replace "_test.py" with ".py"
                potential_paths = [
                    str(test_dir / code_name),
                    str((test_dir / "..").resolve().relative_to(self.project_structure.repo_path) / code_name)
                ]
            else:
                return None
        
        elif file_type in ["javascript", "typescript"]:
            if ".test." in test_name or ".spec." in test_name:
                # module.test.js -> module.js
                code_name = test_name.replace(".test.", ".").replace(".spec.", ".")
                potential_paths = [
                    str(test_dir / code_name)
                ]
            else:
                return None
        
        elif file_type == "go":
            if test_name.endswith("_test.go"):
                # module_test.go -> module.go
                code_name = test_name[:-8] + ".go"  # Replace "_test.go" with ".go"
                potential_paths = [
                    str(test_dir / code_name)
                ]
            else:
                return None
        
        elif file_type == "rust":
            if test_name.endswith("_test.rs"):
                # module_test.rs -> module.rs
                code_name = test_name[:-8] + ".rs"  # Replace "_test.rs" with ".rs"
                potential_paths = [
                    str(test_dir / code_name)
                ]
            else:
                return None
        
        elif file_type == "java":
            if test_name.endswith("Test.java"):
                # ModuleTest.java -> Module.java
                code_name = test_name[:-9] + ".java"  # Replace "Test.java" with ".java"
                potential_paths = [
                    str(test_dir / code_name)
                ]
            else:
                return None
        
        else:
            return None
        
        # Check potential paths
        for potential_path in potential_paths:
            normalized_path = str(Path(potential_path))
            if normalized_path in file_map:
                return normalized_path
        
        # Fallback: look for files with similar names throughout the project
        base_name = test_path.stem
        if file_type == "python":
            if base_name.startswith("test_"):
                search_name = base_name[5:]  # Remove "test_" prefix
            elif base_name.endswith("_test"):
                search_name = base_name[:-5]  # Remove "_test" suffix
            else:
                search_name = base_name
        elif file_type in ["javascript", "typescript"]:
            if ".test" in base_name or ".spec" in base_name:
                search_name = base_name.split(".")[0]  # Get first part before dot
            else:
                search_name = base_name
        else:
            search_name = base_name.replace("_test", "").replace("Test", "")
        
        for path, info in file_map.items():
            if info.get("type") == file_type and not self._is_test_file(path, file_type):
                path_stem = Path(path).stem
                if search_name.lower() in path_stem.lower():
                    return path
        
        return None
    
    def _is_test_file(self, file_path: str, file_type: str) -> bool:
        """Check if a file is a test file based on naming conventions"""
        path = Path(file_path)
        file_name = path.name
        
        if file_type == "python":
            return file_name.startswith("test_") or file_name.endswith("_test.py")
        elif file_type in ["javascript", "typescript"]:
            return ".test." in file_name or ".spec." in file_name
        elif file_type == "go":
            return file_name.endswith("_test.go")
        elif file_type == "rust":
            return file_name.endswith("_test.rs")
        elif file_type == "java":
            return file_name.endswith("Test.java")
        
        return False
    
    async def run_tests(self, specific_tests: List[str] = None) -> Dict[str, Any]:
        """Run tests and collect results"""
        test_files = await self.discover_tests()
        all_tests = []
        
        for tests in test_files.values():
            all_tests.extend(tests)
        
        tests_to_run = specific_tests if specific_tests else all_tests
        
        if not tests_to_run:
            log_message("No tests found to run")
            return {"status": "no_tests", "message": "No tests found to run"}
        
        build_id = str(int(time.time()))
        test_run = {
            "id": build_id,
            "start_time": time.time(),
            "status": "running",
            "tests": [],
            "summary": {
                "total": len(tests_to_run),
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "error": 0
            }
        }
        
        log_message(f"Starting test run {build_id} with {len(tests_to_run)} tests")
        
        # Run tests
        for test_file in tests_to_run:
            file_type = self.project_structure.file_map.get(test_file, {}).get("type", "unknown")
            
            if file_type == "unknown":
                continue
            
            test_start = time.time()
            test_result = {
                "file": test_file,
                "type": file_type,
                "start_time": test_start,
                "status": "unknown",
                "output": "",
                "error": ""
            }
            
            try:
                # Get corresponding code file for validation
                code_file = None
                test_to_code = await self.map_tests_to_code({file_type: [test_file]})
                if test_file in test_to_code:
                    code_file = test_to_code[test_file]
                
                # Validate test file
                validation = await self.test_validator.validate_test_file(
                    self.project_structure.repo_path / test_file,
                    self.project_structure.repo_path / code_file if code_file else None
                )
                
                test_result["validation"] = validation
                
                if not validation["valid"]:
                    test_result["status"] = "invalid"
                    test_result["error"] = "; ".join(validation["errors"])
                else:
                    # Run the test
                    cmd = await self._get_test_command(test_file, file_type)
                    
                    if cmd:
                        process = await asyncio.create_subprocess_shell(
                            cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=str(self.project_structure.repo_path)
                        )
                        
                        stdout, stderr = await process.communicate()
                        
                        test_result["output"] = stdout.decode()
                        test_result["error"] = stderr.decode()
                        test_result["exit_code"] = process.returncode
                        
                        if process.returncode == 0:
                            test_result["status"] = "passed"
                            test_run["summary"]["passed"] += 1
                        else:
                            test_result["status"] = "failed"
                            test_run["summary"]["failed"] += 1
                    else:
                        test_result["status"] = "skipped"
                        test_result["error"] = "No test command available for this file type"
                        test_run["summary"]["skipped"] += 1
            
            except Exception as e:
                test_result["status"] = "error"
                test_result["error"] = str(e)
                test_run["summary"]["error"] += 1
                log_message(f"Error running test {test_file}: {e}")
            
            test_result["end_time"] = time.time()
            test_result["duration"] = test_result["end_time"] - test_start
            
            test_run["tests"].append(test_result)
            self.test_results[test_file] = test_result
        
        # Update test run status
        if test_run["summary"]["failed"] > 0 or test_run["summary"]["error"] > 0:
            test_run["status"] = "failed"
        else:
            test_run["status"] = "passed"
        
        test_run["end_time"] = time.time()
        test_run["duration"] = test_run["end_time"] - test_run["start_time"]
        
        self.test_history.append(test_run)
        
        success_rate = test_run["summary"]["passed"] / test_run["summary"]["total"] * 100 if test_run["summary"]["total"] > 0 else 0
        log_message(f"Test run {build_id} completed: {test_run['summary']['passed']}/{test_run['summary']['total']} passed ({success_rate:.1f}%)")
        
        return test_run
    
    async def _get_test_command(self, test_file: str, file_type: str) -> Optional[str]:
        """Get command to run a specific test file"""
        if file_type == "python":
            return f"python -m pytest {test_file} -v"
        elif file_type in ["javascript", "typescript"]:
            return f"npx jest {test_file}"
        elif file_type == "go":
            test_dir = str(Path(test_file).parent)
            return f"cd {test_dir} && go test -v"
        elif file_type == "rust":
            test_name = Path(test_file).stem
            return f"cargo test --test {test_name}"
        elif file_type == "java":
            test_name = Path(test_file).stem
            if (self.project_structure.repo_path / "pom.xml").exists():
                return f"mvn test -Dtest={test_name}"
            elif (self.project_structure.repo_path / "build.gradle").exists():
                return f"./gradlew test --tests {test_name}"
        
        return None
    
    def get_test_results(self, test_file: str = None) -> Dict[str, Any]:
        """Get results for a specific test or all tests"""
        if test_file:
            return self.test_results.get(test_file, {"status": "unknown", "message": "No test results available"})
        return self.test_results
    
    def get_latest_test_run(self) -> Dict[str, Any]:
        """Get the latest test run information"""
        if self.test_history:
            return self.test_history[-1]
        else:
            return {"status": "no_tests", "message": "No test runs have been executed"}
    
    def get_test_history(self) -> List[Dict[str, Any]]:
        """Get the test run history"""
        return self.test_history
    
    async def analyze_test_coverage(self) -> Dict[str, Any]:
        """Analyze test coverage based on test-to-code mapping"""
        test_files = await self.discover_tests()
        all_tests = []
        
        for tests in test_files.values():
            all_tests.extend(tests)
        
        # Map tests to code
        test_to_code = await self.map_tests_to_code(test_files)
        
        # Get all code files
        code_files = set()
        for file_path, info in self.project_structure.file_map.items():
            file_type = info.get("type")
            if file_type and file_type != "unknown" and not self._is_test_file(file_path, file_type):
                code_files.add(file_path)
        
        # Find covered and uncovered files
        covered_files = set(test_to_code.values())
        uncovered_files = code_files - covered_files
        
        coverage_percentage = len(covered_files) / len(code_files) * 100 if code_files else 0
        
        return {
            "total_files": len(code_files),
            "covered_files": len(covered_files),
            "uncovered_files": len(uncovered_files),
            "coverage_percentage": coverage_percentage,
            "uncovered_file_list": list(uncovered_files)
        }


class ProjectManager:
    """Main class to manage the entire project lifecycle"""
    
    def __init__(self, repo_path: str = "repo"):
        self.structure = ProjectStructure(repo_path)
        self.builder = None
        self.tester = None
        self.system_monitor = SystemMonitor()
        self.status = "initializing"
        self.events = []
    
    async def initialize(self):
        """Initialize the project manager and its components"""
        await self.structure.initialize()
        self.builder = ProjectBuilder(self.structure)
        self.tester = ProjectTester(self.structure)
        
        # Start system monitoring
        asyncio.create_task(self.system_monitor.start())
        
        self.status = "ready"
        self._add_event("Project manager initialized")
        log_message("Project manager initialized")
    
    async def update_project(self, spec: Dict[str, Any]):
        """Update project based on specification from AI"""
        self.status = "updating"
        self._add_event("Updating project structure")
        
        # Update structure
        await self.structure.update_from_spec(spec)
        
        # Analyze dependencies
        await self.structure.analyze_dependencies()
        
        # Commit changes
        await self.structure.commit_changes("Update project structure")
        
        self.status = "ready"
        self._add_event("Project structure updated")
        log_message("Project updated successfully")
        
        return {"status": "success", "message": "Project updated successfully"}
    
    async def build_project(self):
        """Build the project"""
        self.status = "building"
        self._add_event("Building project")
        
        # Detect project type if needed
        if not self.builder.build_config:
            project_type = await self.builder.detect_project_type()
            await self.builder.configure_build(project_type["project_type"])
        
        # Execute build
        build_result = await self.builder.execute_build()
        
        if build_result["status"] == "success":
            self.status = "ready"
            self._add_event("Project built successfully")
        else:
            self.status = "build_failed"
            self._add_event(f"Build failed: {build_result.get('failure_reason', 'Unknown error')}")
        
        log_message(f"Build completed with status: {build_result['status']}")
        return build_result
    
    async def test_project(self, specific_tests: List[str] = None):
        """Run tests for the project"""
        self.status = "testing"
        self._add_event("Running tests")
        
        # Run tests
        test_result = await self.tester.run_tests(specific_tests)
        
        if test_result["status"] == "passed":
            self.status = "ready"
            self._add_event("Tests passed successfully")
        else:
            self.status = "tests_failed"
            self._add_event(f"Tests failed: {test_result['summary']['failed']} failures, {test_result['summary']['error']} errors")
        
        log_message(f"Testing completed with status: {test_result['status']}")
        return test_result
    
    async def analyze_project(self) -> Dict[str, Any]:
        """Analyze the project and generate a report"""
        self._add_event("Analyzing project")
        
        # Detect project type
        project_type = await self.builder.detect_project_type()
        
        # Analyze dependencies
        await self.structure.analyze_dependencies()
        
        # Get test coverage
        test_coverage = await self.tester.analyze_test_coverage()
        
        # Count files by type
        file_stats = {}
        for file_path, info in self.structure.file_map.items():
            file_type = info.get("type", "unknown")
            file_stats[file_type] = file_stats.get(file_type, 0) + 1
        
        # Count lines of code (simple implementation)
        lines_of_code = await self._count_lines_of_code()
        
        analysis = {
            "project_type": project_type,
            "files": len(self.structure.file_map),
            "file_stats": file_stats,
            "lines_of_code": lines_of_code,
            "test_coverage": test_coverage,
            "dependencies": len(self.structure.dependencies),
            "timestamp": time.time()
        }
        
        self._add_event("Project analysis completed")
        log_message("Project analysis completed")
        
        return analysis
    
    async def _count_lines_of_code(self) -> Dict[str, int]:
        """Count lines of code by file type"""
        lines_by_type = {}
        total_lines = 0
        
        for file_path, info in self.structure.file_map.items():
            file_type = info.get("type", "unknown")
            
            try:
                full_path = self.structure.repo_path / file_path
                if not full_path.exists() or not full_path.is_file():
                    continue
                
                async with aiofiles.open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = await f.read()
                    
                    lines = len(content.splitlines())
                    lines_by_type[file_type] = lines_by_type.get(file_type, 0) + lines
                    total_lines += lines
            
            except Exception as e:
                log_message(f"Error counting lines in {file_path}: {e}")
        
        lines_by_type["total"] = total_lines
        return lines_by_type
    
    def get_structure(self) -> Dict[str, Any]:
        """Get current project structure"""
        return self.structure.get_structure()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current project status"""
        return {
            "status": self.status,
            "events": self.events[-10:],  # Return the last 10 events
            "files": len(self.structure.file_map),
            "latest_build": self.builder.get_latest_build() if self.builder else None,
            "latest_test_run": self.tester.get_latest_test_run() if self.tester else None,
            "last_updated": self.events[-1]["timestamp"] if self.events else None
        }
    
    def _add_event(self, message: str):
        """Add an event to the event log"""
        self.events.append({
            "timestamp": time.time(),
            "message": message
        })
        log_message(message)
    
    async def cleanup(self):
        """Clean up resources"""
        # Stop system monitoring
        self.system_monitor.stop()
        log_message("Project manager resources cleaned up")